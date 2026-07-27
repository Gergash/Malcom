// dashboard_handler.go: página HTML del dashboard premium (ECharts) y API de sesión por token.
package handlers

import (
	"log/slog"
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/powerups/insightflow-malcom/internal/api/types"
	"github.com/powerups/insightflow-malcom/internal/db/repositories"
	"github.com/powerups/insightflow-malcom/internal/filesystem"
)

// DashboardHandler sirve la SPA mínima del tablero y el JSON de sesión.
type DashboardHandler struct {
	tokens          *TokenStore
	users           repositories.UserRepository
	dataDir         string
	devForcePremium bool // SOLO DEV: si true, omite el gate is_premium en DB
}

// NewDashboardHandler construye el handler.
func NewDashboardHandler(tokens *TokenStore, users repositories.UserRepository, dataDir string, devForcePremium bool) *DashboardHandler {
	return &DashboardHandler{tokens: tokens, users: users, dataDir: dataDir, devForcePremium: devForcePremium}
}

// SessionJSON devuelve el JSON de la sesión (incluye echarts_option) para el token dashboard.
// Acceso por token válido (ownership); sin gate premium (v2).
func (h *DashboardHandler) SessionJSON(c *gin.Context) {
	token := c.Param("token")
	if token == "" {
		c.JSON(http.StatusBadRequest, types.ErrorResponse{Detail: "Token requerido."})
		return
	}
	asset, ok := h.tokens.PeekDashboardSession(token)
	if !ok || asset.PayloadJSON == nil || *asset.PayloadJSON == "" {
		if chatID, metaOk := h.tokens.LookupDashboardTokenChatID(token); metaOk {
			ctx := c.Request.Context()
			snap, err := h.users.GetLastDashboardSnapshot(ctx, chatID)
			if err != nil {
				slog.Error("dashboard snapshot read", "error", err, "chat_id", chatID)
				c.JSON(http.StatusInternalServerError, types.ErrorResponse{Detail: "No se pudo leer el tablero guardado."})
				return
			}
			if strings.TrimSpace(snap) != "" {
				c.JSON(http.StatusConflict, types.ErrorResponse{
					Detail: "Este enlace de tablero ya fue utilizado. Solicita uno nuevo desde el chat.",
				})
				return
			}
			if h.dataDir != "" && filesystem.HasUploadedDataFiles(h.dataDir, chatID) {
				c.Header("Cache-Control", "no-store")
				c.JSON(http.StatusAccepted, types.DashboardPendingResponse{
					Status: "pending",
					Message: "Preparando tablero: aún no hay una gráfica guardada. " +
						"Envía un mensaje de análisis en el chat para generarla.",
				})
				return
			}
		}
		c.JSON(http.StatusNotFound, types.ErrorResponse{
			Detail: "Sesión de dashboard expirada, ya utilizada o inválida.",
		})
		return
	}
	if !h.tokens.MarkDashboardConsumed(token) {
		c.JSON(http.StatusConflict, types.ErrorResponse{
			Detail: "Este enlace de tablero ya fue utilizado. Solicita uno nuevo desde el chat.",
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
  <title>InsightFlow — Dashboard</title>
  <script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
  <style>
    :root { --pu-bg:#0b0e1b; --pu-accent:#39ff14; --pu-text:#e8edf5; --pu-muted:#8b98a8; --pu-border:rgba(57,255,20,.14); }
    body { margin: 0; font-family: system-ui, sans-serif; background: var(--pu-bg); color: var(--pu-text); }
    header { padding: 12px 16px; background: #12162a; border-bottom: 1px solid var(--pu-border); display:flex; align-items:center; gap:10px; }
    .live { font-size:11px; font-weight:700; color:var(--pu-accent); border:1px solid rgba(57,255,20,.35); border-radius:999px; padding:3px 10px; }
    #board { display:grid; gap:12px; padding:14px; grid-template-columns: 2fr 1fr; }
    .card { background:rgba(22,27,48,.72); border:1px solid var(--pu-border); border-radius:14px; padding:12px; min-height:280px; }
    .card.full { grid-column:1/-1; min-height:420px; }
    .chart { width:100%; height:260px; }
    .card.full .chart { height:calc(100vh - 120px); min-height:400px; }
    .err { padding: 24px; color: #f0a0a0; }
    .pending { padding: 24px 28px; color: #9ec5ff; line-height: 1.5; max-width: 520px; }
    .pending strong { color: #e8edf5; }
    @media (max-width:900px){ #board{grid-template-columns:1fr;} }
  </style>
</head>
<body>
  <header>
    <strong>InsightFlow</strong>
    <span style="color:var(--pu-muted);font-size:12px;">Tablero interactivo</span>
    <span class="live" id="live" hidden>Live</span>
  </header>
  <div id="board"></div>
  <script>
(function () {
  var params = new URLSearchParams(window.location.search);
  var token = params.get('token');
  var board = document.getElementById('board');
  if (!token) {
    board.innerHTML = '<p class="err">Falta el parámetro <code>token</code> en la URL.</p>';
    return;
  }
  echarts.registerTheme('powerups', {
    color: ['#39FF14','#7CFF6B','#3a5fb8','#6bc9a8','#d4a853','#ff6b6b'],
    backgroundColor: 'transparent',
    textStyle: { fontFamily: 'system-ui,sans-serif' },
    categoryAxis: { axisLine:{lineStyle:{color:'#8b98a8'}}, axisLabel:{color:'#8b98a8'}, splitLine:{lineStyle:{color:'#1e2638'}} },
    valueAxis: { axisLine:{lineStyle:{color:'#8b98a8'}}, axisLabel:{color:'#8b98a8'}, splitLine:{lineStyle:{color:'#1e2638'}} },
    title: { textStyle:{color:'#e8edf5'} },
    tooltip: { backgroundColor:'rgba(18,22,42,.94)', borderColor:'rgba(57,255,20,.25)', textStyle:{color:'#e8edf5'} }
  });
  var headers = { 'Accept': 'application/json' };
  if (window.location.hostname.indexOf('ngrok') !== -1) {
    headers['ngrok-skip-browser-warning'] = 'true';
  }
  fetch('/api/v1/dashboard/session/' + encodeURIComponent(token), { credentials: 'omit', headers: headers })
    .then(function (r) {
      if (r.status === 202) {
        return r.json().then(function (data) {
          var msg = (data && data.message) ? data.message : 'Genera la gráfica enviando un mensaje en el chat.';
          board.innerHTML = '<div class="pending"><p><strong>Preparando tablero…</strong></p><p>' + msg + '</p></div>';
        });
      }
      if (!r.ok) {
        var st = r.status;
        if (st === 404) {
          board.innerHTML = '<div class="pending"><p><strong>Preparando tablero…</strong></p><p>No hay una sesión de gráfica lista todavía.</p></div>';
          return;
        }
        throw new Error('HTTP ' + st);
      }
      return r.json();
    })
    .then(function (data) {
      if (!data || data.status === 'pending') return;
      var dash = data.dashboard;
      var primary = data.echarts_option;
      if (dash && dash.live) document.getElementById('live').hidden = false;
      var widgets = (dash && Array.isArray(dash.widgets)) ? dash.widgets.filter(function(w){ return w && w.kind==='echarts' && w.option; }) : [];
      if (!widgets.length && primary) {
        widgets = [{ title: 'Panel unificado', option: primary, span: 'full' }];
      }
      if (!widgets.length) throw new Error('Respuesta sin echarts_option');
      board.innerHTML = '';
      var charts = [];
      widgets.slice(0, 2).forEach(function (w, i) {
        var card = document.createElement('div');
        card.className = 'card' + (widgets.length === 1 || w.span === 'full' || w.span === 'wide' && i===0 && widgets.length===1 ? ' full' : '');
        if (widgets.length === 1) card.className = 'card full';
        card.innerHTML = '<div style="font-size:13px;font-weight:700;margin-bottom:8px;">' + (w.title || 'Vista') + '</div><div class="chart" id="c'+i+'"></div>';
        board.appendChild(card);
        var inst = echarts.init(document.getElementById('c'+i), 'powerups');
        inst.setOption(w.option || primary, true);
        charts.push(inst);
      });
      window.addEventListener('resize', function () { charts.forEach(function(c){ c.resize(); }); });
    })
    .catch(function (e) {
      board.innerHTML = '<p class="err">No se pudo cargar el tablero: ' + (e.message || e) + '</p>';
    });
})();
  </script>
</body>
</html>
`

