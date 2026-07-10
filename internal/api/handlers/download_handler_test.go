package handlers

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"

	"github.com/gin-gonic/gin"
	malcomdb "github.com/powerups/insightflow-malcom/internal/db"
	"github.com/powerups/insightflow-malcom/internal/db/repositories"
)

// stubUserRepo implementa repositories.UserRepository para probar el gate premium
// del download_handler. Solo IsPremiumForChat tiene lógica real; el resto son stubs.
type stubUserRepo struct {
	premium bool
}

func (s *stubUserRepo) BumpAndCheck(ctx context.Context, chatID int64, username *string) (*repositories.UserState, error) {
	return &repositories.UserState{IsPremium: s.premium}, nil
}
func (s *stubUserRepo) GetState(ctx context.Context, chatID *int64, email *string) (*repositories.UserState, error) {
	return &repositories.UserState{IsPremium: s.premium}, nil
}
func (s *stubUserRepo) LinkEmail(ctx context.Context, chatID int64, email string) error { return nil }
func (s *stubUserRepo) ActivatePremium(ctx context.Context, chatID *int64, email *string) (*repositories.PaymentUser, error) {
	return &repositories.PaymentUser{IsPremium: true}, nil
}
func (s *stubUserRepo) IsPremiumForChat(ctx context.Context, chatID int64) (bool, error) {
	return s.premium, nil
}
func (s *stubUserRepo) SaveLastDashboardSnapshot(ctx context.Context, chatID int64, payloadJSON string) error {
	return nil
}
func (s *stubUserRepo) GetLastDashboardSnapshot(ctx context.Context, chatID int64) (string, error) {
	return "", nil
}
func (s *stubUserRepo) GetUserIDForChat(ctx context.Context, chatID int64) (*uint, error) {
	return nil, nil
}
func (s *stubUserRepo) RecordUploadedFile(ctx context.Context, file *malcomdb.UserFile) error {
	return nil
}

// writeAsset crea data/{chatID}/{name} con contenido dummy y devuelve su ruta absoluta.
func writeAsset(t *testing.T, dataDir string, chatID int64, name string) string {
	t.Helper()
	chatDir := filepath.Join(dataDir, "123")
	if err := os.MkdirAll(chatDir, 0o755); err != nil {
		t.Fatal(err)
	}
	p := filepath.Join(chatDir, name)
	if err := os.WriteFile(p, []byte("dummy-content"), 0o644); err != nil {
		t.Fatal(err)
	}
	return p
}

// doDownload ejecuta DownloadHandler.Download contra un token y devuelve el recorder.
func doDownload(t *testing.T, h *DownloadHandler, token string) *httptest.ResponseRecorder {
	t.Helper()
	gin.SetMode(gin.TestMode)
	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Request = httptest.NewRequest(http.MethodGet, "/download/"+token, nil)
	c.Params = gin.Params{{Key: "token", Value: token}}
	h.Download(c)
	return w
}

// Un usuario free NO puede descargar un reporte PDF: el gate devuelve 403.
func TestDownload_PDF_BlockedForFreeUser(t *testing.T) {
	dir := t.TempDir()
	path := writeAsset(t, dir, 123, "reporte_final.pdf")
	tokens := NewTokenStore()
	token := tokens.Store(123, "pdf", path)
	h := NewDownloadHandler(tokens, &stubUserRepo{premium: false}, dir)

	w := doDownload(t, h, token)
	if w.Code != http.StatusForbidden {
		t.Fatalf("free/pdf: esperaba 403, obtuvo %d (body=%s)", w.Code, w.Body.String())
	}
}

// Mismo bloqueo para Excel en usuario free.
func TestDownload_Excel_BlockedForFreeUser(t *testing.T) {
	dir := t.TempDir()
	path := writeAsset(t, dir, 123, "reporte_final.xlsx")
	tokens := NewTokenStore()
	token := tokens.Store(123, "excel", path)
	h := NewDownloadHandler(tokens, &stubUserRepo{premium: false}, dir)

	w := doDownload(t, h, token)
	if w.Code != http.StatusForbidden {
		t.Fatalf("free/excel: esperaba 403, obtuvo %d (body=%s)", w.Code, w.Body.String())
	}
}

// Un usuario premium SÍ descarga el PDF: 200 OK.
func TestDownload_PDF_AllowedForPremiumUser(t *testing.T) {
	dir := t.TempDir()
	path := writeAsset(t, dir, 123, "reporte_final.pdf")
	tokens := NewTokenStore()
	token := tokens.Store(123, "pdf", path)
	h := NewDownloadHandler(tokens, &stubUserRepo{premium: true}, dir)

	w := doDownload(t, h, token)
	if w.Code != http.StatusOK {
		t.Fatalf("premium/pdf: esperaba 200, obtuvo %d (body=%s)", w.Code, w.Body.String())
	}
}

// Las gráficas (chart) siguen libres para todos: un free las descarga con 200.
func TestDownload_Chart_AllowedForFreeUser(t *testing.T) {
	dir := t.TempDir()
	path := writeAsset(t, dir, 123, "output_plot_123.png")
	tokens := NewTokenStore()
	token := tokens.Store(123, "chart", path)
	h := NewDownloadHandler(tokens, &stubUserRepo{premium: false}, dir)

	w := doDownload(t, h, token)
	if w.Code != http.StatusOK {
		t.Fatalf("free/chart: esperaba 200, obtuvo %d (body=%s)", w.Code, w.Body.String())
	}
}
