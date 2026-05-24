// chat_handler.go: endpoints principales de conversación y subida de archivos.
// Reemplaza app/api/routes/chat.py
//
// POST /api/v1/chat           → enviar mensaje al agente de análisis
// POST /api/v1/chat/upload    → subir archivo para análisis
// GET  /api/v1/chat/:chat_id/credits → consultar créditos sin modificarlos
package handlers

import (
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/powerups/insightflow-malcom/internal/api/types"
	malcomdb "github.com/powerups/insightflow-malcom/internal/db"
	"github.com/powerups/insightflow-malcom/internal/db/repositories"
	"github.com/powerups/insightflow-malcom/internal/filesystem"
	"github.com/powerups/insightflow-malcom/internal/worker"
)

// ChatHandler agrupa las dependencias de los endpoints de chat.
type ChatHandler struct {
	userRepo         repositories.UserRepository
	convRepo         repositories.ConversationRepository
	worker           worker.Client
	dataDir          string // ruta absoluta al directorio data/ del proyecto
	tokens           *TokenStore
	enablePublicData bool // si true, URLs de gráficas vía /data/...; si false, vía /download/:token
	maxUploadBytes   int64
	// devForcePremium: SOLO DESARROLLO. Si true, todos los chats actúan como premium
	// (paywall desactivado, ECharts habilitado, multi-gráfica, descargas, dashboard URL).
	// Controlado por DEV_FORCE_PREMIUM en .env. Mantener false en producción.
	devForcePremium bool
}

// NewChatHandler construye el handler con sus dependencias.
func NewChatHandler(
	userRepo repositories.UserRepository,
	convRepo repositories.ConversationRepository,
	workerClient worker.Client,
	dataDir string,
	tokens *TokenStore,
	enablePublicData bool,
	maxUploadBytes int64,
	devForcePremium bool,
) *ChatHandler {
	if maxUploadBytes <= 0 {
		maxUploadBytes = 32 << 20
	}
	return &ChatHandler{
		userRepo:         userRepo,
		convRepo:         convRepo,
		worker:           workerClient,
		dataDir:          dataDir,
		tokens:           tokens,
		enablePublicData: enablePublicData,
		maxUploadBytes:   maxUploadBytes,
		devForcePremium:  devForcePremium,
	}
}

// ── POST /api/v1/chat ─────────────────────────────────────────────────────────

