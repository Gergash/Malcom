// health_handler.go: GET /health
// Reemplaza app/api/routes/health.py
package handlers

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/powerups/insightflow-malcom/internal/api/types"
)

type HealthHandler struct{}

func NewHealthHandler() *HealthHandler {
	return &HealthHandler{}
}

// HealthCheck godoc
// @Summary  Estado del servicio
// @Tags     Health
// @Produce  json
// @Success  200 {object} types.HealthResponse
// @Router   /health [get]
func (h *HealthHandler) HealthCheck(c *gin.Context) {
	c.JSON(http.StatusOK, types.HealthResponse{
		Status:  "ok",
		Service: "InsightFlow Malcom API",
		Version: "2.0.0",
	})
}
