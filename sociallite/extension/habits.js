/*
 * SocialLite — hábitos de la extensión: presupuesto diario, aviso de pausa y
 * «¿A qué vienes?».
 *
 * La lógica es pura (sin almacenamiento ni temporizadores propios) para poder probarla
 * en Node; los dos overlays reciben el `document` donde dibujarse. Mismas reglas que la
 * app de iPhone, incluida la anti-trampa del presupuesto.
 */
(function (root) {
  'use strict';

  var FREE_ROUTES = ['direct', 'shared', 'auth'];
  var INTENT_GAP_MS = 5 * 60 * 1000;
  var INBOX = '/direct/inbox/';

  // Lo que va al filtro (shared/filter.js), sin lockToDMs: ese lo decide el presupuesto.
  var DEFAULT_CONFIG = {
    blockReels: true,
    hideFeedReels: true,
    blockExplore: true,
    hideAds: true,
    hideSuggested: true,
    grayscale: true,
    feedLimit: 20,
    dmOnlyMode: false
  };

  var DEFAULT_HABITS = {
    askIntent: true,
    nudgeMinutes: 5,
    dailyBudgetMinutes: 15,
    pendingBudgetMinutes: null,
    pendingBudgetDay: null
  };

  function assign(target) {
    for (var i = 1; i < arguments.length; i++) {
      var src = arguments[i];
      if (!src) continue;
      for (var k in src) {
        if (Object.prototype.hasOwnProperty.call(src, k)) target[k] = src[k];
      }
    }
    return target;
  }

  function pad(n) { return n < 10 ? '0' + n : String(n); }

  /** Fecha local «YYYY-MM-DD». */
  function dayKey(date) {
    var d = date || new Date();
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
  }

  function withDefaults(habits) { return assign({}, DEFAULT_HABITS, habits); }
  function configWithDefaults(config) { return assign({}, DEFAULT_CONFIG, config); }

  // ------------------------------------------------------------ presupuesto

  /** 0–120, de 5 en 5. 0 = sin límite. */
  function clampBudget(minutes) {
    var m = Math.round((Number(minutes) || 0) / 5) * 5;
    return Math.max(0, Math.min(120, m));
  }

  /** ¿Pasar de `current` a `next` da más tiempo? (0 = sin límite, lo más permisivo). */
  function isMorePermissive(next, current) {
    if (current === 0) return false;
    if (next === 0) return true;
    return next > current;
  }

  /**
   * Regla anti-trampa: bajar (o igualar) el límite aplica de inmediato y descarta lo
   * pendiente; subirlo o pasar a «sin límite» queda pendiente hasta mañana.
   */
  function requestBudget(habits, minutes, today) {
    var h = withDefaults(habits);
    var m = clampBudget(minutes);
    if (isMorePermissive(m, h.dailyBudgetMinutes)) {
      h.pendingBudgetMinutes = m;
      h.pendingBudgetDay = today;
    } else {
      h.dailyBudgetMinutes = m;
      h.pendingBudgetMinutes = null;
      h.pendingBudgetDay = null;
    }
    return h;
  }

  /** Aplica lo pendiente si ya es otro día (posterior al del pedido). */
  function applyPending(habits, today) {
    var h = withDefaults(habits);
    if (h.pendingBudgetMinutes === null || h.pendingBudgetMinutes === undefined || !h.pendingBudgetDay) return h;
    if (today > h.pendingBudgetDay) {
      h.dailyBudgetMinutes = h.pendingBudgetMinutes;
      h.pendingBudgetMinutes = null;
      h.pendingBudgetDay = null;
    }
    return h;
  }

  /** Lo que se pediría con el control: lo pendiente si hay, si no lo vigente. */
  function requestedBudget(habits) {
    var h = withDefaults(habits);
    return h.pendingBudgetMinutes !== null && h.pendingBudgetMinutes !== undefined ? h.pendingBudgetMinutes : h.dailyBudgetMinutes;
  }

  function isLocked(habits, feedSeconds) {
    var b = withDefaults(habits).dailyBudgetMinutes;
    return b > 0 && feedSeconds >= b * 60;
  }

  /** Minutos que quedan fuera de mensajes, o null si no hay límite. */
  function minutesLeft(habits, feedSeconds) {
    var b = withDefaults(habits).dailyBudgetMinutes;
    if (b <= 0) return null;
    return Math.max(0, Math.ceil((b * 60 - feedSeconds) / 60));
  }

  function budgetLabel(minutes) { return minutes === 0 ? 'Sin límite' : minutes + ' min'; }

  // ----------------------------------------------------------- estadísticas

  function freshStats(today) {
    return { day: today, dmSeconds: 0, feedSeconds: 0, blocksToday: 0 };
  }

  /** Reinicio diario: si el día guardado no es hoy, se empieza de cero. */
  function rollDay(stats, today) {
    if (!stats || stats.day !== today) return freshStats(today);
    return assign(freshStats(today), stats);
  }

  function isFreeRoute(route) { return FREE_ROUTES.indexOf(route) >= 0; }

  /** Suma segundos al cubo de la ruta: mensajes (gratis) o todo lo demás. */
  function addTime(stats, route, seconds) {
    var s = assign({}, stats);
    if (isFreeRoute(route)) s.dmSeconds += seconds;
    else s.feedSeconds += seconds;
    return s;
  }

  // ------------------------------------------------------------------ racha

  /**
   * Inicio del tramo continuo fuera de mensajes. Se corta al entrar a una ruta libre o
   * cuando la pestaña deja de contar (oculta o sin foco).
   */
  function updateStreak(streakStart, route, counting, now) {
    if (!counting || !route || isFreeRoute(route)) return null;
    return streakStart === null || streakStart === undefined ? now : streakStart;
  }

  function streakSeconds(streakStart, now) {
    if (streakStart === null || streakStart === undefined) return 0;
    return Math.max(0, (now - streakStart) / 1000);
  }

  function shouldNudge(o) {
    return o.nudgeMinutes > 0 && !o.locked && !o.intentOpen &&
      streakSeconds(o.streakStart, o.now) >= o.nudgeMinutes * 60 &&
      (o.snoozedUntil === null || o.snoozedUntil === undefined || o.now >= o.snoozedUntil);
  }

  /** «¿A qué vienes?» al abrir instagram.com tras más de 5 min sin visitarlo. */
  function shouldAskIntent(askIntent, lastVisit, now) {
    return !!askIntent && (lastVisit === null || lastVisit === undefined || now - lastVisit > INTENT_GAP_MS);
  }

  // --------------------------------------------------------------- overlays

  var STYLE = [
    '.sl-ov{position:fixed;inset:0;z-index:2147483647;display:flex;align-items:center;justify-content:center;',
    'padding:20px;background:rgba(0,0,0,.55);font:16px/1.4 -apple-system,system-ui,"Segoe UI",sans-serif}',
    '.sl-card{width:100%;max-width:380px;padding:22px;border-radius:18px;background:#fff;color:#111;',
    'box-shadow:0 12px 40px rgba(0,0,0,.35);text-align:center}',
    '.sl-card h2{margin:0 0 6px;font-size:21px}',
    '.sl-card p{margin:0 0 16px;color:#555}',
    '.sl-card button{display:block;width:100%;margin:8px 0 0;padding:12px;border:0;border-radius:12px;',
    'font:600 16px/1.2 inherit;cursor:pointer;background:#eee;color:#111}',
    '.sl-card button.sl-main{background:#0a66ff;color:#fff}',
    '.sl-card button:disabled{opacity:.45;cursor:not-allowed}',
    '.sl-card button:focus-visible{outline:3px solid #7aa7ff;outline-offset:2px}',
    '@media (prefers-color-scheme: dark){.sl-card{background:#1c1c1e;color:#f2f2f2}',
    '.sl-card p{color:#aaa}.sl-card button{background:#2c2c2e;color:#f2f2f2}}'
  ].join('');

  function ensureStyle(doc) {
    if (doc.getElementById('sl-habits-style')) return;
    var s = doc.createElement('style');
    s.id = 'sl-habits-style';
    s.textContent = STYLE;
    (doc.head || doc.documentElement).appendChild(s);
  }

  function overlay(doc, id, title, subtitle) {
    var prev = doc.getElementById(id);
    if (prev) prev.remove();
    ensureStyle(doc);
    var ov = doc.createElement('div');
    ov.id = id;
    ov.className = 'sl-ov';
    ov.setAttribute('role', 'dialog');
    ov.setAttribute('aria-modal', 'true');
    ov.setAttribute('aria-labelledby', id + '-t');
    var card = doc.createElement('div');
    card.className = 'sl-card';
    var h = doc.createElement('h2');
    h.id = id + '-t';
    h.textContent = title;
    var p = doc.createElement('p');
    p.textContent = subtitle;
    card.appendChild(h);
    card.appendChild(p);
    ov.appendChild(card);
    doc.documentElement.appendChild(ov);
    return { ov: ov, card: card, sub: p };
  }

  function button(doc, card, text, main, onClick) {
    var b = doc.createElement('button');
    b.type = 'button';
    b.textContent = text;
    if (main) b.className = 'sl-main';
    b.addEventListener('click', onClick);
    card.appendChild(b);
    return b;
  }

  /**
   * «¿A qué vienes?». opts: { locked, minutesLeft (null = sin límite), onChoose(path) }.
   * Si está bloqueado solo queda «Hablar con amigos».
   */
  function showIntent(doc, opts) {
    var sub;
    if (opts.locked) sub = 'Se acabó tu tiempo de hoy fuera de mensajes. Los mensajes siguen libres.';
    else if (opts.minutesLeft === null || opts.minutesLeft === undefined) sub = 'Sin límite diario fuera de mensajes.';
    else sub = 'Te quedan ' + opts.minutesLeft + ' min fuera de mensajes hoy.';
    var o = overlay(doc, 'sl-intent', '¿A qué vienes?', sub);
    function choose(path) {
      close();
      opts.onChoose(path);
    }
    var b1 = button(doc, o.card, 'Hablar con amigos', true, function () { choose(INBOX); });
    var b2 = button(doc, o.card, 'Buscar a alguien', false, function () { choose('/explore/'); });
    var b3 = button(doc, o.card, 'Ver el inicio', false, function () { choose('/'); });
    b2.disabled = !!opts.locked;
    b3.disabled = !!opts.locked;
    function close() { if (o.ov.parentNode) o.ov.remove(); }
    try { b1.focus(); } catch (e) { /* sin foco disponible */ }
    return { el: o.ov, close: close, buttons: [b1, b2, b3] };
  }

  /**
   * Aviso de pausa. opts: { streakMinutes, snoozeMinutes, seconds (5), onInbox(), onSnooze() }.
   * «Seguir X min más» queda deshabilitado durante la cuenta regresiva.
   */
  function showNudge(doc, opts) {
    var o = overlay(doc, 'sl-nudge', 'Llevas ' + opts.streakMinutes + ' min fuera de mensajes',
      '¿Estás buscando algo concreto o es scroll?');
    var remaining = opts.seconds === undefined ? 5 : opts.seconds;
    var label = 'Seguir ' + opts.snoozeMinutes + ' min más';
    var timer = null;
    var inbox = button(doc, o.card, 'Ir a mensajes', true, function () { close(); opts.onInbox(); });
    var snooze = button(doc, o.card, label, false, function () {
      if (remaining > 0) return;
      close();
      opts.onSnooze();
    });
    function paint() {
      snooze.disabled = remaining > 0;
      snooze.textContent = remaining > 0 ? label + ' (' + remaining + ')' : label;
    }
    function tick() {
      if (remaining > 0) remaining -= 1;
      paint();
      if (remaining <= 0 && timer !== null) {
        doc.defaultView.clearInterval(timer);
        timer = null;
      }
    }
    function close() {
      if (timer !== null) {
        doc.defaultView.clearInterval(timer);
        timer = null;
      }
      if (o.ov.parentNode) o.ov.remove();
    }
    paint();
    if (remaining > 0 && doc.defaultView) timer = doc.defaultView.setInterval(tick, 1000);
    try { inbox.focus(); } catch (e) { /* sin foco disponible */ }
    return { el: o.ov, tick: tick, close: close, snoozeButton: snooze };
  }

  var api = {
    INBOX: INBOX,
    INTENT_GAP_MS: INTENT_GAP_MS,
    DEFAULT_CONFIG: DEFAULT_CONFIG,
    DEFAULT_HABITS: DEFAULT_HABITS,
    dayKey: dayKey,
    withDefaults: withDefaults,
    configWithDefaults: configWithDefaults,
    clampBudget: clampBudget,
    isMorePermissive: isMorePermissive,
    requestBudget: requestBudget,
    applyPending: applyPending,
    requestedBudget: requestedBudget,
    isLocked: isLocked,
    minutesLeft: minutesLeft,
    budgetLabel: budgetLabel,
    freshStats: freshStats,
    rollDay: rollDay,
    isFreeRoute: isFreeRoute,
    addTime: addTime,
    updateStreak: updateStreak,
    streakSeconds: streakSeconds,
    shouldNudge: shouldNudge,
    shouldAskIntent: shouldAskIntent,
    showIntent: showIntent,
    showNudge: showNudge
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.SocialLiteHabits = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
