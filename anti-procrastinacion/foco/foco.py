"""foco — bloques de trabajo con intención escrita, y un arranque de 5 minutos.

Antes de cada bloque escribes qué vas a hacer; al terminar, dices si lo
hiciste. Si no logras empezar, «Solo 5 minutos» baja la barrera: al cumplirse,
decides si sigues. Lo que se te cruce durante el bloque se anota para después
en vez de atenderlo.

Uso:
    python foco.py              # interfaz gráfica
    python foco.py --accesos    # crea los lanzadores de doble clic
    python foco.py --selftest   # prueba toda la lógica interna, sin GUI
    python foco.py --guitest    # recorre la interfaz completa en segundos y la cierra

Si la aplicación no arranca, el detalle queda en foco_error.log,
junto a este archivo.
"""

from __future__ import annotations

import base64
import csv
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import traceback
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

APP_NAME = "foco"
APP_VERSION = "1.0"
APP_COMMENT = "Bloques de trabajo con intencion y arranque de 5 minutos"
IS_WINDOWS = os.name == "nt"
NO_WINDOW = 0x08000000 if IS_WINDOWS else 0  # CREATE_NO_WINDOW: sin consola al usar pythonw


# =====================================================================
# 1. Rutas de datos y log (defensivo: si la carpeta de la app no se
#    puede escribir, cae a la carpeta del usuario)
# =====================================================================

def _app_dir() -> Path:
    try:
        return Path(__file__).resolve().parent
    except NameError:
        return Path.cwd()


def _writable_dir() -> Path:
    d = _app_dir()
    try:
        probe = d / f".{APP_NAME}_write_test"
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
        return d
    except Exception:
        alt = Path.home() / f".{APP_NAME}"
        try:
            alt.mkdir(parents=True, exist_ok=True)
            return alt
        except Exception:
            return Path(tempfile.gettempdir())


APP_DIR = _app_dir()
DATA_DIR = _writable_dir()
CONFIG_PATH = DATA_DIR / f"{APP_NAME}_config.json"
REGISTRO_PATH = DATA_DIR / f"{APP_NAME}_registro.csv"
PENDIENTES_PATH = DATA_DIR / f"{APP_NAME}_para_despues.txt"
ERROR_LOG_PATH = DATA_DIR / f"{APP_NAME}_error.log"
# Si plazos está al lado (o en su carpeta de usuario), sus «siguiente paso» se ofrecen como intención.
PLAZOS_PATHS = [APP_DIR.parent / "plazos" / "plazos_datos.json", Path.home() / ".plazos" / "plazos_datos.json"]


