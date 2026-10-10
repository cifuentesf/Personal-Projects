// Pruebas del núcleo del filtro (shared/filter.js) con jsdom.
// jsdom no navega: el filtro recibe hooks.navigate y aquí se registra a dónde quiso ir.
import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { JSDOM } from 'jsdom';

const SRC = readFileSync(new URL('../shared/filter.js', import.meta.url), 'utf8');
const ventanas = [];
after(() => { for (const w of ventanas) w.close(); });

const espera = (ms) => new Promise((r) => setTimeout(r, ms));

function hoy() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/** Carga el filtro en una página de instagram.com con la ruta dada y lo arranca. */
function cargar(ruta, { html = '', config = {}, vistos, antes } = {}) {
  const dom = new JSDOM(`<!doctype html><html><head></head><body>${html}</body></html>`, {
    url: 'https://www.instagram.com' + ruta,
    runScripts: 'outside-only',
  });
  const w = dom.window;
  ventanas.push(w);
  if (vistos) w.localStorage.setItem('sociallite:seen', JSON.stringify(vistos));
  if (antes) antes(w);
  const reportes = [];
  const navegaciones = [];
  w.eval(SRC);
  w.SocialLiteFilter.start(config, {
    report: (p) => reportes.push({ type: p.type, reason: p.reason, path: p.path }),
    navigate: (p) => navegaciones.push(p),
  });
  return {
    w,
    doc: w.document,
    html: w.document.documentElement,
    reportes,
    navegaciones,
    ir: (p) => w.history.pushState({}, '', p),
    bloqueos: () => reportes.filter((r) => r.type === 'blocked').map((r) => r.reason),
    rutas: () => reportes.filter((r) => r.type === 'route').map((r) => r.reason),
    oculto: (id) => w.document.getElementById(id).getAttribute('data-sl-hidden'),
  };
}

function gesto(w, tipo, extra = {}) {
  const ev = new w.Event(tipo, { cancelable: true, bubbles: true });
  Object.assign(ev, extra);
  w.dispatchEvent(ev);
  return ev;
}

// ---------------------------------------------------------------- casos de §7

test('1. /reels/ bloquea el feed de reels y vuelve a /', () => {
  const t = cargar('/reels/');
  assert.deepEqual(t.bloqueos(), ['reels-feed']);
  assert.deepEqual(t.navegaciones, ['/']);
});

test('2. un reel desde un DM se abre, pero pasar al siguiente vuelve a la conversación', () => {
  const t = cargar('/direct/t/123/');
  t.ir('/reel/AAA/');
  assert.equal(t.html.getAttribute('data-sl-route'), 'shared');
  assert.deepEqual(t.navegaciones, []);
  t.ir('/reel/BBB/');
  assert.deepEqual(t.bloqueos(), ['reel-swipe']);
  assert.deepEqual(t.navegaciones, ['/direct/t/123/']);
});

test('3. en un reel suelto, el scroll se cancela y se reporta reel-scroll una sola vez', () => {
  const t = cargar('/reel/AAA/');
  const ev = gesto(t.w, 'touchmove');
  assert.equal(ev.defaultPrevented, true);
  gesto(t.w, 'wheel');
  assert.deepEqual(t.bloqueos(), ['reel-scroll']);
  assert.equal(t.doc.getElementById('sl-toast').textContent, 'Un reel a la vez');
});

test('4. dmOnlyMode en / lleva a la bandeja sin contar un bloqueo', () => {
  const t = cargar('/', { config: { dmOnlyMode: true } });
  assert.deepEqual(t.navegaciones, ['/direct/inbox/']);
  assert.deepEqual(t.bloqueos(), []);
});

test('5. lockToDMs: un post abierto desde un DM se permite; un perfil vuelve a la bandeja', () => {
  const t = cargar('/direct/t/1/', { config: { lockToDMs: true } });
  t.ir('/p/XYZ/');
  assert.equal(t.html.getAttribute('data-sl-route'), 'shared');
  assert.deepEqual(t.navegaciones, []);
  t.ir('/alguien/');
  assert.deepEqual(t.navegaciones, ['/direct/inbox/']);
  assert.deepEqual(t.bloqueos(), ['locked']);
});