// Chat procesa un mensaje del usuario.
//
// Flujo (espeja chat.py):
//  1. Verificar/crear usuario y evaluar paywall (bump_and_check).
//  2. Si paywall → respuesta inmediata sin llamar al worker.
//  3. Persistir mensaje del usuario en el historial.
//  4. Llamar al Worker Python (Orchestrator/AnalystAgent).
//  5. Persistir respuesta del asistente.
//  6. Resolver URL pública de la gráfica si existe.
//  7. Retornar ChatResponse.
func (h *ChatHandler) Chat(c *gin.Context) {
	var req types.ChatRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusUnprocessableEntity, types.ErrorResponse{Detail: err.Error()})
		return
	}

	ctx := c.Request.Context()

	// 1+2 · Verificar créditos
	creditStatus, err := h.userRepo.BumpAndCheck(ctx, req.ChatID, req.Username)
	if err != nil {
		c.JSON(http.StatusInternalServerError, types.ErrorResponse{
			Detail: fmt.Sprintf("Error verificando créditos: %v", err),
		})
		return
	}

	// Modo desarrollo: tratar todos los chats como premium (sin paywall ni límites).
	// Activado por DEV_FORCE_PREMIUM=true en .env. NO usar en producción.
	if h.devForcePremium && creditStatus != nil {
		creditStatus.IsPremium = true
		creditStatus.Paywall = false
		if creditStatus.CreditsRemaining < 1 {
			creditStatus.CreditsRemaining = 9999
		}
		slog.Debug("DEV_FORCE_PREMIUM activo: chat tratado como premium", "chat_id", req.ChatID)
	}

	if creditStatus.Paywall {
		imgURL := (*string)(nil)
		c.JSON(http.StatusOK, types.ChatResponse{
			Response: "Has alcanzado el límite gratuito de análisis.\n\n" +
				"Activa el plan premium para desbloquear análisis ilimitados " +
				"y reportes avanzados (PDF / Excel).",
			Paywall:          true,
			CreditsRemaining: 0,
			ImageURL:         imgURL,
		})
		return
	}

	// 3 · Persistir mensaje del usuario
	if err := h.convRepo.AddMessage(ctx, req.ChatID, "user", req.Message); err != nil {
		c.JSON(http.StatusInternalServerError, types.ErrorResponse{
			Detail: fmt.Sprintf("Error guardando mensaje: %v", err),
		})
		return
	}

	// 4 · Gatekeeper: construir ReportConfig desde el tier/perfil real del usuario (DB es la autoridad).
	// El frontend NO puede auto-upgradear enviando tier="premium" en el JSON.
	rc := buildTierConfig(req.ReportConfig, creditStatus)

	// 5 · Worker: strict data si ya hay archivos del usuario en data/{chat_id}/
	requireStrict := filesystem.HasUploadedDataFiles(h.dataDir, req.ChatID)
	result, err := h.worker.ProcessMessage(ctx, req.ChatID, req.Message, rc, requireStrict)
	if err != nil {
		c.JSON(http.StatusInternalServerError, types.ErrorResponse{
			Detail: fmt.Sprintf("Error procesando la consulta: %v", err),
		})
		return
	}

	// 6 · Persistir respuesta del asistente
	if err := h.convRepo.AddMessage(ctx, req.ChatID, "assistant", result.Response); err != nil {
		_ = err // No bloqueamos la respuesta por un fallo de persistencia de historial
	}

	// 7 · Enforcement duro (tier) + colección de gráficas para UI.
	cid := strconv.FormatInt(req.ChatID, 10)
	enforcedCharts := enforceChartPolicy(result.ChartPaths, result.ChartPath, rc, creditStatus.IsPremium)
	chartURLs := make([]string, 0, len(enforcedCharts))
	base := publicBaseURL(c)
	for _, p := range enforcedCharts {
		if h.enablePublicData {
			chartURLs = append(chartURLs, chartImageURL(c, cid, filepath.Base(p)))
		} else {
			tok := h.tokens.Store(req.ChatID, "chart", p)
			chartURLs = append(chartURLs, base+"/download/"+tok)
		}
	}
	var imageURL *string
	if len(chartURLs) > 0 {
		imageURL = &chartURLs[0]
	}

	// 8 · Enlaces de descarga tokenizados + artefactos
	var downloadURL *string
	var downloadLabel string
	artifacts := make([]types.ArtifactInfo, 0, len(chartURLs)+2)
	for i, u := range chartURLs {
		label := fmt.Sprintf("Ver Gráfica %d", i+1)
		artifacts = append(artifacts, types.ArtifactInfo{Type: "chart", URL: u, Label: label})
	}
	reportPath := result.PDFPath
	reportType := "pdf"
	if reportPath == "" {
		reportPath = result.ExcelPath
		reportType = "excel"
	}
	if reportPath != "" {
		if _, statErr := os.Stat(reportPath); statErr == nil {
			token := h.tokens.Store(req.ChatID, reportType, reportPath)
			u := publicBaseURL(c) + "/download/" + token
			downloadURL = &u
			if creditStatus.IsPremium {
				downloadLabel = "Descargar Dashboard Corporativo ✦"
			} else {
				downloadLabel = "Descargar Reporte Básico"
			}
			artifacts = append(artifacts, types.ArtifactInfo{
				Type:  reportType,
				URL:   u,
				Label: downloadLabel,
			})
		}
	}

	// 8b · Dashboard premium (ECharts): solo premium; token de sesión para /dashboard
	var dashboardURL *string
	var echartsOpt json.RawMessage
	if creditStatus.IsPremium && len(result.EChartsOption) > 0 {
		echartsOpt = result.EChartsOption
		wrap, err := json.Marshal(map[string]json.RawMessage{"echarts_option": result.EChartsOption})
		if err == nil {
			tok := h.tokens.StorePayload(req.ChatID, "dashboard", string(wrap))
			u := base + "/dashboard?token=" + tok
			dashboardURL = &u
			if err := h.userRepo.SaveLastDashboardSnapshot(ctx, req.ChatID, string(wrap)); err != nil {
				slog.Warn("SaveLastDashboardSnapshot", "error", err, "chat_id", req.ChatID)
			}
			artifacts = append(artifacts, types.ArtifactInfo{
				Type:  "dashboard",
				URL:   u,
				Label: "Abrir dashboard interactivo (ECharts)",
			})
		}
	}

	// 9 · Respuesta
	out := types.ChatResponse{
		Response:         result.Response,
		HasPDF:           result.HasPDF,
		HasExcel:         result.HasExcel,
		HasChart:         result.HasChart,
		Paywall:          false,
		CreditsRemaining: creditStatus.CreditsRemaining,
		ImageURL:         imageURL,
		DownloadURL:      downloadURL,
		DownloadLabel:    downloadLabel,
		ChartURLs:        chartURLs,
		Artifacts:        artifacts,
		DashboardURL:     dashboardURL,
	}
	if len(echartsOpt) > 0 {
		out.EChartsOption = echartsOpt
	}
	c.JSON(http.StatusOK, out)
}

