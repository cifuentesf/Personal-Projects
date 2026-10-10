/*
 * SocialLite — content script de la extensión.
 *
 * Une el filtro (shared/filter.js) con los hábitos (habits.js) y api.storage.local.
 * Solo usa almacenamiento local del navegador: ninguna petición de red, ninguna
 * analítica. Guarda solo números y fechas (nunca contenido, nombres ni cookies).
 */
(function () {
  'use strict';

  const api = globalThis.browser ?? globalThis.chrome;
  const F = globalThis.SocialLiteFilter;
  const H = globalThis.SocialLiteHabits;
  if (!api || !api.storage || !F || !H) return;

  const TICK_MS = 1000;
  const FLUSH_MS = 15000;
  const HEARTBEAT_EVERY_MS = 3000;
  const HEARTBEAT_STALE_MS = 7000;
  const ME = Math.random().toString(36).slice(2) + Date.now().toString(36);

  let config = H.configWithDefaults({});
  let habits = H.withDefaults({});
  let stats = H.freshStats(H.dayKey());
  let heartbeat = null;
  let loaded = false;
  let route = null;
  let locked = false;
  let pending = { dm: 0, feed: 0, blocks: 0 };
  let lastTick = Date.now();
  let lastFlush = Date.now();
  let lastBeat = 0;
  let streakStart = null;
  let snoozedUntil = null;
  let intent = null;
  let nudge = null;

  // Arranca de inmediato con los valores por omisión (los más estrictos) para no dejar
  // ver nada antes de leer el almacenamiento; luego se ajusta con update().
  F.start(filterConfig(), { report });

  function filterConfig() {
    return Object.assign({}, config, { lockToDMs: locked });
  }

  function report(p) {
    if (p.type === 'route') {
      tick();  // el tiempo hasta ahora se cobra a la ruta anterior
      route = p.reason;
      if (H.isFreeRoute(route)) {
        snoozedUntil = null;
        if (nudge) { nudge.close(); nudge = null; }
      }
    } else if (p.type === 'blocked') {
      pending.blocks += 1;
    }
  }

  // ------------------------------------------------------------ contabilidad

  /** Cuenta solo si la pestaña está visible, con foco y es la dueña del latido. */
  function counting(now) {
    if (document.visibilityState !== 'visible' || !document.hasFocus()) return false;
    if (heartbeat && heartbeat.id !== ME && now - heartbeat.ts < HEARTBEAT_STALE_MS) return false;
    return true;
  }

  function beat(now) {
    if (now - lastBeat < HEARTBEAT_EVERY_MS) return;
    lastBeat = now;
    heartbeat = { id: ME, ts: now };
    api.storage.local.set({ heartbeat }).catch(() => {});
  }

  function feedSecondsNow() { return stats.feedSeconds + pending.feed; }

  function tick() {
    const now = Date.now();
    // Tope de 5 s: si el equipo se suspendió, ese hueco no se cobra.
    const dt = Math.min(Math.max(0, (now - lastTick) / 1000), 5);
    lastTick = now;
    if (!loaded) return;
    const cuenta = counting(now);
    if (cuenta) {
      beat(now);
      if (route) {
        if (H.isFreeRoute(route)) pending.dm += dt;
        else pending.feed += dt;
      }
    }
    streakStart = H.updateStreak(streakStart, route, cuenta, now);
    refreshLock();
    maybeNudge(now);
    if (now - lastFlush >= FLUSH_MS) flush();
  }

  async function flush() {
    lastFlush = Date.now();
    if (!pending.dm && !pending.feed && !pending.blocks && !counting(Date.now())) return;
    const p = pending;
    pending = { dm: 0, feed: 0, blocks: 0 };
    try {
      const got = await api.storage.local.get(['stats']);
      let s = H.rollDay(got.stats, H.dayKey());
      s = H.addTime(s, 'direct', p.dm);
      s = H.addTime(s, 'home', p.feed);
      s.blocksToday += p.blocks;
      stats = s;
      const cambios = { stats: s };
      if (counting(Date.now())) cambios.lastVisit = Date.now();
      await api.storage.local.set(cambios);
    } catch (e) {
      // Si falla, se devuelve lo pendiente para el próximo intento.
      pending.dm += p.dm;
      pending.feed += p.feed;
      pending.blocks += p.blocks;
    }
  }

  function refreshLock() {
    const ahora = H.isLocked(habits, feedSecondsNow());
    if (ahora !== locked) {
      locked = ahora;
      F.update({ lockToDMs: locked });
      if (locked && nudge) { nudge.close(); nudge = null; }
    }
  }

  // ------------------------------------------------------------ overlays

  function maybeNudge(now) {
    if (nudge || intent) return;
    const debe = H.shouldNudge({
      nudgeMinutes: habits.nudgeMinutes, locked, intentOpen: !!intent,
      streakStart, snoozedUntil, now,
    });
    if (!debe) return;
    nudge = H.showNudge(document, {
      streakMinutes: Math.floor(H.streakSeconds(streakStart, now) / 60),
      snoozeMinutes: habits.nudgeMinutes,
      onInbox: () => { nudge = null; location.assign(H.INBOX); },
      onSnooze: () => { nudge = null; snoozedUntil = Date.now() + habits.nudgeMinutes * 60 * 1000; },
    });
  }

  function askIntent(lastVisit) {
    if (!H.shouldAskIntent(habits.askIntent, lastVisit, Date.now())) return;
    intent = H.showIntent(document, {
      locked,
      minutesLeft: H.minutesLeft(habits, feedSecondsNow()),
      onChoose: (path) => {
        intent = null;
        api.storage.local.set({ lastVisit: Date.now() }).catch(() => {});
        if (path !== location.pathname) location.assign(path);
      },
    });
  }

  // ------------------------------------------------------------ carga

  async function load() {
    const got = await api.storage.local.get(['config', 'habits', 'stats', 'heartbeat', 'lastVisit']);
    const hoy = H.dayKey();
    config = H.configWithDefaults(got.config);
    habits = H.applyPending(got.habits, hoy);
    if (JSON.stringify(habits) !== JSON.stringify(H.withDefaults(got.habits))) {
      await api.storage.local.set({ habits });
    }
    stats = H.rollDay(got.stats, hoy);
    heartbeat = got.heartbeat || null;
    locked = H.isLocked(habits, stats.feedSeconds);
    loaded = true;
    F.update(filterConfig());
    askIntent(got.lastVisit);
    lastTick = Date.now();
  }

  api.storage.onChanged.addListener((changes, area) => {
    if (area !== 'local') return;
    if (changes.config) {
      config = H.configWithDefaults(changes.config.newValue);
      F.update(filterConfig());
    }
    if (changes.habits) {
      habits = H.withDefaults(changes.habits.newValue);
      refreshLock();
    }
    if (changes.stats && changes.stats.newValue) {
      stats = H.rollDay(changes.stats.newValue, H.dayKey());
      refreshLock();
    }
    if (changes.heartbeat) heartbeat = changes.heartbeat.newValue || null;
  });

  // Cada minuto: cambio de día y presupuesto pendiente que ya corresponde aplicar.
  setInterval(() => {
    const hoy = H.dayKey();
    if (stats.day !== hoy) stats = H.freshStats(hoy);
    const h = H.applyPending(habits, hoy);
    if (h.dailyBudgetMinutes !== habits.dailyBudgetMinutes) {
      habits = h;
      api.storage.local.set({ habits }).catch(() => {});
      refreshLock();
    }
  }, 60000);

  setInterval(tick, TICK_MS);
  document.addEventListener('visibilitychange', tick);
  window.addEventListener('focus', tick);
  window.addEventListener('blur', tick);
  window.addEventListener('pagehide', () => { tick(); flush(); });

  load().catch(() => { loaded = true; });
})();
