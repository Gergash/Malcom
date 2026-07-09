/**
 * InsightFlow — checkout Bold (Embedded Checkout)
 * Cargado desde Hook Bottom cuando existe #pu-bold-mount.
 * Medios: https://www.powerupsagencia.com/wp-content/uploads/2026/07/powerups-bold-checkout.js
 *
 * Bold doc: el script del SDK puede ir en el mismo <script> que data-bold-button
 * (src="https://checkout.bold.co/library/boldPaymentButton.js").
 */
(function () {
  'use strict';

  var DEFAULT_API_BASE = 'https://nonconfidential-suprarational-sage.ngrok-free.dev';
  var STORAGE_CHAT = 'powerups_edge_chat_id_v1';
  var STORAGE_API = 'powerups_edge_api_base';
  var BOLD_SDK = 'https://checkout.bold.co/library/boldPaymentButton.js';

  function el(id) {
    return document.getElementById(id);
  }

  function setStatus(msg, isError) {
    var hint = el('pu-bold-hint');
    var err = el('pu-bold-error');
    if (isError) {
      if (hint) hint.hidden = true;
      if (err) {
        err.textContent = msg;
        err.hidden = false;
      }
      return;
    }
    if (err) err.hidden = true;
    if (hint) {
      hint.textContent = msg;
      hint.hidden = false;
    }
  }

  function resolveApiBase() {
    var card = el('pu-pro-card');
    var fromData = card && card.getAttribute('data-api-base');
    if (fromData && String(fromData).trim()) return String(fromData).trim().replace(/\/$/, '');
    try {
      var cfg = window.POWERUPS_WIDGET_CONFIG || {};
      if (cfg.API_BASE && String(cfg.API_BASE).trim()) {
        return String(cfg.API_BASE).trim().replace(/\/$/, '');
      }
      var stored = localStorage.getItem(STORAGE_API);
      if (stored && String(stored).trim()) return String(stored).trim().replace(/\/$/, '');
    } catch (e) { /* private mode */ }
    return DEFAULT_API_BASE.replace(/\/$/, '');
  }

  function resolveChatId() {
    var params = new URLSearchParams(window.location.search);
    var fromUrl = (params.get('chat_id') || '').trim();
    if (/^\d+$/.test(fromUrl)) return fromUrl;
    try {
      var stored = localStorage.getItem(STORAGE_CHAT);
      if (stored && /^\d+$/.test(String(stored).trim())) return String(stored).trim();
    } catch (e) { /* private mode */ }
    return '';
  }

  function mountBoldButton(cfg) {
    var mount = el('pu-bold-mount');
    if (!mount) return;

    mount.innerHTML = '';

    // Bold: src del SDK + atributos en el MISMO <script> (integración manual §1).
    var btn = document.createElement('script');
    btn.src = BOLD_SDK;
    btn.setAttribute('data-bold-button', '');
    btn.setAttribute('data-order-id', cfg.order_id);
    btn.setAttribute('data-currency', cfg.currency);
    btn.setAttribute('data-amount', String(cfg.amount_cop));
    btn.setAttribute('data-api-key', cfg.api_key);
    btn.setAttribute('data-integrity-signature', cfg.integrity_signature);
    btn.setAttribute('data-description', cfg.description);
    btn.setAttribute('data-redirection-url', cfg.redirection_url);
    btn.setAttribute('data-render-mode', cfg.render_mode || 'embedded');

    btn.onload = function () {
      if (el('pu-bold-hint')) el('pu-bold-hint').hidden = true;
    };
    btn.onerror = function () {
      setStatus('No se pudo cargar el botón de Bold. Revisa la consola (F12).', true);
    };

    mount.appendChild(btn);
  }

  function init() {
    if (!el('pu-bold-mount')) return;
    if (window.__PU_BOLD_CHECKOUT_INIT) return;
    window.__PU_BOLD_CHECKOUT_INIT = true;

    var chatId = resolveChatId();
    if (!chatId) {
      setStatus(
        'Abre el chat y pulsa «Activar mensajes ilimitados», o entra con ?chat_id=TU_ID en la URL.',
        false
      );
      return;
    }

    setStatus('Preparando botón de pago Bold…', false);

    var apiBase = resolveApiBase();
    var url = apiBase + '/api/v1/billing/bold-checkout?chat_id=' + encodeURIComponent(chatId);

    fetch(url, {
      mode: 'cors',
      credentials: 'omit',
      headers: { 'ngrok-skip-browser-warning': '1', Accept: 'application/json' },
    })
      .then(function (res) {
        return res.text().then(function (text) {
          var body = {};
          try { body = text ? JSON.parse(text) : {}; } catch (e) { /* HTML error page */ }
          if (!res.ok) {
            throw new Error(body.detail || ('API respondió ' + res.status));
          }
          return body;
        });
      })
      .then(function (cfg) {
        if (!cfg || !cfg.order_id || !cfg.integrity_signature) {
          throw new Error('Respuesta incompleta del servidor de pago.');
        }
        mountBoldButton(cfg);
      })
      .catch(function (err) {
        setStatus((err && err.message) ? err.message : 'Error al conectar con la API de pago.', true);
      });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
