// Pruebas de extension/habits.js: lógica pura (presupuesto, día, racha) y overlays.
import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { JSDOM } from 'jsdom';

const require = createRequire(import.meta.url);
const H = require('../extension/habits.js');
const ventanas = [];
after(() => { for (const w of ventanas) w.close(); });

const HOY = '2026-10-09';
const MANANA = '2026-10-10';

test('anti-trampa: bajar el límite aplica de inmediato', () => {
  const h = H.requestBudget({ dailyBudgetMinutes: 15 }, 10, HOY);
  assert.equal(h.dailyBudgetMinutes, 10);
  assert.equal(h.pendingBudgetMinutes, null);
});

test('anti-trampa: igualarlo aplica de inmediato y descarta lo pendiente', () => {
  let h = H.requestBudget({ dailyBudgetMinutes: 15 }, 30, HOY);
  h = H.requestBudget(h, 15, HOY);
  assert.equal(h.dailyBudgetMinutes, 15);
  assert.equal(h.pendingBudgetMinutes, null);
});

test('anti-trampa: subirlo queda pendiente hasta mañana', () => {
  const h = H.requestBudget({ dailyBudgetMinutes: 15 }, 30, HOY);
  assert.equal(h.dailyBudgetMinutes, 15);
  assert.equal(h.pendingBudgetMinutes, 30);
  assert.equal(h.pendingBudgetDay, HOY);
  assert.equal(H.requestedBudget(h), 30);
});

test('anti-trampa: pasar a «sin límite» también queda pendiente', () => {
  const h = H.requestBudget({ dailyBudgetMinutes: 15 }, 0, HOY);
  assert.equal(h.dailyBudgetMinutes, 15);
  assert.equal(h.pendingBudgetMinutes, 0);
});

test('anti-trampa: pedir un valor menor descarta lo pendiente', () => {
  let h = H.requestBudget({ dailyBudgetMinutes: 15 }, 60, HOY);
  h = H.requestBudget(h, 10, HOY);
  assert.equal(h.dailyBudgetMinutes, 10);
  assert.equal(h.pendingBudgetMinutes, null);
  assert.equal(h.pendingBudgetDay, null);
});

test('anti-trampa: desde «sin límite», poner un límite es más estricto y aplica ya', () => {
  const h = H.requestBudget({ dailyBudgetMinutes: 0 }, 20, HOY);
  assert.equal(h.dailyBudgetMinutes, 20);
});

test('lo pendiente no se aplica el mismo día, sí al siguiente', () => {
  const h = H.requestBudget({ dailyBudgetMinutes: 15 }, 30, HOY);
  assert.equal(H.applyPending(h, HOY).dailyBudgetMinutes, 15);
  const m = H.applyPending(h, MANANA);
  assert.equal(m.dailyBudgetMinutes, 30);
  assert.equal(m.pendingBudgetMinutes, null);
  // Si el reloj se atrasa, tampoco se aplica antes de tiempo.
  assert.equal(H.applyPending(h, '2026-10-08').dailyBudgetMinutes, 15);
});

test('el presupuesto se ajusta a 0–120 en pasos de 5', () => {
  assert.deepEqual([7, 200, -5, 'abc', 12.6, 3].map(H.clampBudget), [5, 120, 0, 0, 15, 5]);
});

test('reinicio diario de las estadísticas', () => {
  const ayer = { day: '2026-10-08', dmSeconds: 300, feedSeconds: 900, blocksToday: 4 };
  assert.deepEqual(H.rollDay(ayer, HOY), { day: HOY, dmSeconds: 0, feedSeconds: 0, blocksToday: 0 });
  const hoy = { day: HOY, dmSeconds: 10, feedSeconds: 20, blocksToday: 1 };
  assert.deepEqual(H.rollDay(hoy, HOY), hoy);
  assert.deepEqual(H.rollDay(undefined, HOY), H.freshStats(HOY));
});

test('cada ruta suma a su cubo: mensajes gratis, el resto gasta', () => {
  let s = H.freshStats(HOY);
  for (const r of ['direct', 'shared', 'auth']) s = H.addTime(s, r, 10);
  for (const r of ['home', 'explore', 'reel', 'other']) s = H.addTime(s, r, 5);
  assert.equal(s.dmSeconds, 30);
  assert.equal(s.feedSeconds, 20);
});

test('bloqueo y minutos restantes', () => {
  assert.equal(H.isLocked({ dailyBudgetMinutes: 15 }, 899), false);
  assert.equal(H.isLocked({ dailyBudgetMinutes: 15 }, 900), true);
  assert.equal(H.isLocked({ dailyBudgetMinutes: 0 }, 1e9), false, '0 = sin límite');
  assert.equal(H.minutesLeft({ dailyBudgetMinutes: 15 }, 61), 14);
  assert.equal(H.minutesLeft({ dailyBudgetMinutes: 15 }, 2000), 0);
  assert.equal(H.minutesLeft({ dailyBudgetMinutes: 0 }, 5), null);
});