// ── POST /api/v1/chat/upload ──────────────────────────────────────────────────

// UploadFile recibe un archivo multipart, lo escribe en un temporal
// y lo delega al Worker Python para ingestión/indexación.
func (h *ChatHandler) UploadFile(c *gin.Context) {
	// Leer el chat_id del form
	chatIDStr := c.PostForm("chat_id")
	chatID, err := strconv.ParseInt(chatIDStr, 10, 64)
	if err != nil || chatID == 0 {
		c.JSON(http.StatusUnprocessableEntity, types.ErrorResponse{
			Detail: "chat_id es obligatorio y debe ser un entero válido",
		})
		return
	}

	// Leer el archivo del form
	fh, err := c.FormFile("file")
	if err != nil {
		c.JSON(http.StatusUnprocessableEntity, types.ErrorResponse{
			Detail: "Campo 'file' ausente o inválido",
		})
		return
	}

	if h.maxUploadBytes > 0 && fh.Size > h.maxUploadBytes {
		c.JSON(http.StatusRequestEntityTooLarge, types.ErrorResponse{
			Detail: "El archivo supera el tamaño máximo permitido.",
		})
		return
	}

	// Archivo en data/.upload-tmp/ para que el worker Python (mismo volumen Docker) pueda leerlo.
	uploadDir := filepath.Join(h.dataDir, ".upload-tmp")
	if err := os.MkdirAll(uploadDir, 0o755); err != nil {
		c.JSON(http.StatusInternalServerError, types.ErrorResponse{Detail: "No se pudo crear directorio de subidas"})
		return
	}
	baseName := filepath.Base(fh.Filename)
	if baseName == "" || baseName == "." {
		baseName = "archivo"
	}
	ext := strings.ToLower(filepath.Ext(baseName))
	if ext == "" {
		ext = ".bin"
	}
	storedName := uuid.New().String() + ext
	tmpPath := filepath.Join(uploadDir, storedName)
	defer os.Remove(tmpPath)

	out, err := os.Create(tmpPath)
	if err != nil {
		c.JSON(http.StatusInternalServerError, types.ErrorResponse{
			Detail: "No se pudo crear archivo temporal",
		})
		return
	}

	src, err := fh.Open()
	if err != nil {
		out.Close()
		c.JSON(http.StatusInternalServerError, types.ErrorResponse{Detail: err.Error()})
		return
	}
	defer src.Close()

	if _, err := io.Copy(out, src); err != nil {
		out.Close()
		c.JSON(http.StatusInternalServerError, types.ErrorResponse{Detail: err.Error()})
		return
	}
	out.Close()

	if err := validateUploadMIME(tmpPath, fh.Filename); err != nil {
		c.JSON(http.StatusUnprocessableEntity, types.ErrorResponse{Detail: err.Error()})
		return
	}

	// Delegar ingestión al Worker Python
	ctx := c.Request.Context()
	result, err := h.worker.IngestFile(ctx, chatID, tmpPath, storedName, baseName)
	if err != nil {
		c.JSON(http.StatusInternalServerError, types.ErrorResponse{
			Detail: fmt.Sprintf("No se pudo subir/procesar el archivo: %v", err),
		})
		return
	}

	// Auditoría user_files solo cuando el worker confirmó indexación (evita filas sin RAG real).
	if result.Error == nil && result.Indexed {
		if _, ge := h.userRepo.GetState(ctx, &chatID, nil); ge == nil {
			if uid, _ := h.userRepo.GetUserIDForChat(ctx, chatID); uid != nil {
				sz := int(fh.Size)
				rec := &malcomdb.UserFile{
					UserID:        *uid,
					ChatID:        chatID,
					Filename:      baseName,
					FileType:      uploadAuditFileType(ext),
					FilePath:      result.SavedPath,
					SizeBytes:     &sz,
					Indexed:       true,
					IndexedChunks: result.Chunks,
				}
				if re := h.userRepo.RecordUploadedFile(ctx, rec); re != nil {
					slog.Warn("RecordUploadedFile", "error", re, "chat_id", chatID)
				}
			}
		}
	}

	c.JSON(http.StatusOK, types.UploadResponse{
		ChatID:    chatID,
		Filename:  fh.Filename,
		SavedPath: result.SavedPath,
		Indexed:   result.Indexed,
		Chunks:    result.Chunks,
		Message:   result.Message,
		Error:     result.Error,
	})
}

