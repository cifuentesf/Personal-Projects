// Integración de la extensión: content.js y popup.js con un chrome.storage simulado.
import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { JSDOM, VirtualConsole } from 'jsdom';

const leer = (p) => readFileSync(new URL(p, import.meta.url), 'utf8');
const FILTER = leer('../shared/filter.js');
const HABITS = leer('../extension/habits.js');
const CONTENT = leer('../extension/content.js');
const POPUP_JS = leer('../extension/popup.js');
const POPUP_HTML = leer('../extension/popup.html');
const MANIFEST = JSON.parse(leer('../extension/manifest.json'));

const ventanas = [];
after(() => { for (const w of ventanas) w.close(); });
const espera = (ms) => new Promise((r) => setTimeout(r, ms));

function hoy() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/** chrome.storage.local en memoria, con onChanged como el real. */
function almacen(inicial = {}) {
  const datos = structuredClone(inicial);
  const oyentes = [];
  const local = {
    async get(claves) {
      const out = {};
      for (const k of [].concat(claves)) if (k in datos) out[k] = structuredClone(datos[k]);
      return out;
    },
    async set(obj) {
      const cambios = {};
      for (const [k, v] of Object.entries(obj)) {
        cambios[k] = { oldValue: datos[k], newValue: structuredClone(v) };
        datos[k] = structuredClone(v);
      }
      for (const f of oyentes) f(cambios, 'local');
    },
  };
  return { datos, api: { storage: { local, onChanged: { addListener: (f) => oyentes.push(f) } } } };
}

/** Una pestaña de instagram.com con los tres content scripts del manifest. */
function pestana(ruta, inicial, { foco = true } = {}) {
  const st = almacen(inicial);
  const navegaciones = [];
  const vc = new VirtualConsole();
  vc.on('jsdomError', (e) => { if (/navigation/i.test(e.message)) navegaciones.push(e.message); });
  const dom = new JSDOM('<!doctype html><html><head></head><body></body></html>', {
    url: 'https://www.instagram.com' + ruta, runScripts: 'outside-only', pretendToBeVisual: true, virtualConsole: vc,
  });
  const w = dom.window;
  ventanas.push(w);
  w.document.hasFocus = () => foco;
  w.chrome = st.api;
  w.eval(FILTER);
  w.eval(HABITS);
  w.eval(CONTENT);
  return { w, doc: w.document, html: w.document.documentElement, st, navegaciones };
}

test('el manifest carga los tres scripts en orden, en document_start, solo con «storage»', () => {
  const cs = MANIFEST.content_scripts[0];
  assert.deepEqual(cs.js, ['shared/filter.js', 'extension/habits.js', 'extension/content.js']);
  assert.equal(cs.run_at, 'document_start');
  assert.deepEqual(cs.matches, ['*://www.instagram.com/*']);
  assert.deepEqual(MANIFEST.permissions, ['storage']);
  assert.equal(MANIFEST.host_permissions, undefined);
  assert.equal(MANIFEST.background, undefined);
  assert.equal(MANIFEST.manifest_version, 3);
  assert.ok(MANIFEST.browser_specific_settings.gecko.id);
});