test('6. lockToDMs nunca bloquea el login', () => {
  const t = cargar('/accounts/login/', { config: { lockToDMs: true } });
  assert.deepEqual(t.navegaciones, []);
  assert.equal(t.html.getAttribute('data-sl-route'), 'auth');
  assert.deepEqual(t.rutas(), ['auth']);
});

test('7. update({lockToDMs:true}) en un perfil redirige en vivo, sin recargar', () => {
  const t = cargar('/alguien/');
  assert.deepEqual(t.navegaciones, []);
  t.w.SocialLiteFilter.update({ lockToDMs: true });
  assert.deepEqual(t.navegaciones, ['/direct/inbox/']);
  assert.deepEqual(t.bloqueos(), ['locked']);
});

test('8. las rutas se reportan en orden: direct → home → explore', () => {
  const t = cargar('/direct/inbox/');
  t.ir('/');
  t.ir('/explore/');
  assert.deepEqual(t.rutas(), ['direct', 'home', 'explore']);
});

const INICIO = `<main>
  <article id="ad"><header><span>Publicidad</span></header><a href="/p/AD1/">foto</a></article>
  <article id="sug"><span>Sugerencias para ti</span><a href="/p/SG1/">foto</a></article>
  <article id="reel"><a href="/reel/R1/">video</a></article>
  <article id="ok"><span>amigo</span><a href="/p/N1/">foto</a><span>Un pie de foto largo sobre la publicidad en general</span></article>
  <div><span>Ya viste todo</span></div>
  <article id="despues"><a href="/p/X1/">foto</a></article>
</main>`;

test('9. el inicio oculta publicidad, sugeridos, reels y lo que viene después de «Ya viste todo»', () => {
  const t = cargar('/', { html: INICIO });
  assert.equal(t.oculto('ad'), 'ad');
  assert.equal(t.oculto('sug'), 'suggested');
  assert.equal(t.oculto('reel'), 'reel');
  assert.equal(t.oculto('ok'), null, 'una publicación normal queda visible aunque su texto diga «publicidad»');
  assert.equal(t.oculto('despues'), 'suggested');
});

const TRES = `<main>
  <article id="a0"><a href="/p/P0/">0</a></article>
  <article id="a1"><a href="/p/P1/">1</a></article>
  <article id="a2"><a href="/p/P2/">2</a></article>
</main>`;

test('10. tope de 2 con 3 publicaciones: la tercera es limit, tarjeta de fin y rueda bloqueada', () => {
  const t = cargar('/', { html: TRES, config: { feedLimit: 2 } });
  assert.equal(t.oculto('a0'), null);
  assert.equal(t.oculto('a1'), null);
  assert.equal(t.oculto('a2'), 'limit');
  const tarjeta = t.doc.getElementById('sl-endcard');
  assert.ok(tarjeta, 'aparece la tarjeta de fin');
  assert.match(tarjeta.textContent, /Viste tus 2 publicaciones de hoy\. El inicio terminó\./);
  assert.equal(tarjeta.querySelector('a').getAttribute('href'), '/direct/inbox/');
  assert.equal(gesto(t.w, 'wheel').defaultPrevented, true);
  assert.deepEqual(JSON.parse(t.w.localStorage.getItem('sociallite:seen')), { day: hoy(), keys: ['P0', 'P1'] });
});

test('11. lo ya visto hoy se sigue mostrando; lo nuevo, sin cupo, se oculta', () => {
  const t = cargar('/', {
    html: TRES,
    config: { feedLimit: 2 },
    vistos: { day: hoy(), keys: ['P1', 'P2'] },
  });
  assert.equal(t.oculto('a0'), 'limit');
  assert.equal(t.oculto('a1'), null);
  assert.equal(t.oculto('a2'), null);
});

test('12. escala de grises: atributo presente y ruta direct (que la exime)', () => {
  const t = cargar('/direct/inbox/');
  assert.equal(t.html.hasAttribute('data-sl-gray'), true);
  assert.equal(t.html.getAttribute('data-sl-route'), 'direct');
  const css = t.doc.getElementById('sl-style').textContent;
  assert.match(css, /html\[data-sl-gray\]:not\(\[data-sl-route="direct"\]\)/);
});

