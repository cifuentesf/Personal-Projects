/*
 * SocialLite — popup de la extensión: ajustes y estadísticas del día.
 * Lee y escribe solo api.storage.local; no carga nada remoto.
 */
(function () {
  'use strict';

  const api = globalThis.browser ?? globalThis.chrome;
  const H = globalThis.SocialLiteHabits;
  const $ = (id) => document.getElementById(id);

  let config = H.configWithDefaults({});
  let habits = H.withDefaults({});
  let stats = H.freshStats(H.dayKey());

  function minutos(seg) { return Math.floor((seg || 0) / 60) + ' min'; }

  function pintar() {
    const hoy = H.dayKey();
    const s = H.rollDay(stats, hoy);
    $('s-dm').textContent = minutos(s.dmSeconds);
    $('s-feed').textContent = minutos(s.feedSeconds);
    $('s-blocks').textContent = String(s.blocksToday);

    const bloqueado = H.isLocked(habits, s.feedSeconds);
    const quedan = H.minutesLeft(habits, s.feedSeconds);
    const estado = $('estado');
    estado.classList.toggle('bloqueado', bloqueado);
    estado.textContent = bloqueado
      ? '🔒 Solo mensajes hasta mañana'
      : quedan === null ? 'Sin límite fuera de mensajes' : `Te quedan ${quedan} min fuera de mensajes`;

    $('budget').value = String(H.requestedBudget(habits));
    const nota = $('budget-nota');
    const pendiente = habits.pendingBudgetMinutes !== null && habits.pendingBudgetMinutes !== undefined;
    nota.classList.toggle('pendiente', pendiente);
    nota.textContent = `Vigente hoy: ${H.budgetLabel(habits.dailyBudgetMinutes)}` +
      (pendiente ? ` · Desde mañana: ${H.budgetLabel(habits.pendingBudgetMinutes)}` : '');

    $('nudgeMinutes').value = String(habits.nudgeMinutes);
    $('askIntent').checked = !!habits.askIntent;

    for (const el of document.querySelectorAll('[data-config]')) {
      const k = el.dataset.config;
      if (el.type === 'checkbox') el.checked = !!config[k];
      else el.value = String(config[k]);
    }
  }

  function entero(el, min, max) {
    const n = Math.round(Number(el.value));
    return Number.isFinite(n) ? Math.max(min, Math.min(max, n)) : min;
  }

  async function guardar(cambios) {
    await api.storage.local.set(cambios);
  }

  $('budget').addEventListener('change', async (e) => {
    habits = H.requestBudget(habits, e.target.value, H.dayKey());
    await guardar({ habits });
    pintar();
  });

  $('nudgeMinutes').addEventListener('change', async (e) => {
    habits = Object.assign({}, habits, { nudgeMinutes: entero(e.target, 0, 30) });
    await guardar({ habits });
    pintar();
  });

  $('askIntent').addEventListener('change', async (e) => {
    habits = Object.assign({}, habits, { askIntent: e.target.checked });
    await guardar({ habits });
  });

  for (const el of document.querySelectorAll('[data-config]')) {
    el.addEventListener('change', async () => {
      const k = el.dataset.config;
      const valor = el.type === 'checkbox' ? el.checked : Math.round(entero(el, 0, 60) / 5) * 5;
      config = Object.assign({}, config, { [k]: valor });
      await guardar({ config });
      pintar();
    });
  }

  async function cargar() {
    const got = await api.storage.local.get(['config', 'habits', 'stats']);
    config = H.configWithDefaults(got.config);
    habits = H.applyPending(got.habits, H.dayKey());
    stats = H.rollDay(got.stats, H.dayKey());
    pintar();
  }

  api.storage.onChanged.addListener((changes, area) => {
    if (area !== 'local') return;
    if (changes.stats && changes.stats.newValue) stats = changes.stats.newValue;
    if (changes.habits && changes.habits.newValue) habits = H.withDefaults(changes.habits.newValue);
    if (changes.config && changes.config.newValue) config = H.configWithDefaults(changes.config.newValue);
    pintar();
  });

  cargar();
})();