test('ningún archivo de la extensión hace peticiones de red', () => {
  for (const src of [FILTER, HABITS, CONTENT, POPUP_JS, POPUP_HTML]) {
    assert.doesNotMatch(src, /\bfetch\s*\(|XMLHttpRequest|WebSocket|sendBeacon|EventSource|importScripts/);
    assert.doesNotMatch(src, /https?:\/\/(?!www\.instagram\.com)/, 'sin URLs a otros dominios');
  }
});

test('con el presupuesto agotado, al cargar se bloquea en vivo y redirige', async () => {
  const t = pestana('/alguien/', {
    habits: { dailyBudgetMinutes: 15 },
    stats: { day: hoy(), dmSeconds: 0, feedSeconds: 900, blocksToday: 0 },
    lastVisit: Date.now(),
  });
  await espera(50);
  assert.equal(t.html.getAttribute('data-sl-leaving'), '', 'intenta salir del perfil');
  assert.ok(t.navegaciones.length >= 1, 'pidió navegar (jsdom no navega)');
});

test('con presupuesto disponible, un perfil se ve normal', async () => {
  const t = pestana('/alguien/', {
    habits: { dailyBudgetMinutes: 15 },
    stats: { day: hoy(), dmSeconds: 0, feedSeconds: 100, blocksToday: 0 },
    lastVisit: Date.now(),
  });
  await espera(50);
  assert.equal(t.html.hasAttribute('data-sl-leaving'), false);
  assert.equal(t.doc.getElementById('sl-intent'), null, 'visitó hace poco: no pregunta');
});

test('las estadísticas de ayer no bloquean hoy', async () => {
  const t = pestana('/alguien/', {
    habits: { dailyBudgetMinutes: 15 },
    stats: { day: '2000-01-01', dmSeconds: 0, feedSeconds: 99999, blocksToday: 0 },
    lastVisit: Date.now(),
  });
  await espera(50);
  assert.equal(t.html.hasAttribute('data-sl-leaving'), false);
});

test('«¿A qué vienes?» aparece tras más de 5 min sin visitar; bloqueado, deja solo los mensajes', async () => {
  const t = pestana('/', {
    habits: { dailyBudgetMinutes: 15 },
    stats: { day: hoy(), dmSeconds: 0, feedSeconds: 900, blocksToday: 0 },
  });
  await espera(50);
  const ov = t.doc.getElementById('sl-intent');
  assert.ok(ov);
  const botones = [...ov.querySelectorAll('button')];
  assert.deepEqual(botones.map((b) => b.disabled), [false, true, true]);
});

test('cambiar la config en el popup se aplica en vivo (storage.onChanged)', async () => {
  const t = pestana('/', { lastVisit: Date.now() });
  await espera(50);
  assert.equal(t.html.hasAttribute('data-sl-gray'), true);
  await t.st.api.storage.local.set({ config: { grayscale: false } });
  assert.equal(t.html.hasAttribute('data-sl-gray'), false);
});

test('cuenta el tiempo de la pestaña visible y con foco, y lo guarda al salir', async () => {
  const t = pestana('/', { lastVisit: Date.now() });
  await espera(1300);
  t.w.dispatchEvent(new t.w.Event('pagehide'));
  await espera(50);
  const s = t.st.datos.stats;
  assert.equal(s.day, hoy());
  assert.ok(s.feedSeconds >= 0.8 && s.feedSeconds <= 3, `feedSeconds = ${s.feedSeconds}`);
  assert.equal(s.dmSeconds, 0);
  assert.ok(t.st.datos.lastVisit > Date.now() - 5000);
});

test('en mensajes el tiempo va al cubo gratis', async () => {
  const t = pestana('/direct/inbox/', { lastVisit: Date.now() });
  await espera(1300);
  t.w.dispatchEvent(new t.w.Event('pagehide'));
  await espera(50);
  assert.ok(t.st.datos.stats.dmSeconds >= 0.8);
  assert.equal(t.st.datos.stats.feedSeconds, 0);
});

test('sin foco no cuenta', async () => {
  const t = pestana('/', { lastVisit: Date.now() }, { foco: false });
  await espera(1300);
  t.w.dispatchEvent(new t.w.Event('pagehide'));
  await espera(50);
  assert.equal(t.st.datos.stats, undefined);
});

test('no cuenta doble: si otra pestaña tiene el latido vigente, esta no suma', async () => {
  const t = pestana('/', { lastVisit: Date.now(), heartbeat: { id: 'otra-pestana', ts: Date.now() + 60000 } });
  await espera(1300);
  t.w.dispatchEvent(new t.w.Event('pagehide'));
  await espera(50);
  assert.equal(t.st.datos.stats, undefined);
});

function popup(inicial) {
  const st = almacen(inicial);
  const dom = new JSDOM(POPUP_HTML.replace(/<script[^>]*><\/script>/g, ''), { runScripts: 'outside-only' });
  const w = dom.window;
  ventanas.push(w);
  w.chrome = st.api;
  w.eval(HABITS);
  w.eval(POPUP_JS);
  return { w, doc: w.document, st };
}

function cambiar(w, el, valor) {
  if (el.type === 'checkbox') el.checked = valor;
  else el.value = String(valor);
  el.dispatchEvent(new w.Event('change'));
}

test('popup: muestra lo de hoy y el presupuesto vigente', async () => {
  const p = popup({
    habits: { dailyBudgetMinutes: 15 },
    stats: { day: hoy(), dmSeconds: 600, feedSeconds: 300, blocksToday: 2 },
  });
  await espera(30);
  assert.equal(p.doc.getElementById('s-dm').textContent, '10 min');
  assert.equal(p.doc.getElementById('s-feed').textContent, '5 min');
  assert.equal(p.doc.getElementById('s-blocks').textContent, '2');
  assert.equal(p.doc.getElementById('estado').textContent, 'Te quedan 10 min fuera de mensajes');
  assert.equal(p.doc.getElementById('budget-nota').textContent, 'Vigente hoy: 15 min');
});

test('popup: subir el tiempo queda «Desde mañana»; bajarlo aplica ya', async () => {
  const p = popup({ habits: { dailyBudgetMinutes: 15 } });
  await espera(30);
  cambiar(p.w, p.doc.getElementById('budget'), 45);
  await espera(30);
  assert.equal(p.st.datos.habits.dailyBudgetMinutes, 15);
  assert.equal(p.st.datos.habits.pendingBudgetMinutes, 45);
  assert.equal(p.doc.getElementById('budget-nota').textContent, 'Vigente hoy: 15 min · Desde mañana: 45 min');
  cambiar(p.w, p.doc.getElementById('budget'), 10);
  await espera(30);
  assert.equal(p.st.datos.habits.dailyBudgetMinutes, 10);
  assert.equal(p.st.datos.habits.pendingBudgetMinutes, null);
});

test('popup: los interruptores guardan la config del filtro', async () => {
  const p = popup({});
  await espera(30);
  const reels = p.doc.querySelector('[data-config="blockReels"]');
  assert.equal(reels.checked, true);
  cambiar(p.w, reels, false);
  cambiar(p.w, p.doc.querySelector('[data-config="feedLimit"]'), 33);
  await espera(30);
  assert.equal(p.st.datos.config.blockReels, false);
  assert.equal(p.st.datos.config.feedLimit, 35, 'se redondea a pasos de 5');
});

test('popup: todos los controles tienen etiqueta (accesible con teclado y lector)', () => {
  const dom = new JSDOM(POPUP_HTML);
  ventanas.push(dom.window);
  for (const input of dom.window.document.querySelectorAll('input')) {
    assert.ok(input.closest('label'), `input sin etiqueta: ${input.outerHTML}`);
  }
  assert.doesNotMatch(POPUP_HTML, /<script>[^<]/, 'MV3 no permite scripts en línea');
});
