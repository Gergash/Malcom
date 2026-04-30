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
	payload   *string
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
			PayloadJSON:  nil,
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
		filePath: filePath,
		payload:  nil,
		expiresAt: expiresAt,
	}
	ts.mu.Unlock()
	return token
}

// StorePayload guarda JSON efímero (p. ej. sesión ECharts dashboard) bajo resourceType "dashboard".
func (ts *TokenStore) StorePayload(chatID int64, resourceType, jsonBody string) string {
	token := newTokenValue()
	expiresAt := time.Now().Add(tokenTTL)
	body := jsonBody

	if ts.db != nil {
		entry := &malcomdb.DownloadToken{
			Token:        token,
			FilePath:     "",
			PayloadJSON:  &body,
			ChatID:       chatID,
			ResourceType: resourceType,
			ExpiresAt:    expiresAt,
		}
		if err := ts.db.WithContext(context.Background()).Create(entry).Error; err == nil {
			return token
		}
	}

	ts.mu.Lock()
	ts.store[token] = tokenEntry{
		chatID:    chatID,
		resType:   resourceType,
		filePath:  "",
		payload:   &body,
		expiresAt: expiresAt,
	}
	ts.mu.Unlock()
	return token
}

// ResolveFull devuelve ruta y/o payload JSON si el token sigue vigente.
// chart y dashboard no marcan used_at (múltiples GET).
func (ts *TokenStore) ResolveFull(token string) (*ResolvedToken, bool) {
	if ts.db != nil {
		var e malcomdb.DownloadToken
		err := ts.db.WithContext(context.Background()).Where("token = ?", token).First(&e).Error
		if err != nil {
			return nil, false
		}
		if time.Now().After(e.ExpiresAt) {
			_ = ts.db.WithContext(context.Background()).Delete(&e).Error
			return nil, false
		}
		rt := e.ResourceType
		if rt != "chart" && rt != "dashboard" && e.UsedAt == nil {
			now := time.Now().UTC()
			_ = ts.db.WithContext(context.Background()).Model(&e).Update("used_at", &now).Error
		}
		return &ResolvedToken{
			FilePath:     e.FilePath,
			PayloadJSON:  e.PayloadJSON,
			ResourceType: rt,
		}, true
	}

	ts.mu.Lock()
	defer ts.mu.Unlock()
	e, ok := ts.store[token]
	if !ok || time.Now().After(e.expiresAt) {
		delete(ts.store, token)
		return nil, false
	}
	return &ResolvedToken{
		FilePath:     e.filePath,
		PayloadJSON:  e.payload,
		ResourceType: e.resType,
	}, true
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
