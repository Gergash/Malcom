// token_store.go: almacén de tokens de descarga con TTL.
// Soporta persistencia en PostgreSQL (DownloadToken) y fallback en memoria.
package handlers

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"strings"
	"sync"
	"time"

	malcomdb "github.com/powerups/insightflow-malcom/internal/db"
	"gorm.io/gorm"
)

const (
	standardTokenTTL  = 30 * time.Minute
	dashboardTokenTTL = 15 * time.Minute
)

type tokenEntry struct {
	chatID    int64
	resType   string
	filePath  string
	payload   *string
	expiresAt time.Time
	consumed  bool // solo dashboard en memoria: un solo uso efectivo
}

func ttlForResourceType(resourceType string) time.Duration {
	if strings.EqualFold(resourceType, "dashboard") {
		return dashboardTokenTTL
	}
	return standardTokenTTL
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
	expiresAt := time.Now().Add(ttlForResourceType(resourceType))

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
		chatID:    chatID,
		resType:   resourceType,
		filePath:  filePath,
		payload:   nil,
		expiresAt: expiresAt,
	}
	ts.mu.Unlock()
	return token
}

// StorePayload guarda JSON efímero (p. ej. sesión ECharts dashboard) bajo resourceType "dashboard".
func (ts *TokenStore) StorePayload(chatID int64, resourceType, jsonBody string) string {
	token := newTokenValue()
	expiresAt := time.Now().Add(ttlForResourceType(resourceType))
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

// PeekDashboardSession devuelve el payload del tablero si el token es válido, no expirado y aún no consumido.
func (ts *TokenStore) PeekDashboardSession(token string) (*ResolvedToken, bool) {
	if ts.db != nil {
		var e malcomdb.DownloadToken
		err := ts.db.WithContext(context.Background()).
			Where("token = ? AND resource_type = ?", token, "dashboard").
			First(&e).Error
		if err != nil {
			return nil, false
		}
		if time.Now().After(e.ExpiresAt) {
			_ = ts.db.WithContext(context.Background()).Delete(&e).Error
			return nil, false
		}
		if e.UsedAt != nil {
			return nil, false
		}
		if e.PayloadJSON == nil || strings.TrimSpace(*e.PayloadJSON) == "" {
			return nil, false
		}
		return &ResolvedToken{
			ChatID:       e.ChatID,
			FilePath:     e.FilePath,
			PayloadJSON:  e.PayloadJSON,
			ResourceType: e.ResourceType,
		}, true
	}

	ts.mu.Lock()
	defer ts.mu.Unlock()
	e, ok := ts.store[token]
	if !ok || time.Now().After(e.expiresAt) {
		delete(ts.store, token)
		return nil, false
	}
	if !strings.EqualFold(e.resType, "dashboard") || e.payload == nil || strings.TrimSpace(*e.payload) == "" {
		return nil, false
	}
	if e.consumed {
		return nil, false
	}
	return &ResolvedToken{
		ChatID:       e.chatID,
		FilePath:     e.filePath,
		PayloadJSON:  e.payload,
		ResourceType: e.resType,
	}, true
}

// LookupDashboardTokenChatID devuelve el chat_id de un token dashboard no expirado, aunque ya esté consumido.
// Permite distinguir 404 “roto” de 202 “pendiente” o 409 “refrescar enlace”.
func (ts *TokenStore) LookupDashboardTokenChatID(token string) (int64, bool) {
	if strings.TrimSpace(token) == "" {
		return 0, false
	}
	if ts.db != nil {
		var e malcomdb.DownloadToken
		err := ts.db.WithContext(context.Background()).
			Where("token = ? AND resource_type = ?", token, "dashboard").
			First(&e).Error
		if err != nil {
			return 0, false
		}
		if time.Now().After(e.ExpiresAt) {
			return 0, false
		}
		return e.ChatID, true
	}

	ts.mu.Lock()
	defer ts.mu.Unlock()
	e, ok := ts.store[token]
	if !ok || time.Now().After(e.expiresAt) {
		return 0, false
	}
	if !strings.EqualFold(e.resType, "dashboard") {
		return 0, false
	}
	return e.chatID, true
}

// MarkDashboardConsumed marca el token dashboard como usado (un solo acceso exitoso tras validar premium).
func (ts *TokenStore) MarkDashboardConsumed(token string) bool {
	now := time.Now().UTC()
	if ts.db != nil {
		r := ts.db.WithContext(context.Background()).
			Model(&malcomdb.DownloadToken{}).
			Where("token = ? AND resource_type = ? AND used_at IS NULL", token, "dashboard").
			Update("used_at", &now)
		return r.RowsAffected == 1
	}

	ts.mu.Lock()
	defer ts.mu.Unlock()
	e, ok := ts.store[token]
	if !ok || !strings.EqualFold(e.resType, "dashboard") || e.consumed {
		return false
	}
	e.consumed = true
	ts.store[token] = e
	return true
}

// ResolveFull devuelve ruta y/o payload JSON si el token sigue vigente.
// chart no marca used_at (múltiples GET). dashboard con JSON solo vía Peek/Mark o descarga legacy no-dashboard.
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
		if strings.EqualFold(rt, "dashboard") && e.PayloadJSON != nil && strings.TrimSpace(*e.PayloadJSON) != "" {
			if e.UsedAt != nil {
				return nil, false
			}
		}
		if rt != "chart" && rt != "dashboard" && e.UsedAt == nil {
			now := time.Now().UTC()
			_ = ts.db.WithContext(context.Background()).Model(&e).Update("used_at", &now).Error
		}
		return &ResolvedToken{
			ChatID:       e.ChatID,
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
	if strings.EqualFold(e.resType, "dashboard") && e.payload != nil && strings.TrimSpace(*e.payload) != "" {
		if e.consumed {
			return nil, false
		}
	}
	return &ResolvedToken{
		ChatID:       e.chatID,
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
