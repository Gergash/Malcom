// token_store.go: almacén de tokens de descarga con TTL.
// Soporta persistencia en PostgreSQL (DownloadToken) y fallback en memoria.
package handlers

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"strings"
	"sync"
	"time"

	malcomdb "github.com/powerups/insightflow-malcom/internal/db"
	"gorm.io/gorm"
)

const (
	standardTokenTTL  = 30 * time.Minute
	dashboardTokenTTL = 15 * time.Minute
	sessionTokenTTL   = 7 * 24 * time.Hour
	magicLinkTokenTTL = 15 * time.Minute

	resourceTypeSession   = "session"
	resourceTypeMagicLink = "magiclink"
)

type tokenEntry struct {
	chatID    int64
	resType   string
	filePath  string
	payload   *string
	email     *string // solo magiclink en memoria: email pendiente de verificar
	expiresAt time.Time
	consumed  bool // dashboard/magiclink en memoria: un solo uso efectivo (session ignora este flag)
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

// magicLinkPayload es el JSON guardado en DownloadToken.PayloadJSON para tokens magiclink.
type magicLinkPayload struct {
	Email string `json:"email"`
}

func newSessionTokenValue() string {
	// 32 bytes = 64 hex chars; igual longitud/entropía que el magic-link (Q3 del diseño).
	b := make([]byte, 32)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}

// hashTokenValue deriva el valor persistido/indexado para tokens de sesión y magic-link.
// Estos tokens son credenciales bearer reutilizables (sesión, 7 días) o de un solo uso con
// ventana corta (magic-link, 15 min); a diferencia de los tokens de descarga de corta vida
// de `Store`/`StorePayload`, una fuga de la base de datos permitiría suplantar a un usuario
// mientras el token siga vigente. Por eso solo se persiste/indexa el hash SHA-256; el valor
// crudo nunca toca disco y únicamente se devuelve al emisor original (respuesta HTTP / URL
// del magic-link). Se aplica también a la ruta en memoria (mapa `ts.store`) por consistencia
// entre ambos caminos de código, aunque hoy esa ruta solo se ejercita en tests/fallback local.
func hashTokenValue(token string) string {
	sum := sha256.Sum256([]byte(token))
	return hex.EncodeToString(sum[:])
}

// IssueSession crea un token de sesión reutilizable (multi-uso, TTL 7 días) ligado a chatID.
// A diferencia de los tokens de descarga, NO marca used_at/consumed: debe autorizar múltiples
// acciones (p. ej. BoldCheckout) durante toda la ventana de 7 días.
func (ts *TokenStore) IssueSession(chatID int64) (string, time.Time, error) {
	token := newSessionTokenValue()
	tokenHash := hashTokenValue(token)
	expiresAt := time.Now().Add(sessionTokenTTL)

	if ts.db != nil {
		entry := &malcomdb.DownloadToken{
			Token:        tokenHash,
			FilePath:     "",
			PayloadJSON:  nil,
			ChatID:       chatID,
			ResourceType: resourceTypeSession,
			ExpiresAt:    expiresAt,
		}
		if err := ts.db.WithContext(context.Background()).Create(entry).Error; err != nil {
			return "", time.Time{}, fmt.Errorf("token_store: IssueSession: %w", err)
		}
		return token, expiresAt, nil
	}

	ts.mu.Lock()
	ts.store[tokenHash] = tokenEntry{
		chatID:    chatID,
		resType:   resourceTypeSession,
		expiresAt: expiresAt,
	}
	ts.mu.Unlock()
	return token, expiresAt, nil
}

// ValidateSession valida un token de sesión: existe, resource_type=session y no expiró.
// Ignora used_at/consumed deliberadamente (sesión multi-uso, ver IssueSession).
func (ts *TokenStore) ValidateSession(token string) (int64, bool) {
	if strings.TrimSpace(token) == "" {
		return 0, false
	}
	tokenHash := hashTokenValue(token)
	if ts.db != nil {
		var e malcomdb.DownloadToken
		err := ts.db.WithContext(context.Background()).
			Where("token = ? AND resource_type = ?", tokenHash, resourceTypeSession).
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
	e, ok := ts.store[tokenHash]
	if !ok || !strings.EqualFold(e.resType, resourceTypeSession) || time.Now().After(e.expiresAt) {
		return 0, false
	}
	return e.chatID, true
}

// IssueMagicLink crea un token de un solo uso (TTL 15 min) ligado a chatID + email.
// Antes de emitir uno nuevo, invalida cualquier magic-link vigente y no consumido para el
// mismo chatID (spec: "New request while a previous link is still valid" — un solo enlace
// válido por chat_id a la vez).
func (ts *TokenStore) IssueMagicLink(chatID int64, email string) (string, error) {
	if ts.db != nil {
		ctx := context.Background()
		// Invalida (soft) cualquier magic-link previo vigente para este chat_id marcándolo usado,
		// para que ConsumeMagicLink lo rechace sin necesidad de borrarlo.
		now := time.Now().UTC()
		if err := ts.db.WithContext(ctx).
			Model(&malcomdb.DownloadToken{}).
			Where("chat_id = ? AND resource_type = ? AND used_at IS NULL AND expires_at > ?", chatID, resourceTypeMagicLink, now).
			Update("used_at", &now).Error; err != nil {
			return "", fmt.Errorf("token_store: IssueMagicLink: invalidar previos: %w", err)
		}

		payloadBytes, err := json.Marshal(magicLinkPayload{Email: email})
		if err != nil {
			return "", fmt.Errorf("token_store: IssueMagicLink: %w", err)
		}
		payload := string(payloadBytes)

		token := newSessionTokenValue()
		entry := &malcomdb.DownloadToken{
			Token:        hashTokenValue(token),
			FilePath:     "",
			PayloadJSON:  &payload,
			ChatID:       chatID,
			ResourceType: resourceTypeMagicLink,
			ExpiresAt:    time.Now().Add(magicLinkTokenTTL),
		}
		if err := ts.db.WithContext(ctx).Create(entry).Error; err != nil {
			return "", fmt.Errorf("token_store: IssueMagicLink: %w", err)
		}
		return token, nil
	}

	ts.mu.Lock()
	defer ts.mu.Unlock()
	now := time.Now()
	for tok, e := range ts.store {
		if e.chatID == chatID && strings.EqualFold(e.resType, resourceTypeMagicLink) && !e.consumed && now.Before(e.expiresAt) {
			e.consumed = true
			ts.store[tok] = e
		}
	}
	token := newSessionTokenValue()
	emailCopy := email
	ts.store[hashTokenValue(token)] = tokenEntry{
		chatID:    chatID,
		resType:   resourceTypeMagicLink,
		email:     &emailCopy,
		expiresAt: now.Add(magicLinkTokenTTL),
	}
	return token, nil
}

// ConsumeMagicLink valida y marca usado (atómicamente) un token magiclink. Rechaza tokens
// desconocidos, expirados o ya consumidos, sin distinguir el motivo (spec: sin revelar info).
func (ts *TokenStore) ConsumeMagicLink(token string) (int64, string, bool) {
	if strings.TrimSpace(token) == "" {
		return 0, "", false
	}
	tokenHash := hashTokenValue(token)
	if ts.db != nil {
		ctx := context.Background()

		var e malcomdb.DownloadToken
		err := ts.db.WithContext(ctx).
			Where("token = ? AND resource_type = ?", tokenHash, resourceTypeMagicLink).
			First(&e).Error
		if err != nil {
			return 0, "", false
		}
		if time.Now().After(e.ExpiresAt) {
			return 0, "", false
		}
		if e.PayloadJSON == nil {
			return 0, "", false
		}
		var payload magicLinkPayload
		if err := json.Unmarshal([]byte(*e.PayloadJSON), &payload); err != nil {
			return 0, "", false
		}

		now := time.Now().UTC()
		res := ts.db.WithContext(ctx).
			Model(&malcomdb.DownloadToken{}).
			Where("token = ? AND resource_type = ? AND used_at IS NULL", tokenHash, resourceTypeMagicLink).
			Update("used_at", &now)
		if res.Error != nil || res.RowsAffected != 1 {
			// Ya consumido (o carrera perdida) → rechazar, no revelar el motivo exacto.
			return 0, "", false
		}
		return e.ChatID, payload.Email, true
	}

	ts.mu.Lock()
	defer ts.mu.Unlock()
	e, ok := ts.store[tokenHash]
	if !ok || !strings.EqualFold(e.resType, resourceTypeMagicLink) || time.Now().After(e.expiresAt) {
		return 0, "", false
	}
	if e.consumed || e.email == nil {
		return 0, "", false
	}
	e.consumed = true
	ts.store[tokenHash] = e
	return e.chatID, *e.email, true
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
