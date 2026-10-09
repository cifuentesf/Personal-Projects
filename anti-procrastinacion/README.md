# anti-procrastinación

Tres apps de escritorio chicas, cada una contra una causa distinta de postergar.
Mismo formato que doc2tts: un solo archivo Python por app, interfaz en tkinter,
nada que instalar con `pip`.

| Si el problema es… | App | Qué hace |
|---|---|---|
| No ves lo que cuesta dejarlo para mañana | **plazos** | Entregas con cuenta regresiva, horas que tocan hoy y cuánto sube eso si postergas un día. |
| No logras empezar, o el bloque se te escapa | **foco** | Bloques con intención escrita, arranque de 5 minutos y lista de distracciones para después. |
| Los sitios y las apps te tragan | **bloqueo** | Bloquea sitios y cierra apps por un tiempo fijo; salir antes cuesta a propósito. |

Se conectan sin depender una de otra: **plazos** dice cuál es el siguiente paso
de cada entrega, **foco** te lo ofrece como intención del bloque, y **bloqueo**
cuida ese bloque. Cada una funciona sola.

## Ejecutar

Python 3.9 o más nuevo, con tkinter (el instalador de python.org lo trae; en
Linux: `sudo apt install python3-tk`).

```
python plazos/plazos.py            # cada app abre su ventana
python foco/foco.py
python bloqueo/bloqueo.py

python foco/foco.py --accesos      # lanzadores de doble clic (.bat y acceso
                                   # directo en el Escritorio; .sh y .desktop en Linux)
python foco/foco.py --selftest     # prueba la lógica interna, sin ventana
python foco/foco.py --guitest      # recorre la interfaz sola y se cierra
```

Si una app no abre, el traceback queda en `<app>_error.log`, junto al `.py`.

Los datos quedan junto a cada `.py` (o en `~/.<app>` si esa carpeta no se puede
escribir) y git los ignora: son tuyos, no del repositorio.

| App | Archivos que crea |
|---|---|
| plazos | `plazos_datos.json`, `plazos_config.json` |
| foco | `foco_registro.csv`, `foco_para_despues.txt`, `foco_config.json` |
| bloqueo | `bloqueo_registro.csv`, `bloqueo_hosts_respaldo.txt`, `bloqueo_config.json` |

Los CSV usan `;` como separador, que es lo que Excel en español abre directo
con doble clic.

---

## plazos

Por cada entrega anotas la fecha, cuántas horas de trabajo crees que toma y el
**siguiente paso**. Arriba, en grande, la app dice cuántas horas necesitas hoy
para ir al día con todo, y debajo, cuánto subiría esa cifra si hoy no haces
nada. Ese segundo número es el punto: postergar se siente gratis, y no lo es.

**Cómo calcula.** Supone ritmo parejo: lo que falta se reparte entre los días
que quedan, y si queda menos de un día, todo lo que falta toca hoy. El total de
hoy es la suma de todas las entregas. No es un calendario ni decide el orden:
te dice el tamaño del problema, no cómo resolverlo.

| Color | Cuándo |
|---|---|
| verde, «holgada» | hoy toca la mitad de tu capacidad diaria o menos |
| amarillo, «ajustada» | entre la mitad y el total de tu capacidad |
| rojo, «sobre tu ritmo» | más de lo que rindes en un día |
| «no alcanza» | faltan más horas de trabajo que horas de reloj hasta la entrega |

La capacidad diaria (4 h por omisión) es lo que de verdad rindes en un día
normal, no lo que te gustaría rendir.

**El siguiente paso tiene que ser concreto.** «Avanzar T2» no sirve: no se sabe
por dónde empezar ni cuándo está hecho. La app avisa cuando el paso es muy
general y pide uno nuevo cada vez que marcas uno como hecho.

**Fechas.** Acepta `15-10`, `15/10 18:00`, `15-10-2026 9h30`, `2026-10-15`,
`hoy`, `mañana 14:00`, `viernes`, `el lunes 8h30`, `en 3 días`, `en 2 semanas`.
Sin hora vence a las 23:59; sin año, toma la próxima vez que llega esa fecha.

**Estimaciones.** Súmale un tercio a lo que creas. Casi todo toma más.

## foco

Antes de cada bloque escribes qué vas a hacer, y al final dices si lo hiciste:
*Lo terminé*, *Avancé* o *No avancé*. Sin intención escrita el bloque no
arranca: «estudiar» no se puede cumplir ni fallar, y al final no sabrás si lo
hiciste.

- **Solo 5 minutos.** Para cuando no logras empezar. Lo difícil es arrancar:
  al cumplirse los 5 minutos, la app pregunta si sigues hasta completar el
  bloque, y casi siempre la respuesta es sí.
- **Para después.** Si a mitad del bloque se te ocurre otra cosa (responder un
  mensaje, buscar algo), la anotas en una línea y sigues. La lista aparece en
  el descanso, no antes.
