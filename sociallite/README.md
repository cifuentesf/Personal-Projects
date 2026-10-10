# SocialLite

Instagram sin doomscrolling. Los mensajes directos nunca tienen límite. El resto (inicio, perfiles, historias y búsqueda) tiene fricción y un tiempo diario, y los Reels, Explorar, la publicidad y las sugerencias desaparecen.

Hay dos partes que comparten el mismo filtro, [`shared/filter.js`](shared/filter.js):

- **App para iPhone**: abre instagram.com dentro de la app y le aplica el filtro.
- **Extensión** para Firefox, Chrome, Edge y Brave en Windows.

Todo funciona en local: no hay servidor, cuentas propias, analítica ni telemetría. Lo único que sale del teléfono o del navegador es el tráfico normal hacia Instagram.

> Esta guía es para Windows, sin Mac. La app de iPhone se compila en GitHub Actions y se instala con Sideloadly.

---

## Qué hace

| | iPhone | Extensión |
|---|---|---|
| Abre en Mensajes; chatear no gasta tiempo | ✔ | (se cuenta aparte) |
| Tiempo diario fuera de mensajes (15 min por defecto); al agotarse quedan solo los mensajes, en vivo y sin recargar | ✔ | ✔ |
| Bajar el límite aplica de inmediato; subirlo o quitarlo rige desde mañana | ✔ | ✔ |
| Sin pestaña Reels ni feed de reels; un reel enviado por mensaje se abre, pero no se puede pasar al siguiente | ✔ | ✔ |
| Sin cuadrícula de Explorar (la búsqueda de perfiles sigue funcionando) | ✔ | ✔ |
| Sin publicidad, sugerencias ni reels en el inicio | ✔ | ✔ |
| El inicio se corta en 20 publicaciones al día, también después de recargar | ✔ | ✔ |
| Escala de grises fuera de mensajes | ✔ | ✔ |
| «¿A qué vienes?» al abrir y aviso de pausa cada 5 min seguidos fuera de mensajes | ✔ | ✔ |
| Modo solo mensajes | ✔ | ✔ |

---

## 1. Dónde está el proyecto y cómo se compila

