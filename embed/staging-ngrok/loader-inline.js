/**
 * Loader del widget InsightFlow para staging ngrok.
 * Requiere window.POWERUPS_WIDGET_LOADER y window.POWERUPS_WIDGET_CONFIG
 * (los define standalone-harness.html o bebuilder-install-snippet.ngrok.html).
 */
(function () {
  if (typeof document === "undefined") return;
  if (window.__POWERUPS_WIDGET_LOADER_RAN) return;
  window.__POWERUPS_WIDGET_LOADER_RAN = true;

  var LOADER = window.POWERUPS_WIDGET_LOADER || {};
  var cfg = window.POWERUPS_WIDGET_CONFIG || {};
  var DEFAULT_ASSETS_BASE = (window.location.origin || "") + "/embed/";
  var baseDir = String(LOADER.assetsBase || DEFAULT_ASSETS_BASE).trim().replace(/\/?$/, "/");
  if (!baseDir) return;

  var BUBBLE_W = 336;
  var BUBBLE_H = 96;
  var HOST_INSET = "18px";
  var hostRef = null;
  var ifrRef = null;

  function clampBubbleSize(w, h) {
    return {
      w: Math.max(BUBBLE_W, w && w > 0 ? Math.ceil(w) : BUBBLE_W),
      h: Math.max(BUBBLE_H, h && h > 0 ? Math.ceil(h) : BUBBLE_H),
    };
  }

  function abrirInsightFlow(host, ifr) {
    host = host || hostRef;
    ifr = ifr || ifrRef;
    if (!host) return;
    host.style.width = "min(960px, 100vw)";
    host.style.height = "min(92vh, 100vh)";
    host.style.maxWidth = "100vw";
    host.style.maxHeight = "100vh";
    host.style.overflow = "visible";
    host.setAttribute("data-powerups-open", "true");
    if (ifr) ifr.style.overflow = "visible";
  }

  function cerrarInsightFlow(host, ifr, w, h) {
    host = host || hostRef;
    ifr = ifr || ifrRef;
    if (!host) return;
    var size = clampBubbleSize(w, h);
    host.style.width = size.w + "px";
    host.style.height = size.h + "px";
    host.style.maxWidth = size.w + "px";
    host.style.maxHeight = size.h + "px";
    host.style.overflow = "hidden";
    host.setAttribute("data-powerups-open", "false");
    if (ifr) ifr.style.overflow = "hidden";
  }

  window.POWERUPS_WIDGET_LOADER_API = {
    abrirInsightFlow: function () {
      abrirInsightFlow(hostRef, ifrRef);
    },
    cerrarInsightFlow: function () {
      cerrarInsightFlow(hostRef, ifrRef);
    },
  };

  function measureBubbleFromIframe(ifr) {
    try {
      var doc = ifr.contentDocument || (ifr.contentWindow && ifr.contentWindow.document);
      var toggle = doc && (doc.getElementById("powerups-edge-launcher") || doc.getElementById("powerups-edge-toggle"));
      if (!toggle) return null;
      var r = toggle.getBoundingClientRect();
      return clampBubbleSize(r.width + 12, r.height + 12);
    } catch (e) {
      return null;
    }
  }

  function handleResizeMessage(host, ifr, ev) {
    var data = ev.data;
    if (!data || data.type !== "insightflow-widget" || data.action !== "resize") return;
    if (ifr && ifr.contentWindow && ev.source && ev.source !== ifr.contentWindow) return;
    if (data.open) {
      abrirInsightFlow(host, ifr);
      return;
    }
    try {
      var doc = ifr && (ifr.contentDocument || (ifr.contentWindow && ifr.contentWindow.document));
      var chatRoot = doc && doc.getElementById("powerups-edge-chat");
      if (chatRoot && chatRoot.classList.contains("is-open")) return;
    } catch (e) { /* cross-origin */ }
    cerrarInsightFlow(host, ifr, data.width, data.height);
  }

  function wireIframeResize(host, ifr) {
    window.addEventListener("message", function (ev) {
      handleResizeMessage(host, ifr, ev);
    });
  }

  function wireIframeOpenStateSync(host, ifr) {
    function syncFromRoot(root) {
      if (!root) return;
      if (root.classList.contains("is-open")) abrirInsightFlow(host, ifr);
      else {
        var m = measureBubbleFromIframe(ifr);
        cerrarInsightFlow(host, ifr, m && m.w, m && m.h);
      }
    }
    function attach(doc) {
      if (!doc) return false;
      var root = doc.getElementById("powerups-edge-chat");
      if (!root) return false;
      syncFromRoot(root);
      if (typeof MutationObserver === "undefined") return true;
      new MutationObserver(function () {
        syncFromRoot(root);
      }).observe(root, {
        attributes: true,
        attributeFilter: ["class"],
      });
      return true;
    }
    ifr.addEventListener("load", function () {
      try {
        var doc = ifr.contentDocument || (ifr.contentWindow && ifr.contentWindow.document);
        if (!attach(doc)) {
          console.error(
            "[InsightFlow staging] iframe no cargó powerups-edge-frame.html. frameUrl=" +
              String(ifr.src || ""),
          );
        }
      } catch (e) { /* cross-origin */ }
    });
  }

  var frameHref = LOADER.frameUrl || baseDir + "powerups-edge-frame.html";
  var u;
  try {
    u = new URL(frameHref, window.location.href);
  } catch (e) {
    return;
  }

  var qp = [
    ["apiBase", cfg.API_BASE],
    ["checkoutUrl", cfg.CHECKOUT_URL],
    ["premiumPortalUrl", cfg.PREMIUM_PORTAL_URL],
    ["dashboardSessionUrl", cfg.DASHBOARD_SESSION_URL],
    ["username", cfg.USERNAME],
  ];
  for (var i = 0; i < qp.length; i++) {
    var val = qp[i][1];
    if (val != null && val !== "") u.searchParams.set(qp[i][0], String(val));
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
  ifr.setAttribute("scrolling", "no");
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
    "overflow:hidden",
    "pointer-events:auto",
  ].join(";");
  ifr.src = u.toString();
  wrap.appendChild(ifr);

  hostRef = wrap;
  ifrRef = ifr;
  cerrarInsightFlow(wrap, ifr);
  wireIframeResize(wrap, ifr);
  wireIframeOpenStateSync(wrap, ifr);
})();
