package handlers

import (
	"testing"
	"time"
)

// TestIssueSession_ValidateSession_MultiUse: una sesión emitida debe validar múltiples
// veces (multi-uso) sin quedar consumida tras la primera lectura.
func TestIssueSession_ValidateSession_MultiUse(t *testing.T) {
	ts := NewTokenStore()
	token, expiresAt, err := ts.IssueSession(123)
	if err != nil {
		t.Fatalf("IssueSession: error inesperado: %v", err)
	}
	if token == "" {
		t.Fatal("IssueSession: token vacío")
	}
	if !expiresAt.After(time.Now()) {
		t.Fatalf("IssueSession: expiresAt debería estar en el futuro, obtuvo %v", expiresAt)
	}

	for i := 0; i < 3; i++ {
		chatID, ok := ts.ValidateSession(token)
		if !ok {
			t.Fatalf("ValidateSession: llamada #%d falló, esperaba válido", i+1)
		}
		if chatID != 123 {
			t.Fatalf("ValidateSession: chatID = %d, esperaba 123", chatID)
		}
	}
}

// TestValidateSession_ExpiredRejected: un token de sesión expirado debe rechazarse.
func TestValidateSession_ExpiredRejected(t *testing.T) {
	ts := NewTokenStore()
	token, _, err := ts.IssueSession(456)
	if err != nil {
		t.Fatalf("IssueSession: error inesperado: %v", err)
	}

	// Forzamos expiración manipulando la entrada en memoria directamente.
	ts.mu.Lock()
	e := ts.store[token]
	e.expiresAt = time.Now().Add(-1 * time.Minute)
	ts.store[token] = e
	ts.mu.Unlock()

	if _, ok := ts.ValidateSession(token); ok {
		t.Fatal("ValidateSession: esperaba rechazo de token expirado")
	}
}

// TestValidateSession_UnknownToken: un token inexistente debe rechazarse.
func TestValidateSession_UnknownToken(t *testing.T) {
	ts := NewTokenStore()
	if _, ok := ts.ValidateSession("token-que-no-existe"); ok {
		t.Fatal("ValidateSession: esperaba rechazo de token desconocido")
	}
}

// TestIssueMagicLink_ConsumeMagicLink_SingleUse: un magic-link válido se consume una sola
// vez; el segundo intento de consumo debe rechazarse.
func TestIssueMagicLink_ConsumeMagicLink_SingleUse(t *testing.T) {
	ts := NewTokenStore()
	token, err := ts.IssueMagicLink(789, "user@example.com")
	if err != nil {
		t.Fatalf("IssueMagicLink: error inesperado: %v", err)
	}

	chatID, email, ok := ts.ConsumeMagicLink(token)
	if !ok {
		t.Fatal("ConsumeMagicLink: esperaba éxito en primer consumo")
	}
	if chatID != 789 {
		t.Fatalf("ConsumeMagicLink: chatID = %d, esperaba 789", chatID)
	}
	if email != "user@example.com" {
		t.Fatalf("ConsumeMagicLink: email = %q, esperaba user@example.com", email)
	}

	if _, _, ok := ts.ConsumeMagicLink(token); ok {
		t.Fatal("ConsumeMagicLink: esperaba rechazo en segundo consumo (ya usado)")
	}
}

// TestConsumeMagicLink_ExpiredRejected: un magic-link fuera de su TTL debe rechazarse.
func TestConsumeMagicLink_ExpiredRejected(t *testing.T) {
	ts := NewTokenStore()
	token, err := ts.IssueMagicLink(111, "expired@example.com")
	if err != nil {
		t.Fatalf("IssueMagicLink: error inesperado: %v", err)
	}

	ts.mu.Lock()
	e := ts.store[token]
	e.expiresAt = time.Now().Add(-1 * time.Minute)
	ts.store[token] = e
	ts.mu.Unlock()

	if _, _, ok := ts.ConsumeMagicLink(token); ok {
		t.Fatal("ConsumeMagicLink: esperaba rechazo de token expirado")
	}
}

// TestConsumeMagicLink_UnknownToken: un token inexistente debe rechazarse.
func TestConsumeMagicLink_UnknownToken(t *testing.T) {
	ts := NewTokenStore()
	if _, _, ok := ts.ConsumeMagicLink("token-inexistente"); ok {
		t.Fatal("ConsumeMagicLink: esperaba rechazo de token desconocido")
	}
}

// TestIssueMagicLink_InvalidatesPrevious: emitir un nuevo magic-link para el mismo chat_id
// invalida el anterior (spec: "New request while a previous link is still valid" — solo
// un enlace válido por chat_id a la vez).
func TestIssueMagicLink_InvalidatesPrevious(t *testing.T) {
	ts := NewTokenStore()
	firstToken, err := ts.IssueMagicLink(222, "old@example.com")
	if err != nil {
		t.Fatalf("IssueMagicLink (primero): error inesperado: %v", err)
	}

	secondToken, err := ts.IssueMagicLink(222, "new@example.com")
	if err != nil {
		t.Fatalf("IssueMagicLink (segundo): error inesperado: %v", err)
	}
	if secondToken == firstToken {
		t.Fatal("IssueMagicLink: el segundo token no debería coincidir con el primero")
	}

	if _, _, ok := ts.ConsumeMagicLink(firstToken); ok {
		t.Fatal("ConsumeMagicLink: el primer token debería estar invalidado tras emitir el segundo")
	}

	chatID, email, ok := ts.ConsumeMagicLink(secondToken)
	if !ok {
		t.Fatal("ConsumeMagicLink: el segundo token debería seguir siendo válido")
	}
	if chatID != 222 || email != "new@example.com" {
		t.Fatalf("ConsumeMagicLink: got (chatID=%d, email=%q), esperaba (222, new@example.com)", chatID, email)
	}
}

// TestIssueMagicLink_DifferentChatIDsIndependent: emitir un magic-link para un chat_id
// distinto no debe invalidar el enlace vigente de otro chat_id.
func TestIssueMagicLink_DifferentChatIDsIndependent(t *testing.T) {
	ts := NewTokenStore()
	tokenA, err := ts.IssueMagicLink(1, "a@example.com")
	if err != nil {
		t.Fatalf("IssueMagicLink (A): error inesperado: %v", err)
	}
	_, err = ts.IssueMagicLink(2, "b@example.com")
	if err != nil {
		t.Fatalf("IssueMagicLink (B): error inesperado: %v", err)
	}

	if _, _, ok := ts.ConsumeMagicLink(tokenA); !ok {
		t.Fatal("ConsumeMagicLink: el token del chat_id 1 no debería verse afectado por el del chat_id 2")
	}
}