test('13. con todos los interruptores apagados no se oculta nada', () => {
  const t = cargar('/', {
    html: INICIO,
    config: { blockReels: false, hideFeedReels: false, blockExplore: false, hideAds: false,
      hideSuggested: false, grayscale: false, feedLimit: 0 },
  });
  assert.equal(t.doc.querySelectorAll('[data-sl-hidden]').length, 0);
  assert.equal(t.html.hasAttribute('data-sl-gray'), false);
  assert.equal(t.html.hasAttribute('data-sl-block-reels'), false);
  assert.equal(t.doc.getElementById('sl-endcard'), null);
});

test('14. /explore/ es la ruta explore y no redirige (la búsqueda sigue funcionando)', () => {
  const t = cargar('/explore/');
  assert.equal(t.html.getAttribute('data-sl-route'), 'explore');
  assert.deepEqual(t.navegaciones, []);
  assert.equal(t.html.hasAttribute('data-sl-block-explore'), true);
});

// ------------------------------------------------------------ robustez extra

test('el inicio recicla nodos: si un artículo deja de ser publicidad, vuelve a verse', async () => {
  const t = cargar('/', { html: INICIO });
  assert.equal(t.oculto('ad'), 'ad');
  const art = t.doc.getElementById('ad');
  art.innerHTML = '<span>amiga</span><a href="/p/N2/">foto</a>';
  await espera(350);
  assert.equal(t.oculto('ad'), null);
});

test('artículos nuevos que llegan con el scroll se filtran solos (MutationObserver)', async () => {
  const t = cargar('/', { html: '<main id="m"></main>' });
  const nuevo = t.doc.createElement('article');
  nuevo.id = 'tarde';
  nuevo.innerHTML = '<span>Sponsored</span><a href="/p/Z/">x</a>';
  t.doc.getElementById('m').appendChild(nuevo);
  await espera(350);
  assert.equal(t.oculto('tarde'), 'ad');
});

test('comillas tipográficas: «You’re all caught up» también marca el fin', () => {
  const t = cargar('/', {
    html: '<main><article id="a"><a href="/p/A/">a</a></article><p>You’re all caught up</p>' +
      '<article id="b"><a href="/p/B/">b</a></article></main>',
  });
  assert.equal(t.oculto('a'), null);
  assert.equal(t.oculto('b'), 'suggested');
});

test('fuera del inicio no se oculta ningún artículo (un post suelto es un <article>)', () => {
  const t = cargar('/p/ABC/', { html: '<main><article id="post"><span>Publicidad</span><a href="/p/ABC/">x</a></article></main>' });
  assert.equal(t.oculto('post'), null);
});

test('con el tope alcanzado, salir del inicio quita la tarjeta y libera el scroll', async () => {
  const t = cargar('/', { html: TRES, config: { feedLimit: 1 } });
  assert.ok(t.doc.getElementById('sl-endcard'));
  t.ir('/alguien/');
  await espera(20);
  assert.equal(t.doc.getElementById('sl-endcard'), null);
  assert.equal(gesto(t.w, 'wheel').defaultPrevented, false);
});

test('el tope sobrevive a recargar: con el cupo lleno, todo lo nuevo se oculta', () => {
  const t = cargar('/', {
    html: '<main><article id="n"><a href="/p/NUEVO/">x</a></article></main>',
    config: { feedLimit: 2 },
    vistos: { day: hoy(), keys: ['P0', 'P1'] },
  });
  assert.equal(t.oculto('n'), 'limit');
  assert.ok(t.doc.getElementById('sl-endcard'));
});

test('los vistos de otro día no cuentan', () => {
  const t = cargar('/', { html: TRES, config: { feedLimit: 2 }, vistos: { day: '2000-01-01', keys: ['X', 'Y'] } });
  assert.equal(t.oculto('a0'), null);
  assert.equal(t.oculto('a1'), null);
  assert.equal(t.oculto('a2'), 'limit');
});

