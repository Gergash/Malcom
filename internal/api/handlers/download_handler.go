// download_handler.go: endpoint de descarga de reportes generados.
//
// GET /download/:token → resuelve el token, sirve el archivo como adjunto.
// Los tokens son válidos 30 minutos tras generarse (ver TokenStore).
package handlers

import (
	"log/slog"
	"mime"
	"net/http"
	"os"
	"path/filepath"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/powerups/insightflow-malcom/internal/api/types"
	"github.com/powerups/insightflow-malcom/internal/db/repositories"
	"github.com/powerups/insightflow-malcom/internal/filesystem"
)

// DownloadHandler sirve archivos de reporte generados por el agente Python.
type DownloadHandler struct {
	tokens  *TokenStore
	users   repositories.UserRepository
	dataDir string // raíz data/ absoluta: solo se sirven archivos bajo data/{chat_id}/
}

// NewDownloadHandler construye el handler con su TokenStore.
func NewDownloadHandler(tokens *TokenStore, users repositories.UserRepository, dataDir string) *DownloadHandler {
	return &DownloadHandler{tokens: tokens, users: users, dataDir: dataDir}
}

// Download resuelve el token y sirve el archivo como descarga adjunta.
func (h *DownloadHandler) Download(c *gin.Context) {
	token := c.Param("token")
	if token == "" {
		c.JSON(http.StatusBadRequest, types.ErrorResponse{Detail: "Token requerido."})
		return
	}

	ctx := c.Request.Context()

	// Sesión ECharts (JSON): mismo flujo que /api/v1/dashboard/session (premium + un solo uso).
	if dash, ok := h.tokens.PeekDashboardSession(token); ok && dash.PayloadJSON != nil {
		premium, err := h.users.IsPremiumForChat(ctx, dash.ChatID)
		if err != nil {
			slog.Error("download dashboard premium check", "error", err, "chat_id", dash.ChatID)
			c.JSON(http.StatusInternalServerError, types.ErrorResponse{Detail: "No se pudo validar el acceso."})
			return
		}
		if !premium {
			slog.Warn("download dashboard forbidden", "chat_id", dash.ChatID)
			c.JSON(http.StatusForbidden, types.ErrorResponse{
				Detail: "Este recurso requiere plan premium activo.",
			})
			return
		}
		if !h.tokens.MarkDashboardConsumed(token) {
			c.JSON(http.StatusConflict, types.ErrorResponse{
				Detail: "Este enlace ya fue utilizado.",
			})
			return
		}
		c.Header("Cache-Control", "no-store")
		c.Data(http.StatusOK, "application/json; charset=utf-8", []byte(*dash.PayloadJSON))
		return
	}

	asset, ok := h.tokens.ResolveFull(token)
	if !ok {
		c.JSON(http.StatusNotFound, types.ErrorResponse{
			Detail: "Enlace de descarga expirado o inválido. Genera un nuevo reporte.",
		})
		return
	}

	if asset.PayloadJSON != nil && strings.TrimSpace(*asset.PayloadJSON) != "" {
		c.Header("Cache-Control", "no-store")
		c.Data(http.StatusOK, "application/json; charset=utf-8", []byte(*asset.PayloadJSON))
		return
	}

	filePath := asset.FilePath
	if filePath == "" {
		c.JSON(http.StatusNotFound, types.ErrorResponse{
			Detail: "El recurso no está disponible.",
		})
		return
	}

	if _, err := os.Stat(filePath); err != nil {
		c.JSON(http.StatusNotFound, types.ErrorResponse{
			Detail: "El archivo no está disponible en el servidor.",
		})
		return
	}
	if h.dataDir == "" || !filesystem.FileUnderChatData(h.dataDir, filePath, asset.ChatID) {
		slog.Warn("download path outside chat jail", "chat_id", asset.ChatID, "path", filePath)
		c.JSON(http.StatusForbidden, types.ErrorResponse{
			Detail: "Archivo fuera del directorio permitido para este chat.",
		})
		return
	}

	resType := asset.ResourceType
	ext := filepath.Ext(filePath)
	mimeType := mime.TypeByExtension(ext)
	if mimeType == "" {
		mimeType = "application/octet-stream"
	}

	filename := filepath.Base(filePath)
	if strings.EqualFold(resType, "chart") {
		c.Header("Content-Disposition", `inline; filename="`+filename+`"`)
	} else {
		c.Header("Content-Disposition", `attachment; filename="`+filename+`"`)
	}
	c.Header("Content-Type", mimeType)
	c.Header("Cache-Control", "no-store")
	c.File(filePath)
}
