// Prueba de punta a punta en un Chromium real con la extensión cargada.
// instagram.com se simula (page.route): nunca se conecta al Instagram real.
//
// Comprueba lo que jsdom no puede: que Chrome acepte el manifest, que los scripts
// corran en document_start en el mundo aislado, y que el sondeo detecte las
// navegaciones que la página hace con su propio history.pushState.
//
//   python3 scripts/build_extension.py
//   npm install --no-save playwright && npx playwright install chromium
//   node tests/e2e/chromium.cjs dist/extension
const path = require('path');
const os = require('os');
const fs = require('fs');
const assert = require('assert/strict');
const { chromium } = require('playwright');

const EXT = path.resolve(process.argv[2] || 'dist/extension');

const PAGINA = `<!doctype html><html><head></head><body>
<nav><a href="/reels/">Reels</a><a href="/direct/inbox/">Mensajes</a></nav>
<main>
  <article id="ad"><span>Publicidad</span><a href="/p/AD1/">x</a></article>
  <article id="ok"><a href="/p/N1/">x</a></article>
  <article id="reel"><a href="/reel/R1/">x</a></article>
</main>
<script>window.irA = (p) => history.pushState({}, '', p);</script>
</body></html>`;

(async () => {
  const perfil = fs.mkdtempSync(path.join(os.tmpdir(), 'sociallite-e2e-'));
  const ctx = await chromium.launchPersistentContext(perfil, {
    channel: 'chromium',
    headless: true,
    args: [`--disable-extensions-except=${EXT}`, `--load-extension=${EXT}`],
  });
  const pedidas = [];
  await ctx.route('https://www.instagram.com/**', async (route) => {
    pedidas.push(new URL(route.request().url()).pathname);
    await route.fulfill({ status: 200, contentType: 'text/html', body: PAGINA });
  });
  const page = await ctx.newPage();
  const atributo = (sel, a) => page.evaluate(([s, n]) => document.querySelector(s).getAttribute(n), [sel, a]);

  await page.goto('https://www.instagram.com/');
  await page.waitForTimeout(800);
  assert.equal(await atributo('html', 'data-sl-route'), 'home', 'el filtro corre en el inicio');
  assert.equal(await atributo('#ad', 'data-sl-hidden'), 'ad', 'oculta la publicidad');
  assert.equal(await atributo('#reel', 'data-sl-hidden'), 'reel', 'oculta los reels del inicio');
  assert.equal(await atributo('#ok', 'data-sl-hidden'), null, 'deja ver lo normal');
  assert.equal(await page.evaluate(() => getComputedStyle(document.querySelector('a[href="/reels/"]')).display),
    'none', 'oculta la pestaña Reels');
  assert.equal(await page.evaluate(() => getComputedStyle(document.documentElement).filter), 'grayscale(1)');
  assert.equal(await page.evaluate(() => typeof window.SocialLiteFilter), 'undefined',
    'la página no ve el filtro (mundo aislado)');

  pedidas.length = 0;
  await page.evaluate(() => window.irA('/reels/'));
  await page.waitForTimeout(1500);
  assert.deepEqual(pedidas, ['/'], 'el sondeo detecta el pushState de la página y sale del feed de reels');

  await page.goto('https://www.instagram.com/direct/inbox/');
  await page.waitForTimeout(600);
  assert.equal(await atributo('html', 'data-sl-route'), 'direct');
  assert.equal(await page.evaluate(() => getComputedStyle(document.documentElement).filter), 'none',
    'mensajes sin escala de grises');

  await ctx.close();
  fs.rmSync(perfil, { recursive: true, force: true });
  console.log('e2e chromium: ok');
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
