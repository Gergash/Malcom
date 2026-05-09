/**
 * Host (WordPress / BeBuilder): coloca este script al final del body (hook "Bottom").
 * No pegues el iframe aquí: el loader crea un lienzo a pantalla completa; el documento
 * del iframe (#powerups-edge-chat) recoge los clics; el resto deja pasar los eventos
 * según powerups-edge-frame.html (body transparente).
 *
 * Opcional antes de este script:
 *   window.POWERUPS_WIDGET_CONFIG = { API_BASE: '…', CHECKOUT_URL: '…', … };
 *   window.POWERUPS_WIDGET_LOADER = {
 *     frameUrl: 'https://cdn…/powerups-edge-frame.html',
 *     assetsBase: 'https://…/uploads/2026/05/',  // misma carpeta que frame/css/js (p. ej. WordPress Medios)
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
    "inset:0",
    "width:100%",
    "height:100%",
    "border:0",
    "margin:0",
    "padding:0",
    "pointer-events:none",
    "z-index:" + String(z),
    "background:transparent",
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
    /* El padre tiene pointer-events:none; sin auto aquí el iframe no recibe clics en varios navegadores. */
    "pointer-events:auto",
  ].join(";");
  ifr.src = u.toString();
  wrap.appendChild(ifr);
})();