- **Descansos** automáticos: corto después de cada bloque y largo cada 4. Los
  tiempos se cambian en *Tiempos…*.
- **Mini**: una ventana chica, siempre encima, con el reloj y la intención.
  Doble clic en el reloj también la activa.
- **Racha**: días seguidos con al menos un bloque de 5 minutos o más que no
  abandonaste. Hoy no la corta mientras no termine el día.
- Si el PC se suspende a mitad de un bloque, se anotan como mucho los minutos
  del bloque, no las horas que estuvo dormido.

Si **plazos** está en la carpeta de al lado, sus siguientes pasos aparecen en
el desplegable de intención, la entrega más próxima primero.

## bloqueo

Bloquea **sitios** en el archivo hosts del sistema y **cierra apps** de tu lista
cada vez que se abren, por 25, 50, 90 o 120 minutos, o hasta una hora (máximo
12 h: un error de tipeo no debería dejarte sin internet hasta mañana).

**Necesita permisos de administrador** porque el archivo hosts es del sistema.
En Windows la app los pide sola al abrir (y el acceso directo de `--accesos` ya
abre como administrador). En Linux, el lanzador `bloqueo.sh` los pide con
`pkexec`; si no, `sudo -E python3 bloqueo.py`.

**Qué le hace al archivo hosts.** Agrega al final una sección entre dos marcas:

```
# >>> bloqueo-anti-procrastinacion desde=2026-10-09T15:00:00 hasta=2026-10-09T15:50:00 nl=0 >>>
# Bloqueo temporal de bloqueo.py: se quita solo al vencer. Para salir antes, usa la app.
0.0.0.0 instagram.com
:: instagram.com
...
# <<< bloqueo-anti-procrastinacion <<<
```

Al terminar, quita esa sección y el archivo queda **idéntico, byte a byte**, a
como estaba: mismos saltos de línea, misma codificación, aunque no terminara en
salto de línea. Lo que hayas escrito en hosts antes o después no se toca. Antes
del primer bloqueo guarda una copia en `bloqueo_hosts_respaldo.txt`.

- Cada sitio se bloquea con `www.` y `m.` delante, y por IPv4 y por IPv6. El
  archivo hosts no acepta comodines: los subdominios que importan de los sitios
  conocidos (x.com/twitter.com, old.reddit.com, youtu.be…) van incluidos; otros
  hay que agregarlos a mano.
- Los navegadores guardan las direcciones un rato en caché: si un sitio sigue
  abriendo justo después de bloquear, cierra el navegador y vuelve a abrirlo.
  Un navegador con «DNS seguro» en modo estricto puede saltarse el archivo hosts.
- Las apps se buscan cada 5 segundos y se cierran por su número de proceso.
  Nunca cierra procesos del sistema (explorer, svchost…) ni a Python.

**Salir antes** se puede, pero a propósito incómodo: hay que escribir a mano (no
se puede pegar) *«Prefiero distraerme ahora aunque después me pese»* y esperar
30 segundos, que es tiempo para arrepentirse. Queda anotado en el registro.

**Si cierras la app con un bloqueo activo**, los sitios siguen bloqueados y las
apps ya no se cierran. El bloqueo se quita la próxima vez que abras la app
después de la hora de término, o con `python bloqueo.py --limpiar`, que solo
quita bloqueos vencidos. `--estado` dice si hay uno y hasta cuándo.

**Si algo sale mal** y quieres sacar el bloqueo a mano: abre el archivo hosts
como administrador (`C:\Windows\System32\drivers\etc\hosts`, o `/etc/hosts`) y
borra desde la línea `# >>> bloqueo-anti-procrastinacion` hasta
`# <<< bloqueo-anti-procrastinacion <<<`, ambas incluidas.

---

## Pruebas

Cada app trae dos:

- `--selftest` prueba la lógica sin abrir ventanas: fechas, cálculos, lectura
  y escritura de archivos, y en bloqueo la ida y vuelta exacta del hosts sobre
  ocho tipos de archivo distintos, y que de verdad encuentra y cierra un
  proceso del sistema.
- `--guitest` abre la ventana y la recorre como una persona, rellenando los
  diálogos y apretando los botones, con los minutos acelerados a milisegundos
  y datos temporales. bloqueo usa un hosts de prueba, nunca el real.

GitHub Actions corre las dos en Windows y en Linux, con Python 3.9 y 3.13, y en
Windows además crea los accesos directos y revisa que el de bloqueo abra como
administrador.

**Lo que las pruebas no cubren** es si un navegador concreto respeta el archivo
hosts; eso se ve usándolo. Igual que en doc2tts, los defectos que importan
aparecen con el uso real: si un número no calza (minutos de foco que no
corresponden con lo que trabajaste, un «hoy necesitas» absurdo), abre el CSV o
el JSON y compáralo antes de suponer que estás haciendo algo mal.
