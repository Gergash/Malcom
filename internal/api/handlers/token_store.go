// token_store.go: almacén en memoria de tokens de descarga con TTL.
// Cada token mapea a la ruta absoluta del archivo generado (PDF/Excel).
// Los tokens caducan a los 30 minutos y se limpian automáticamente.
package handlers

import (
	"crypto/rand"
	"encoding/hex"
	"sync"
	"time"
)

const tokenTTL = 30 * time.Minute

type tokenEntry struct {
	filePath  string
	expiresAt time.Time
}

// TokenStore es un almacén concurrente de tokens de descarga efímeros.
type TokenStore struct {
	mu    sync.Mutex
	store map[string]tokenEntry
}

// NewTokenStore crea un TokenStore e inicia el GC en background.
func NewTokenStore() *TokenStore {
	ts := &TokenStore{store: make(map[string]tokenEntry)}
	go ts.gc()
	return ts
}

// Store registra filePath y devuelve un token aleatorio de 32 caracteres hex.
func (ts *TokenStore) Store(filePath string) string {
	b := make([]byte, 16)
	_, _ = rand.Read(b)
	token := hex.EncodeToString(b)
	ts.mu.Lock()
	ts.store[token] = tokenEntry{filePath: filePath, expiresAt: time.Now().Add(tokenTTL)}
	ts.mu.Unlock()
	return token
}

// Resolve devuelve la ruta del archivo asociada al token si no expiró.
// Devuelve ("", false) si el token es inválido o expiró.
func (ts *TokenStore) Resolve(token string) (string, bool) {
	ts.mu.Lock()
	defer ts.mu.Unlock()
	e, ok := ts.store[token]
	if !ok || time.Now().After(e.expiresAt) {
		delete(ts.store, token)
		return "", false
	}
	return e.filePath, true
}

// gc elimina las entradas expiradas cada 5 minutos.
func (ts *TokenStore) gc() {
	ticker := time.NewTicker(5 * time.Minute)
	defer ticker.Stop()
	for range ticker.C {
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