test('racha fuera de mensajes: empieza, sigue, y se corta al volver a mensajes o al dejar de contar', () => {
  let r = H.updateStreak(null, 'home', true, 1000);
  assert.equal(r, 1000);
  r = H.updateStreak(r, 'other', true, 61000);
  assert.equal(r, 1000, 'sigue el mismo tramo');
  assert.equal(H.streakSeconds(r, 61000), 60);
  assert.equal(H.updateStreak(r, 'direct', true, 62000), null, 'mensajes la corta');
  assert.equal(H.updateStreak(r, 'home', false, 62000), null, 'pestaña oculta la corta');
  assert.equal(H.streakSeconds(null, 99), 0);
});

test('cuándo aparece el aviso de pausa', () => {
  const base = { nudgeMinutes: 5, locked: false, intentOpen: false, streakStart: 0, snoozedUntil: null, now: 300000 };
  assert.equal(H.shouldNudge(base), true);
  assert.equal(H.shouldNudge({ ...base, now: 299000 }), false, 'aún no llega a 5 min');
  assert.equal(H.shouldNudge({ ...base, nudgeMinutes: 0 }), false, '0 = nunca');
  assert.equal(H.shouldNudge({ ...base, locked: true }), false);
  assert.equal(H.shouldNudge({ ...base, intentOpen: true }), false);
  assert.equal(H.shouldNudge({ ...base, snoozedUntil: 400000 }), false, 'pospuesto');
  assert.equal(H.shouldNudge({ ...base, snoozedUntil: 300000 }), true, 'el pospuesto ya venció');
});

test('«¿A qué vienes?» solo tras más de 5 min sin visitar', () => {
  const ahora = 10_000_000;
  assert.equal(H.shouldAskIntent(true, null, ahora), true);
  assert.equal(H.shouldAskIntent(true, ahora - 5 * 60 * 1000, ahora), false);
  assert.equal(H.shouldAskIntent(true, ahora - 5 * 60 * 1000 - 1, ahora), true);
  assert.equal(H.shouldAskIntent(false, null, ahora), false);
});

function documento() {
  const dom = new JSDOM('<!doctype html><html><head></head><body></body></html>', { url: 'https://www.instagram.com/' });
  ventanas.push(dom.window);
  return dom.window.document;
}

test('overlay «¿A qué vienes?»: bloqueado, solo queda hablar con amigos', () => {
  const doc = documento();
  const elegidos = [];
  const o = H.showIntent(doc, { locked: true, minutesLeft: 0, onChoose: (p) => elegidos.push(p) });
  const [b1, b2, b3] = o.buttons;
  assert.deepEqual([b1.textContent, b2.textContent, b3.textContent], ['Hablar con amigos', 'Buscar a alguien', 'Ver el inicio']);
  assert.deepEqual([b1.disabled, b2.disabled, b3.disabled], [false, true, true]);
  assert.match(doc.querySelector('#sl-intent p').textContent, /Se acabó tu tiempo/);
  assert.equal(doc.activeElement, b1, 'el foco queda en el botón principal (teclado)');
  b1.click();
  assert.deepEqual(elegidos, ['/direct/inbox/']);
  assert.equal(doc.getElementById('sl-intent'), null);
});

test('overlay «¿A qué vienes?»: con tiempo, muestra los minutos y deja elegir', () => {
  const doc = documento();
  const elegidos = [];
  const o = H.showIntent(doc, { locked: false, minutesLeft: 12, onChoose: (p) => elegidos.push(p) });
  assert.match(doc.querySelector('#sl-intent p').textContent, /Te quedan 12 min/);
  o.buttons[1].click();
  assert.deepEqual(elegidos, ['/explore/']);
});

test('aviso de pausa: «Seguir» queda deshabilitado 5 s con cuenta regresiva', () => {
  const doc = documento();
  let pospuesto = 0;
  const n = H.showNudge(doc, { streakMinutes: 5, snoozeMinutes: 5, onInbox() {}, onSnooze() { pospuesto++; } });
  assert.equal(doc.querySelector('#sl-nudge h2').textContent, 'Llevas 5 min fuera de mensajes');
  assert.equal(n.snoozeButton.disabled, true);
  assert.equal(n.snoozeButton.textContent, 'Seguir 5 min más (5)');
  n.snoozeButton.click();
  assert.equal(pospuesto, 0, 'no se puede posponer antes de tiempo');
  for (let i = 0; i < 4; i++) n.tick();
  assert.equal(n.snoozeButton.textContent, 'Seguir 5 min más (1)');
  n.tick();
  assert.equal(n.snoozeButton.disabled, false);
  assert.equal(n.snoozeButton.textContent, 'Seguir 5 min más');
  n.snoozeButton.click();
  assert.equal(pospuesto, 1);
  assert.equal(doc.getElementById('sl-nudge'), null);
});
