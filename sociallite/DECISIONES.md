# Decisiones

Aquí quedan las decisiones que la especificación dejaba abiertas y los puntos donde me aparté de ella, con el motivo. Cuando hubo duda, se eligió la opción más conservadora para la privacidad y el bienestar.

## Dónde vive el proyecto y la CI

1. **El proyecto está en `Personal-Projects/sociallite/`, no en un repositorio propio.** Ese repositorio ya es público, así que los minutos de macOS en Actions son gratis. El README trae los pasos en PowerShell para pasarlo a un repositorio aparte.
2. **Los workflows están en `.github/workflows/` de la raíz y se llaman `sociallite-ios.yml` y `sociallite-extension.yml`**, en vez de `sociallite/.github/workflows/ios.yml` y `extension.yml`. GitHub solo lee los workflows desde la raíz del repositorio. Si se mueve a un repositorio propio conservando la subcarpeta `sociallite/`, funcionan sin cambios.
3. **Disparadores más amplios:** `push` en cualquier rama (solo si cambia `sociallite/` o el propio workflow), `pull_request` y `workflow_dispatch`. La especificación pedía solo `push` a `main`, pero así cada cambio se compila y se prueba antes de unirlo a `main`.
4. **La CI de iOS hace más de lo pedido**, sin cambiar lo pedido. Los jobs siguen llamándose `test-filter` y `build-ios`, y la `.ipa` sale de `xcodebuild -target SocialLite … SYMROOT=… CODE_SIGNING_ALLOWED=NO`. Además:
   - comprueba que `FilterScript.swift` esté al día con `shared/filter.js`;
   - compila para el simulador y corre una **autoprueba** dentro de la app (ver la decisión 17);
   - abre la app normal en el simulador, guarda una captura y comprueba que no se cayó.
   Para el simulador se usa `-scheme`, porque `-destination` lo necesita; por eso `project.yml` declara `scheme: {}`.
5. **La CI de la extensión también corre `web-ext lint`**, la revisión de Mozilla, con advertencias tratadas como errores. Además prueba la extensión en un **Chromium real** con instagram.com simulado: `tests/e2e/chromium.cjs` responde con una página falsa y nunca se conecta a Instagram.
6. **El artefacto `sociallite-chromium` es la carpeta de la extensión.** GitHub la entrega como `.zip`, que es justamente el `sociallite-chromium.zip` que se pide. `scripts/build_extension.py` también genera `dist/sociallite-chromium.zip` y `dist/sociallite-firefox.xpi` en local. Los dos tienen los mismos bytes y son deterministas.

## Herramientas

7. **`"test": "node --test \"tests/**/*.test.mjs\""`** en vez de `node --test tests/`. En Node 22, `node --test` con una carpeta como argumento falla ("Cannot find module"). El patrón entre comillas funciona igual en Windows y en Linux, y `engines.node` exige `>=22`.
8. **jsdom 26.** Las versiones más nuevas piden una versión menor de Node 22 más reciente que la que trae mucha gente instalada. jsdom 26 tiene todo lo que usan las pruebas.
9. **Playwright no es una dependencia del proyecto.** Solo lo instala la CI (`npm install --no-save`), para que `npm install` en Windows siga siendo liviano y no descargue navegadores.

## Filtro (`shared/filter.js`)

10. **Rutas además de las de la especificación:**
    - `/reels` sin barra final también cuenta como feed de reels.
    - Instagram también usa `/usuario/reel/ID` y `/usuario/p/ID`, así que esas formas cuentan como elemento suelto, igual que `/reel/ID` y `/p/ID`.
11. **Fuera del inicio no se oculta ningún `article`, y si quedó alguno oculto se le quita el atributo.** Un post suelto también es un `<article>`, y el inicio recicla nodos al navegar por la SPA. Además, la tarjeta de fin solo aparece en el inicio.
12. **Al redirigir, el cuerpo de la página se oculta** (`html[data-sl-leaving] body{visibility:hidden}`) hasta que llega la página segura, para que no se alcance a ver el reel o el feed bloqueado.
13. **Las teclas de navegación no se bloquean dentro de campos de texto** (`input`, `textarea`, `select` y `contenteditable`), para no romper la escritura.
14. **Las publicaciones del inicio sin enlace `/p/` ni `/reel/` no cuentan para el tope.** Sin ID no se pueden recordar entre recargas. Si se contaran, una misma publicación podría gastar cupo varias veces.
15. **Si cambia `feedLimit` con `update()`, se reinicia `limitReached`.** Así, bajar o subir el tope se nota sin recargar la página.

## App de iPhone

16. **El filtro corre en su propio mundo de JavaScript (`WKContentWorld.defaultClient`)**, igual que un content script de extensión. El handler `sociallite` y los dos `WKUserScript` viven en ese mundo. Así, los scripts de Instagram no pueden ver el filtro, ni llamar a `update()`, ni falsificar avisos de ruta (por ejemplo, para que el tiempo fuera de mensajes no se cuente).
    - Por eso, la llamada en vivo es `evaluateJavaScript(_:in:in:completionHandler:)` con ese mundo. La forma de la especificación, sin mundo, correría en la página, donde `SocialLiteFilter` no existe, y no haría nada.
    - El parche de `history` del filtro no ve la navegación de la página desde ese mundo, pero el sondeo cada 400 ms sí (está probado en la autoprueba y en Chromium).