// ── GET /api/v1/chat/:chat_id/credits ─────────────────────────────────────────

// GetCredits devuelve el estado de créditos del usuario sin modificar el contador.
func (h *ChatHandler) GetCredits(c *gin.Context) {
	chatIDStr := c.Param("chat_id")
	chatID, err := strconv.ParseInt(chatIDStr, 10, 64)
	if err != nil {
		c.JSON(http.StatusUnprocessableEntity, types.ErrorResponse{
			Detail: "chat_id debe ser un entero válido",
		})
		return
	}

	ctx := c.Request.Context()
	state, err := h.userRepo.GetState(ctx, &chatID, nil)
	if err != nil {
		c.JSON(http.StatusInternalServerError, types.ErrorResponse{
			Detail: fmt.Sprintf("Error consultando créditos: %v", err),
		})
		return
	}

	c.JSON(http.StatusOK, types.CreditStateResponse{
		ChatID:           state.ChatID,
		Email:            state.Email,
		Username:         state.Username,
		MessageCount:     state.MessageCount,
		IsPremium:        state.IsPremium,
		FreeMessageLimit: state.FreeMessageLimit,
		CreditsRemaining: state.CreditsRemaining,
		Paywall:          state.Paywall,
		PremiumSince:     state.PremiumSince,
	})
}

