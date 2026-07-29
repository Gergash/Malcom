package handlers

// Pruebas de confusión de tipo de token: un token de sesión no debe ser aceptado como
// magic-link ni viceversa. Cubre tanto la ruta persistida en DB (helpers de
// token_store_db_test.go) como la ruta en memoria.

import "testing"

// TestValidateSession_DB_RejectsMagicLinkToken: un token magiclink no debe ser aceptado
// como sesión. La query real filtra por resource_type=session, así que contra un token de
// tipo distinto no hay fila que devolver.
func TestValidateSession_DB_RejectsMagicLinkToken(t *testing.T) {
	ts, mock := newMockTokenStore(t)

	token := newSessionTokenValue()
	expectSelectRow(mock, nil) // sin filas: no existe registro session con ese token
	if _, ok := ts.ValidateSession(token); ok {
		t.Fatal("ValidateSession: un token magiclink no debería validar como sesión")
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Fatalf("expectativas SQL no cumplidas: %v", err)
	}
}

// TestConsumeMagicLink_DB_RejectsSessionToken: un token de sesión no debe ser consumible
// como magic-link.
func TestConsumeMagicLink_DB_RejectsSessionToken(t *testing.T) {
	ts, mock := newMockTokenStore(t)

	token := newSessionTokenValue()
	expectSelectRow(mock, nil) // sin filas: no existe registro magiclink con ese token
	if _, _, ok := ts.ConsumeMagicLink(token); ok {
		t.Fatal("ConsumeMagicLink: un token de sesión no debería consumirse como magic-link")
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Fatalf("expectativas SQL no cumplidas: %v", err)
	}
}

// TestValidateSession_MemoryRejectsMagicLinkToken: mismo caso que arriba pero contra la
// ruta en memoria (ts.db == nil).
func TestValidateSession_MemoryRejectsMagicLinkToken(t *testing.T) {
	ts := NewTokenStore()
	token, err := ts.IssueMagicLink(1, "confused@example.com")
	if err != nil {
		t.Fatalf("IssueMagicLink: error inesperado: %v", err)
	}
	if _, ok := ts.ValidateSession(token); ok {
		t.Fatal("ValidateSession: un token magiclink no debería validar como sesión (memoria)")
	}
}

// TestConsumeMagicLink_MemoryRejectsSessionToken: mismo caso que arriba pero contra la
// ruta en memoria (ts.db == nil).
func TestConsumeMagicLink_MemoryRejectsSessionToken(t *testing.T) {
	ts := NewTokenStore()
	token, _, err := ts.IssueSession(1)
	if err != nil {
		t.Fatalf("IssueSession: error inesperado: %v", err)
	}
	if _, _, ok := ts.ConsumeMagicLink(token); ok {
		t.Fatal("ConsumeMagicLink: un token de sesión no debería consumirse como magic-link (memoria)")
	}
}
