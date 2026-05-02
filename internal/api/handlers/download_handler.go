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
)

// DownloadHandler sirve archivos de reporte generados por el agente Python.
type DownloadHandler struct {
	tokens *TokenStore
	users  repositories.UserRepository
}

// NewDownloadHandler construye el handler con su TokenStore.
func NewDownloadHandler(tokens *TokenStore, users repositories.UserRepository) *DownloadHandler {
	return &DownloadHandler{tokens: tokens, users: users}
}

// Download resuelve el token y sirve el archivo como descarga adjunta.
func (h *DownloadHandler) Download(c *gin.Context) {
	token := c.Param("token")
	if token == "" {
		c.JSON(http.StatusBadRequest, types.ErrorResponse{Detail: "Token requerido."})
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
		if strings.EqualFold(asset.ResourceType, "dashboard") {
			ctx := c.Request.Context()
			premium, err := h.users.IsPremiumForChat(ctx, asset.ChatID)
			if err != nil {
				slog.Error("download dashboard premium check", "error", err, "chat_id", asset.ChatID)
				c.JSON(http.StatusInternalServerError, types.ErrorResponse{Detail: "No se pudo validar el acceso."})
				return
			}
			if !premium {
				slog.Warn("download dashboard forbidden", "chat_id", asset.ChatID)
				c.JSON(http.StatusForbidden, types.ErrorResponse{
					Detail: "Este recurso requiere plan premium activo.",
				})
				return
			}
		}
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
	// Seguridad: solo servir archivos dentro de DATA_DIR.
	dataRoot := strings.TrimSpace(os.Getenv("DATA_DIR"))
	if dataRoot != "" {
		absRoot, _ := filepath.Abs(dataRoot)
		absFile, _ := filepath.Abs(filePath)
		if absRoot != "" && absFile != "" {
			prefix := absRoot + string(os.PathSeparator)
			if absFile != absRoot && !strings.HasPrefix(absFile, prefix) {
				c.JSON(http.StatusForbidden, types.ErrorResponse{
					Detail: "Archivo fuera del directorio permitido.",
				})
				return
			}
		}
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
