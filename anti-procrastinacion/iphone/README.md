# Al día (iPhone)

**plazos** y **foco** como app nativa de iPhone (SwiftUI, iOS 16 o más nuevo).
Hace lo mismo que las apps de escritorio y además avisa cuando termina un
bloque **aunque el iPhone esté bloqueado**, que en el PC no hace falta y en el
teléfono es lo que más importa.

Usa **los mismos archivos** que la versión de PC (`plazos_datos.json`,
`foco_registro.csv`, `foco_para_despues.txt`), con el mismo formato byte a
byte. Puedes llevar tus entregas del PC al iPhone y de vuelta.

## Qué tiene

- **Plazos**: la lista con colores, el «hoy necesitas X h» y el «si hoy no
  avanzas», el siguiente paso de cada entrega, +25 min / +1 h, *Paso hecho*,
  importar y exportar el JSON del PC.
- **Foco**: intención obligatoria, «Solo 5 minutos», distracciones anotadas
  para después, descansos, racha y gráfico de la semana. Ofrece los siguientes
  pasos de Plazos como intención.
- Si iOS cierra la app a mitad de un bloque, al abrirla sigue donde estaba. Si
  el teléfono estuvo bloqueado más de lo que duraba el bloque, se anotan los
  minutos del bloque, no las horas que pasaron.

**bloqueo no está.** En iPhone ninguna app normal puede bloquear sitios ni
cerrar otras apps. La única vía es la API de Tiempo en pantalla, y Apple exige
una cuenta de desarrollador pagada (US$99 al año) más un permiso especial. Sin
eso, lo que funciona es lo que el iPhone ya trae:

- *Ajustes → Tiempo en pantalla → Límites de apps*: un minuto al día para
  Instagram o TikTok, con contraseña que no sepas de memoria (que la ponga
  otra persona).
- *Ajustes → Concentración*: un modo «Estudio» que oculta las apps que
  distraen y silencia sus avisos. Se puede activar solo a ciertas horas o al
  llegar a la biblioteca.

## Instalarla

No está en la App Store: se instala con tu propia cuenta de Apple. Con una
cuenta gratis, iOS la deja abierta **7 días**; después hay que reinstalarla
(los datos se conservan). Con la cuenta pagada dura un año.

### Desde Windows (sin Mac)

1. En GitHub, pestaña **Actions → iphone**, abre la última corrida en verde y
   descarga el artefacto **AlDia-sin-firmar** (un `.zip` con
   `AlDia-sin-firmar.ipa`).
2. Instala [Sideloadly](https://sideloadly.io) en el PC, conecta el iPhone por
   cable, arrastra el `.ipa` y entra con tu Apple ID. Sideloadly la firma con
   tu cuenta y la instala.
3. En el iPhone: *Ajustes → General → VPN y gestión de dispositivos* → confía
   en tu Apple ID. En iOS 16 o más nuevo, activa también *Ajustes → Privacidad
   y seguridad → Modo de desarrollador* (pide reiniciar).

### Desde un Mac

```
brew install xcodegen
cd anti-procrastinacion/iphone
xcodegen generate
open AlDia.xcodeproj
```

En Xcode: *Signing & Capabilities* → elige tu equipo (tu Apple ID), conecta el
iPhone y dale a ▶︎.

## Pasar datos entre el PC y el iPhone

- **Del PC al iPhone**: copia `plazos_datos.json` al iPhone (por iCloud Drive,
  OneDrive o AirDrop) y en Plazos → ⋯ → *Importar desde el PC…*. Reemplaza lo
  que había; lo anterior queda respaldado como
  `plazos_datos.antes-de-importar.json`.
- **Del iPhone al PC**: Plazos → ⋯ → *Exportar plazos_datos.json*, y déjalo
  junto a `plazos.py`.
- Todos los archivos se ven en la app **Archivos → En mi iPhone → Al día**.

No hay sincronización automática: cada lado tiene su copia y la del último que
exportaste es la que vale.

## Cómo está hecha

```
iphone/
  Logica/      paquete Swift sin interfaz: cálculos, temporizador, archivos
  App/         la app SwiftUI (pantallas, notificaciones, almacenamiento)
  project.yml  el proyecto de Xcode en texto (XcodeGen lo convierte en .xcodeproj)
```

Toda la lógica está en `Logica/` y se prueba sin simulador. Las pruebas son
las mismas que `--selftest` de escritorio, con los mismos números, más dos que
leen un `plazos_datos.json` y un `foco_registro.csv` escritos por las apps de
PC. Además comprueban que el iPhone escribe el CSV con exactamente los mismos
bytes que Python.

GitHub Actions corre en un Mac, en cada cambio:

1. `swift test` sobre `Logica/`.
2. Compila la app y la abre en el simulador con `--autoprueba`: crea entregas,
   suma horas, importa el JSON del PC, hace un ciclo de foco completo con
   minutos de 10 ms y la reabre para ver que todo quedó guardado.
3. Toma capturas de pantalla con datos de ejemplo (`--demo`), en claro y en
   oscuro, y las deja como artefacto **capturas**.
4. Compila el `.ipa` sin firmar para instalar desde Windows.

**Lo que no está probado automáticamente**: que el aviso llegue con el
teléfono bloqueado (el simulador no lo muestra) y cómo se ve en un iPhone
real. Eso se ve usándola.