def write_error_log(header: str, exc_text: str) -> Path:
    """Escribe un traceback al log junto a la app. Nunca lanza excepciones."""
    try:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(ERROR_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write("\n" + "=" * 70 + "\n")
            fh.write(f"{stamp}  {APP_NAME} {APP_VERSION}  Python {sys.version.split()[0]}"
                     f"  {sys.platform}\n{header}\n{exc_text}\n")
    except Exception:
        pass
    return ERROR_LOG_PATH


# =====================================================================
# 2. Temporizador: cuenta contra el reloj monótono, no contando tics,
#    así no se atrasa si la ventana se congela un momento
# =====================================================================

class Temporizador:
    def __init__(self, reloj: Callable[[], float] = time.monotonic):
        self._reloj = reloj
        self.duracion = 0.0
        self._inicio: float | None = None
        self._acumulado = 0.0

    def iniciar(self, segundos: float) -> None:
        self.duracion = float(segundos)
        self._acumulado = 0.0
        self._inicio = self._reloj()

    @property
    def corriendo(self) -> bool:
        return self._inicio is not None

    def pausar(self) -> None:
        if self._inicio is not None:
            # Acotado a la duración: si el fin se nota tarde (PC suspendido), ese tiempo
            # no cuenta; si no, «Seguir» tras el arranque terminaría el bloque al instante.
            self._acumulado = min(self._acumulado + self._reloj() - self._inicio, self.duracion)
            self._inicio = None

    def reanudar(self) -> None:
        if self._inicio is None and self.duracion > 0:
            self._inicio = self._reloj()

    def extender(self, segundos: float) -> None:
        self.duracion += segundos

    def transcurrido(self) -> float:
        extra = self._reloj() - self._inicio if self._inicio is not None else 0.0
        return self._acumulado + extra

    def restante(self) -> float:
        return max(0.0, self.duracion - self.transcurrido())

    def terminado(self) -> bool:
        return self.duracion > 0 and self.transcurrido() >= self.duracion


def formato_mmss(segundos: float) -> str:
    s = int(segundos + 0.999)  # 24:59.2 se muestra 25:00: nunca marca 00:00 antes de tiempo
    m, s = divmod(s, 60)
    if m >= 60:
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def siguiente_descanso(bloques_completados: int, cada: int) -> str:
    return "descanso_largo" if bloques_completados > 0 and bloques_completados % max(1, cada) == 0 \
        else "descanso"


# =====================================================================
# 3. Intención: tiene que ser algo que se pueda terminar o avanzar
# =====================================================================

VERBOS_VAGOS = {"avanzar", "trabajar", "hacer", "estudiar", "ver", "revisar", "terminar",
                "seguir", "empezar", "continuar", "repasar", "preparar", "ponerse"}


def sin_tildes(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def intencion_vaga(texto: str) -> str | None:
    """Consejo si la intención es demasiado general; None si está bien."""
    palabras = re.findall(r"\w+", sin_tildes(texto.lower()))
    if not palabras:
        return None
    if len(palabras) < 3 or (palabras[0] in VERBOS_VAGOS and len(palabras) <= 3):
        return "Muy general: al final no sabrás si lo cumpliste. Ej.: «resolver los ejercicios 1 a 3 de la guía»."
    return None


# =====================================================================
# 4. Registro (CSV con «;», que es lo que Excel en español abre directo)
# =====================================================================

CAMPOS = ["inicio", "fin", "tipo", "minutos_planeados", "minutos_reales", "intencion",
          "resultado", "distracciones"]
RESULTADOS = {"terminado": "Lo terminé", "avance": "Avancé", "sin_avance": "No avancé",
              "abandonado": "Abandonado"}


def anotar_bloque(path: Path, fila: dict) -> None:
    nuevo = not path.exists() or path.stat().st_size == 0
    # BOM solo al crear: así Excel detecta UTF-8; al agregar filas no se repite.
    with open(path, "a", encoding="utf-8-sig" if nuevo else "utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CAMPOS, delimiter=";", extrasaction="ignore")
        if nuevo:
            w.writeheader()
        w.writerow({k: fila.get(k, "") for k in CAMPOS})


def leer_registro(path: Path) -> list[dict]:
    """Filas válidas del registro, con tipos ya convertidos. Nunca lanza."""
    filas: list[dict] = []
    try:
        with open(path, encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh, delimiter=";"):
                try:
                    filas.append({
                        "inicio": datetime.fromisoformat(r["inicio"]),
                        "fin": datetime.fromisoformat(r["fin"]),
                        "tipo": r["tipo"],
                        "minutos_planeados": int(r["minutos_planeados"]),
                        "minutos_reales": int(r["minutos_reales"]),
                        "intencion": r.get("intencion") or "",
                        "resultado": r["resultado"],
                        "distracciones": int(r.get("distracciones") or 0),
                    })
                except Exception:
                    continue
    except FileNotFoundError:
        pass
    except Exception:
        write_error_log(f"No se pudo leer {path}", traceback.format_exc())
    return filas


def bloque_valido(fila: dict) -> bool:
    return fila["resultado"] != "abandonado" and fila["minutos_reales"] >= 5


def estadisticas(filas: list[dict], hoy: date) -> dict:
    minutos: dict[date, int] = {}
    validos: set[date] = set()
    bloques_hoy = distracciones_hoy = 0
    resultados_semana = {k: 0 for k in RESULTADOS}
    for f in filas:
        d = f["inicio"].date()  # un bloque que cruza medianoche cuenta para el día en que empezó
        minutos[d] = minutos.get(d, 0) + f["minutos_reales"]
        if bloque_valido(f):
            validos.add(d)
        if d == hoy:
            bloques_hoy += 1 if bloque_valido(f) else 0
            distracciones_hoy += f["distracciones"]
        if hoy - timedelta(days=6) <= d <= hoy and f["resultado"] in resultados_semana:
            resultados_semana[f["resultado"]] += 1
    # La racha sigue viva durante el día de hoy aunque todavía no hayas hecho un bloque.
    racha = 0
    dia = hoy if hoy in validos else hoy - timedelta(days=1)
    while dia in validos:
        racha += 1
        dia -= timedelta(days=1)
    ultimos7 = [(hoy - timedelta(days=i), minutos.get(hoy - timedelta(days=i), 0)) for i in range(6, -1, -1)]
    return {"minutos_hoy": minutos.get(hoy, 0), "bloques_hoy": bloques_hoy, "racha": racha,
            "ultimos7": ultimos7, "distracciones_hoy": distracciones_hoy,
            "resultados_semana": resultados_semana}


def texto_estadisticas(e: dict) -> str:
    partes = [f"Hoy: {formato_minutos(e['minutos_hoy'])} en {e['bloques_hoy']} bloque(s)"]
    if e["racha"]:
        partes.append(f"racha: {e['racha']} día(s)")
    if e["distracciones_hoy"]:
        partes.append(f"anotaste {e['distracciones_hoy']} distracción(es)")
    return "  ·  ".join(partes)


def formato_minutos(m: int) -> str:
    if m < 60:
        return f"{m} min"
    h, m = divmod(m, 60)
    return f"{h} h {m} min" if m else f"{h} h"


# ---------- lista «para después» ----------

def anotar_pendiente(path: Path, texto: str, ahora: datetime) -> None:
    texto = " ".join(texto.split())
    if texto:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{ahora:%Y-%m-%d %H:%M}  {texto}\n")


def leer_pendientes(path: Path) -> list[str]:
    try:
        return [ln.rstrip("\n") for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except FileNotFoundError:
        return []
    except Exception:
        return []


def guardar_pendientes(path: Path, lineas: list[str]) -> None:
    path.write_text("".join(ln + "\n" for ln in lineas), encoding="utf-8")


# ---------- sugerencias desde plazos ----------

def sugerencias_plazos(rutas: list[Path]) -> list[str]:
    """«siguiente paso — entrega» de las entregas abiertas de plazos, la más próxima primero."""
    for ruta in rutas:
        try:
            data = json.loads(Path(ruta).read_text(encoding="utf-8"))
        except Exception:
            continue
        abiertas = []
        for t in data.get("tareas", []) if isinstance(data, dict) else []:
            try:
                if t.get("entregada") or not str(t.get("siguiente_paso", "")).strip():
                    continue
                abiertas.append((datetime.fromisoformat(t["entrega"]),
                                 f"{t['siguiente_paso'].strip()} — {t['nombre']}"))
            except Exception:
                continue
        return [s for _, s in sorted(abiertas)]
    return []


# =====================================================================
# 5. Lanzadores de doble clic
# =====================================================================

def _interpretes() -> tuple[Path | None, Path | None]:
    """(python, pythonw) con que se está corriendo ahora: es el que seguro funciona."""
    exe = Path(sys.executable) if sys.executable else None
    exe_w = exe.with_name("pythonw.exe") if (exe and IS_WINDOWS) else exe
    if exe_w and not exe_w.exists():
        exe_w = exe
    return exe, exe_w


def textos_lanzadores(folder: Path, app: Path, exe_w: Path | None) -> dict[str, str]:
    bat = (
        "@echo off\r\n"
        f"rem Lanzador de {APP_NAME}: doble clic para abrir la aplicacion.\r\n"
        "setlocal\r\n"
        'cd /d "%~dp0"\r\n'
        f'set "APP=%~dp0{app.name}"\r\n'
        + (f'set "PYW={exe_w}"\r\n'
           'if exist "%PYW%" ( start "" "%PYW%" "%APP%" & exit /b )\r\n' if exe_w else "")
        + 'where pythonw.exe >nul 2>nul && ( start "" pythonw.exe "%APP%" & exit /b )\r\n'
          'where pyw.exe >nul 2>nul && ( start "" pyw.exe "%APP%" & exit /b )\r\n'
          'where python.exe >nul 2>nul && ( start "" python.exe "%APP%" & exit /b )\r\n'
          "echo No se encontro Python en este equipo.\r\n"
          "echo Instalalo desde https://www.python.org/downloads/ marcando\r\n"
          'echo "Add python.exe to PATH" y vuelve a intentarlo.\r\n'
          "pause\r\n"
    )
    sh = ("#!/bin/sh\n"
          f"# Lanzador de {APP_NAME}: doble clic (o ./{APP_NAME}.sh) para abrir la aplicacion.\n"
          'cd "$(dirname "$0")" || exit 1\n'
          f'exec python3 "{app.name}" "$@"\n')
    desktop = ("[Desktop Entry]\n"
               "Type=Application\n"
               f"Name={APP_NAME}\n"
               f"Comment={APP_COMMENT}\n"
               f"Exec=\"{folder / (APP_NAME + '.sh')}\"\n"
               f"Path={folder}\n"
               "Icon=appointment-soon\n"
               "Terminal=false\n"
               "Categories=Utility;\n")
    return {f"{APP_NAME}.bat": bat, f"{APP_NAME}.sh": sh, f"{APP_NAME}.desktop": desktop}


def _desktop_dir_windows() -> Path | None:
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(1024)
        # CSIDL_DESKTOPDIRECTORY = 0x10; respeta Escritorio movido a OneDrive
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0 and buf.value:
            return Path(buf.value)
    except Exception:
        pass
    return None


def _ps_quote(s: object) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def _desktop_shortcut_windows(app: Path, exe_w: Path | None) -> Path | None:
    desk = _desktop_dir_windows()
    if not desk or not desk.is_dir():
        return None
    link = desk / f"{APP_NAME}.lnk"
    ps = ("$ErrorActionPreference='Stop';"
          f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut({_ps_quote(link)});"
          f"$s.TargetPath={_ps_quote(exe_w or 'pythonw.exe')};"
          f"$s.Arguments={_ps_quote(chr(34) + str(app) + chr(34))};"
          f"$s.WorkingDirectory={_ps_quote(app.parent)};"
          f"$s.Description={_ps_quote(APP_COMMENT)};"
          "$s.Save()")
    enc = base64.b64encode(ps.encode("utf-16-le")).decode("ascii")
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                        "-EncodedCommand", enc], capture_output=True, timeout=60,
                       creationflags=NO_WINDOW)
    except Exception:
        return None
    return link if link.exists() else None


def create_launchers(folder: Path | None = None, desktop: bool = True) -> tuple[list[Path], list[str]]:
    """Windows: .bat (arranca con pythonw, sin consola) + acceso directo en el
    Escritorio. Linux: .sh + .desktop. Devuelve (creados, problemas)."""
    app = Path(__file__).resolve()
    folder = Path(folder) if folder else app.parent
    _, exe_w = _interpretes()
    created: list[Path] = []
    problems: list[str] = []
    for name, text in textos_lanzadores(folder, app, exe_w).items():
        path = folder / name
        try:
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(text if name.endswith(".bat") else text.replace("\r\n", "\n"))
            if not IS_WINDOWS and not name.endswith(".bat"):
                os.chmod(path, 0o755)
            created.append(path)
        except Exception as exc:
            problems.append(f"no se pudo escribir {path}: {exc}")
    if desktop and IS_WINDOWS:
        link = _desktop_shortcut_windows(app, exe_w)
        if link:
            created.append(link)
        else:
            problems.append(f"no se pudo crear el acceso directo en el Escritorio "
                            f"(usa igual el {APP_NAME}.bat de esta carpeta)")
    return created, problems


# =====================================================================
# 6. Configuración
# =====================================================================

DEFAULT_CONFIG = {"foco_min": 25, "descanso_min": 5, "descanso_largo_min": 15,
                  "bloques_hasta_largo": 4, "arranque_min": 5, "siempre_visible": False,
                  "sonido": True, "geometria": ""}
RANGOS = {"foco_min": (5, 180), "descanso_min": (1, 60), "descanso_largo_min": (1, 90),
          "bloques_hasta_largo": (2, 8), "arranque_min": (1, 15)}


def load_config(path: Path = CONFIG_PATH) -> dict:
    data = dict(DEFAULT_CONFIG)
    try:
        if path.exists():
            saved = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                for k, v in saved.items():
                    if k in DEFAULT_CONFIG and type(v) is type(DEFAULT_CONFIG[k]):
                        data[k] = v
    except Exception:
        pass
    for k, (lo, hi) in RANGOS.items():
        if not lo <= data[k] <= hi:
            data[k] = DEFAULT_CONFIG[k]
    if data["arranque_min"] >= data["foco_min"]:
        data["arranque_min"] = min(DEFAULT_CONFIG["arranque_min"], data["foco_min"] - 1)
    return data


def save_config(data: dict, path: Path = CONFIG_PATH) -> None:
    try:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


# =====================================================================
# 7. Autoprueba (--selftest)
# =====================================================================

def run_selftest() -> int:
    checks: list[tuple[bool, str]] = []

    def check(cond: bool, label: str) -> None:
        checks.append((bool(cond), label))

    # --- temporizador con reloj falso ---
    t_falso = [1000.0]
    tm = Temporizador(reloj=lambda: t_falso[0])
    check(not tm.corriendo and not tm.terminado() and tm.restante() == 0, "temporizador nuevo: quieto")
    tm.iniciar(25 * 60)
    t_falso[0] += 600
    check(tm.restante() == 900 and tm.corriendo, "a los 10 min quedan 15")
    tm.pausar()
    t_falso[0] += 3600
    check(tm.restante() == 900 and not tm.corriendo, "en pausa no corre aunque pase una hora")
    tm.pausar()
    check(tm.restante() == 900, "pausar dos veces no descuenta nada")
    tm.reanudar()
    t_falso[0] += 899
    check(not tm.terminado() and tm.restante() == 1, "a 1 s del final no termina")
    t_falso[0] += 1
    check(tm.terminado() and tm.restante() == 0, "termina justo a los 25 min corridos")
    t_falso[0] += 50
    check(tm.restante() == 0 and tm.transcurrido() == 1550, "después de terminar el restante no es negativo")
    tm.extender(20 * 60)
    check(not tm.terminado() and tm.restante() == 1150, "extender convierte el arranque en bloque largo")
    tm.reanudar()
    check(tm.transcurrido() == 1550, "reanudar corriendo no reinicia")
    tm.iniciar(5 * 60)
    t_falso[0] += 3 * 3600  # el PC estuvo suspendido 3 horas durante el arranque
    tm.pausar()
    check(tm.transcurrido() == 300, "al pausar tarde, no se cuenta más que la duración")
    tm.extender(20 * 60)
    tm.reanudar()
    check(not tm.terminado() and tm.restante() == 1200, "«Seguir» tras una suspensión da los 20 min completos")

    check(formato_mmss(25 * 60) == "25:00", "formato 25:00")
    check(formato_mmss(1499.2) == "25:00", "24:59,2 se muestra 25:00")
    check(formato_mmss(0) == "00:00" and formato_mmss(0.4) == "00:01", "no marca 00:00 antes de tiempo")
    check(formato_mmss(3725) == "1:02:05", "formato con horas")
    check([siguiente_descanso(n, 4) for n in (1, 2, 3, 4, 5, 8)] ==
          ["descanso", "descanso", "descanso", "descanso_largo", "descanso", "descanso_largo"],
          "descanso largo cada 4 bloques")
    check(siguiente_descanso(0, 4) == "descanso", "sin bloques: descanso corto")

    check(intencion_vaga("estudiar") and intencion_vaga("avanzar informe T2"), "intenciones vagas")
    check(intencion_vaga("resolver ejercicios 1 a 3 de la guía") is None, "intención concreta")
    check(intencion_vaga("") is None, "intención vacía no se juzga aquí (la bloquea la interfaz)")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        reg = tmp / "registro.csv"
        hoy = date(2026, 10, 9)

        def fila(dia: date, hora: int, minutos: int, resultado: str, tipo="foco", dist=0, intencion="x"):
            ini = datetime(dia.year, dia.month, dia.day, hora, 0)
            return {"inicio": ini.isoformat(timespec="seconds"),
                    "fin": (ini + timedelta(minutes=minutos)).isoformat(timespec="seconds"),
                    "tipo": tipo, "minutos_planeados": 25, "minutos_reales": minutos,
                    "intencion": intencion, "resultado": resultado, "distracciones": dist}

        filas_in = [
            fila(hoy, 9, 25, "terminado", intencion='informe; sección "2", con comas,\ny salto'),
            fila(hoy, 10, 25, "avance", dist=2, intencion="ñandú ü áéí"),
            fila(hoy, 11, 3, "abandonado"),
            fila(hoy - timedelta(days=1), 23, 25, "sin_avance"),       # cruza medianoche: cuenta ayer
            fila(hoy - timedelta(days=2), 18, 5, "avance", tipo="arranque"),
            fila(hoy - timedelta(days=4), 18, 25, "terminado"),          # hueco en el día -3: corta racha
            fila(hoy - timedelta(days=9), 18, 25, "terminado"),          # fuera de la semana
        ]
        for f in filas_in:
            anotar_bloque(reg, f)
        crudo = reg.read_bytes()
        check(crudo.startswith(b"\xef\xbb\xbf") and crudo.count(b"\xef\xbb\xbf") == 1,
              "el CSV lleva un solo BOM, al inicio")
        check(crudo.splitlines()[0].decode("utf-8-sig").startswith("inicio;fin;tipo"), "separador «;»")
        filas = leer_registro(reg)
        check(len(filas) == 7, f"se leen las 7 filas ({len(filas)})")
        check(filas[0]["intencion"] == 'informe; sección "2", con comas,\ny salto',
              "intención con ; comillas y salto de línea sobrevive ida y vuelta")
        check(filas[1]["intencion"] == "ñandú ü áéí", "tildes y eñes sobreviven")

        with open(reg, "a", encoding="utf-8", newline="") as fh:
            fh.write("basura;sin;sentido\n2026-10-09T12:00:00;roto\n")
        check(len(leer_registro(reg)) == 7, "filas dañadas se saltan sin romper la lectura")
        check(leer_registro(tmp / "no-existe.csv") == [], "sin registro: lista vacía")

        e = estadisticas(filas, hoy)
        check(e["minutos_hoy"] == 53, f"minutos de hoy incluyen el abandonado ({e['minutos_hoy']})")
        check(e["bloques_hoy"] == 2, "bloques válidos de hoy: 2 (el abandonado no cuenta)")
        check(e["racha"] == 3, f"racha de 3 días: hoy, ayer y anteayer ({e['racha']})")
        check(e["distracciones_hoy"] == 2, "distracciones de hoy")
        check(e["resultados_semana"] == {"terminado": 2, "avance": 2, "sin_avance": 1, "abandonado": 1},
              f"resultados de la semana ({e['resultados_semana']})")
        check([m for _, m in e["ultimos7"]] == [0, 0, 25, 0, 5, 25, 53] and e["ultimos7"][-1][0] == hoy,
              f"barras de los últimos 7 días ({[m for _, m in e['ultimos7']]})")
        e2 = estadisticas(filas, hoy + timedelta(days=1))
        check(e2["racha"] == 3 and e2["minutos_hoy"] == 0, "la racha sigue viva mientras el día no termina")
        e3 = estadisticas(filas, hoy + timedelta(days=2))
        check(e3["racha"] == 0, "un día completo sin bloques corta la racha")
        check("53 min en 2 bloque(s)" in texto_estadisticas(e) and "racha: 3" in texto_estadisticas(e),
              f"texto de estadísticas: {texto_estadisticas(e)}")
        check(formato_minutos(125) == "2 h 5 min" and formato_minutos(60) == "1 h", "formato de minutos")

        pend = tmp / "pendientes.txt"
        anotar_pendiente(pend, "  revisar   correo del profe ", datetime(2026, 10, 9, 15, 20))
        anotar_pendiente(pend, "   ", datetime(2026, 10, 9, 15, 21))
        anotar_pendiente(pend, "comprar café", datetime(2026, 10, 9, 15, 22))
        lineas = leer_pendientes(pend)
        check(lineas == ["2026-10-09 15:20  revisar correo del profe", "2026-10-09 15:22  comprar café"],
              f"lista para después ({lineas})")
        guardar_pendientes(pend, lineas[1:])
        check(leer_pendientes(pend) == ["2026-10-09 15:22  comprar café"], "borrar un pendiente")

        plz = tmp / "plazos_datos.json"
        plz.write_text(json.dumps({"tareas": [
            {"nombre": "T3", "entrega": "2026-10-20T23:59", "siguiente_paso": "leer enunciado"},
            {"nombre": "Informe", "entrega": "2026-10-12T18:00", "siguiente_paso": "escribir intro"},
            {"nombre": "Vieja", "entrega": "2026-10-01T18:00", "siguiente_paso": "x", "entregada": True},
            {"nombre": "Sin paso", "entrega": "2026-10-11T18:00", "siguiente_paso": ""},
            {"nombre": "Rota", "entrega": "mañana", "siguiente_paso": "algo"},
        ]}), encoding="utf-8")
        sug = sugerencias_plazos([tmp / "no-existe.json", plz])
        check(sug == ["escribir intro — Informe", "leer enunciado — T3"],
              f"sugerencias de plazos: abiertas, con paso, por fecha ({sug})")
        check(sugerencias_plazos([tmp / "no-existe.json"]) == [], "sin plazos: sin sugerencias")

        cfg = tmp / "cfg.json"
        cfg.write_text('{"foco_min": 50, "descanso_min": 0, "sonido": "no", "arranque_min": 10, "x": 1}',
                       encoding="utf-8")
        c = load_config(cfg)
        check(c["foco_min"] == 50 and c["descanso_min"] == 5 and c["sonido"] is True
              and c["arranque_min"] == 10 and "x" not in c, f"config validada ({c})")
        cfg.write_text('{"foco_min": 6, "arranque_min": 10}', encoding="utf-8")
        c = load_config(cfg)
        check(c["arranque_min"] < c["foco_min"], f"el arranque nunca es más largo que el bloque ({c})")
        cfg.write_text('{"foco_min": true}', encoding="utf-8")
        check(load_config(cfg)["foco_min"] == 25, "un booleano no pasa por número")

        created, problems = create_launchers(tmp, desktop=False)
        names = {c.name for c in created}
        check(names == {"foco.bat", "foco.sh", "foco.desktop"}, f"lanzadores creados: {sorted(names)}")
        check(not problems, f"lanzadores sin problemas: {problems}")
        bat = (tmp / "foco.bat").read_bytes()
        check(b"\r\n" in bat and b"foco.py" in bat, "el .bat usa CRLF y apunta a foco.py")
        sh = (tmp / "foco.sh").read_bytes()
        check(b"\r\n" not in sh and sh.startswith(b"#!/bin/sh"), "el .sh usa LF y shebang")

    fallidas = [label for ok, label in checks if not ok]
    for label in fallidas:
        print(f"FALLA: {label}")
    print(f"{len(checks) - len(fallidas)}/{len(checks)} comprobaciones correctas.")
    return 0 if not fallidas else 1


# =====================================================================
# 8. Interfaz gráfica (tkinter)
# =====================================================================

NOMBRE_FASE = {"listo": "Listo para empezar", "foco": "Foco", "arranque": "Solo 5 minutos",
               "descanso": "Descanso", "descanso_largo": "Descanso largo"}
COLOR_FASE = {"listo": "#555555", "foco": "#b23a1e", "arranque": "#b26b00",
              "descanso": "#2c7a3f", "descanso_largo": "#1f6a8a"}


def run_gui(smoke_ms: int = 0, dir_datos: Path | None = None, seg_por_min: float = 60.0) -> int:
    """smoke_ms > 0: recorre la interfaz con duraciones aceleradas y se cierra sola.
    seg_por_min < 60 acelera todo (solo para la prueba)."""
    try:
        import tkinter as tk
        from tkinter import messagebox, ttk
        import tkinter.font as tkfont
    except Exception as exc:
        msg = ("No se pudo cargar tkinter, que es parte de la biblioteca estándar de Python.\n"
               "  Windows: reinstala Python desde python.org marcando 'tcl/tk and IDLE'.\n"
               "  Linux (Debian/Ubuntu): sudo apt install python3-tk\n"
               "  Linux (Fedora): sudo dnf install python3-tkinter\n"
               f"Detalle: {exc}")
        print(msg, file=sys.stderr)
        write_error_log("tkinter no disponible", traceback.format_exc())
        return 2

    if IS_WINDOWS:
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    if dir_datos:
        config_path = dir_datos / "cfg.json"
        registro_path = dir_datos / "registro.csv"
        pendientes_path = dir_datos / "para_despues.txt"
        plazos_paths = [dir_datos / "plazos_datos.json"]
    else:
        config_path, registro_path, pendientes_path, plazos_paths = \
            CONFIG_PATH, REGISTRO_PATH, PENDIENTES_PATH, PLAZOS_PATHS
    cfg = load_config(config_path)

    root = tk.Tk()
    root.title(APP_NAME)
    try:
        root.tk.call("tk", "scaling", root.winfo_fpixels("1i") / 72.0)
    except Exception:
        pass
    root.minsize(440, 600)
    root.geometry(cfg["geometria"] if (cfg["geometria"] and not smoke_ms) else "520x700")

    style = ttk.Style(root)
    try:
        if IS_WINDOWS:
            style.theme_use("vista")
        elif "clam" in style.theme_names():
            style.theme_use("clam")
    except Exception:
        pass
    base = tkfont.nametofont("TkDefaultFont")
    tam = int(base.cget("size")) if int(base.cget("size")) > 0 else 10
    f_reloj = base.copy()
    f_reloj.configure(size=max(44, tam * 5), weight="bold")
    f_reloj_mini = base.copy()
    f_reloj_mini.configure(size=max(22, tam * 2 + 4), weight="bold")
    f_fase = base.copy()
    f_fase.configure(size=tam + 3, weight="bold")
    f_intencion = base.copy()
    f_intencion.configure(size=tam + 2)
    fondo = style.lookup("TFrame", "background") or root.cget("bg")

    tm = Temporizador()
    st = {"fase": "listo", "bloque": None, "completados": 0, "mini": False, "intencion": "",
          "ultima": "", "texto_reloj": ""}
    fallas: list[str] = []

    # ---------- cabecera: fase, reloj, barra, intención ----------
    cab = ttk.Frame(root, padding=(16, 14, 16, 0))
    cab.pack(fill="x")
    lbl_fase = tk.Label(cab, text=NOMBRE_FASE["listo"], font=f_fase, fg=COLOR_FASE["listo"], bg=fondo)
    lbl_fase.pack()
    lbl_reloj = tk.Label(cab, text=formato_mmss(cfg["foco_min"] * 60), font=f_reloj, fg="#222", bg=fondo)
    lbl_reloj.pack()
    barra = ttk.Progressbar(cab, maximum=1000, mode="determinate")
    barra.pack(fill="x", pady=(2, 8))
    lbl_intencion = tk.Label(cab, text="", font=f_intencion, wraplength=460, justify="center", bg=fondo)
    lbl_intencion.pack()

    cuerpo = ttk.Frame(root, padding=(16, 8, 16, 0))
    cuerpo.pack(fill="both", expand=True)

    # ---------- panel: listo ----------
    p_listo = ttk.Frame(cuerpo)
    ttk.Label(p_listo, text="¿Qué vas a hacer en este bloque?").pack(anchor="w")
    var_int = tk.StringVar()
    combo = ttk.Combobox(p_listo, textvariable=var_int)
    combo.pack(fill="x", pady=(2, 0))
    lbl_pista = ttk.Label(p_listo, foreground="#8a5300", wraplength=470, justify="left")
    lbl_pista.pack(anchor="w", pady=(2, 6))
    fila_btn = ttk.Frame(p_listo)
    fila_btn.pack(fill="x")
    b_empezar = ttk.Button(fila_btn, command=lambda: empezar("foco"))
    b_empezar.pack(side="left")
    b_arranque = ttk.Button(fila_btn, command=lambda: empezar("arranque"))
    b_arranque.pack(side="left", padx=(8, 0))

    def pista(*_):
        txt = var_int.get()
        lbl_pista.configure(text=intencion_vaga(txt) or "", foreground="#8a5300")
    var_int.trace_add("write", pista)
    combo.bind("<Return>", lambda e: empezar("foco"))

    # ---------- panel: corriendo ----------
    p_corre = ttk.Frame(cuerpo)
    fila_c = ttk.Frame(p_corre)
    fila_c.pack(fill="x")
    b_pausa = ttk.Button(fila_c, text="Pausar", command=lambda: alternar_pausa())
    b_pausa.pack(side="left")
    b_antes = ttk.Button(fila_c, text="Terminé antes", command=lambda: terminar_foco(antes=True))
    b_antes.pack(side="left", padx=(8, 0))
    b_aband = ttk.Button(fila_c, text="Abandonar", command=lambda: abandonar())
    b_aband.pack(side="left", padx=(8, 0))
    ttk.Label(p_corre, text="¿Se te cruzó otra cosa? Anótala para después y sigue:").pack(anchor="w", pady=(14, 2))
    var_dist = tk.StringVar()
    e_dist = ttk.Entry(p_corre, textvariable=var_dist)
    e_dist.pack(fill="x")
    lbl_dist = ttk.Label(p_corre, foreground="#666")
    lbl_dist.pack(anchor="w", pady=(2, 0))

    def anotar_distraccion(*_):
        txt = var_dist.get().strip()
        if not txt or not st["bloque"]:
            return
        anotar_pendiente(pendientes_path, txt, datetime.now())
        st["bloque"]["distracciones"] += 1
        var_dist.set("")
        n = st["bloque"]["distracciones"]
        lbl_dist.configure(text=f"Anotado. Van {n} en este bloque; quedan en la lista para el descanso.")
    e_dist.bind("<Return>", anotar_distraccion)

    # ---------- panel: resultado ----------
    p_res = ttk.Frame(cuerpo)
    lbl_preg = ttk.Label(p_res, wraplength=470, justify="left")
    lbl_preg.pack(anchor="w", pady=(0, 6))
    fila_r = ttk.Frame(p_res)
    fila_r.pack(fill="x")
    for clave in ("terminado", "avance", "sin_avance"):
        ttk.Button(fila_r, text=RESULTADOS[clave],
                   command=lambda c=clave: cerrar_bloque(c)).pack(side="left", padx=(0, 8))

    # ---------- panel: fin del arranque ----------
    p_arr = ttk.Frame(cuerpo)
    lbl_arr = ttk.Label(p_arr, wraplength=470, justify="left")
    lbl_arr.pack(anchor="w", pady=(0, 6))
    fila_a = ttk.Frame(p_arr)
    fila_a.pack(fill="x")
    b_seguir = ttk.Button(fila_a, command=lambda: seguir_tras_arranque())
    b_seguir.pack(side="left")
    ttk.Button(fila_a, text="Parar aquí", command=lambda: terminar_foco(antes=True)).pack(side="left", padx=(8, 0))

    # ---------- panel: descanso ----------
    p_desc = ttk.Frame(cuerpo)
    lbl_desc = ttk.Label(p_desc, wraplength=470, justify="left",
                         text="Levántate, toma agua, mira lejos. Nada de pantallas que enganchen.")
    lbl_desc.pack(anchor="w")
    ttk.Button(p_desc, text="Saltar descanso", command=lambda: ir_a_listo("Descanso saltado.")).pack(
        anchor="w", pady=(6, 0))

    # ---------- lista para después (visible fuera del foco) ----------
    p_pend = ttk.LabelFrame(cuerpo, text="Para después", padding=(8, 4))
    lista = tk.Listbox(p_pend, height=4, activestyle="none")
    lista.pack(fill="both", expand=True)
    fila_p = ttk.Frame(p_pend)
    fila_p.pack(fill="x", pady=(4, 0))
    ttk.Button(fila_p, text="Borrar marcado", command=lambda: borrar_pendiente()).pack(side="left")
    ttk.Button(fila_p, text="Vaciar", command=lambda: vaciar_pendientes()).pack(side="left", padx=(6, 0))

    def cargar_pendientes():
        lista.delete(0, "end")
        for ln in leer_pendientes(pendientes_path):
            lista.insert("end", ln)

    def borrar_pendiente():
        sel = lista.curselection()
        if sel:
            lineas = leer_pendientes(pendientes_path)
            if sel[0] < len(lineas):
                del lineas[sel[0]]
                guardar_pendientes(pendientes_path, lineas)
            cargar_pendientes()

    def vaciar_pendientes():
        if lista.size() and (smoke_ms or messagebox.askyesno(APP_NAME, "¿Vaciar la lista para después?",
                                                              parent=root)):
            guardar_pendientes(pendientes_path, [])
            cargar_pendientes()

    # ---------- pie: estadísticas ----------
    pie = ttk.Frame(root, padding=(16, 6, 16, 12))
    pie.pack(fill="x", side="bottom", before=cuerpo)  # antes que el cuerpo: si achicas, no se corta
    lbl_stats = ttk.Label(pie, foreground="#333")
    lbl_stats.pack(anchor="w")
    canvas = tk.Canvas(pie, height=100, highlightthickness=0, bg=fondo)
    canvas.pack(fill="x", pady=(4, 4))
    fila_pie = ttk.Frame(pie)
    fila_pie.pack(fill="x")
    b_mini = ttk.Button(fila_pie, text="Mini", command=lambda: alternar_mini())
    b_mini.pack(side="left")
    var_top = tk.BooleanVar(value=cfg["siempre_visible"])
    ttk.Checkbutton(fila_pie, text="Siempre visible", variable=var_top,
                    command=lambda: (cfg.__setitem__("siempre_visible", var_top.get()),
                                     save_config(cfg, config_path), aplicar_topmost())).pack(side="left", padx=(10, 0))
    var_son = tk.BooleanVar(value=cfg["sonido"])
    ttk.Checkbutton(fila_pie, text="Sonido", variable=var_son,
                    command=lambda: (cfg.__setitem__("sonido", var_son.get()),
                                     save_config(cfg, config_path))).pack(side="left", padx=(10, 0))
    ttk.Button(fila_pie, text="Tiempos…", command=lambda: configurar()).pack(side="right")

    DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]

    def dibujar_stats():
        e = estadisticas(leer_registro(registro_path), date.today())
        lbl_stats.configure(text=texto_estadisticas(e))
        canvas.delete("all")
        root.update_idletasks()
        w = max(canvas.winfo_width(), 300)
        h = int(canvas.cget("height"))
        maximo = max(60, max(m for _, m in e["ultimos7"]))
        ancho = w / 7
        for i, (d, m) in enumerate(e["ultimos7"]):
            x0 = i * ancho + ancho * 0.22
            x1 = (i + 1) * ancho - ancho * 0.22
            alto = (h - 44) * m / maximo  # deja aire arriba para el número de la barra más alta
            color = "#b23a1e" if d == date.today() else "#d9a28f"
            if m:
                canvas.create_rectangle(x0, h - 18 - alto, x1, h - 18, fill=color, outline="")
                canvas.create_text((x0 + x1) / 2, h - 22 - alto, text=str(m), anchor="s",
                                   fill="#333", font=base)
            canvas.create_text((x0 + x1) / 2, h - 2, text=DIAS[d.weekday()], anchor="s",
                               fill="#000" if d == date.today() else "#777", font=base)

    # ---------- transiciones ----------
    def mostrar_panel(panel):
        for p in (p_listo, p_corre, p_res, p_arr, p_desc, p_pend):
            p.pack_forget()
        if st["mini"]:
            return
        panel.pack(fill="x")
        if panel in (p_listo, p_desc):
            cargar_pendientes()
            if lista.size():
                p_pend.pack(fill="both", expand=True, pady=(14, 0))

    def poner_fase(fase: str):
        st["fase"] = fase
        lbl_fase.configure(text=NOMBRE_FASE[fase] + (
            f" · bloque {st['completados'] % cfg['bloques_hasta_largo'] + 1} de {cfg['bloques_hasta_largo']}"
            if fase == "foco" else ""), fg=COLOR_FASE[fase])

    def ir_a_listo(mensaje: str = ""):
        tm.pausar()
        tm.duracion = 0
        st["bloque"] = None
        poner_fase("listo")
        lbl_reloj.configure(text=formato_mmss(cfg["foco_min"] * 60))
        barra.configure(value=0)
        lbl_intencion.configure(text=mensaje)
        b_empezar.configure(text=f"Empezar {cfg['foco_min']} min")
        b_arranque.configure(text=f"Solo {cfg['arranque_min']} minutos")
        sugerencias = sugerencias_plazos(plazos_paths)
        if st["ultima"] and st["ultima"] not in sugerencias:
            sugerencias.insert(0, st["ultima"])
        combo.configure(values=sugerencias)
        var_int.set("")
        mostrar_panel(p_listo)
        root.title(APP_NAME)
        dibujar_stats()
        if not st["mini"]:
            combo.focus_set()

    def empezar(tipo: str):
        intencion = " ".join(var_int.get().split())
        if not intencion:
            lbl_pista.configure(text="Escribe qué vas a hacer. Sin eso, al final no sabrás si lo hiciste.",
                                foreground="#a00")
            combo.focus_set()
            return
        minutos = cfg["foco_min"] if tipo == "foco" else cfg["arranque_min"]
        st["intencion"] = st["ultima"] = intencion
        st["bloque"] = {"inicio": datetime.now(), "tipo": tipo, "minutos_planeados": minutos,
                        "intencion": intencion, "distracciones": 0}
        tm.iniciar(minutos * seg_por_min)
        poner_fase(tipo)
        lbl_intencion.configure(text=intencion)
        b_pausa.configure(text="Pausar")
        lbl_dist.configure(text="")
        mostrar_panel(p_corre)
        e_dist.focus_set()

    def alternar_pausa():
        if st["fase"] not in ("foco", "arranque"):
            return
        if tm.corriendo:
            tm.pausar()
            b_pausa.configure(text="Reanudar")
            lbl_fase.configure(text=NOMBRE_FASE[st["fase"]] + " · en pausa")
        else:
            tm.reanudar()
            b_pausa.configure(text="Pausar")
            poner_fase(st["fase"])

    def terminar_foco(antes: bool = False):
        tm.pausar()
        if not antes:
            avisar()
        lbl_preg.configure(text=f"¿Cómo te fue con «{st['intencion']}»?")
        mostrar_panel(p_res)

    def seguir_tras_arranque():
        extra = cfg["foco_min"] - cfg["arranque_min"]
        st["bloque"]["tipo"] = "foco"
        st["bloque"]["minutos_planeados"] = cfg["foco_min"]
        tm.extender(extra * seg_por_min)
        tm.reanudar()
        poner_fase("foco")
        mostrar_panel(p_corre)

    def minutos_reales() -> int:
        # Acotado a la duración: si el PC se suspende a mitad del bloque, no anota horas fantasma.
        return int(round(min(tm.transcurrido(), tm.duracion) / seg_por_min))

    def registrar(resultado: str):
        b = st["bloque"]
        anotar_bloque(registro_path, {
            "inicio": b["inicio"].isoformat(timespec="seconds"),
            "fin": datetime.now().isoformat(timespec="seconds"),
            "tipo": b["tipo"], "minutos_planeados": b["minutos_planeados"],
            "minutos_reales": minutos_reales(), "intencion": b["intencion"],
            "resultado": resultado, "distracciones": b["distracciones"]})

    def cerrar_bloque(resultado: str):
        if not st["bloque"]:
            return
        registrar(resultado)
        st["completados"] += 1
        tipo = siguiente_descanso(st["completados"], cfg["bloques_hasta_largo"])
        minutos = cfg["descanso_largo_min"] if tipo == "descanso_largo" else cfg["descanso_min"]
        st["bloque"] = None
        tm.iniciar(minutos * seg_por_min)
        poner_fase(tipo)
        lbl_intencion.configure(text={"terminado": "Bien hecho.", "avance": "Avanzaste: eso cuenta.",
                                      "sin_avance": "Pasa. Para el próximo, elige algo más chico."}[resultado])
        mostrar_panel(p_desc)
        dibujar_stats()

    def abandonar():
        if not st["bloque"]:
            return
        if minutos_reales() >= 1:
            registrar("abandonado")
        ir_a_listo("Bloque abandonado. Si fue por algo urgente, bien; si no, prueba con «Solo 5 minutos».")

    def aplicar_topmost():
        try:
            root.attributes("-topmost", bool(cfg["siempre_visible"] or st["mini"]))
        except Exception:
            pass

    def avisar():
        if cfg["sonido"]:
            try:
                if IS_WINDOWS:
                    import winsound
                    winsound.MessageBeep(winsound.MB_ICONASTERISK)
                else:
                    root.bell()
            except Exception:
                pass
        try:
            root.deiconify()
            root.lift()
            root.attributes("-topmost", True)
            root.after(1500, aplicar_topmost)
        except Exception:
            pass

    def alternar_mini():
        st["mini"] = not st["mini"]
        if st["mini"]:
            st["geo_normal"] = root.geometry()
            for w in (barra, lbl_fase, cuerpo, pie):
                w.pack_forget()
            lbl_reloj.configure(font=f_reloj_mini)
            lbl_intencion.configure(wraplength=240)
            root.minsize(1, 1)
            root.geometry("270x110")
        else:
            lbl_reloj.configure(font=f_reloj)
            lbl_intencion.configure(wraplength=460)
            lbl_intencion.pack_forget()
            lbl_fase.pack(before=lbl_reloj)
            barra.pack(fill="x", pady=(2, 8))
            lbl_intencion.pack()
            pie.pack(fill="x", side="bottom")
            cuerpo.pack(fill="both", expand=True)
            root.minsize(440, 600)
            root.geometry(st.get("geo_normal") or "520x700")
            panel = {"listo": p_listo, "descanso": p_desc, "descanso_largo": p_desc}.get(st["fase"], p_corre)
            if st["fase"] in ("foco", "arranque") and not tm.corriendo and tm.terminado():
                panel = p_arr if st["bloque"] and st["bloque"]["tipo"] == "arranque" else p_res
            mostrar_panel(panel)
        aplicar_topmost()
    lbl_reloj.bind("<Double-1>", lambda e: alternar_mini())

    def configurar():
        dlg = tk.Toplevel(root)
        dlg.title("Tiempos")
        dlg.transient(root)
        frm = ttk.Frame(dlg, padding=14)
        frm.pack()
        vars_ = {}
        etiquetas = [("foco_min", "Bloque de foco (min)"), ("descanso_min", "Descanso (min)"),
                     ("descanso_largo_min", "Descanso largo (min)"),
                     ("bloques_hasta_largo", "Bloques antes del largo"),
                     ("arranque_min", "Arranque «solo unos minutos» (min)")]
        for i, (k, txt) in enumerate(etiquetas):
            ttk.Label(frm, text=txt).grid(row=i, column=0, sticky="w", pady=3, padx=(0, 10))
            v = tk.StringVar(value=str(cfg[k]))
            lo, hi = RANGOS[k]
            ttk.Spinbox(frm, from_=lo, to=hi, textvariable=v, width=6).grid(row=i, column=1, sticky="w")
            vars_[k] = v
        lbl_e = ttk.Label(frm, foreground="#a00")
        lbl_e.grid(row=len(etiquetas), column=0, columnspan=2, sticky="w")

        def guardar():
            nuevo = dict(cfg)
            for k, v in vars_.items():
                try:
                    nuevo[k] = int(v.get())
                except ValueError:
                    lbl_e.configure(text="Solo números enteros.")
                    return
                lo, hi = RANGOS[k]
                if not lo <= nuevo[k] <= hi:
                    lbl_e.configure(text=f"Fuera de rango ({lo} a {hi}).")
                    return
            if nuevo["arranque_min"] >= nuevo["foco_min"]:
                lbl_e.configure(text="El arranque tiene que ser más corto que el bloque.")
                return
            cfg.update(nuevo)
            save_config(cfg, config_path)
            dlg.destroy()
            if st["fase"] == "listo":
                ir_a_listo()
        fb = ttk.Frame(frm)
        fb.grid(row=len(etiquetas) + 1, column=0, columnspan=2, sticky="e", pady=(8, 0))
        ttk.Button(fb, text="Cancelar", command=dlg.destroy).pack(side="right")
        ttk.Button(fb, text="Guardar", command=guardar).pack(side="right", padx=(0, 6))
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        try:
            dlg.grab_set()
        except Exception:
            pass

    # ---------- tic ----------
    def tic():
        fase = st["fase"]
        if fase in ("foco", "arranque", "descanso", "descanso_largo") and tm.duracion > 0:
            txt = formato_mmss(tm.restante())
            if txt != st["texto_reloj"]:
                st["texto_reloj"] = txt
                lbl_reloj.configure(text=txt)
                root.title(f"{txt} · {NOMBRE_FASE[fase].lower()}")
            barra.configure(value=1000 * min(1.0, tm.transcurrido() / tm.duracion))
            if tm.corriendo and tm.terminado():
                tm.pausar()
                if fase == "foco":
                    terminar_foco()
                elif fase == "arranque":
                    avisar()
                    b_seguir.configure(text=f"Seguir {cfg['foco_min'] - cfg['arranque_min']} min más")
                    lbl_arr.configure(text=f"Pasaron los {cfg['arranque_min']} minutos. Lo difícil era empezar, "
                                           "y ya empezaste. ¿Sigues hasta completar el bloque?")
                    if not st["mini"]:
                        mostrar_panel(p_arr)
                else:
                    avisar()
                    ir_a_listo("Terminó el descanso. ¿Qué sigue?")
        root.after(50 if smoke_ms else 200, tic)

    def al_cerrar():
        if st["bloque"] and not smoke_ms:
            if not messagebox.askyesno(APP_NAME, "Hay un bloque en curso. ¿Abandonarlo y cerrar?", parent=root):
                return
            if minutos_reales() >= 1:
                registrar("abandonado")
        try:
            if not st["mini"]:
                cfg["geometria"] = root.geometry()
            save_config(cfg, config_path)
        finally:
            root.destroy()

    def reportar_excepcion(exc, val, tb):
        texto = "".join(traceback.format_exception(exc, val, tb))
        fallas.append(f"excepción en la interfaz: {val!r}")
        write_error_log("Excepción en la interfaz", texto)
        print(texto, file=sys.stderr)
    root.report_callback_exception = reportar_excepcion

    root.protocol("WM_DELETE_WINDOW", al_cerrar)
    # Espacio pausa, salvo donde ya significa algo: escribir o apretar el botón enfocado.
    root.bind("<space>", lambda e: None if e.widget.winfo_class() in
              ("TEntry", "TCombobox", "TButton", "TCheckbutton", "TSpinbox", "Listbox") else alternar_pausa())
    aplicar_topmost()
    ir_a_listo()
    tic()

    if smoke_ms:
        _guion_de_prueba(root, st, tm, fallas, var_int, var_dist, e_dist, b_empezar, b_arranque, b_seguir,
                         p_res, p_arr, lista, registro_path, alternar_mini, anotar_distraccion, cerrar_bloque,
                         combo, smoke_ms)
    root.mainloop()
    return 1 if fallas else 0


def _guion_de_prueba(root, st, tm, fallas, var_int, var_dist, e_dist, b_empezar, b_arranque, b_seguir,
                     p_res, p_arr, lista, registro_path, alternar_mini, anotar_distraccion, cerrar_bloque,
                     combo, smoke_ms) -> None:
    """Recorre la interfaz como una persona: intención vacía, bloque completo con
    distracción anotada, descanso, arranque de 5 min que se convierte en bloque,
    y modo mini. Todo con minutos de 20 ms."""
    pasos: list[tuple[Callable[[], bool], Callable[[], None], str]] = []

    def esperar(cond, accion, descripcion):
        pasos.append((cond, accion, descripcion))

    def poner_intencion(txt):
        var_int.set(txt)

    def sugerencias_ok():
        vals = list(combo.cget("values"))
        if "escribir intro — Informe" not in vals:
            fallas.append(f"no aparecieron las sugerencias de plazos: {vals}")
        b_empezar.invoke()  # intención vacía: no debe empezar

    esperar(lambda: st["fase"] == "listo", sugerencias_ok, "listo al abrir")
    esperar(lambda: st["fase"] == "listo", lambda: (poner_intencion("resolver ejercicios 1 a 3 de la guía"),
                                                     b_empezar.invoke()), "intención vacía no arranca")
    esperar(lambda: st["fase"] == "foco",
            lambda: (var_dist.set("responder a Pedro"), anotar_distraccion()), "foco corriendo")
    esperar(lambda: p_res.winfo_ismapped(), lambda: cerrar_bloque("terminado"), "fin del foco pide resultado")
    esperar(lambda: st["fase"] == "descanso", lambda: None, "descanso automático")
    esperar(lambda: st["fase"] == "listo",
            lambda: (lista.size() == 1 or fallas.append("la distracción no apareció en «para después»"),
                     poner_intencion("leer el paper hasta la sección 3"), b_arranque.invoke()),
            "vuelve a listo y muestra la lista")
    esperar(lambda: p_arr.winfo_ismapped(), lambda: b_seguir.invoke(), "fin del arranque ofrece seguir")
    esperar(lambda: st["fase"] == "foco" and tm.corriendo, lambda: alternar_mini(), "el arranque pasa a foco")
    esperar(lambda: st["mini"] and tm.terminado(), lambda: alternar_mini(), "en mini sigue corriendo")
    esperar(lambda: p_res.winfo_ismapped(), lambda: cerrar_bloque("avance"), "al salir de mini pide resultado")

    def verificar():
        filas = leer_registro(registro_path)
        resumen = [(f["tipo"], f["resultado"], f["minutos_reales"], f["distracciones"]) for f in filas]
        esperado = [("foco", "terminado", 25, 1), ("foco", "avance", 25, 0)]
        if resumen != esperado:
            fallas.append(f"registro inesperado: {resumen} (esperaba {esperado})")
        if st["completados"] != 2:
            fallas.append(f"bloques completados: {st['completados']}")
    esperar(lambda: st["fase"] == "descanso", verificar, "segundo descanso")

    estado = {"i": 0, "inicio": time.monotonic()}

    def avanzar():
        if estado["i"] >= len(pasos):
            root.update_idletasks()
            print(f"ventana {root.winfo_width()}x{root.winfo_height()}, "
                  f"{len(pasos)} pasos del guion recorridos")
            for f in fallas:
                print(f"FALLA: {f}")
            print("interfaz: " + ("sin fallas." if not fallas else f"{len(fallas)} falla(s)."))
            root.destroy()
            return
        cond, accion, descripcion = pasos[estado["i"]]
        if cond():
            estado["i"] += 1
            estado["inicio"] = time.monotonic()
            accion()
        elif time.monotonic() - estado["inicio"] > max(5.0, smoke_ms / 1000):
            fallas.append(f"se quedó esperando: {descripcion} (fase {st['fase']})")
            estado["i"] = len(pasos)
        root.after(30, avanzar)
    root.after(300, avanzar)


# =====================================================================
# 9. Entrada
# =====================================================================

def _show_fatal_dialog(path: Path, tb: str) -> None:
    text = f"{APP_NAME} no pudo arrancar.\n\nEl detalle quedó en:\n{path}\n\n{tb[-800:]}"
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(APP_NAME, text)
        root.destroy()
        return
    except Exception:
        pass
    if IS_WINDOWS:
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, text, APP_NAME, 0x10)
        except Exception:
            pass


