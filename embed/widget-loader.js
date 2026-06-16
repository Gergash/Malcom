/**
 * Host (WordPress / BeBuilder): coloca este script al final del body (hook "Bottom").
 *
 * El iframe inicia PEQUEÑO (solo la burbuja, ~240×70) para no bloquear clics en la página.
 * Cuando el usuario abre el asistente, powerups-edge-widget.js envía postMessage y el
 * iframe crece a min(960px,100vw) × min(92vh,100vh).
 *
 * Opcional antes de este script:
 *   window.POWERUPS_WIDGET_CONFIG = { API_BASE: '…', CHECKOUT_URL: '…', … };
 *   window.POWERUPS_WIDGET_LOADER = {
 *     frameUrl: 'https://cdn…/powerups-edge-frame.html',
 *     assetsBase: 'https://…/uploads/2026/05/',
 *     zIndex: 2147483000
 *   };
 */
(function () {
  if (typeof window === "undefined" || typeof document === "undefined") return;
  if (window.__POWERUPS_WIDGET_LOADER_RAN) return;
  window.__POWERUPS_WIDGET_LOADER_RAN = true;

  var LOADER = window.POWERUPS_WIDGET_LOADER && typeof window.POWERUPS_WIDGET_LOADER === "object"
    ? window.POWERUPS_WIDGET_LOADER
    : {};
  var cfg = window.POWERUPS_WIDGET_CONFIG && typeof window.POWERUPS_WIDGET_CONFIG === "object"
    ? window.POWERUPS_WIDGET_CONFIG
    : {};

  var BUBBLE_W = 240;
  var BUBBLE_H = 70;
  var HOST_INSET = "18px";

  function cerrarInsightFlow(host, w, h) {
    if (!host) return;
    var bw = w && w > 0 ? Math.ceil(w) : BUBBLE_W;
    var bh = h && h > 0 ? Math.ceil(h) : BUBBLE_H;
    host.style.width = bw + "px";
    host.style.height = bh + "px";
    host.style.maxWidth = bw + "px";
    host.style.maxHeight = bh + "px";
    host.setAttribute("data-powerups-open", "false");
  }

  function abrirInsightFlow(host) {
    if (!host) return;
    host.style.width = "min(960px, 100vw)";
    host.style.height = "min(92vh, 100vh)";
    host.style.maxWidth = "100vw";
    host.style.maxHeight = "100vh";
    host.setAttribute("data-powerups-open", "true");
  }

  function handleResizeMessage(host, ifr, ev) {
    var data = ev.data;
    if (!data || data.type !== "insightflow-widget" || data.action !== "resize") return;
    if (ifr && ifr.contentWindow && ev.source && ev.source !== ifr.contentWindow) return;
    if (data.open) abrirInsightFlow(host);
    else cerrarInsightFlow(host, data.width, data.height);
  }

  function wireIframeResize(host, ifr) {
    window.addEventListener("message", function (ev) {
      handleResizeMessage(host, ifr, ev);
    });
  }

  /** Mismo origen (WP uploads): observa .is-open si postMessage falla o hay caché vieja del widget. */
  function wireIframeOpenStateSync(host, ifr) {
    function syncFromRoot(root) {
      if (!root) return;
      if (root.classList.contains("is-open")) abrirInsightFlow(host);
      else cerrarInsightFlow(host);
    }
    function attach(doc) {
      if (!doc) return;
      var root = doc.getElementById("powerups-edge-chat");
      if (!root) return;
      syncFromRoot(root);
      if (typeof MutationObserver === "undefined") return;
      new MutationObserver(function () { syncFromRoot(root); }).observe(root, {
        attributes: true,
        attributeFilter: ["class"],
      });
    }
    ifr.addEventListener("load", function () {
      try {
        attach(ifr.contentDocument || (ifr.contentWindow && ifr.contentWindow.document));
      } catch (e) { /* cross-origin */ }
    });
    try {
      if (ifr.contentDocument && ifr.contentDocument.getElementById("powerups-edge-chat")) {
        attach(ifr.contentDocument);
      }
    } catch (e) { /* not loaded */ }
  }

  var script = document.currentScript;
  var baseDir = "";
  if (script && script.src) {
    baseDir = script.src.replace(/[^/]*$/, "");
  }
  if (!baseDir && LOADER.assetsBase) {
    baseDir = String(LOADER.assetsBase).trim().replace(/\/?$/, "/");
  }

  var frameHref;
  if (LOADER.frameUrl) {
    frameHref = LOADER.frameUrl;
  } else if (baseDir) {
    frameHref = new URL("powerups-edge-frame.html", baseDir).href;
  } else {
    frameHref = "powerups-edge-frame.html";
  }

  var u;
  try {
    u = new URL(frameHref, window.location.href);
  } catch (e) {
    u = new URL("powerups-edge-frame.html", window.location.href);
  }

  var qp = [
    ["apiBase", cfg.API_BASE],
    ["checkoutUrl", cfg.CHECKOUT_URL],
    ["premiumPortalUrl", cfg.PREMIUM_PORTAL_URL],
    ["dashboardSessionUrl", cfg.DASHBOARD_SESSION_URL],
    ["username", cfg.USERNAME],
  ];
  for (var i = 0; i < qp.length; i++) {
    var key = qp[i][0];
    var val = qp[i][1];
    if (val != null && val !== "") u.searchParams.set(key, String(val));
  }

  var id = LOADER.containerId || "powerups-edge-widget-host";
  var z = LOADER.zIndex != null ? LOADER.zIndex : 2147483000;

  var wrap = document.getElementById(id);
  if (!wrap) {
    wrap = document.createElement("div");
    wrap.id = id;
    document.body.appendChild(wrap);
  }
  wrap.setAttribute("data-powerups-widget-host", "");
  wrap.style.cssText = [
    "position:fixed",
    "right:" + HOST_INSET,
    "bottom:" + HOST_INSET,
    "left:auto",
    "top:auto",
    "border:0",
    "margin:0",
    "padding:0",
    "pointer-events:none",
    "z-index:" + String(z),
    "background:transparent",
    "overflow:visible",
  ].join(";");

  var ifr = document.createElement("iframe");
  ifr.setAttribute("title", LOADER.frameTitle || "InsightFlow asistente");
  ifr.setAttribute(
    "sandbox",
    "allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox allow-downloads allow-top-navigation-by-user-activation",
  );
  ifr.setAttribute("allow", "clipboard-write");
  ifr.referrerPolicy = "strict-origin-when-cross-origin";
  ifr.style.cssText = [
    "position:absolute",
    "inset:0",
    "width:100%",
    "height:100%",
    "border:0",
    "margin:0",
    "padding:0",
    "background:transparent",
    "pointer-events:auto",
  ].join(";");
  ifr.src = u.toString();
  wrap.appendChild(ifr);

  cerrarInsightFlow(wrap);
  wireIframeResize(wrap, ifr);
  wireIframeOpenStateSync(wrap, ifr);

  window.POWERUPS_WIDGET_LOADER_API = window.POWERUPS_WIDGET_LOADER_API || {};
  window.POWERUPS_WIDGET_LOADER_API.abrirInsightFlow = function () { abrirInsightFlow(wrap); };
  window.POWERUPS_WIDGET_LOADER_API.cerrarInsightFlow = function () { cerrarInsightFlow(wrap); };
})();
