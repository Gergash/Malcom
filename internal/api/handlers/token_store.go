// token_store.go: almacén de tokens de descarga con TTL.
// Soporta persistencia en PostgreSQL (DownloadToken) y fallback en memoria.
package handlers

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"sync"
	"time"

	malcomdb "github.com/powerups/insightflow-malcom/internal/db"
	"gorm.io/gorm"
)

const tokenTTL = 30 * time.Minute

type tokenEntry struct {
	chatID    int64
	resType   string
	filePath  string
	expiresAt time.Time
}

// TokenStore guarda tokens efímeros; si db != nil persiste en PostgreSQL.
type TokenStore struct {
	db    *gorm.DB
	mu    sync.Mutex
	store map[string]tokenEntry
}

// NewTokenStore crea un TokenStore en memoria e inicia GC en background.
func NewTokenStore() *TokenStore {
	ts := &TokenStore{store: make(map[string]tokenEntry)}
	go ts.gc()
	return ts
}

// NewPersistentTokenStore crea un TokenStore con persistencia en DB.
func NewPersistentTokenStore(gdb *gorm.DB) *TokenStore {
	ts := &TokenStore{db: gdb, store: make(map[string]tokenEntry)}
	go ts.gc()
	return ts
}

func newTokenValue() string {
	b := make([]byte, 16)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}

// Store registra un token en memoria/DB y devuelve su valor.
func (ts *TokenStore) Store(chatID int64, resourceType, filePath string) string {
	token := newTokenValue()
	expiresAt := time.Now().Add(tokenTTL)

	if ts.db != nil {
		entry := &malcomdb.DownloadToken{
			Token:        token,
			FilePath:     filePath,
			ChatID:       chatID,
			ResourceType: resourceType,
			ExpiresAt:    expiresAt,
		}
		// Fallback a memoria si falla DB: mantenemos operatividad de descarga.
		if err := ts.db.WithContext(context.Background()).Create(entry).Error; err == nil {
			return token
		}
	}

	ts.mu.Lock()
	ts.store[token] = tokenEntry{
		chatID:   chatID,
		resType:  resourceType,
		filePath: filePath, expiresAt: expiresAt,
	}
	ts.mu.Unlock()
	return token
}

// Resolve devuelve la ruta y el tipo de recurso si el token sigue vigente.
// resourceType: "pdf" | "excel" | "chart" | "" (memoria legacy).
// Las gráficas no marcan used_at para permitir varias cargas en <img>.
func (ts *TokenStore) Resolve(token string) (filePath string, resourceType string, ok bool) {
	if ts.db != nil {
		var e malcomdb.DownloadToken
		err := ts.db.WithContext(context.Background()).Where("token = ?", token).First(&e).Error
		if err != nil {
			return "", "", false
		}
		if time.Now().After(e.ExpiresAt) {
			_ = ts.db.WithContext(context.Background()).Delete(&e).Error
			return "", "", false
		}
		rt := e.ResourceType
		if rt != "chart" && e.UsedAt == nil {
			now := time.Now().UTC()
			_ = ts.db.WithContext(context.Background()).Model(&e).Update("used_at", &now).Error
		}
		return e.FilePath, rt, true
	}

	ts.mu.Lock()
	defer ts.mu.Unlock()
	e, ok := ts.store[token]
	if !ok || time.Now().After(e.expiresAt) {
		delete(ts.store, token)
		return "", "", false
	}
	return e.filePath, e.resType, true
}

// gc elimina las entradas expiradas cada 5 minutos.
func (ts *TokenStore) gc() {
	ticker := time.NewTicker(5 * time.Minute)
	defer ticker.Stop()
	for range ticker.C {
		if ts.db != nil {
			_ = ts.db.WithContext(context.Background()).
				Where("expires_at < ?", time.Now()).
				Delete(&malcomdb.DownloadToken{}).Error
			continue
		}
		ts.mu.Lock()
		now := time.Now()
		for tok, e := range ts.store {
			if now.After(e.expiresAt) {
				delete(ts.store, tok)
			}
		}
		ts.mu.Unlock()
	}
}