test('las flechas no se bloquean mientras se escribe', () => {
  const t = cargar('/reel/AAA/', { html: '<input id="i">' });
  const input = t.doc.getElementById('i');
  const ev = new t.w.KeyboardEvent('keydown', { key: 'ArrowDown', cancelable: true, bubbles: true });
  input.dispatchEvent(ev);
  assert.equal(ev.defaultPrevented, false);
  const ev2 = new t.w.KeyboardEvent('keydown', { key: 'ArrowDown', cancelable: true, bubbles: true });
  t.doc.body.dispatchEvent(ev2);
  assert.equal(ev2.defaultPrevented, true);
});

test('URLs nuevas de Instagram (/usuario/reel/ID/ y /usuario/p/ID/) cuentan como sueltas', () => {
  const t = cargar('/direct/t/9/');
  t.ir('/fulano/p/QQ/');
  assert.equal(t.html.getAttribute('data-sl-route'), 'shared');
  t.ir('/fulano/reel/R1/');
  t.ir('/fulano/reel/R2/');
  assert.deepEqual(t.bloqueos(), ['reel-swipe']);
});

test('una historia enviada por DM se abre aunque esté bloqueado', () => {
  const t = cargar('/direct/t/5/', { config: { lockToDMs: true } });
  t.ir('/stories/fulano/123/');
  assert.equal(t.html.getAttribute('data-sl-route'), 'shared');
  assert.deepEqual(t.navegaciones, []);
});

test('con bloqueo, la «última ruta segura» es siempre la bandeja', () => {
  const t = cargar('/direct/t/1/', { config: { dmOnlyMode: true } });
  t.ir('/reel/A/');
  t.ir('/reel/B/');
  assert.deepEqual(t.navegaciones, ['/direct/inbox/']);
});

test('reportes por el puente de iOS (webkit.messageHandlers.sociallite)', () => {
  const enviados = [];
  cargar('/reels/', {
    antes: (w) => { w.webkit = { messageHandlers: { sociallite: { postMessage: (p) => enviados.push(p.type + ':' + p.reason) } } }; },
  });
  assert.deepEqual(enviados, ['blocked:reels-feed']);
});

test('autoinicio con window.__SOCIALLITE_CONFIG__ (como en iOS) y guarda contra doble carga', () => {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', {
    url: 'https://www.instagram.com/direct/inbox/', runScripts: 'outside-only',
  });
  const w = dom.window;
  ventanas.push(w);
  w.__SOCIALLITE_CONFIG__ = { grayscale: false, lockToDMs: true };
  w.eval(SRC);
  w.eval(SRC);
  assert.equal(typeof w.SocialLiteFilter.version, 'string');
  assert.equal(w.document.documentElement.getAttribute('data-sl-route'), 'direct');
  assert.equal(w.document.documentElement.hasAttribute('data-sl-gray'), false);
  assert.equal(w.document.querySelectorAll('#sl-style').length, 1);
});

test('si alguien borra el <style>, se vuelve a inyectar', async () => {
  const t = cargar('/');
  t.doc.getElementById('sl-style').remove();
  await espera(350);
  assert.ok(t.doc.getElementById('sl-style'));
});

test('el código del filtro es ES2019: sin ?. ni ??', () => {
  const sinComentarios = SRC.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
  assert.equal(/\?\.(?!\d)/.test(sinComentarios), false, 'usa ?.');
  assert.equal(/\?\?/.test(sinComentarios), false, 'usa ??');
});

test('FilterScript.swift contiene exactamente shared/filter.js (correr scripts/embed_filter.py si falla)', () => {
  const swift = readFileSync(new URL('../ios/SocialLite/Sources/FilterScript.swift', import.meta.url), 'utf8');
  const inicio = swift.indexOf('#"""\n') + 5;
  const fin = swift.lastIndexOf('"""#');
  assert.ok(inicio > 4 && fin > inicio, 'formato del string crudo');
  assert.equal(swift.slice(inicio, fin), SRC.endsWith('\n') ? SRC : SRC + '\n');
});