// DashboardTokenRefresh emite un nuevo token de dashboard desde el último snapshot guardado (premium).
// POST /api/v1/chat/token/refresh — usado por el widget cuando el token one-shot ya se consumió.
func (h *ChatHandler) DashboardTokenRefresh(c *gin.Context) {
	var req types.DashboardTokenRefreshRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusUnprocessableEntity, types.ErrorResponse{Detail: err.Error()})
		return
	}
	if req.ChatID <= 0 {
		c.JSON(http.StatusUnprocessableEntity, types.ErrorResponse{Detail: "chat_id inválido."})
		return
	}
	ctx := c.Request.Context()
	premium, err := h.userRepo.IsPremiumForChat(ctx, req.ChatID)
	if err != nil {
		slog.Error("DashboardTokenRefresh premium", "error", err, "chat_id", req.ChatID)
		c.JSON(http.StatusInternalServerError, types.ErrorResponse{Detail: "No se pudo validar el acceso."})
		return
	}
	if h.devForcePremium {
		premium = true
	}
	if !premium {
		c.JSON(http.StatusForbidden, types.ErrorResponse{Detail: "Se requiere plan premium activo."})
		return
	}
	snap, err := h.userRepo.GetLastDashboardSnapshot(ctx, req.ChatID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, types.ErrorResponse{Detail: "No se pudo leer el tablero guardado."})
		return
	}
	if snap == "" {
		if filesystem.HasUploadedDataFiles(h.dataDir, req.ChatID) {
			c.JSON(http.StatusAccepted, types.DashboardPendingResponse{
				Status: "pending",
				Message: "Preparando tablero: aún no hay una gráfica guardada. " +
					"Envía un mensaje de análisis en el chat para generarla.",
			})
			return
		}
		c.JSON(http.StatusNotFound, types.ErrorResponse{
			Detail: "No hay tablero guardado. Envía un mensaje en el chat para generar uno nuevo.",
		})
		return
	}
	tok := h.tokens.StorePayload(req.ChatID, "dashboard", snap)
	base := strings.TrimRight(publicBaseURL(c), "/")
	u := base + "/dashboard?token=" + tok
	c.JSON(http.StatusOK, types.DashboardTokenRefreshResponse{DashboardURL: u, Token: tok})
}

// ── Helpers internos ──────────────────────────────────────────────────────────

func uploadAuditFileType(ext string) string {
	switch strings.ToLower(ext) {
	case ".pdf":
		return "pdf"
	case ".csv", ".xlsx", ".xls":
		return "data"
	case ".txt", ".doc", ".docx":
		return "document"
	default:
		return "other"
	}
}

// publicBaseURL devuelve la base pública del servidor (sin barra final).
// Prioridad: PUBLIC_BASE_URL env → X-Forwarded headers (ngrok/proxy) → Host del request.
// Fuerza HTTPS en dominios ngrok / powerups.com para evitar mixed-content.
func publicBaseURL(c *gin.Context) string {
	base := strings.TrimRight(os.Getenv("PUBLIC_BASE_URL"), "/")
	if base == "" {
		xProto := c.GetHeader("X-Forwarded-Proto")
		xHost := c.GetHeader("X-Forwarded-Host")
		if xProto != "" && xHost != "" {
			proto := strings.TrimSpace(strings.SplitN(xProto, ",", 2)[0])
			host := strings.TrimSpace(strings.SplitN(xHost, ",", 2)[0])
			base = strings.TrimRight(fmt.Sprintf("%s://%s", proto, host), "/")
		} else {
			scheme := "http"
			if c.Request.TLS != nil {
				scheme = "https"
			}
			base = fmt.Sprintf("%s://%s", scheme, c.Request.Host)
		}
	}
	if strings.Contains(base, "ngrok") || strings.Contains(base, "powerups.com") {
		base = strings.ReplaceAll(base, "http://", "https://")
	}
	return base
}

// chartImageURL construye la URL pública de una gráfica bajo /data/{chatID}/{filename}.
func chartImageURL(c *gin.Context, chatID, filename string) string {
	return fmt.Sprintf("%s/data/%s/%s", publicBaseURL(c), chatID, filename)
}