El proyecto vive en la carpeta `sociallite/` del repositorio público [cifuentesf/Personal-Projects](https://github.com/cifuentesf/Personal-Projects). La CI está en `.github/workflows/`, en la raíz, porque GitHub solo lee los workflows desde ahí:

- `sociallite-ios.yml`: pruebas → autoprueba en el simulador de iPhone → `SocialLite.ipa` sin firmar.
- `sociallite-extension.yml`: pruebas → revisión de Mozilla (`web-ext lint`) → prueba en Chromium → paquetes de la extensión.

Se ejecutan solos con cada `push` que toque `sociallite/`. Como el repositorio es **público**, los minutos de macOS son gratis. En un repositorio privado, cada minuto de macOS cuenta como 10.

### Opcional: moverlo a un repositorio propio

En PowerShell (con [Git para Windows](https://git-scm.com/download/win) instalado), cambiando `TU_USUARIO` por tu usuario de GitHub. Antes, crea un repositorio público vacío llamado `SocialLite` en github.com/new:

```powershell
cd $HOME\Documents
git clone https://github.com/cifuentesf/Personal-Projects.git
mkdir SocialLite
cd SocialLite
git init -b main
Copy-Item -Recurse ..\Personal-Projects\sociallite .\sociallite
New-Item -ItemType Directory -Force .github\workflows | Out-Null
Copy-Item ..\Personal-Projects\.github\workflows\sociallite-*.yml .github\workflows\
git add .
git commit -m "SocialLite"
git remote add origin https://github.com/TU_USUARIO/SocialLite.git
git push -u origin main
```

Se mantiene la subcarpeta `sociallite/` para que los workflows funcionen tal cual, sin editarlos.

---

## 2. Descargar la app (`SocialLite.ipa`)

1. Entra a **Actions** en GitHub → **sociallite-ios** → la ejecución más reciente con ✔ verde.
2. Abajo, en **Artifacts**, descarga **SocialLite-ipa**. Llega un `.zip`: descomprímelo y queda `SocialLite.ipa`.
3. Los artefactos duran 30 días. Si ya expiró: **Actions → sociallite-ios → Run workflow** y espera unos 10 minutos.

El artefacto **SocialLite-capturas** trae una captura de la app abriendo en el simulador.

---

## 3. Instalar en el iPhone desde Windows

### 3.1 Programas en el PC

1. **iTunes de la web de Apple, no de Microsoft Store.** Las versiones de Microsoft Store de iTunes, *Dispositivos Apple* y *Apple Music* no instalan el servicio **Apple Mobile Device Service**, y sin él ni Sideloadly ni AltServer ven el iPhone. En PowerShell **como administrador**:
   ```powershell
   # Quita iTunes, Dispositivos Apple y Apple Music de Microsoft Store (no toca el iPhone)
   Get-AppxPackage *AppleInc* | Remove-AppxPackage
   # Instala iTunes de la web de Apple, que trae el servicio
   winget install --id Apple.iTunes --source winget --exact --accept-package-agreements --accept-source-agreements
   Start-Service "Apple Mobile Device Service" -ErrorAction SilentlyContinue
   Get-Service "Apple Mobile Device Service"
   ```
   Tiene que decir `Running`. Si `winget` falla, instala iTunes a mano desde <https://www.apple.com/itunes/download/win64> y repite las dos últimas líneas. Reinicia el PC.
2. **iCloud**, también la versión de la web de Apple. Sideloadly lo pide para iniciar sesión con el Apple ID. Si ya tienes iCloud instalado y no es de Microsoft Store, sirve.
3. **Sideloadly**, desde <https://sideloadly.io>.

### 3.2 Instalar con Sideloadly

1. Conecta el iPhone por cable, desbloquéalo y acepta **Confiar en este computador**.
2. Abre Sideloadly. Arriba debe aparecer tu iPhone.
3. Arrastra `SocialLite.ipa` a la ventana.
4. Escribe un **Apple ID**. Se recomienda una cuenta secundaria, solo para esto: Sideloadly la usa para firmar la app.
5. Presiona **Start** e ingresa la contraseña y el código de verificación si te los pide.

Con un Apple ID gratis puedes tener **3 apps** instaladas así al mismo tiempo; la app *Al día* también cuenta.

### 3.3 Configurar el iPhone

1. *Ajustes → Privacidad y seguridad → **Modo de desarrollador*** → activar y reiniciar. Esta opción aparece recién después de instalar la app.
2. *Ajustes → General → **VPN y gestión de dispositivos*** → tu Apple ID → **Confiar**.
3. Abre SocialLite e inicia sesión en Instagram. La sesión queda guardada solo dentro de la app.

### 3.4 Renovar cada 7 días

Con un Apple ID gratis, la firma dura 7 días. Pasado ese plazo la app no abre (no se pierde nada).

- **Automático:** en Sideloadly activa el *auto-refresh*, deja Sideloadly abierto en el PC y el iPhone en la misma red Wi-Fi. En iTunes, con el iPhone conectado, activa *Sincronizar con este iPhone por Wi-Fi*.
- **A mano:** conecta el cable y vuelve a instalar el mismo `.ipa` con el mismo Apple ID. Los ajustes y la sesión se mantienen.

---

## 4. Notificaciones de mensajes

La app no recibe notificaciones push: eso requiere una cuenta de desarrollador pagada. La solución es usar la app oficial solo como "timbre":

1. En la **app oficial de Instagram**: *Configuración → Notificaciones*. Deja activas solo las de **Mensajes**.
2. En **Atajos → Automatización → Nueva automatización → App** → elige **Instagram** → marca **Se abre** → **Ejecutar inmediatamente**. Como acción, agrega **Abrir URL** con `sociallite://inbox`.

Cuando toques una notificación, Instagram se abrirá un instante y saltará a SocialLite, directo a Mensajes.

## 5. Cerrar la puerta trasera de Safari (opcional, con advertencia)

*Ajustes → Tiempo en pantalla → Restricciones de contenido y privacidad → Restricciones de contenido → Contenido web → Limitar sitios web para adultos → Nunca permitir → agregar `instagram.com`*.

> **Ojo:** la restricción de Tiempo en pantalla se aplica a WebKit, el mismo motor que usa SocialLite. Es probable que también bloquee instagram.com **dentro de SocialLite**. Pruébalo justo después de activarla. Si SocialLite muestra una página de "restringido", quita instagram.com de la lista. En ese caso, cerrar la sesión de Instagram en Safari es la alternativa más débil. No pude comprobarlo sin un iPhone real.

---

## 6. La extensión (Firefox, Chrome, Edge y Brave)

Descárgala desde **Actions → sociallite-extension →** la ejecución más reciente con ✔ → **Artifacts**.

### Chrome, Edge y Brave

1. Descarga **sociallite-chromium** y descomprímelo en una carpeta que no vayas a borrar, por ejemplo `Documentos\SocialLite-extension`. Dentro debe estar `manifest.json`.
2. Abre `chrome://extensions` (o `edge://extensions` o `brave://extensions`).
3. Activa **Modo de desarrollador** (arriba a la derecha) → **Cargar descomprimida** → elige esa carpeta.
4. Fija el ícono en la barra para ver el tiempo del día y los ajustes.

Chrome puede mostrar una advertencia sobre la clave `browser_specific_settings`: es la configuración de Firefox y no afecta a Chrome. Si mueves o borras la carpeta, la extensión deja de funcionar.

### Firefox

- **De prueba (hasta cerrar Firefox):** descarga **sociallite-firefox** y descomprímelo para obtener `sociallite-firefox.xpi`. Luego ve a `about:debugging` → **Este Firefox** → **Cargar complemento temporal…** → elige el `.xpi`.
- **Permanente:** Firefox solo instala de forma permanente las extensiones firmadas por Mozilla. La firma es gratis y no publica nada. Entra a <https://addons.mozilla.org/developers/> → **Enviar un nuevo complemento** → **En tu propio sitio** (no listado) → sube el `.xpi`. Mozilla te devuelve un `.xpi` firmado, que se instala arrastrándolo a Firefox.
- **Permiso del sitio:** en Manifest V3, Firefox puede dejar el acceso a instagram.com como opcional. Si el filtro no actúa, ve a `about:addons` → SocialLite → **Permisos** y activa *www.instagram.com*.

### Borrar los datos de la extensión

Los datos de la extensión (preferencias y contadores del día) se borran al quitarla. La sesión de Instagram y la lista de publicaciones vistas hoy son datos del sitio: se borran desde el candado de la barra de direcciones → *Borrar datos del sitio* (o las *Cookies y datos del sitio* del navegador).

---

## 7. Privacidad

- La app y la extensión no hacen peticiones de red propias y no tienen analítica ni SDKs. Puedes comprobarlo buscando en el código: en `shared/`, `extension/` e `ios/` no aparecen `fetch`, `XMLHttpRequest`, `WebSocket`, `sendBeacon` ni `URLSession`. Una prueba automática ([tests/extension.test.mjs](tests/extension.test.mjs)) revisa lo mismo en la extensión.
  ```powershell
  Select-String -Path sociallite\shared\*.js, sociallite\extension\*.js, sociallite\ios\SocialLite\Sources\*.swift -Pattern "fetch\(|XMLHttpRequest|WebSocket|sendBeacon|URLSession"
  ```
  Desde la carpeta del repositorio, ese comando no debería mostrar nada.
- Nunca lee ni guarda contraseñas, cookies, mensajes ni nombres de contactos. Las estadísticas son solo números y fechas.
- No hace nada por ti en Instagram (ni "me gusta", ni seguir, ni enviar): solo **oculta** y **redirige**.
- Lo guardado es solo: preferencias, contadores del día y los IDs de las publicaciones vistas hoy (para el tope del inicio).
- En el iPhone, *Ajustes de SocialLite → Datos → **Cerrar sesión y borrar datos*** borra la sesión de Instagram y las publicaciones vistas. El tiempo usado hoy se mantiene hasta medianoche, para que borrar no sirva para saltarse el límite. Desinstalar la app borra todo.

---

## 8. Desarrollo (si Instagram cambia su web)

Necesitas [Node.js 22](https://nodejs.org) y [Python 3](https://www.python.org). En PowerShell:

```powershell
winget install OpenJS.NodeJS.LTS
winget install Python.Python.3.12
cd $HOME\Documents\Personal-Projects\sociallite
npm install
npm test
```

Si se cuela publicidad o una sugerencia, o si Reels vuelve a aparecer:

1. Abre [`shared/filter.js`](shared/filter.js). Arriba están las listas de textos (`AD_TEXTS`, `SUGGESTED_TEXTS`, `END_MARKERS`) y las rutas. El filtro nunca usa clases CSS de Instagram, porque cambian a cada rato: solo rutas, `href`, etiquetas como `article` o `main`, y textos visibles cortos.
2. Agrega el texto nuevo (en minúsculas) y un caso en [`tests/filter.test.mjs`](tests/filter.test.mjs) con el HTML que viste.
3. `npm test` debe quedar en verde.
4. Regenera el filtro de la app: `py scripts\embed_filter.py` (escribe `ios/SocialLite/Sources/FilterScript.swift`, que no se edita a mano).
5. `git add`, `git commit` y `git push`. La CI arma una `.ipa` y una extensión nuevas. La `.ipa` se instala encima de la anterior con Sideloadly, sin perder nada.

Para probar la extensión en Chromium con un Instagram simulado (sin conectarse al real):

```powershell
py scripts\build_extension.py
npm install --no-save playwright
npx playwright install chromium
node tests\e2e\chromium.cjs dist\extension
```

### Qué hay en esta carpeta

```
sociallite/
├─ shared/filter.js          núcleo del filtro (único, sin dependencias, ES2019)
├─ extension/                manifest, content.js, habits.js, popup e íconos
├─ ios/project.yml           proyecto de Xcode descrito en texto (XcodeGen)
├─ ios/SocialLite/Sources/   app de iPhone en SwiftUI
├─ tests/                    pruebas (node:test + jsdom) y la prueba en Chromium
├─ scripts/                  embed_filter.py, build_extension.py y make_icons.py
├─ README.md
└─ DECISIONES.md             decisiones de diseño y diferencias con la especificación
```

---

## 9. Solución de problemas

| Problema | Qué hacer |
|---|---|
| La CI quedó en rojo en **Pruebas del filtro** | Falló una prueba: corre `npm test` en el PC y mira cuál. |
| Rojo en **FilterScript.swift igual a shared/filter.js** | Editaste `filter.js` sin regenerar: `py scripts\embed_filter.py`, commit y push. |
| Rojo en **Compilar** | Error de Swift: abre el paso y busca la línea `error:`. |
| Rojo en **Autoprueba del filtro en WebKit** | El filtro no corrió bien dentro del WebView del simulador. El registro lista qué revisión falló. |
| Sideloadly no ve el iPhone | Falta *Apple Mobile Device Service*: sección 3.1. Usa un cable de datos, desbloquea el iPhone y acepta *Confiar*. |
| No aparece *Modo de desarrollador* | Aparece recién después de instalar la app con Sideloadly. |
| La app no abre después de 7 días | Venció la firma: vuelve a instalar la `.ipa` con Sideloadly (sección 3.4). |
| Sideloadly dice que llegaste al máximo de apps | Un Apple ID gratis permite 3 apps a la vez y 10 instalaciones nuevas por semana. Borra una o espera. |
| Se cerró la sesión de Instagram | Vuelve a iniciar sesión dentro de SocialLite. El login y la verificación en dos pasos nunca se bloquean, ni con el tiempo agotado. |
| Se cuela publicidad, una sugerencia o un reel | Instagram cambió un texto: sección 8. |
| Subí el límite y sigo bloqueado | Es a propósito: subirlo rige desde mañana. Bajarlo aplica de inmediato. |
| Instagram se ve como computador o dice "navegador no compatible" | Recarga desde *Ajustes → Datos → Recargar Instagram*. Si sigue, avisa: puede que haya que ajustar `applicationNameForUserAgent` en `InstagramWebView.swift`. |
| La extensión no hace nada en Firefox | Activa el permiso de *www.instagram.com* (sección 6). |
