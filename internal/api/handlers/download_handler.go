// download_handler.go: endpoint de descarga de reportes generados.
//
// GET /download/:token → resuelve el token, sirve el archivo como adjunto.
// Los tokens son válidos 30 minutos tras generarse (ver TokenStore).
package handlers

import (
	"mime"
	"net/http"
	"os"
	"path/filepath"

	"github.com/gin-gonic/gin"
	"github.com/powerups/insightflow-malcom/internal/api/types"
)

// DownloadHandler sirve archivos de reporte generados por el agente Python.
type DownloadHandler struct {
	tokens *TokenStore
}

// NewDownloadHandler construye el handler con su TokenStore.
func NewDownloadHandler(tokens *TokenStore) *DownloadHandler {
	return &DownloadHandler{tokens: tokens}
}

// Download resuelve el token y sirve el archivo como descarga adjunta.
func (h *DownloadHandler) Download(c *gin.Context) {
	token := c.Param("token")
	if token == "" {
		c.JSON(http.StatusBadRequest, types.ErrorResponse{Detail: "Token requerido."})
		return
	}

	filePath, ok := h.tokens.Resolve(token)
	if !ok {
		c.JSON(http.StatusNotFound, types.ErrorResponse{
			Detail: "Enlace de descarga expirado o inválido. Genera un nuevo reporte.",
		})
		return
	}

	if _, err := os.Stat(filePath); err != nil {
		c.JSON(http.StatusNotFound, types.ErrorResponse{
			Detail: "El archivo no está disponible en el servidor.",
		})
		return
	}

	ext := filepath.Ext(filePath)
	mimeType := mime.TypeByExtension(ext)
	if mimeType == "" {
		mimeType = "application/octet-stream"
	}

	filename := filepath.Base(filePath)
	c.Header("Content-Disposition", `attachment; filename="`+filename+`"`)
	c.Header("Content-Type", mimeType)
	c.Header("Cache-Control", "no-store")
	c.File(filePath)
}
