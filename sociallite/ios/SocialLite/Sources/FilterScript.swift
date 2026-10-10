// GENERADO por scripts/embed_filter.py desde shared/filter.js. No editar a mano:
// cambia shared/filter.js y vuelve a correr el script.

enum FilterScript {
    static let source = #"""
/*
 * SocialLite — núcleo del filtro para instagram.com.
 *
 * El mismo archivo corre en la app de iPhone (WKUserScript) y en la extensión de
 * navegador (content script). Sin dependencias, ES2019.
 *
 * Solo oculta elementos y redirige rutas: no lee ni guarda contenido de mensajes,
 * nombres, cookies ni contraseñas, y no hace peticiones de red. Lo único que guarda
 * es la lista de IDs de publicaciones del inicio vistas hoy (para el tope diario).
 *
 * Robustez frente a cambios de Instagram: nunca usa clases CSS ofuscadas, solo rutas
 * (location.pathname), atributos href, etiquetas semánticas (article, main) y textos
 * visibles cortos en español e inglés.
 */
(function () {
  'use strict';

  var w = window;
  if (w.__SOCIALLITE_LOADED__) return;
  w.__SOCIALLITE_LOADED__ = true;

  var VERSION = '1.0.0';

  var DEFAULTS = {
    blockReels: true,
    hideFeedReels: true,
    blockExplore: true,
    hideAds: true,
    hideSuggested: true,
    grayscale: true,
    feedLimit: 20,
    dmOnlyMode: false,
    lockToDMs: false
  };

  // Textos visibles que delatan publicidad, sugerencias y el fin del inicio (normalizados).
  var AD_TEXTS = ['sponsored', 'publicidad', 'patrocinado', 'anuncio', 'ad'];
  var SUGGESTED_TEXTS = ['suggested for you', 'sugerencias para ti', 'sugerencia para ti',
    'sugerido para ti', 'recomendado para ti'];
  var END_MARKERS = ["you're all caught up", 'ya viste todo', 'estás al día', 'ya estás al día',
    'suggested posts', 'publicaciones sugeridas'];

  var INBOX = '/direct/inbox/';
  var SEEN_KEY = 'sociallite:seen';
  var NAV_KEYS = { ArrowUp: true, ArrowDown: true, PageUp: true, PageDown: true };

  var CSS = [
    'html[data-sl-block-reels] a[href="/reels/"]{display:none!important}',
    'html[data-sl-block-explore][data-sl-route="explore"] main a[href*="/p/"],' +
      'html[data-sl-block-explore][data-sl-route="explore"] main a[href*="/reel/"]{display:none!important}',
    // En html y no en body: así no se rompen los position:fixed de la página.
    'html[data-sl-gray]:not([data-sl-route="direct"]):not([data-sl-route="shared"])' +
      ':not([data-sl-route="auth"]){filter:grayscale(1)}',
    '[data-sl-hidden]{display:none!important}',
    'html[data-sl-leaving] body{visibility:hidden!important}',
    '#sl-toast{position:fixed;left:50%;bottom:calc(84px + env(safe-area-inset-bottom,0px));' +
      'transform:translateX(-50%);z-index:2147483647;max-width:80vw;padding:10px 18px;border-radius:999px;' +
      'background:rgba(24,24,24,.94);color:#fff;font:600 15px/1.3 -apple-system,system-ui,sans-serif;' +
      'text-align:center;pointer-events:none;opacity:0;transition:opacity .2s}',
    '#sl-toast[data-show]{opacity:1}',
    '#sl-endcard{position:fixed;left:12px;right:12px;bottom:calc(76px + env(safe-area-inset-bottom,0px));' +
      'z-index:2147483647;padding:18px 16px;border-radius:16px;background:#fff;color:#111;' +
      'box-shadow:0 8px 30px rgba(0,0,0,.28);font:15px/1.45 -apple-system,system-ui,sans-serif;' +
      'text-align:center;pointer-events:auto}',
    '#sl-endcard p{margin:0 0 10px}',
    '#sl-endcard a{display:inline-block;padding:8px 14px;border-radius:10px;background:#0a66ff;color:#fff;' +
      'font-weight:700;text-decoration:none}',
    '@media (prefers-color-scheme: dark){#sl-endcard{background:#1c1c1e;color:#f2f2f2}}'
  ].join('\n');

  // ------------------------------------------------------------------ estado

  var config = assign({}, DEFAULTS);
  var hooks = {};
  var started = false;
  var booted = false;

  var lastPath = null;     // última ruta evaluada; null fuerza la reevaluación
  var curPath = null;      // ruta actual
  var originPath = null;   // ruta anterior a la actual (para saber si algo viene de un DM)
  var lastSafe = '/';      // última ruta que no fue un reel ni el feed de reels (con ?search)
  var route = null;
  var reportedRoute = null;
  var reportedPath = null;
  var reelScrollReported = false;
  var limitReached = false;  // pegajoso durante la página
  var markerCache = null;
  var scanTimer = null;
  var toastTimer = null;

  // ---------------------------------------------------------------- utilidades

  function assign(target, src) {
    if (src) {
      for (var k in src) {
        if (Object.prototype.hasOwnProperty.call(src, k)) target[k] = src[k];
      }
    }
    return target;
  }

  function normalize(s) {
    return String(s || '')
      .replace(/[‘’‚‛′´`]/g, "'")
      .replace(/\s+/g, ' ')
      .trim()
      .toLowerCase();
  }

  function pad(n) { return n < 10 ? '0' + n : String(n); }

  function today() {
    var d = new Date();
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
  }

  function setAttr(el, name, on, value) {
    if (!el) return;
    if (on) {
      if (el.getAttribute(name) !== (value || '')) el.setAttribute(name, value || '');
    } else if (el.hasAttribute(name)) {
      el.removeAttribute(name);
    }
  }

  // ------------------------------------------------------------------- rutas

  function isDirect(p) { return p === '/direct' || p.indexOf('/direct/') === 0; }
  function isAuth(p) { return /^\/(accounts|challenge|auth_platform|two_factor|oauth|emails|legal)(\/|$)/.test(p); }
  function isReelsFeed(p) { return p === '/reels/' || p === '/reels'; }
  // /reel/ID, /reels/ID y /usuario/reel/ID (Instagram usa las tres formas).
  function isReelSingle(p) { return /^\/reels?\/[^/]+\/?$/.test(p) || /^\/[^/]+\/reel\/[^/]+\/?$/.test(p); }
  function isPostSingle(p) { return /^\/p\/[^/]+\/?$/.test(p) || /^\/[^/]+\/p\/[^/]+\/?$/.test(p); }
  function isStorySingle(p) { return /^\/stories\/[^/]+\/[^/]+\/?$/.test(p); }
  function isSingle(p) { return isReelSingle(p) || isPostSingle(p) || isStorySingle(p); }

  function classify(p, origin) {
    if (isDirect(p)) return 'direct';
    if (isSingle(p) && origin !== null && isDirect(origin)) return 'shared';
    if (isAuth(p)) return 'auth';
    if (p === '/') return 'home';
    if (p.indexOf('/explore') === 0) return 'explore';
    if (isReelSingle(p)) return 'reel';
    return 'other';
  }

  function isLocked() { return !!(config.dmOnlyMode || config.lockToDMs); }

  function safePath() { return isLocked() ? INBOX : lastSafe; }

  // ---------------------------------------------------------------- reportes

  function report(type, reason) {
    var payload = { type: type, reason: reason, path: location.pathname };
    try {
      var mh = w.webkit && w.webkit.messageHandlers && w.webkit.messageHandlers.sociallite;
      if (mh) mh.postMessage(payload);
    } catch (e) { /* sin puente nativo */ }
    if (typeof hooks.report === 'function') {
      try { hooks.report(payload); } catch (e2) { /* el host no debe romper el filtro */ }
    }
  }

  function reportRoute(r, p) {
    if (r === reportedRoute && p === reportedPath) return;
    reportedRoute = r;
    reportedPath = p;
    report('route', r);
  }

  function go(path) {
    if (typeof hooks.navigate === 'function') {
      hooks.navigate(path);
      return;
    }
    var h = document.documentElement;
    setAttr(h, 'data-sl-leaving', true);  // no mostrar lo bloqueado mientras se va
    try {
      location.replace(path);
    } catch (e) {
      setAttr(h, 'data-sl-leaving', false);
    }
  }

  // -------------------------------------------------------------- navegación

  function check() {
    var p = location.pathname || '/';
    if (p === lastPath) return;
    lastPath = p;
    if (p !== curPath) {
      originPath = curPath;
      curPath = p;
      reelScrollReported = false;
    }
    evaluate(p);
  }

  function evaluate(p) {
    var r = classify(p, originPath);
    route = r;
    setAttr(document.documentElement, 'data-sl-route', true, r);

    // 1. Bloqueado: solo mensajes, login y lo que se abre desde un mensaje.
    if (isLocked() && r !== 'direct' && r !== 'auth' && r !== 'shared') {
      if (p !== '/') report('blocked', 'locked');
      go(INBOX);
      return;
    }

    // 2. Reels: nada de feed de reels ni de pasar de un reel a otro.
    if (config.blockReels) {
      if (isReelsFeed(p)) {
        report('blocked', 'reels-feed');
        go(safePath());
        return;
      }
      if (isReelSingle(p) && originPath !== null && isReelSingle(originPath)) {
        report('blocked', 'reel-swipe');
        go(safePath());
        return;
      }
    }

    // 3. Última ruta segura: la última que no fue un reel ni el feed de reels.
    if (!isReelsFeed(p) && !isReelSingle(p)) lastSafe = p + (location.search || '');

    reportRoute(r, p);
    scheduleScan(0);
  }

  function patchHistory() {
    ['pushState', 'replaceState'].forEach(function (name) {
      var orig = history[name];
      if (typeof orig !== 'function' || orig.__sociallite) return;
      var wrapped = function () {
        var res = orig.apply(this, arguments);
        try { check(); } catch (e) { /* nunca romper la navegación de la página */ }
        return res;
      };
      wrapped.__sociallite = true;
      try { history[name] = wrapped; } catch (e2) { /* el sondeo cubre este caso */ }
    });
  }

  // --------------------------------------------------------- guardas de gesto

  function onGesture(e) {
    if (e.type === 'keydown') {
      if (!NAV_KEYS[e.key]) return;
      var t = e.target;
      if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName || ''))) return;
    }
    if (config.blockReels && curPath !== null && isReelSingle(curPath)) {
      if (e.cancelable) e.preventDefault();
      if (!reelScrollReported) {
        reelScrollReported = true;
        report('blocked', 'reel-scroll');
        toast('Un reel a la vez');
      }
      return;
    }
    // Inicio agotado: sin scroll no hay scroll infinito pidiendo más publicaciones.
    if (route === 'home' && limitReached && config.feedLimit > 0) {
      if (e.cancelable) e.preventDefault();
    }
  }

  function toast(text) {
    var root = document.documentElement;
    if (!root) return;
    var el = document.getElementById('sl-toast');
    if (!el) {
      el = document.createElement('div');
      el.id = 'sl-toast';
      el.setAttribute('role', 'status');
      el.setAttribute('aria-live', 'polite');
      root.appendChild(el);
    }
    el.textContent = text;
    el.setAttribute('data-show', '');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.removeAttribute('data-show'); }, 2200);
  }

  // -------------------------------------------------------------- el inicio

  function readSeen() {
    var t = today();
    var data = null;
    try { data = JSON.parse(w.localStorage.getItem(SEEN_KEY) || 'null'); } catch (e) { data = null; }
    if (!data || data.day !== t || !Array.isArray(data.keys)) data = { day: t, keys: [] };
    return data;
  }

  function writeSeen(data) {
    try { w.localStorage.setItem(SEEN_KEY, JSON.stringify(data)); } catch (e) { /* sin almacenamiento */ }
  }

  function postKey(art) {
    var links = art.querySelectorAll('a[href*="/p/"], a[href*="/reel/"]');
    for (var i = 0; i < links.length; i++) {
      var m = /\/(?:p|reel)\/([^/?#]+)/.exec(links[i].getAttribute('href') || '');
      if (m) return m[1];
    }
    return null;
  }

  function hasShortText(art, list) {
    var els = art.querySelectorAll('span, a, h2, h3, h4');
    for (var i = 0; i < els.length; i++) {
      var t = els[i].textContent;
      if (!t || t.length > 80) continue;
      var n = normalize(t);
      if (n.length <= 40 && list.indexOf(n) >= 0) return true;
    }
    return false;
  }

  // El marcador de fin («Ya viste todo»): todo lo que viene después es sugerido.
  function endMarker() {
    if (markerCache && markerCache.isConnected) return markerCache;
    markerCache = null;
    var scope = document.querySelector('main') || document.body;
    if (!scope) return null;
    var showText = w.NodeFilter ? w.NodeFilter.SHOW_TEXT : 4;
    var walker = document.createTreeWalker(scope, showText);
    var n;
    while ((n = walker.nextNode())) {
      var v = n.nodeValue;
      if (!v || v.length > 80) continue;
      if (END_MARKERS.indexOf(normalize(v)) >= 0) {
        markerCache = n;
        return n;
      }
    }
    return null;
  }

  function isAfter(node, marker) {
    // 4 = DOCUMENT_POSITION_FOLLOWING; si el artículo contiene al marcador no cuenta.
    return !!(marker.compareDocumentPosition(node) & 4) && !node.contains(marker);
  }

  function updateEndcard(show) {
    var el = document.getElementById('sl-endcard');
    if (!show) {
      if (el && el.parentNode) el.parentNode.removeChild(el);
      return;
    }
    if (!el) {
      el = document.createElement('div');
      el.id = 'sl-endcard';
      el.setAttribute('role', 'status');
      var p = document.createElement('p');
      var a = document.createElement('a');
      a.href = INBOX;
      a.textContent = 'Ir a mensajes →';
      el.appendChild(p);
      el.appendChild(a);
      document.documentElement.appendChild(el);
    }
    var texto = 'Viste tus ' + config.feedLimit + ' publicaciones de hoy. El inicio terminó.';
    if (el.firstChild.textContent !== texto) el.firstChild.textContent = texto;
  }

  function scheduleScan(delay) {
    if (scanTimer !== null) return;
    scanTimer = setTimeout(function () {
      scanTimer = null;
      scan();
    }, delay === undefined ? 250 : delay);
  }

  function scan() {
    var root = document.documentElement;
    if (!root) return;
    ensureStyle();
    applyFlags();

    var arts = document.querySelectorAll('article');
    if (route !== 'home') {
      // Fuera del inicio no se oculta ningún artículo (un post suelto también es un <article>).
      for (var j = 0; j < arts.length; j++) setAttr(arts[j], 'data-sl-hidden', false);
      updateEndcard(false);
      return;
    }

    var marker = config.hideSuggested ? endMarker() : null;
    var limit = config.feedLimit > 0 ? config.feedLimit : 0;
    var seen = limit ? readSeen() : null;
    var dirty = false;

    for (var i = 0; i < arts.length; i++) {
      var art = arts[i];
      var reason = null;
      if (config.hideAds && hasShortText(art, AD_TEXTS)) {
        reason = 'ad';
      } else if (config.hideSuggested && (hasShortText(art, SUGGESTED_TEXTS) || (marker && isAfter(art, marker)))) {
        reason = 'suggested';
      } else if (config.hideFeedReels && art.querySelector('a[href*="/reel/"]')) {
        reason = 'reel';
      } else if (limit) {
        var key = postKey(art);
        if (key && seen.keys.indexOf(key) < 0) {
          if (!limitReached && seen.keys.length < limit) {
            seen.keys.push(key);
            dirty = true;
          } else {
            reason = 'limit';
            limitReached = true;
          }
        }
      }
      // Se quita si ya no aplica: el inicio recicla nodos.
      setAttr(art, 'data-sl-hidden', reason !== null, reason || '');
    }

    if (dirty) writeSeen(seen);
    updateEndcard(limit > 0 && limitReached);
  }

  // ------------------------------------------------------------ estilo y flags

  function ensureStyle() {
    if (document.getElementById('sl-style')) return;
    var s = document.createElement('style');
    s.id = 'sl-style';
    s.textContent = CSS;
    (document.head || document.documentElement).appendChild(s);
  }

  // Atributos data-* en <html> y no clases: React puede reescribir className.
  function applyFlags() {
    var h = document.documentElement;
    setAttr(h, 'data-sl-block-reels', !!config.blockReels);
    setAttr(h, 'data-sl-block-explore', !!config.blockExplore);
    setAttr(h, 'data-sl-gray', !!config.grayscale);
  }

  // ------------------------------------------------------------------ arranque

  function boot() {
    if (booted) return;
    if (!document.documentElement) {
      document.addEventListener('DOMContentLoaded', boot, { once: true });
      return;
    }
    booted = true;
    applyFlags();
    ensureStyle();
    patchHistory();
    w.addEventListener('popstate', check);
    // El sondeo es imprescindible en la extensión: el content script vive en un mundo
    // aislado y no ve el parche de history que hace la página.
    setInterval(check, 400);
    ['touchmove', 'wheel', 'keydown'].forEach(function (t) {
      w.addEventListener(t, onGesture, { capture: true, passive: false });
    });
    new MutationObserver(function () { scheduleScan(250); })
      .observe(document.documentElement, { childList: true, subtree: true });
    check();
    scan();
  }

  function start(cfg, hk) {
    if (hk) hooks = hk;
    if (started) {
      update(cfg || {});
      return;
    }
    started = true;
    config = assign(assign({}, DEFAULTS), cfg || {});
    boot();
  }

  function update(partial) {
    var prevLimit = config.feedLimit;
    assign(config, partial || {});
    if (config.feedLimit !== prevLimit) limitReached = false;
    if (!booted) return;
    applyFlags();
    lastPath = null;
    check();
    scheduleScan(0);
  }

  w.SocialLiteFilter = { start: start, update: update, version: VERSION };

  if (w.__SOCIALLITE_CONFIG__) start(w.__SOCIALLITE_CONFIG__);
})();
"""#
}