// buildTierConfig — Gatekeeper: construye el ReportConfig con el tier real del usuario.
// Go es la autoridad; el tier enviado por el frontend se ignora.
// Los campos de estilo del request (colores, fuentes) se preservan si el usuario es premium;
// para free se fuerzan valores predeterminados grises.
func buildTierConfig(req *types.ReportConfig, state *repositories.UserState) *types.ReportConfig {
	rc := &types.ReportConfig{}
	if req != nil {
		*rc = *req // copiar preferencias de estilo del frontend
	}
	if state != nil && state.IsPremium {
		rc.Tier = "premium"
		rc.ChartTypes = []string{"bars", "heatmap", "pie", "treemap"}
		if state.BrandingCharts != nil && strings.TrimSpace(*state.BrandingCharts) != "" {
			var charts []string
			if err := json.Unmarshal([]byte(*state.BrandingCharts), &charts); err == nil {
				allowed := filterAllowedCharts(charts)
				if len(allowed) > 0 {
					rc.ChartTypes = allowed
				}
			}
		}
		if state.BrandingColor != nil && strings.TrimSpace(*state.BrandingColor) != "" {
			rc.PrimaryColor = *state.BrandingColor
		}
		if state.BrandingColorSec != nil && strings.TrimSpace(*state.BrandingColorSec) != "" {
			rc.SecondaryColor = *state.BrandingColorSec
		}
		if state.BrandingFontBody != nil {
			rc.FontSizeBody = *state.BrandingFontBody
		}
		if state.BrandingFontTitle != nil {
			rc.FontSizeTitles = *state.BrandingFontTitle
		}
		if rc.PrimaryColor == "" {
			rc.PrimaryColor = "#28468C"
		}
	} else {
		rc.Tier = "free"
		rc.ChartTypes = []string{"bars"}
		rc.PrimaryColor = "#808080" // gris estándar — no personalizable en free
	}
	// El worker Python exige font_size_body >= 6, font_size_titles >= 8.
	// Los ceros aparecen cuando el frontend no envía report_config (zero value de Go).
	if rc.FontSizeBody < 6 {
		rc.FontSizeBody = 11
	}
	if rc.FontSizeTitles < 8 {
		rc.FontSizeTitles = 16
	}
	return rc
}

func filterAllowedCharts(input []string) []string {
	allow := map[string]struct{}{
		"bars": {}, "heatmap": {}, "pie": {}, "treemap": {},
	}
	out := make([]string, 0, len(input))
	seen := map[string]struct{}{}
	for _, v := range input {
		v = strings.ToLower(strings.TrimSpace(v))
		if _, ok := allow[v]; !ok {
			continue
		}
		if _, dup := seen[v]; dup {
			continue
		}
		seen[v] = struct{}{}
		out = append(out, v)
	}
	return out
}

func enforceChartPolicy(chartPaths []string, primary string, cfg *types.ReportConfig, isPremium bool) []string {
	merged := make([]string, 0, len(chartPaths)+1)
	if primary != "" {
		merged = append(merged, primary)
	}
	merged = append(merged, chartPaths...)

	existing := make([]string, 0, len(merged))
	seen := map[string]struct{}{}
	for _, p := range merged {
		p = strings.TrimSpace(p)
		if p == "" {
			continue
		}
		if _, ok := seen[p]; ok {
			continue
		}
		if _, err := os.Stat(p); err == nil {
			seen[p] = struct{}{}
			existing = append(existing, p)
		}
	}
	if len(existing) == 0 {
		return existing
	}
	if !isPremium {
		return existing[:1]
	}
	// Premium: devolver máximo tantas rutas como tipos permitidos (mínimo 1, máximo 6).
	limit := 4
	if cfg != nil && len(cfg.ChartTypes) > 0 {
		limit = len(cfg.ChartTypes)
	}
	if limit < 1 {
		limit = 1
	}
	if limit > 6 {
		limit = 6
	}
	if len(existing) > limit {
		return existing[:limit]
	}
	return existing
}
