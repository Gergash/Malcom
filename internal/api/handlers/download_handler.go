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

// isPremiumGatedResource indica si el tipo de recurso requiere plan premium
// para descargarse. Los reportes PDF/Excel son premium-only (v2); charts y
// dashboards ECharts son libres para todos los usuarios.
func isPremiumGatedResource(resType string) bool {
	return strings.EqualFold(resType, "pdf") || strings.EqualFold(resType, "excel")
}

// Download resuelve el token y sirve el archivo como descarga adjunta.
func (h *DownloadHandler) Download(c *gin.Context) {
	token := c.Param("token")
	if token == "" {
		c.JSON(http.StatusBadRequest, types.ErrorResponse{Detail: "Token requerido."})
		return
	}

	// Sesión ECharts (JSON): mismo flujo que /api/v1/dashboard/session (v2: sin gate premium).
	if dash, ok := h.tokens.PeekDashboardSession(token); ok && dash.PayloadJSON != nil {
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

	// Gate premium (v2): los reportes PDF/Excel son exclusivos del plan premium.
	// Charts y dashboards siguen libres para todos. Este es el punto de enforcement
	// autoritativo: aunque un token de PDF/Excel se filtre o se comparta, sin premium
	// no se sirve el archivo.
	if isPremiumGatedResource(asset.ResourceType) {
		isPremium, err := h.users.IsPremiumForChat(c.Request.Context(), asset.ChatID)
		if err != nil {
			slog.Error("download premium check failed", "chat_id", asset.ChatID, "error", err)
			c.JSON(http.StatusInternalServerError, types.ErrorResponse{
				Detail: "No se pudo verificar el plan del usuario.",
			})
			return
		}
		if !isPremium {
			slog.Info("download bloqueado: reporte requiere premium",
				"chat_id", asset.ChatID, "resource", asset.ResourceType)
			c.JSON(http.StatusForbidden, types.ErrorResponse{
				Detail: "Los reportes PDF/Excel son exclusivos del plan premium ($40.000 COP).",
			})
			return
		}
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