17. **Autoprueba en el simulador (`--autoprueba`), que no estaba en la especificación.** Sin un iPhone, era la única forma de comprobar el filtro en el WebKit real:
    - carga una página falsa de Instagram con los mismos scripts y el mismo mundo;
    - revisa que oculte publicidad, reels y la pestaña Reels, que aplique la escala de grises, que la página no vea el filtro, que el puente nativo reciba la ruta, que el sondeo saque del feed de reels y que el bloqueo en vivo mande a Mensajes;
    - usa un almacén de datos no persistente y cancela toda navegación después de la primera, así que no toca la sesión ni se conecta a Instagram;
    - solo se activa con un argumento de lanzamiento que únicamente la CI puede pasar.
18. **"Cerrar sesión y borrar datos" no borra el tiempo usado hoy ni las preferencias.** Borra todo `WKWebsiteDataStore.default()`: la sesión, las cookies y el `localStorage` con las publicaciones vistas hoy.
    - Los contadores del día son solo números y se reinician solos a medianoche. Si se borraran, el botón serviría para saltarse el límite.
    - Las preferencias tampoco se borran: volver a los valores por defecto podría subir el presupuesto (que solo puede subir desde mañana).
    - Para borrarlo todo, se desinstala la app; el README lo dice. Es la opción conservadora para el bienestar, sin costo de privacidad: ninguno de esos datos identifica a nadie ni dice qué se vio.
19. **La ruta inicial cuenta como `direct`.** La app siempre abre en Mensajes, así que el tiempo antes del primer aviso del filtro no gasta presupuesto.
20. **Ícono incluido**, aunque la especificación no lo exigía: sin ícono, la app aparece en blanco en la pantalla de inicio. `scripts/make_icons.py` lo genera (un globo de diálogo sobre un degradado), y lo mismo hace con los íconos de la extensión. No hay imágenes de terceros.
21. **Gesto de volver atrás activo** (`allowsBackForwardNavigationGestures`). Las reglas del filtro se aplican igual en cada ruta a la que se vuelve.
22. **Los interruptores de los filtros aplican de inmediato**, como pide la especificación; la regla anti-trampa solo cubre el presupuesto diario. El bloqueo por presupuesto (`lockToDMs`) no depende de ningún interruptor: apagar "Bloquear Reels" no desbloquea un día agotado.

## Extensión

23. **Sin botón "Cerrar sesión y borrar datos".** Borrar las cookies de Instagram exige permisos (`cookies` o `browsingData`) que la regla de "solo `storage`" no permite. El README explica cómo hacerlo desde el navegador ("Borrar datos del sitio") y que quitar la extensión borra sus datos.
24. **Contabilidad con varias pestañas:**
    - Cada pestaña escribe un "latido" (`id` + hora) cada 3 s, solo mientras está visible y con foco.
    - Una pestaña no cuenta tiempo si otra latió hace menos de 7 s. Así nunca se cuenta doble.
    - Cada tick suma como máximo 5 s, para que una pestaña suspendida no sume de golpe el tiempo que estuvo dormida.
    - Se guarda cada 15 s y en `pagehide`.
25. **"¿A qué vienes?" en la extensión** aparece al abrir instagram.com cuando pasaron más de 5 min desde la última visita. Usa `lastVisit` en `storage.local` (solo una fecha).
26. **`data_collection_permissions: { required: ["none"] }`** en `browser_specific_settings.gecko`. Firefox ahora pide declarar qué datos recoge una extensión. Esta no recoge ninguno, y con esa línea `web-ext lint` queda sin avisos.
27. **`strict_min_version: "115.0"`.** Firefox soporta MV3 desde la versión 109, y la 115 es la ESR (versión de soporte extendido) más antigua posterior a eso.
28. **`content.js` y `habits.js` usan sintaxis moderna** (`??`, `const`, funciones flecha), que tienen todos los navegadores soportados. Solo `shared/filter.js` se limita a ES2019, porque también corre en el WebKit de iOS 16; una prueba lo comprueba.

## Riesgos conocidos

- **Los textos reales de Instagram pueden diferir** de los de las listas (publicidad, sugerencias y marcadores de fin), sobre todo en otros idiomas o en pruebas A/B. Las pruebas usan HTML armado a mano, no el de Instagram. Si algo se cuela, se agrega el texto y un test (README, sección 8).
- **Tiempo en pantalla puede bloquear también SocialLite.** La restricción de sitios de Tiempo en pantalla aplica a WebKit en todo el sistema, incluido el WKWebView. El README advierte que hay que probarlo.
- **Instagram puede cambiar la web móvil.** Si deja de servirla con el user agent de Safari, o cambia las rutas (`/direct/`, `/reels/`), hay que ajustar el filtro o `applicationNameForUserAgent`.
- **Cambiar la fecha del teléfono o del PC adelanta el presupuesto pendiente.** No hay forma local y sin servidor de evitarlo; se acepta.
- **Firefox puede dejar el permiso de instagram.com como opcional** en extensiones MV3; el README explica cómo activarlo.
- **No se probó en un iPhone físico ni con una cuenta real de Instagram.** Lo verificado está en la tabla de la entrega: pruebas en Node, autoprueba en el simulador y Chromium con un Instagram simulado.
