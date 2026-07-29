package handlers

// Cobertura de la ruta persistida en DB (ts.db != nil) de los primitivos de sesión y
// magic-link. Los tests en token_store_test.go solo construyen el store vía
// NewTokenStore() (ts.db == nil), por lo que nunca ejercitan el guard atómico de un solo
// uso (UPDATE ... WHERE used_at IS NULL + RowsAffected != 1), la invalidación de un
// magic-link previo, ni el round-trip real de JSON marshal/unmarshal del email a través
// de PayloadJSON. Usamos go-sqlmock para simular *sql.DB y así ejercitar el código real de
// GORM/SQL que corre en producción vía NewPersistentTokenStore(gdb) en cmd/api/main.go.
//
// No perseguimos coincidencia exacta de SQL: usamos matchers regexp sueltos (solo
// prefijo/tabla) para no acoplar los tests a detalles de renderizado de GORM.

import (
	"testing"
	"time"

	"github.com/DATA-DOG/go-sqlmock"
	malcomdb "github.com/powerups/insightflow-malcom/internal/db"
	"gorm.io/driver/postgres"
	"gorm.io/gorm"
)

// downloadTokenColumns refleja el orden de columnas de malcomdb.DownloadToken tal como
// GORM las genera en "SELECT *" (mismo orden que el INSERT: id, token, file_path,
// payload_json, chat_id, resource_type, expires_at, used_at, created_at).
var downloadTokenColumns = []string{
	"id", "token", "file_path", "payload_json", "chat_id", "resource_type", "expires_at", "used_at", "created_at",
}

// newMockTokenStore crea un *TokenStore respaldado por un *gorm.DB con conexión mockeada
// (go-sqlmock), forzando la ruta `ts.db != nil` en todos los métodos bajo prueba.
func newMockTokenStore(t *testing.T) (*TokenStore, sqlmock.Sqlmock) {
	t.Helper()

	sqlDB, mock, err := sqlmock.New(sqlmock.QueryMatcherOption(sqlmock.QueryMatcherRegexp))
	if err != nil {
		t.Fatalf("sqlmock.New: %v", err)
	}
	t.Cleanup(func() { _ = sqlDB.Close() })

	gdb, err := gorm.Open(postgres.New(postgres.Config{
		Conn:                 sqlDB,
		PreferSimpleProtocol: true,
	}), &gorm.Config{SkipDefaultTransaction: true})
	if err != nil {
		t.Fatalf("gorm.Open: %v", err)
	}

	return &TokenStore{db: gdb, store: make(map[string]tokenEntry)}, mock
}

func expectInsertReturningID(mock sqlmock.Sqlmock, id int64) {
	mock.ExpectQuery(`INSERT INTO "download_tokens"`).
		WillReturnRows(sqlmock.NewRows([]string{"id"}).AddRow(id))
}

func expectSelectRow(mock sqlmock.Sqlmock, row *malcomdb.DownloadToken) {
	rows := sqlmock.NewRows(downloadTokenColumns)
	if row != nil {
		rows.AddRow(row.ID, row.Token, row.FilePath, row.PayloadJSON, row.ChatID, row.ResourceType, row.ExpiresAt, row.UsedAt, row.CreatedAt)
	}
	mock.ExpectQuery(`SELECT \* FROM "download_tokens"`).WillReturnRows(rows)
}

func expectUpdateUsedAt(mock sqlmock.Sqlmock, rowsAffected int64) {
	mock.ExpectExec(`UPDATE "download_tokens" SET`).WillReturnResult(sqlmock.NewResult(0, rowsAffected))
}

// TestIssueSession_ValidateSession_DB_HappyPath ejercita IssueSession + ValidateSession
// contra la ruta DB, y confirma que el token queda hasheado (no en texto plano) al
// persistirse (Fix 2).
func TestIssueSession_ValidateSession_DB_HappyPath(t *testing.T) {
	ts, mock := newMockTokenStore(t)

	expectInsertReturningID(mock, 1)
	token, expiresAt, err := ts.IssueSession(42)
	if err != nil {
		t.Fatalf("IssueSession: error inesperado: %v", err)
	}
	if token == "" {
		t.Fatal("IssueSession: token vacío")
	}
	if !expiresAt.After(time.Now()) {
		t.Fatalf("IssueSession: expiresAt debería estar en el futuro, obtuvo %v", expiresAt)
	}

	expectSelectRow(mock, &malcomdb.DownloadToken{
		ID:           1,
		Token:        hashTokenValue(token),
		ChatID:       42,
		ResourceType: resourceTypeSession,
		ExpiresAt:    expiresAt,
	})
	chatID, ok := ts.ValidateSession(token)
	if !ok {
		t.Fatal("ValidateSession: esperaba éxito")
	}
	if chatID != 42 {
		t.Fatalf("ValidateSession: chatID = %d, esperaba 42", chatID)
	}

	if err := mock.ExpectationsWereMet(); err != nil {
		t.Fatalf("expectativas SQL no cumplidas: %v", err)
	}
}

