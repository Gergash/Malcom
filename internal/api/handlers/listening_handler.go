// listening_handler.go: proxy público InsightFlow → Termómetro Cultural + overview chart-ready.
// Todas las rutas de producto requieren chat_id premium (salvo /health).
package handlers

import (
	"fmt"
	"log/slog"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/go-resty/resty/v2"
	"github.com/powerups/insightflow-malcom/internal/api/types"
	"github.com/powerups/insightflow-malcom/internal/db/repositories"
	"github.com/powerups/insightflow-malcom/internal/listening"
	"github.com/powerups/insightflow-malcom/internal/worker"
)

// ListeningHandler expone /api/v1/listening/* hacia listening-api y overview vía Brain.
type ListeningHandler struct {
	listening       *listening.Client
	users           repositories.UserRepository
	workerURL       string
	timeout         time.Duration
	devForcePremium bool
}

// NewListeningHandler construye el handler. workerURL = Brain (para overview ECharts).
func NewListeningHandler(
	listeningClient *listening.Client,
	users repositories.UserRepository,
	workerURL string,
	timeoutSec int,
	devForcePremium bool,
) *ListeningHandler {
	if timeoutSec <= 0 {
		timeoutSec = 45
	}
	return &ListeningHandler{
		listening:       listeningClient,
		users:           users,
		workerURL:       strings.TrimRight(strings.TrimSpace(workerURL), "/"),
		timeout:         time.Duration(timeoutSec) * time.Second,
		devForcePremium: devForcePremium,
	}
}

func (h *ListeningHandler) requirePremium(c *gin.Context) bool {
	raw := strings.TrimSpace(c.Query("chat_id"))
	if raw == "" {
		raw = strings.TrimSpace(c.GetHeader("X-Chat-Id"))
	}
	if raw == "" {
		c.JSON(http.StatusUnauthorized, types.ErrorResponse{
			Detail: "chat_id requerido (query ?chat_id= o cabecera X-Chat-Id). Termómetro Cultural es Premium.",
		})
		return false
	}
	chatID, err := strconv.ParseInt(raw, 10, 64)
	if err != nil || chatID == 0 {
		c.JSON(http.StatusUnprocessableEntity, types.ErrorResponse{Detail: "chat_id inválido."})
		return false
	}
	if h.devForcePremium {
		return true
	}
	ok, err := h.users.IsPremiumForChat(c.Request.Context(), chatID)
	if err != nil {
		slog.Error("listening premium check", "error", err, "chat_id", chatID)
		c.JSON(http.StatusInternalServerError, types.ErrorResponse{Detail: "No se pudo verificar el plan."})
		return false
	}
	if !ok {
		c.JSON(http.StatusForbidden, types.ErrorResponse{
			Detail: worker.PremiumListeningDeniedMessage,
		})
		return false
	}
	return true
}

// Overview — GET /api/v1/listening/overview?chat_id=
func (h *ListeningHandler) Overview(c *gin.Context) {
	if !h.requirePremium(c) {
		return
	}
	if h.workerURL == "" {
		c.JSON(http.StatusServiceUnavailable, types.ErrorResponse{Detail: "WORKER_URL no configurado."})
		return
	}
	body := map[string]any{}
	if d := strings.TrimSpace(c.Query("days")); d != "" {
		var days int
		if _, err := fmt.Sscanf(d, "%d", &days); err == nil && days > 0 {
			body["days"] = days
		}
	}
	if strings.EqualFold(c.Query("scrape"), "1") || strings.EqualFold(c.Query("scrape"), "true") {
		body["trigger_scrape"] = true
		body["scrape_note"] = "insightflow-api-overview"
	}

	client := resty.New().SetTimeout(h.timeout)
	res, err := client.R().
		SetContext(c.Request.Context()).
		SetHeader("Content-Type", "application/json").
		SetBody(body).
		Post(h.workerURL + "/internal/listening/overview")
	if err != nil {
		slog.Error("listening overview brain", "error", err)
		c.JSON(http.StatusBadGateway, types.ErrorResponse{
			Detail: "No se pudo contactar el Brain para el overview del Termómetro.",
		})
		return
	}
	c.Header("Cache-Control", "no-store")
	c.Data(res.StatusCode(), "application/json; charset=utf-8", res.Body())
}

