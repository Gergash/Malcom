// dashboard_handler.go: página HTML del dashboard premium (ECharts) y API de sesión por token.
package handlers

import (
	"log/slog"
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/powerups/insightflow-malcom/internal/api/types"
	"github.com/powerups/insightflow-malcom/internal/db/repositories"
)

// DashboardHandler sirve la SPA mínima del tablero y el JSON de sesión.
type DashboardHandler struct {
	tokens *TokenStore
	users  repositories.UserRepository
}

// NewDashboardHandler construye el handler.
func NewDashboardHandler(tokens *TokenStore, users repositories.UserRepository) *DashboardHandler {
	return &DashboardHandler{tokens: tokens, users: users}
}

// SessionJSON devuelve el JSON de la sesión (incluye echarts_option) para el token dashboard.
// Exige suscripción premium vigente en PostgreSQL para el chat_id asociado al token.
func (h *DashboardHandler) SessionJSON(c *gin.Context) {
	token := c.Param("token")
	if token == "" {
		c.JSON(http.StatusBadRequest, types.ErrorResponse{Detail: "Token requerido."})
		return
	}
	asset, ok := h.tokens.ResolveFull(token)
	if !ok || asset.ResourceType != "dashboard" || asset.PayloadJSON == nil || *asset.PayloadJSON == "" {
		c.JSON(http.StatusNotFound, types.ErrorResponse{
			Detail: "Sesión de dashboard expirada o inválida.",
		})
		return
	}
	ctx := c.Request.Context()
	premium, err := h.users.IsPremiumForChat(ctx, asset.ChatID)
	if err != nil {
		slog.Error("dashboard session premium check", "error", err, "chat_id", asset.ChatID)
		c.JSON(http.StatusInternalServerError, types.ErrorResponse{Detail: "No se pudo validar el acceso."})
		return
	}
	if !premium {
		slog.Warn("dashboard session forbidden", "chat_id", asset.ChatID, "reason", "not_premium")
		c.JSON(http.StatusForbidden, types.ErrorResponse{
			Detail: "El tablero interactivo requiere plan premium activo.",
		})
		return
	}
	c.Header("Cache-Control", "no-store")
	c.Data(http.StatusOK, "application/json; charset=utf-8", []byte(*asset.PayloadJSON))
}

// Page sirve una página mínima que carga ECharts y pide la sesión al API (mismo origen).
func (h *DashboardHandler) Page(c *gin.Context) {
	c.Header("Content-Type", "text/html; charset=utf-8")
	c.Header("Cache-Control", "no-store")
	c.String(http.StatusOK, dashboardPremiumHTML)
}

const dashboardPremiumHTML = `<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>InsightFlow — Dashboard Premium</title>
  <script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
  <style>
    body { margin: 0; font-family: system-ui, sans-serif; background: #0e1116; color: #e8edf5; }
    header { padding: 12px 16px; background: #161b24; border-bottom: 1px solid #2a3344; }
    #chart { width: 100%; height: calc(100vh - 56px); min-height: 420px; }
    .err { padding: 24px; color: #f0a0a0; }
  </style>
</head>
<body>
  <header><strong>InsightFlow</strong> · Dashboard interactivo (Premium)</header>
  <div id="chart"></div>
  <script>
(function () {
  var params = new URLSearchParams(window.location.search);
  var token = params.get('token');
  var el = document.getElementById('chart');
  if (!token) {
    el.innerHTML = '<p class="err">Falta el parámetro <code>token</code> en la URL.</p>';
    return;
  }
  var headers = { 'Accept': 'application/json' };
  if (window.location.hostname.indexOf('ngrok') !== -1) {
    headers['ngrok-skip-browser-warning'] = 'true';
  }
  fetch('/api/v1/dashboard/session/' + encodeURIComponent(token), { credentials: 'omit', headers: headers })
    .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then(function (data) {
      var opt = data.echarts_option || data;
      if (!opt || typeof opt !== 'object') throw new Error('Respuesta sin echarts_option');
      var chart = echarts.init(el, 'dark');
      chart.setOption(opt);
      window.addEventListener('resize', function () { chart.resize(); });
    })
    .catch(function (e) {
      el.innerHTML = '<p class="err">No se pudo cargar el tablero: ' + (e.message || e) + '</p>';
    });
})();
  </script>
</body>
</html>
`