def main(argv: list) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:
            pass
    if "--selftest" in argv:
        return run_selftest()
    if "--accesos" in argv:
        created, problems = create_launchers()
        for path in created:
            print(f"creado: {path}")
        for problem in problems:
            print(f"aviso:  {problem}")
        print("\nYa puedes abrir la app con doble clic desde cualquiera de esos archivos.")
        return 0 if created else 1
    if "--help" in argv or "-h" in argv:
        print(__doc__)
        return 0
    if "--guitest" in argv:
        rest = argv[argv.index("--guitest") + 1:]
        ms = int(rest[0]) if rest and rest[0].isdigit() else 8000
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "plazos_datos.json").write_text(json.dumps({"tareas": [
                {"nombre": "Informe", "entrega": "2099-01-01T18:00", "siguiente_paso": "escribir intro"}]}),
                encoding="utf-8")
            return run_gui(smoke_ms=ms, dir_datos=d, seg_por_min=0.02)
    return run_gui()


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except SystemExit:
        raise
    except BaseException:
        _tb = traceback.format_exc()
        _path = write_error_log("Fallo no controlado al iniciar la aplicación", _tb)
        try:
            print(_tb, file=sys.stderr)
        except Exception:
            pass
        _show_fatal_dialog(_path, _tb)
        sys.exit(1)