// ProxySentiment — GET /api/v1/listening/sentiment/summary?chat_id=
func (h *ListeningHandler) ProxySentiment(c *gin.Context) {
	if !h.requirePremium(c) {
		return
	}
	h.proxyGET(c, "/api/sentiment/summary")
}

// ProxyTopics — GET /api/v1/listening/topics/trending?chat_id=
func (h *ListeningHandler) ProxyTopics(c *gin.Context) {
	if !h.requirePremium(c) {
		return
	}
	h.proxyGET(c, "/api/topics/trending")
}

// ProxyTimeline — GET /api/v1/listening/timeline?chat_id=
func (h *ListeningHandler) ProxyTimeline(c *gin.Context) {
	if !h.requirePremium(c) {
		return
	}
	h.proxyGET(c, "/api/timeline")
}

// ProxyAlerts — GET /api/v1/listening/alerts?chat_id=
func (h *ListeningHandler) ProxyAlerts(c *gin.Context) {
	if !h.requirePremium(c) {
		return
	}
	h.proxyGET(c, "/api/alerts")
}

// ProxySources — GET /api/v1/listening/sources?chat_id=
func (h *ListeningHandler) ProxySources(c *gin.Context) {
	if !h.requirePremium(c) {
		return
	}
	h.proxyGET(c, "/api/sources")
}

// TriggerScrape — POST /api/v1/listening/scrape?chat_id=
func (h *ListeningHandler) TriggerScrape(c *gin.Context) {
	if !h.requirePremium(c) {
		return
	}
	var payload map[string]any
	_ = c.ShouldBindJSON(&payload)
	if payload == nil {
		payload = map[string]any{}
	}
	if _, ok := payload["note"]; !ok {
		payload["note"] = "insightflow-api"
	}
	status, body, ct, err := h.listening.ProxyPOSTJSON(
		c.Request.Context(),
		"/webhooks/trigger-scraping",
		payload,
		true,
	)
	if err != nil {
		slog.Error("listening scrape", "error", err)
		c.JSON(http.StatusBadGateway, types.ErrorResponse{
			Detail: "No se pudo disparar scraping en listening-api.",
		})
		return
	}
	c.Header("Cache-Control", "no-store")
	c.Data(status, ct, body)
}

// Health — GET /api/v1/listening/health (sin gate; solo estado del servicio).
func (h *ListeningHandler) Health(c *gin.Context) {
	if err := h.listening.Health(c.Request.Context()); err != nil {
		c.JSON(http.StatusBadGateway, gin.H{
			"status":  "down",
			"service": "listening-api",
			"detail":  err.Error(),
			"base":    h.listening.BaseURL(),
		})
		return
	}
	c.JSON(http.StatusOK, gin.H{
		"status":  "ok",
		"service": "listening-api",
		"base":    h.listening.BaseURL(),
	})
}

func (h *ListeningHandler) proxyGET(c *gin.Context, upstreamPath string) {
	q := url.Values{}
	for k, vals := range c.Request.URL.Query() {
		if k == "chat_id" {
			continue // no reenviar a listening-api
		}
		for _, v := range vals {
			q.Add(k, v)
		}
	}
	status, body, ct, err := h.listening.ProxyGET(c.Request.Context(), upstreamPath, q)
	if err != nil {
		slog.Error("listening proxy", "path", upstreamPath, "error", err)
		c.JSON(http.StatusBadGateway, types.ErrorResponse{
			Detail: "listening-api no disponible (" + upstreamPath + ").",
		})
		return
	}
	c.Header("Cache-Control", "no-store")
	c.Data(status, ct, body)
}