// TestValidateSession_DB_ExpiredRejected: un token de sesión expirado, aunque exista en
// DB, debe rechazarse.
func TestValidateSession_DB_ExpiredRejected(t *testing.T) {
	ts, mock := newMockTokenStore(t)

	token := newSessionTokenValue()
	expectSelectRow(mock, &malcomdb.DownloadToken{
		ID:           1,
		Token:        hashTokenValue(token),
		ChatID:       99,
		ResourceType: resourceTypeSession,
		ExpiresAt:    time.Now().Add(-1 * time.Minute),
	})

	if _, ok := ts.ValidateSession(token); ok {
		t.Fatal("ValidateSession: esperaba rechazo de token expirado")
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Fatalf("expectativas SQL no cumplidas: %v", err)
	}
}

// TestIssueMagicLink_ConsumeMagicLink_DB_HappyPath ejercita el round-trip real de
// json.Marshal/Unmarshal del email a través de PayloadJSON (no solo el campo en memoria).
func TestIssueMagicLink_ConsumeMagicLink_DB_HappyPath(t *testing.T) {
	ts, mock := newMockTokenStore(t)

	// IssueMagicLink: primero intenta invalidar un magic-link previo (no hay ninguno),
	// luego inserta el nuevo.
	expectUpdateUsedAt(mock, 0)
	expectInsertReturningID(mock, 1)

	token, err := ts.IssueMagicLink(555, "user@example.com")
	if err != nil {
		t.Fatalf("IssueMagicLink: error inesperado: %v", err)
	}

	payloadJSON := `{"email":"user@example.com"}`
	expectSelectRow(mock, &malcomdb.DownloadToken{
		ID:           1,
		Token:        hashTokenValue(token),
		PayloadJSON:  &payloadJSON,
		ChatID:       555,
		ResourceType: resourceTypeMagicLink,
		ExpiresAt:    time.Now().Add(magicLinkTokenTTL),
	})
	expectUpdateUsedAt(mock, 1)

	chatID, email, ok := ts.ConsumeMagicLink(token)
	if !ok {
		t.Fatal("ConsumeMagicLink: esperaba éxito")
	}
	if chatID != 555 {
		t.Fatalf("ConsumeMagicLink: chatID = %d, esperaba 555", chatID)
	}
	if email != "user@example.com" {
		t.Fatalf("ConsumeMagicLink: email = %q, esperaba user@example.com (round-trip JSON real)", email)
	}

	if err := mock.ExpectationsWereMet(); err != nil {
		t.Fatalf("expectativas SQL no cumplidas: %v", err)
	}
}

// TestConsumeMagicLink_DB_SingleUse prueba el guard atómico real: un segundo intento de
// consumo debe fallar porque el UPDATE ... WHERE used_at IS NULL ya no afecta filas
// (RowsAffected != 1), no por lógica en memoria.
func TestConsumeMagicLink_DB_SingleUse(t *testing.T) {
	ts, mock := newMockTokenStore(t)

	token := newSessionTokenValue()
	payloadJSON := `{"email":"single@example.com"}`
	entry := &malcomdb.DownloadToken{
		ID:           7,
		Token:        hashTokenValue(token),
		PayloadJSON:  &payloadJSON,
		ChatID:       321,
		ResourceType: resourceTypeMagicLink,
		ExpiresAt:    time.Now().Add(magicLinkTokenTTL),
	}

	// Primer consumo: la fila aún no tiene used_at, el UPDATE atómico afecta 1 fila.
	expectSelectRow(mock, entry)
	expectUpdateUsedAt(mock, 1)

	chatID, email, ok := ts.ConsumeMagicLink(token)
	if !ok {
		t.Fatal("ConsumeMagicLink: esperaba éxito en primer consumo")
	}
	if chatID != 321 || email != "single@example.com" {
		t.Fatalf("ConsumeMagicLink: got (chatID=%d, email=%q)", chatID, email)
	}

	// Segundo consumo: la fila sigue existiendo (SELECT la encuentra), pero el UPDATE
	// atómico ya no matchea (used_at IS NULL falla) → RowsAffected = 0 → rechazo real,
	// no una bandera en memoria.
	usedAt := time.Now().UTC()
	entry.UsedAt = &usedAt
	expectSelectRow(mock, entry)
	expectUpdateUsedAt(mock, 0)

	if _, _, ok := ts.ConsumeMagicLink(token); ok {
		t.Fatal("ConsumeMagicLink: esperaba rechazo en segundo consumo (guard atómico real)")
	}

	if err := mock.ExpectationsWereMet(); err != nil {
		t.Fatalf("expectativas SQL no cumplidas: %v", err)
	}
}

// TestIssueMagicLink_DB_InvalidatesPrevious confirma que emitir un magic-link ejecuta el
// UPDATE de invalidación (soft) del enlace previo antes del INSERT del nuevo, contra la
// ruta DB real.
func TestIssueMagicLink_DB_InvalidatesPrevious(t *testing.T) {
	ts, mock := newMockTokenStore(t)

	// Existe un magic-link previo sin consumir para el mismo chat_id → 1 fila afectada.
	expectUpdateUsedAt(mock, 1)
	expectInsertReturningID(mock, 2)

	if _, err := ts.IssueMagicLink(777, "second@example.com"); err != nil {
		t.Fatalf("IssueMagicLink: error inesperado: %v", err)
	}

	if err := mock.ExpectationsWereMet(); err != nil {
		t.Fatalf("expectativas SQL no cumplidas (invalidación + insert en orden): %v", err)
	}
}
