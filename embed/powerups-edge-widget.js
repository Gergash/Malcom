/**
 * InsightFlow widget app — carga en powerups-edge-frame.html o monolito.
 * CONFIG: window.POWERUPS_WIDGET_CONFIG (antes del script) y/o query (?apiBase=… &checkoutUrl=…)
 *         cuando el padre es otro origen y widget-loader.js pasa la config en el src del iframe.
 */
(function () {
  var DEFAULT_CONFIG = {
    API_BASE: 'https://meroblastic-estefana-isoperimetrical.ngrok-free.dev',
    // Pasarela Wompi / ePayco / página de producto WooCommerce. Puedes usar {chatId} en la cadena.
    CHECKOUT_URL: 'https://tu-tienda.com/premium-edge-bi/?chat_id={chatId}',
    // Opcional: nombre para registro en el backend
    USERNAME: null,
    STORAGE_KEY_CHAT: 'powerups_edge_chat_id_v1',
    STORAGE_KEY_HISTORY: 'powerups_edge_history_v1',
    // Token del último tablero ECharts por chat_id (para el link "Abrir en pestaña").
    STORAGE_KEY_DASH_PREFIX: 'powerups_edge_dash_tok_',
    // Historial de opciones ECharts (array, max 6) por chat_id — para el visor inline.
    STORAGE_KEY_CHARTS_PREFIX: 'powerups_edge_charts_',
    STORAGE_KEY_PANEL_SIZE: 'powerups_edge_panel_size_v1',
    // URLs públicas de los embebidos premium en producción.
    PREMIUM_PORTAL_URL: 'https://www.powerupsagencia.com/portal-premium/',
    DASHBOARD_SESSION_URL: 'https://www.powerupsagencia.com/dashboard-premium-echarts/',
    // Mensajes enviados al agente cuando el usuario ya es premium y pulsa las acciones
    PROMPT_PDF: 'Genera el informe PDF premium consolidado de este hilo de análisis, listo para presentación ejecutiva.',
    PROMPT_EXCEL: 'Exporta un libro Excel con gráficas a partir del análisis actual (hojas claras y un gráfico por insight clave).',
  };
  var _extra = typeof window !== "undefined" && window.POWERUPS_WIDGET_CONFIG && typeof window.POWERUPS_WIDGET_CONFIG === "object" ? window.POWERUPS_WIDGET_CONFIG : {};
  var CONFIG = Object.assign({}, DEFAULT_CONFIG, _extra);
  /** Si el host inyecta el iframe con ?apiBase=… (p. ej. widget-loader.js), fusiona aquí. */
  (function applyQueryConfig() {
    try {
      var sp = new URLSearchParams(window.location.search);
      if (!sp.toString()) return;
      var map = {
        apiBase: "API_BASE",
        checkoutUrl: "CHECKOUT_URL",
        premiumPortalUrl: "PREMIUM_PORTAL_URL",
        dashboardSessionUrl: "DASHBOARD_SESSION_URL",
        username: "USERNAME",
      };
      var o = {};
      for (var qk in map) {
        if (!sp.has(qk)) continue;
        var v = sp.get(qk);
        if (v === "" && map[qk] === "USERNAME") o.USERNAME = null;
        else o[map[qk]] = v;
      }
      Object.assign(CONFIG, o);
    } catch (e) { /* ignore */ }
  })();

  function el(id) { return document.getElementById(id); }

  function isEmbedHost() {
    try { return window.parent !== window; } catch (e) { return false; }
  }

  function measureBubbleHostSize() {
    var root = el('powerups-edge-chat');
    var launcher = el('powerups-edge-launcher');
    var toggle = el('powerups-edge-toggle');
    var hint = el('powerups-edge-bubble-hint');
    var target = launcher || toggle;
    if (!target) return { w: 336, h: 96 };
    var r = target.getBoundingClientRect();
    var w = Math.ceil(r.width) + 16;
    var h = Math.ceil(r.height) + 16;
    if (root && hint && root.classList.contains('is-hint-visible') && !root.classList.contains('is-open')) {
      var hr = hint.getBoundingClientRect();
      w = Math.max(w, Math.ceil(Math.max(r.width, hr.width) + 16));
      h = Math.ceil(r.height + hr.height + 28);
    }
    return {
      w: Math.max(336, w),
      h: Math.max(96, h),
    };
  }

  function wireBubbleHint(root) {
    var launcher = el('powerups-edge-launcher');
    if (!launcher || !root) return;
    var hintTimer = null;
    var HINT_DELAY_MS = 5000;

    function showHint() {
      if (root.classList.contains('is-open')) return;
      root.classList.add('is-hint-visible');
      notifyParentFrameSize(false);
    }
    function hideHint() {
      root.classList.remove('is-hint-visible');
      if (!root.classList.contains('is-open')) notifyParentFrameSize(false);
    }
    function scheduleHint() {
      if (hintTimer) clearTimeout(hintTimer);
      hintTimer = setTimeout(showHint, HINT_DELAY_MS);
    }
    function clearHintSchedule() {
      if (hintTimer) clearTimeout(hintTimer);
      hintTimer = null;
    }

    scheduleHint();

    launcher.addEventListener('mouseenter', function () {
      clearHintSchedule();
      showHint();
    });
    launcher.addEventListener('mouseleave', function () {
      if (root.classList.contains('is-open')) return;
      hideHint();
      scheduleHint();
    });
    launcher.addEventListener('focusin', function () {
      clearHintSchedule();
      showHint();
    });
    launcher.addEventListener('focusout', function () {
      if (root.classList.contains('is-open')) return;
      hideHint();
      scheduleHint();
    });

    root.__powerupsClearBubbleHint = function () {
      clearHintSchedule();
      root.classList.remove('is-hint-visible');
    };
    root.__powerupsScheduleBubbleHint = scheduleHint;
  }

  /** Notifica al host (widget-loader) que redimensione el iframe: pequeño = burbuja, grande = panel abierto. */
  function notifyParentFrameSize(open) {
    if (!isEmbedHost()) return;
    var root = el('powerups-edge-chat');
    if (!open && root && root.classList.contains('is-open')) return;
    var payload = { type: 'insightflow-widget', action: 'resize', open: !!open };
    if (!open) {
      var m = measureBubbleHostSize();
      payload.width = m.w;
      payload.height = m.h;
    }
    try {
      window.parent.postMessage(payload, '*');
    } catch (e) { /* cross-origin */ }
  }

  function ensureParentFrameOpen() {
    notifyParentFrameSize(true);
    if (!isEmbedHost()) return;
    requestAnimationFrame(function () { notifyParentFrameSize(true); });
    setTimeout(function () { notifyParentFrameSize(true); }, 80);
  }

  function apiOriginBase() {
    return String(CONFIG.API_BASE || '').replace(/\/$/, '');
  }

  /** premium-portal.html — pegar token o abrir visor premium. */
  function resolvePremiumPortalUrl() {
    if (CONFIG.PREMIUM_PORTAL_URL) return CONFIG.PREMIUM_PORTAL_URL;
    return apiOriginBase() + '/premium-portal.html';
  }

  /** premium-dashboard-session.html — añade ?token= si hay tablero guardado para este chat. */
  function resolveDashboardSessionUrl() {
    var base = CONFIG.DASHBOARD_SESSION_URL ? CONFIG.DASHBOARD_SESSION_URL : (apiOriginBase() + '/premium-dashboard-session.html');
    var path = base.split('?')[0];
    var tok = loadDashboardToken();
    if (tok) return path + '?token=' + encodeURIComponent(tok);
    return path;
  }

  function updatePortalLinks() {
    var aPortal = el('powerups-edge-link-portal');
    var aDash = el('powerups-edge-link-dashboard');
    if (aPortal) aPortal.href = resolvePremiumPortalUrl();
    if (aDash) aDash.href = resolveDashboardSessionUrl();
  }

  /** Evita la página intersticial de ngrok (tunnel gratuito) en peticiones al API. */
  function apiHeaders(extra) {
    var h = { 'ngrok-skip-browser-warning': 'true' };
    if (extra) {
      for (var k in extra) {
        if (Object.prototype.hasOwnProperty.call(extra, k)) h[k] = extra[k];
      }
    }
    return h;
  }

  function getOrCreateChatId() {
    var raw = localStorage.getItem(CONFIG.STORAGE_KEY_CHAT);
    var n = raw ? parseInt(raw, 10) : NaN;
    if (!isFinite(n) || n <= 0) {
      n = Math.floor(1e9 + Math.random() * 8.99e9);
      localStorage.setItem(CONFIG.STORAGE_KEY_CHAT, String(n));
    }
    // Exponer API_BASE en localStorage para que el portal premium y el visor puedan
    // usar el mismo endpoint sin que el usuario tenga que configurarlo manualmente.
    try { localStorage.setItem('powerups_edge_api_base', apiOriginBase()); } catch (e) {}
    return n;
  }

  function dashboardTokenStorageKey() {
    return CONFIG.STORAGE_KEY_DASH_PREFIX + String(getOrCreateChatId());
  }

  function saveDashboardToken(token) {
    if (!token) return;
    try {
      localStorage.setItem(dashboardTokenStorageKey(), token);
    } catch (e) { /* quota */ }
    updatePortalLinks();
  }

  function loadDashboardToken() {
    try {
      return localStorage.getItem(dashboardTokenStorageKey()) || '';
    } catch (e) {
      return '';
    }
  }

  /** Extrae token de una URL absoluta o relativa con ?token= */
  function tokenFromDashboardUrl(url) {
    if (!url || typeof url !== 'string') return null;
    var m = url.match(/(?:\?|&)token=([^&]+)/i);
    return m ? decodeURIComponent(m[1]) : null;
  }

  // ── Instancia ECharts global (un solo chart dentro del widget) ──────────────
  var _echartInstance = null;
  var _chartHistoryIndex = 0;

  function chartsStorageKey() {
    return CONFIG.STORAGE_KEY_CHARTS_PREFIX + String(getOrCreateChatId());
  }

  function loadChartsHistory() {
    try {
      var raw = localStorage.getItem(chartsStorageKey());
      if (!raw) return [];
      var arr = JSON.parse(raw);
      return Array.isArray(arr) ? arr : [];
    } catch (e) { return []; }
  }

  /** Añade un option al historial (más reciente primero, máx 6). */
  function saveChartToHistory(opt) {
    if (!opt || typeof opt !== 'object') return;
    var h = loadChartsHistory();
    h.unshift(opt);
    if (h.length > 6) h = h.slice(0, 6);
    try { localStorage.setItem(chartsStorageKey(), JSON.stringify(h)); } catch (e) {}
  }

  /** Actualiza la barra de navegación ← 2/4 → */
  function updateChartNav(total, index) {
    var nav = el('powerups-edge-chart-nav');
    if (!nav) return;
    if (total <= 1) { nav.hidden = true; return; }
    nav.hidden = false;
    nav.innerHTML = '';
    var prevBtn = document.createElement('button');
    prevBtn.type = 'button';
    prevBtn.className = 'powerups-edge__chart-nav-btn';
    prevBtn.textContent = '←';
    prevBtn.title = 'Gráfica anterior (más antigua)';
    prevBtn.disabled = index >= total - 1;
    prevBtn.addEventListener('click', function () { showChartAtIndex(index + 1); });
    var label = document.createElement('span');
    label.className = 'powerups-edge__chart-nav-label';
    label.textContent = (index + 1) + ' / ' + total;
    var nextBtn = document.createElement('button');
    nextBtn.type = 'button';
    nextBtn.className = 'powerups-edge__chart-nav-btn';
    nextBtn.textContent = '→';
    nextBtn.title = 'Gráfica siguiente (más reciente)';
    nextBtn.disabled = index <= 0;
    nextBtn.addEventListener('click', function () { showChartAtIndex(index - 1); });
    nav.appendChild(prevBtn);
    nav.appendChild(label);
    nav.appendChild(nextBtn);
  }

  /** Renderiza un ECharts option directamente en el canvas del widget (sin iframe). */
  function renderLiveChart(opt, noSave) {
    if (!opt || typeof opt !== 'object') return;
    if (!noSave) saveChartToHistory(opt);
    _chartHistoryIndex = noSave ? _chartHistoryIndex : 0;

    var canvas = el('powerups-edge-chart-canvas');
    var ph = el('powerups-edge-dashboard-placeholder');
    var openA = el('powerups-edge-dashboard-open');
    var wrapLive = el('powerups-edge-dashboard-live');
    if (!canvas) return;

    expandLiveDashboard();
    if (ph) ph.hidden = true;
    canvas.hidden = false;
    if (wrapLive) wrapLive.hidden = false;

    // Destruir instancia anterior para evitar leak de memoria
    if (_echartInstance) { try { _echartInstance.dispose(); } catch (e) {} _echartInstance = null; }

    if (typeof window.echarts === 'undefined') {
      // ECharts aún no cargó (ej. sin conexión); mostrar aviso en placeholder
      if (ph) { ph.hidden = false; ph.textContent = 'ECharts no disponible. Verifica la conexión a internet.'; }
      canvas.hidden = true;
      return;
    }

    _echartInstance = window.echarts.init(canvas, 'dark', { renderer: 'canvas' });
    _echartInstance.setOption(opt, true);
    setPanelChartMode(true);

    var h = loadChartsHistory();
    var idx = noSave ? _chartHistoryIndex : 0;
    updateChartNav(h.length, idx);
  }

  /** Muestra una gráfica del historial por índice (0 = más reciente). */
  function showChartAtIndex(index) {
    var h = loadChartsHistory();
    if (!h || index < 0 || index >= h.length) return;
    _chartHistoryIndex = index;
    renderLiveChart(h[index], true);
  }

  function setPanelChartMode(enabled) {
    var panel = el('powerups-edge-panel');
    if (!panel) return;
    if (enabled) {
      if (panel.classList.contains('has-chart')) return;
      var baseW = panel.offsetWidth || 420;
      panel.dataset.puPreChartW = String(baseW);
      var maxW = Math.min(920, window.innerWidth - 24);
      var expanded = Math.min(Math.round(baseW * 1.3), Math.round(maxW * 1.3));
      panel.style.width = expanded + 'px';
      panel.classList.add('has-chart');
      setTimeout(resizeLiveChart, 420);
    } else {
      panel.classList.remove('has-chart');
      if (panel.dataset.puPreChartW) {
        panel.style.width = panel.dataset.puPreChartW + 'px';
        delete panel.dataset.puPreChartW;
      }
    }
  }

  function expandLiveDashboard() {
    var wrap = el('powerups-edge-dashboard-frame-wrap');
    var btn = el('powerups-edge-dashboard-toggle');
    if (wrap) wrap.classList.remove('is-collapsed');
    if (!btn) return;
    btn.setAttribute('aria-expanded', 'true');
    btn.textContent = 'Ocultar gráfico';
  }

  function showDashboardPlaceholder() {
    setPanelChartMode(false);
    var canvas = el('powerups-edge-chart-canvas');
    var nav = el('powerups-edge-chart-nav');
    var ph = el('powerups-edge-dashboard-placeholder');
    var openA = el('powerups-edge-dashboard-open');
    if (_echartInstance) { try { _echartInstance.dispose(); } catch (e) {} _echartInstance = null; }
    if (canvas) canvas.hidden = true;
    if (nav) nav.hidden = true;
    if (ph) {
      ph.hidden = false;
      ph.textContent = 'Cuando pidas un análisis con datos, el tablero interactivo aparecerá aquí. Prueba: «gráfico de barras por mes», «mapa de calor por categoría» o «evolución en línea».';
    }
    if (openA) openA.hidden = true;
  }

  /** Al abrir el widget siendo premium: cargar la gráfica más reciente del historial local. */
  function hydrateLiveDashboardForPremium() {
    var h = loadChartsHistory();
    if (h.length > 0) {
      renderLiveChart(h[0], true); // noSave=true, no duplicar en historial
    } else {
      showDashboardPlaceholder();
    }
    updatePortalLinks();
  }

  /**
   * Tras POST /chat: renderiza la gráfica ECharts inline y actualiza el link externo.
   * Fuente principal: `echarts_option` en el JSON de respuesta.
   * Fuente secundaria: `dashboard_url` → link "Abrir en pestaña" con token one-shot.
   */
  function applyDashboardFromChatResponse(out) {
    if (!out) return;

    // 1. Renderizado inline (sin iframe, sin token, sin problema cross-origin)
    var opt = out.echarts_option || out.echartsOption || null;
    if (opt && typeof opt === 'object' && Object.keys(opt).length > 0) {
      renderLiveChart(opt); // guarda en historial y dibuja
    }

    // 2. Actualizar link "Abrir en pestaña" con la URL tokenizada del API
    var url = out.dashboard_url || out.dashboardUrl;
    if (!url && out.artifacts && out.artifacts.length) {
      for (var i = 0; i < out.artifacts.length; i++) {
        var a = out.artifacts[i];
        if (a && String(a.type).toLowerCase() === 'dashboard' && a.url) { url = a.url; break; }
      }
    }
    var openA = el('powerups-edge-dashboard-open');
    if (url && openA) { openA.href = url; openA.hidden = false; }
    var tok = url ? tokenFromDashboardUrl(url) : null;
    if (tok) saveDashboardToken(tok);
    updatePortalLinks();
  }

  /** Redimensiona el chart ECharts cuando el panel del widget cambia de tamaño. */
  function resizeLiveChart() {
    if (_echartInstance) { try { _echartInstance.resize(); } catch (e) {} }
  }

  function checkoutUrl() {
    var id = getOrCreateChatId();
    return String(CONFIG.CHECKOUT_URL).replace(/\{chatId\}/g, String(id));
  }

  function loadHistory() {
    try {
      var raw = localStorage.getItem(CONFIG.STORAGE_KEY_HISTORY);
      if (!raw) return [];
      var arr = JSON.parse(raw);
      return Array.isArray(arr) ? arr : [];
    } catch (e) { return []; }
  }

  function saveHistory(items) {
    try {
      localStorage.setItem(CONFIG.STORAGE_KEY_HISTORY, JSON.stringify(items.slice(-200)));
    } catch (e) { /* ignore quota */ }
  }

  async function setImageWithNgrokBypass(img, imageUrl) {
    try {
      var res = await fetch(imageUrl, {
        method: 'GET',
        headers: { 'ngrok-skip-browser-warning': 'true' },
        credentials: 'omit',
      });
      if (!res.ok) throw new Error('No se pudo descargar la imagen');
      var blob = await res.blob();
      var objectUrl = URL.createObjectURL(blob);
      img.onload = function () {
        setTimeout(function () { URL.revokeObjectURL(objectUrl); }, 1000);
      };
      img.src = objectUrl;
    } catch (e) {
      // Fallback por si el proxy/cdn bloquea fetch custom headers
      img.src = imageUrl;
    }
  }

  /**
   * Añade un mensaje al hilo.
   * - imageUrl: inserta <img> debajo del texto si es mensaje de bot.
   * - downloadInfo: { url, label } → inserta un botón de descarga del reporte.
   */
  function appendMessage(role, text, imageUrl, downloadInfo) {
    var box = el('powerups-edge-messages');
    var d = document.createElement('div');
    d.className = 'powerups-edge__msg powerups-edge__msg--' + (role === 'user' ? 'user' : role === 'sys' ? 'sys' : 'bot');
    var textEl = document.createElement('div');
    textEl.className = 'powerups-edge__msg-text';
    textEl.textContent = text;
    d.appendChild(textEl);
    if (imageUrl && role === 'bot') {
      var img = document.createElement('img');
      img.className = 'powerups-edge__chart';
      img.alt = 'Gráfica del análisis (InsightFlow)';
      img.loading = 'lazy';
      img.decoding = 'async';
      img.referrerPolicy = 'no-referrer-when-downgrade';
      d.appendChild(img);
      setImageWithNgrokBypass(img, imageUrl);
    }
    if (downloadInfo && downloadInfo.url && role === 'bot') {
      var isPremium = downloadInfo.label && downloadInfo.label.indexOf('Corporativo') !== -1;
      var btn = document.createElement('a');
      btn.href = downloadInfo.url;
      btn.target = '_blank';
      btn.rel = 'noopener noreferrer';
      btn.className = 'powerups-edge__download-btn' + (isPremium ? '' : ' powerups-edge__download-btn--basic');
      btn.textContent = (isPremium ? '⬇ ' : '↓ ') + (downloadInfo.label || 'Descargar Reporte');
      d.appendChild(btn);
    }
    box.appendChild(d);
    box.scrollTop = box.scrollHeight;
  }

  function hydrateFromStorage() {
    el('powerups-edge-messages').innerHTML = '';
    loadHistory().forEach(function (m) {
      appendMessage(m.role, m.text, m.imageUrl || null);
    });
  }

  function pushHistory(role, text, imageUrl) {
    var h = loadHistory();
    var entry = { role: role, text: text, t: Date.now() };
    if (imageUrl) entry.imageUrl = imageUrl;
    h.push(entry);
    saveHistory(h);
  }

  function setComposerLocked(locked) {
    el('powerups-edge-input').disabled = locked;
    el('powerups-edge-send').disabled = locked;
    el('powerups-edge-file').disabled = locked;
  }

  /** Solo mientras fetch al API: reemplaza "Enviar" por "Pensando…" + spinner (clase .is-processing). */
  function setComposerSending(sending) {
    var sendBtn = el('powerups-edge-send');
    var input = el('powerups-edge-input');
    sendBtn.setAttribute('aria-busy', sending ? 'true' : 'false');
    sendBtn.classList.toggle('is-processing', !!sending);
    // BUG FIX: la rama else faltaba; sin ella, disabled quedaba true para siempre
    // y el chat se bloqueaba tras el primer mensaje hasta recargar la página.
    sendBtn.disabled = !!sending;
    if (input) input.disabled = !!sending;
  }

  function setUsageUI(state) {
    var textEl = el('powerups-edge-usage-text');
    var fill = el('powerups-edge-usage-fill');
    var banner = el('powerups-edge-paywall');
    if (!state) {
      textEl.textContent = 'Mensajes usados: —/—';
      fill.style.width = '0%';
      return;
    }
    var limit = state.free_message_limit || 15;
    if (state.is_premium) {
      textEl.textContent = 'Plan premium activo · mensajes ilimitados';
      fill.style.width = '100%';
      banner.hidden = true;
      setComposerLocked(false);
      var dashLive = el('powerups-edge-dashboard-live');
      if (dashLive) {
        dashLive.hidden = false;
        hydrateLiveDashboardForPremium();
      }
      return;
    }
    var used = Math.min(state.message_count, limit);
    textEl.textContent = 'Mensajes usados: ' + used + '/' + limit;
    var pct = Math.min(100, Math.round((used / limit) * 100));
    fill.style.width = pct + '%';
    var wall = !!state.paywall && used >= limit;
    banner.hidden = !wall;
    setComposerLocked(wall);
    var premiumRow = document.querySelector('.powerups-edge__premium-row');
    var portalRow = document.querySelector('.powerups-edge__portal-row');
    if (premiumRow) premiumRow.hidden = wall;
    if (portalRow) portalRow.hidden = wall;
    var dashLiveFree = el('powerups-edge-dashboard-live');
    if (dashLiveFree) dashLiveFree.hidden = true;
  }

  async function fetchCredits() {
    var id = getOrCreateChatId();
    var url = CONFIG.API_BASE + '/api/v1/chat/' + encodeURIComponent(String(id)) + '/credits';
    var res = await fetch(url, { method: 'GET', headers: apiHeaders(), credentials: 'omit' });
    if (!res.ok) throw new Error('No se pudo obtener créditos');
    return res.json();
  }

  async function refreshCredits() {
    try {
      var j = await fetchCredits();
      setUsageUI(j);
      return j;
    } catch (e) {
      el('powerups-edge-usage-text').textContent = 'Estado de uso no disponible';
      return null;
    }
  }

  async function fetchBillingStatus() {
    var id = getOrCreateChatId();
    var url = CONFIG.API_BASE + '/api/v1/billing/status?chat_id=' + encodeURIComponent(String(id));
    var res = await fetch(url, { headers: apiHeaders(), credentials: 'omit' });
    if (!res.ok) throw new Error('billing/status');
    return res.json();
  }

  async function sendChatMessage(text) {
    var id = getOrCreateChatId();
    var body = { chat_id: id, message: text };
    if (CONFIG.USERNAME) body.username = CONFIG.USERNAME;
    var res = await fetch(CONFIG.API_BASE + '/api/v1/chat', {
      method: 'POST',
      headers: apiHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body),
      credentials: 'omit',
    });
    var j = await res.json().catch(function () { return {}; });
    if (!res.ok) {
      var det = j.detail || j.message || res.statusText;
      throw new Error(typeof det === 'string' ? det : 'Error del servidor');
    }
    return j;
  }

  async function uploadFile(file) {
    var id = getOrCreateChatId();
    var fd = new FormData();
    fd.append('chat_id', String(id));
    fd.append('file', file, file.name);
    var res = await fetch(CONFIG.API_BASE + '/api/v1/chat/upload', {
      method: 'POST',
      headers: apiHeaders(),
      body: fd,
      credentials: 'omit',
    });
    var j = await res.json().catch(function () { return {}; });
    if (!res.ok) {
      var det = j.detail || j.message || res.statusText;
      throw new Error(typeof det === 'string' ? det : 'Fallo al subir');
    }
    return j;
  }

  var panelResizeSaveTimer = null;

  function applySavedPanelSize() {
    var panel = el('powerups-edge-panel');
    var root = el('powerups-edge-chat');
    if (!panel) return;
    if (!root || !root.classList.contains('is-open')) return;
    if (isEmbedHost() && window.innerHeight < 200) return;
    if (typeof window.matchMedia === 'function' && window.matchMedia('(max-width: 480px)').matches) {
      panel.style.width = '';
      panel.style.height = '';
      return;
    }
    try {
      var raw = localStorage.getItem(CONFIG.STORAGE_KEY_PANEL_SIZE);
      if (!raw) return;
      var o = JSON.parse(raw);
      if (!o || typeof o.w !== 'number' || typeof o.h !== 'number') return;
      var maxW = Math.max(300, window.innerWidth - 24);
      var maxH = Math.max(340, window.innerHeight - 80);
      var w = Math.round(Math.min(Math.max(o.w, 300), maxW));
      var h = Math.round(Math.min(Math.max(o.h, 340), maxH));
      panel.style.width = w + 'px';
      panel.style.height = h + 'px';
    } catch (e) {}
  }

  function wirePanelResizePersistence() {
    var root = el('powerups-edge-chat');
    var panel = el('powerups-edge-panel');
    if (!root || !panel || typeof ResizeObserver === 'undefined') return;
    var ro = new ResizeObserver(function () {
      if (!root.classList.contains('is-open')) return;
      if (typeof window.matchMedia === 'function' && window.matchMedia('(max-width: 480px)').matches) return;
      if (root.classList.contains('is-resizing')) return;
      resizeLiveChart(); // mantener el chart ECharts responsivo al redimensionar el panel
      if (panelResizeSaveTimer) clearTimeout(panelResizeSaveTimer);
      panelResizeSaveTimer = setTimeout(function () {
        try {
          localStorage.setItem(CONFIG.STORAGE_KEY_PANEL_SIZE, JSON.stringify({
            w: panel.offsetWidth,
            h: panel.offsetHeight
          }));
        } catch (e) {}
      }, 320);
    });
    ro.observe(panel);
  }

  function wirePanelDragResize() {
    var panel = el('powerups-edge-panel');
    var root = el('powerups-edge-chat');
    if (!panel || !root) return;
    var minW = 300;
    var minH = 340;
    function maxDims() {
      return {
        w: Math.min(920, window.innerWidth - 24),
        h: Math.min(Math.floor(window.innerHeight * 0.92), window.innerHeight - 80),
      };
    }
    function persistPanelSize() {
      if (typeof window.matchMedia === 'function' && window.matchMedia('(max-width: 480px)').matches) return;
      try {
        localStorage.setItem(CONFIG.STORAGE_KEY_PANEL_SIZE, JSON.stringify({
          w: panel.offsetWidth,
          h: panel.offsetHeight,
        }));
      } catch (e) {}
    }
    function applyBounds(w, h) {
      var m = maxDims();
      return {
        w: Math.round(Math.min(Math.max(w, minW), m.w)),
        h: Math.round(Math.min(Math.max(h, minH), m.h)),
      };
    }
    function start(mode, clientX, clientY) {
      if (!root.classList.contains('is-open')) return;
      if (typeof window.matchMedia === 'function' && window.matchMedia('(max-width: 480px)').matches) return;
      var startX = clientX;
      var startY = clientY;
      var startW = panel.offsetWidth;
      var startH = panel.offsetHeight;
      var prevCursor = document.body.style.cursor;
      root.classList.add('is-resizing');
      if (mode === 'left' || mode === 'right') document.body.style.cursor = 'ew-resize';
      else if (mode === 'bottom') document.body.style.cursor = 'ns-resize';
      else if (mode === 'bl') document.body.style.cursor = 'nesw-resize';
      else if (mode === 'br') document.body.style.cursor = 'nwse-resize';
      function move(x, y) {
        var dx = x - startX;
        var dy = y - startY;
        var w = startW;
        var h = startH;
        if (mode === 'left') w = startW - dx;
        else if (mode === 'right') w = startW + dx;
        else if (mode === 'bottom') h = startH + dy;
        else if (mode === 'bl') {
          w = startW - dx;
          h = startH + dy;
        } else if (mode === 'br') {
          w = startW + dx;
          h = startH + dy;
        }
        var b = applyBounds(w, h);
        panel.style.width = b.w + 'px';
        panel.style.height = b.h + 'px';
      }
      function end() {
        document.removeEventListener('mousemove', onMouseMove);
        document.removeEventListener('mouseup', onMouseUp);
        document.removeEventListener('touchmove', onTouchMove);
        document.removeEventListener('touchend', onTouchEnd);
        document.removeEventListener('touchcancel', onTouchEnd);
        document.body.style.cursor = prevCursor;
        root.classList.remove('is-resizing');
        persistPanelSize();
      }
      function onMouseMove(e) {
        move(e.clientX, e.clientY);
      }
      function onMouseUp() {
        end();
      }
      function onTouchMove(e) {
        if (!e.touches || e.touches.length !== 1) return;
        e.preventDefault();
        move(e.touches[0].clientX, e.touches[0].clientY);
      }
      function onTouchEnd() {
        end();
      }
      document.addEventListener('mousemove', onMouseMove);
      document.addEventListener('mouseup', onMouseUp);
      document.addEventListener('touchmove', onTouchMove, { passive: false });
      document.addEventListener('touchend', onTouchEnd);
      document.addEventListener('touchcancel', onTouchEnd);
    }
    var edges = panel.querySelectorAll('[data-pu-resize]');
    for (var i = 0; i < edges.length; i++) {
      (function (edge) {
        edge.addEventListener('mousedown', function (e) {
          if (e.button !== 0) return;
          e.preventDefault();
          e.stopPropagation();
          start(edge.getAttribute('data-pu-resize') || '', e.clientX, e.clientY);
        });
        edge.addEventListener('touchstart', function (e) {
          if (!e.touches || e.touches.length !== 1) return;
          if (typeof window.matchMedia === 'function' && window.matchMedia('(max-width: 480px)').matches) return;
          e.preventDefault();
          e.stopPropagation();
          var t = e.touches[0];
          start(edge.getAttribute('data-pu-resize') || '', t.clientX, t.clientY);
        }, { passive: false });
      })(edges[i]);
    }
  }

  var viewportClampTimer = null;
  function wirePanelViewportClamp() {
    window.addEventListener('resize', function () {
      if (viewportClampTimer) clearTimeout(viewportClampTimer);
      viewportClampTimer = setTimeout(function () {
        var panel = el('powerups-edge-panel');
        if (!panel || typeof window.matchMedia === 'function' && window.matchMedia('(max-width: 480px)').matches) return;
        var m = {
          w: Math.min(920, window.innerWidth - 24),
          h: Math.min(Math.floor(window.innerHeight * 0.92), window.innerHeight - 80),
        };
        var ch = false;
        if (panel.offsetWidth > m.w) {
          panel.style.width = m.w + 'px';
          ch = true;
        }
        if (panel.offsetHeight > m.h) {
          panel.style.height = m.h + 'px';
          ch = true;
        }
        if (ch) {
          try {
            localStorage.setItem(CONFIG.STORAGE_KEY_PANEL_SIZE, JSON.stringify({
              w: panel.offsetWidth,
              h: panel.offsetHeight,
            }));
          } catch (e) {}
        }
      }, 120);
    });
  }

  async function premiumAction(prompt) {
    try {
      var bill = await fetchBillingStatus();
      if (!bill.is_premium) {
        window.location.href = checkoutUrl();
        return;
      }
      appendMessage('user', '[Acción premium] ' + (prompt === CONFIG.PROMPT_PDF ? 'Generar Informe PDF Premium' : 'Exportar Excel con Gráficas'), null, null);
      pushHistory('user', '[Acción premium] Solicitud de entregable');
      var out = await sendChatMessage(prompt);
      var imgUrl = out.image_url || out.imageUrl || null;
      var dlInfo = (out.download_url) ? { url: out.download_url, label: out.download_label || 'Descargar Reporte' } : null;
      appendMessage('bot', out.response || '(Sin texto de respuesta)', imgUrl, dlInfo);
      pushHistory('bot', out.response || '', imgUrl);
      applyDashboardFromChatResponse(out);
      await refreshCredits();
    } catch (e) {
      appendMessage('sys', 'No se pudo completar la acción: ' + (e.message || e), null);
    }
  }

  function wireUI() {
    var root = el('powerups-edge-chat');
    var panel = el('powerups-edge-panel');
    var toggle = el('powerups-edge-toggle');
    var closeBtn = el('powerups-edge-close');
    var form = el('powerups-edge-form');
    var input = el('powerups-edge-input');
    var sendBtn = el('powerups-edge-send');
    var file = el('powerups-edge-file');

    if (isEmbedHost()) {
      document.documentElement.classList.add('powerups-edge-in-iframe');
    }

    wirePanelResizePersistence();
    wirePanelDragResize();
    wirePanelViewportClamp();
    updatePortalLinks();
    wireBubbleHint(root);
    notifyParentFrameSize(false);
    setTimeout(function () {
      if (!root.classList.contains('is-open')) notifyParentFrameSize(false);
    }, 120);
    setTimeout(function () {
      if (!root.classList.contains('is-open')) notifyParentFrameSize(false);
    }, 480);

    toggle.addEventListener('click', function () {
      var open = !root.classList.contains('is-open');
      if (open) {
        if (root.__powerupsClearBubbleHint) root.__powerupsClearBubbleHint();
        root.classList.add('is-open');
        toggle.setAttribute('aria-expanded', 'true');
        panel.setAttribute('aria-hidden', 'false');
        ensureParentFrameOpen();
        applySavedPanelSize();
        updatePortalLinks();
        hydrateFromStorage();
        refreshCredits();
        setTimeout(function () { input.focus(); }, 280);
      } else {
        root.classList.remove('is-open');
        toggle.setAttribute('aria-expanded', 'false');
        panel.setAttribute('aria-hidden', 'true');
        notifyParentFrameSize(false);
      }
    });
    closeBtn.addEventListener('click', function () {
      root.classList.remove('is-open');
      toggle.setAttribute('aria-expanded', 'false');
      panel.setAttribute('aria-hidden', 'true');
      notifyParentFrameSize(false);
      if (root.__powerupsScheduleBubbleHint) root.__powerupsScheduleBubbleHint();
    });

    el('powerups-edge-paywall-pay').addEventListener('click', function () {
      window.location.href = checkoutUrl();
    });
    el('powerups-edge-dashboard-toggle').addEventListener('click', function () {
      var wrap = el('powerups-edge-dashboard-frame-wrap');
      var btn = el('powerups-edge-dashboard-toggle');
      if (!wrap || !btn) return;
      var collapsed = wrap.classList.toggle('is-collapsed');
      btn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
      btn.textContent = collapsed ? 'Mostrar gráfico' : 'Ocultar gráfico';
    });
    el('powerups-edge-btn-pdf').addEventListener('click', function () { premiumAction(CONFIG.PROMPT_PDF); });
    el('powerups-edge-btn-excel').addEventListener('click', function () { premiumAction(CONFIG.PROMPT_EXCEL); });

    form.addEventListener('submit', async function (ev) {
      ev.preventDefault();
      var t = (input.value || '').trim();
      if (!t) return;
      if (sendBtn && sendBtn.disabled) return;
      var st = await refreshCredits();
      if (st && st.paywall && !st.is_premium) return;

      setComposerSending(true);

      input.value = '';
      appendMessage('user', t, null);
      pushHistory('user', t);

      try {
        var out = await sendChatMessage(t);
        var imgU = out.image_url || out.imageUrl || null;
        var dlInfo = (out.download_url) ? { url: out.download_url, label: out.download_label || 'Descargar Reporte' } : null;
        if (out.paywall) {
          appendMessage('bot', out.response || 'Límite alcanzado.', null, null);
          pushHistory('bot', out.response || '');
        } else {
          appendMessage('bot', out.response || '(Sin respuesta)', imgU, dlInfo);
          pushHistory('bot', out.response || '', imgU);
        }
        applyDashboardFromChatResponse(out);
      } catch (err) {
        appendMessage('sys', 'Error: ' + (err.message || err), null, null);
      } finally {
        // BUG FIX: setComposerSending(false) va primero para garantizar que el
        // compositor se re-habilite incluso si refreshCredits() falla o devuelve
        // null (cuando retorna null, setUsageUI hace return temprano sin llamar
        // setComposerLocked, dejando los inputs bloqueados indefinidamente).
        // refreshCredits() aplica después el bloqueo de paywall si corresponde.
        setComposerSending(false);
        await refreshCredits();
      }
    });

    // El listener de token_refresh ya no es necesario (ECharts es inline, no en iframe externo).
    // Se mantiene como no-op por compatibilidad con instancias antiguas en caché.
    window.addEventListener('message', function (ev) {
      try {
        var d = ev.data;
        if (!d || d.type !== 'insightflow-dashboard') return;
        // no-op: el visor en vivo ya no usa iframe/token externo
      } catch (e) {}
    });

    file.addEventListener('change', async function () {
      var f = file.files && file.files[0];
      if (!f) return;
      file.value = '';
      var st = await refreshCredits();
      if (st && st.paywall && !st.is_premium) {
        appendMessage('sys', 'Primero desbloquea el análisis para adjuntar archivos.', null);
        return;
      }
      appendMessage('sys', 'Subiendo: ' + f.name + '…', null);
      try {
        var up = await uploadFile(f);
        var msg = up.message || ('Archivo recibido' + (up.indexed ? ' (indexado).' : '.'));
        appendMessage('bot', msg, null);
        pushHistory('bot', msg);
      } catch (err) {
        appendMessage('sys', 'No se pudo subir el archivo: ' + (err.message || err), null);
      }
    });
  }

  if (document.readyState === 'loading')
    document.addEventListener('DOMContentLoaded', wireUI);
  else
    wireUI();
})();
