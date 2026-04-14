// chat_handler.go: endpoints principales de conversación y subida de archivos.
// Reemplaza app/api/routes/chat.py
//
// POST /api/v1/chat           → enviar mensaje al agente de análisis
// POST /api/v1/chat/upload    → subir archivo para análisis
// GET  /api/v1/chat/:chat_id/credits → consultar créditos sin modificarlos
package handlers

import (
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/powerups/insightflow-malcom/internal/api/types"
	"github.com/powerups/insightflow-malcom/internal/db/repositories"
	"github.com/powerups/insightflow-malcom/internal/filesystem"
	"github.com/powerups/insightflow-malcom/internal/worker"
)

// ChatHandler agrupa las dependencias de los endpoints de chat.
type ChatHandler struct {
	userRepo repositories.UserRepository
	convRepo repositories.ConversationRepository
	worker   worker.Client
	dataDir  string // ruta absoluta al directorio data/ del proyecto
}

// NewChatHandler construye el handler con sus dependencias.
func NewChatHandler(
	userRepo repositories.UserRepository,
	convRepo repositories.ConversationRepository,
	workerClient worker.Client,
	dataDir string,
) *ChatHandler {
	return &ChatHandler{
		userRepo: userRepo,
		convRepo: convRepo,
		worker:   workerClient,
		dataDir:  dataDir,
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

	// 4 · Worker: strict data si ya hay archivos del usuario en data/{chat_id}/
	requireStrict := filesystem.HasUploadedDataFiles(h.dataDir, req.ChatID)
	result, err := h.worker.ProcessMessage(ctx, req.ChatID, req.Message, req.ReportConfig, requireStrict)
	if err != nil {
		c.JSON(http.StatusInternalServerError, types.ErrorResponse{
			Detail: fmt.Sprintf("Error procesando la consulta: %v", err),
		})
		return
	}

	// 5 · Persistir respuesta del asistente
	if err := h.convRepo.AddMessage(ctx, req.ChatID, "assistant", result.Response); err != nil {
		// No bloqueamos la respuesta por un fallo de persistencia de historial
		_ = err
	}

	// 6 · Resolver URL pública de la gráfica
	var imageURL *string
	cid := strconv.FormatInt(req.ChatID, 10)

	if result.ChartPath != "" {
		if _, statErr := os.Stat(result.ChartPath); statErr == nil {
			u := chartImageURL(c, cid, filepath.Base(result.ChartPath))
			imageURL = &u
		}
	}
	if imageURL == nil {
		for _, fname := range []string{fmt.Sprintf("output_plot_%s.png", cid), "output_plot.png"} {
			candidate := filepath.Join(h.dataDir, cid, fname)
			if _, statErr := os.Stat(candidate); statErr == nil {
				u := chartImageURL(c, cid, fname)
				imageURL = &u
				break
			}
		}
	}

	// 7 · Respuesta
	c.JSON(http.StatusOK, types.ChatResponse{
		Response:         result.Response,
		HasPDF:           result.HasPDF,
		HasExcel:         result.HasExcel,
		HasChart:         result.HasChart,
		Paywall:          false,
		CreditsRemaining: creditStatus.CreditsRemaining,
		ImageURL:         imageURL,
	})
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
	ext := filepath.Ext(baseName)
	if ext == "" {
		ext = ".bin"
	}
	tmpName := fmt.Sprintf("%d_%d%s", chatID, time.Now().UnixNano(), ext)
	tmpPath := filepath.Join(uploadDir, tmpName)
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

	// Delegar ingestión al Worker Python
	ctx := c.Request.Context()
	result, err := h.worker.IngestFile(ctx, chatID, tmpPath, fh.Filename)
	if err != nil {
		c.JSON(http.StatusInternalServerError, types.ErrorResponse{
			Detail: fmt.Sprintf("No se pudo subir/procesar el archivo: %v", err),
		})
		return
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

// ── Helpers internos ──────────────────────────────────────────────────────────

// chartImageURL construye la URL pública de una gráfica.
// Lógica (espeja _public_base_for_assets + _chart_image_url de chat.py):
//  1. PUBLIC_BASE_URL de entorno.
//  2. X-Forwarded-Proto + X-Forwarded-Host (ngrok / reverse proxy).
//  3. Fallback al Host del request.
//  4. Fuerza HTTPS en dominios ngrok / powerups.com para evitar mixed-content.
func chartImageURL(c *gin.Context, chatID, filename string) string {
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

	url := fmt.Sprintf("%s/data/%s/%s", base, chatID, filename)

	// Blindaje contra mixed-content en dominios públicos
	if strings.Contains(url, "ngrok") || strings.Contains(url, "powerups.com") {
		url = strings.ReplaceAll(url, "http://", "https://")
	}
	return url
}
