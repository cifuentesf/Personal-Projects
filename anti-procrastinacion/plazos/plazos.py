"""plazos — tus entregas con cuenta regresiva y el costo real de postergar.

Cada entrega lleva las horas de trabajo que crees que toma y el siguiente
paso concreto. Con eso la app calcula cuántas horas necesitas hoy para ir al
día con todo, y cuánto sube esa cifra si hoy no haces nada.

Uso:
    python plazos.py              # interfaz gráfica
    python plazos.py --accesos    # crea los lanzadores de doble clic
    python plazos.py --selftest   # prueba toda la lógica interna, sin GUI
    python plazos.py --guitest    # abre la ventana 4 s con datos de ejemplo

Si la aplicación no arranca, el detalle queda en plazos_error.log,
junto a este archivo.
"""

from __future__ import annotations

import base64
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
import traceback
import unicodedata
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

APP_NAME = "plazos"
APP_VERSION = "1.0"
APP_COMMENT = "Entregas con cuenta regresiva y costo de postergar"
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
DATA_PATH = DATA_DIR / f"{APP_NAME}_datos.json"
ERROR_LOG_PATH = DATA_DIR / f"{APP_NAME}_error.log"


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
# 2. Fechas: lectura flexible y formato corto en español
# =====================================================================

DIAS = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
DIAS_CORTOS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


def sin_tildes(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


_HORA_RE = re.compile(r"(?:^|\s)(?:a las\s+)?(\d{1,2})(?::(\d{2})|h(\d{2})?)\s*(?:hrs?|h)?$")
_FECHA_DMY = re.compile(r"^(\d{1,2})[-/.](\d{1,2})(?:[-/.](\d{2}|\d{4}))?$")
_FECHA_YMD = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_EN_N = re.compile(r"^en (\d{1,3}) (dia|dias|semana|semanas)$")


def parse_entrega(texto: str, ahora: datetime) -> datetime:
    """Convierte lo que escribe una persona en una fecha de entrega.

    Acepta: «15-10», «15/10 18:00», «15-10-2026 9h», «2026-10-15 18:30»,
    «hoy», «mañana 14:00», «pasado mañana», «viernes», «el jueves 8h30»,
    «en 3 días», «en 2 semanas» o solo «18:00». Sin hora, vence a las 23:59.
    Sin año, toma la próxima vez que llega esa fecha.
    """
    t = re.sub(r"\s+", " ", sin_tildes(texto.strip().lower()))
    if not t:
        raise ValueError("Escribe una fecha, por ejemplo «15-10 18:00» o «viernes».")

    hora, minuto, con_hora = 23, 59, False
    m = _HORA_RE.search(t)
    if m:
        hora = int(m.group(1))
        minuto = int(m.group(2) or m.group(3) or 0)
        if hora > 23 or minuto > 59:
            raise ValueError(f"Hora inválida: {m.group(0).strip()}")
        con_hora = True
        t = t[:m.start()].strip()

    t = re.sub(r"^(el|este|esta|proximo|proxima)\s+", "", t)
    hoy = ahora.replace(hour=0, minute=0, second=0, microsecond=0)

    def con_hora_en(dia: datetime) -> datetime:
        return dia.replace(hour=hora, minute=minuto)

    if t == "":
        if not con_hora:
            raise ValueError("Escribe una fecha, por ejemplo «15-10 18:00» o «viernes».")
        dt = con_hora_en(hoy)
        return dt if dt > ahora else dt + timedelta(days=1)
    if t == "hoy":
        return con_hora_en(hoy)
    if t == "manana":
        return con_hora_en(hoy + timedelta(days=1))
    if t == "pasado manana":
        return con_hora_en(hoy + timedelta(days=2))
    if t in DIAS:
        adelante = (DIAS.index(t) - hoy.weekday()) % 7
        dt = con_hora_en(hoy + timedelta(days=adelante))
        return dt if dt > ahora else dt + timedelta(days=7)
    m = _EN_N.match(t)
    if m:
        n = int(m.group(1)) * (7 if m.group(2).startswith("semana") else 1)
        return con_hora_en(hoy + timedelta(days=n))

    m = _FECHA_YMD.match(t)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return _fecha_valida(y, mo, d, hora, minuto, texto)
    m = _FECHA_DMY.match(t)
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        if m.group(3):
            y = int(m.group(3))
            y = y + 2000 if y < 100 else y
            return _fecha_valida(y, mo, d, hora, minuto, texto)
        dt = _fecha_valida(ahora.year, mo, d, hora, minuto, texto)
        if dt.date() < ahora.date():
            dt = _fecha_valida(ahora.year + 1, mo, d, hora, minuto, texto)
        return dt
    raise ValueError(f"No entendí «{texto.strip()}». Prueba con «15-10 18:00», "
                     "«viernes» o «en 3 días».")


def _fecha_valida(y: int, mo: int, d: int, h: int, mi: int, original: str) -> datetime:
    try:
        return datetime(y, mo, d, h, mi)
    except ValueError:
        raise ValueError(f"Esa fecha no existe: «{original.strip()}».") from None


def formato_entrega(dt: datetime, ahora: datetime) -> str:
    base = f"{DIAS_CORTOS[dt.weekday()]} {dt.day:02d}-{dt.month:02d}"
    if dt.year != ahora.year:
        base += f"-{dt.year}"
    return f"{base} {dt.hour:02d}:{dt.minute:02d}"


def formato_reloj(horas: float) -> str:
    """Tiempo de calendario: «3 d 4 h», «5 h 20 min», «vencida hace 2 h 0 min»."""
    if horas < 0:
        return "vencida hace " + formato_reloj(-horas)
    total = int(round(horas * 60))
    d, resto = divmod(total, 1440)
    h, m = divmod(resto, 60)
    if d:
        return f"{d} d {h} h"
    if h:
        return f"{h} h {m} min"
    return f"{m} min"


def formato_horas(horas: float) -> str:
    """Horas de trabajo: «40 min», «2 h», «2,5 h». Coma decimal, como en Chile."""
    if horas < 1:
        return f"{int(round(horas * 60))} min"
    txt = f"{horas:.1f}".replace(".", ",")
    if txt.endswith(",0"):
        txt = txt[:-2]
    return f"{txt} h"


def parse_horas(texto: str) -> float:
    """«2», «2,5», «2.5», «1h30», «1 h 30 min», «90 min», «45m» → horas."""
    t = sin_tildes(texto.strip().lower()).replace(",", ".")
    t = re.sub(r"\s+", "", t)
    if not t:
        raise ValueError("Escribe un número de horas, por ejemplo 2 o 1,5.")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(?:h|hrs?|horas?)?", t)
    if m:
        return float(m.group(1))
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(?:m|min|mins|minutos?)", t)
    if m:
        return float(m.group(1)) / 60
    m = re.fullmatch(r"(\d+)(?:h|hrs?|horas?)(\d{1,2})(?:m|min|mins|minutos?)?", t)
    if m and int(m.group(2)) < 60:
        return int(m.group(1)) + int(m.group(2)) / 60
    raise ValueError(f"No entendí «{texto.strip()}» como horas. Ejemplos: 2, 1,5, 1h30, 90 min.")


def horas_editables(horas: float) -> str:
    """Horas para un campo editable, exactas al minuto: «2», «1h45», «0h25».
    (formato_horas redondea a un decimal: al guardar sin cambios, el número iría corriendo.)"""
    hh, mm = divmod(int(round(horas * 60)), 60)
    return f"{hh}" if mm == 0 else f"{hh}h{mm:02d}"


def fecha_editable(dt: datetime) -> str:
    """Fecha para un campo editable, siempre con año: sin él, una entrega vencida
    que se edita saltaría al año siguiente."""
    return f"{dt.day:02d}-{dt.month:02d}-{dt.year} {dt.hour:02d}:{dt.minute:02d}"


# =====================================================================
# 3. Modelo y cálculo de presión
# =====================================================================

@dataclass
class Tarea:
    nombre: str
    entrega: str                  # ISO local, «2026-10-15T23:59»
    horas_estimadas: float
    horas_hechas: float = 0.0
    curso: str = ""
    siguiente_paso: str = ""
    entregada: bool = False
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    creada: str = field(default_factory=lambda: datetime.now().isoformat(timespec="minutes"))

    @property
    def entrega_dt(self) -> datetime:
        return datetime.fromisoformat(self.entrega)

    @classmethod
    def desde_dict(cls, d: dict) -> "Tarea":
        t = cls(
            nombre=str(d["nombre"]).strip(),
            entrega=str(d["entrega"]),
            horas_estimadas=float(d["horas_estimadas"]),
            horas_hechas=float(d.get("horas_hechas", 0.0)),
            curso=str(d.get("curso", "")),
            siguiente_paso=str(d.get("siguiente_paso", "")),
            entregada=bool(d.get("entregada", False)),
        )
        if d.get("id"):
            t.id = str(d["id"])
        if d.get("creada"):
            t.creada = str(d["creada"])
        t.entrega_dt  # valida el formato: si está mal, que falle aquí y no en la interfaz
        if not t.nombre or t.horas_estimadas < 0 or t.horas_hechas < 0:
            raise ValueError("nombre vacío u horas negativas")
        return t


@dataclass
class Analisis:
    estado: str                 # lista | vencida | imposible | rojo | amarillo | verde
    horas_reloj: float          # horas de calendario hasta la entrega (negativo si venció)
    faltan: float               # horas de trabajo pendientes
    hoy: float                  # horas que tocan hoy para ir al día a ritmo parejo
    si_postergas: float | None  # h/día desde mañana si hoy no avanzas; None = vence antes
    carga: float                # hoy / capacidad diaria


# Orden en la lista: primero lo que exige una decisión, al final lo resuelto.
ORDEN_ESTADO = {"vencida": 0, "imposible": 1, "rojo": 2, "amarillo": 3, "verde": 4, "lista": 5}


def analizar(t: Tarea, ahora: datetime, capacidad: float) -> Analisis:
    """Cuánto pesa una entrega hoy.

    Supone ritmo parejo: lo que falta se reparte entre los días que quedan.
    Si queda menos de un día, todo lo que falta toca hoy.
    """
    horas_reloj = (t.entrega_dt - ahora).total_seconds() / 3600
    faltan = max(0.0, t.horas_estimadas - t.horas_hechas)
    if faltan < 1e-9:
        return Analisis("lista", horas_reloj, 0.0, 0.0, 0.0, 0.0)
    if horas_reloj <= 0:
        return Analisis("vencida", horas_reloj, faltan, 0.0, None, 0.0)
    dias = horas_reloj / 24
    hoy = faltan / max(dias, 1.0)
    si_postergas = faltan / max(dias - 1.0, 1.0) if dias > 1.0 else None
    carga = hoy / capacidad if capacidad > 0 else math.inf
    if faltan > horas_reloj:
        estado = "imposible"
    elif carga > 1.0:
        estado = "rojo"
    elif carga > 0.5:
        estado = "amarillo"
    else:
        estado = "verde"
    return Analisis(estado, horas_reloj, faltan, hoy, si_postergas, carga)


@dataclass
class Resumen:
    hoy_total: float          # horas que tocan hoy sumando todas las entregas vivas
    manana_total: float       # h/día desde mañana si hoy no avanzas nada
    se_pierden: int           # entregas que vencerían antes de mañana con trabajo pendiente
    vencidas: int
    activas: int
    capacidad: float


def resumir(tareas: list[Tarea], ahora: datetime, capacidad: float) -> Resumen:
    hoy_total = manana_total = 0.0
    se_pierden = vencidas = activas = 0
    for t in tareas:
        if t.entregada:
            continue
        a = analizar(t, ahora, capacidad)
        if a.estado == "lista":
            continue
        if a.estado == "vencida":
            vencidas += 1
            continue
        activas += 1
        hoy_total += a.hoy
        if a.si_postergas is None:
            se_pierden += 1
        else:
            manana_total += a.si_postergas
    return Resumen(hoy_total, manana_total, se_pierden, vencidas, activas, capacidad)


def ordenar(tareas: list[Tarea], ahora: datetime, capacidad: float) -> list[Tarea]:
    def clave(t: Tarea):
        a = analizar(t, ahora, capacidad)
        return (1 if t.entregada else 0, ORDEN_ESTADO[a.estado] if a.estado in ("vencida", "lista") else 2,
                t.entrega_dt)
    return sorted(tareas, key=clave)


def texto_resumen(r: Resumen) -> tuple[str, str]:
    """Las dos líneas de arriba de la ventana."""
    if r.activas == 0:
        linea1 = "Nada pendiente con trabajo por hacer."
        if r.vencidas:
            linea1 += f" Hay {r.vencidas} vencida(s) sin cerrar."
        return linea1, "Agrega una entrega con «Nueva entrega»." if not r.vencidas else ""
    linea1 = (f"Hoy necesitas {formato_horas(r.hoy_total)} para ir al día con todo "
              f"(tu capacidad: {formato_horas(r.capacidad)})")
    partes = []
    if r.manana_total > 0:
        partes.append(f"desde mañana necesitarías {formato_horas(r.manana_total)} al día")
    if r.se_pierden:
        partes.append(f"{r.se_pierden} entrega(s) vencerían antes de mañana")
    linea2 = "Si hoy no avanzas nada: " + " y ".join(partes) + "." if partes else ""
    return linea1, linea2


# =====================================================================
# 4. El siguiente paso: concreto o no sirve
# =====================================================================

VERBOS_VAGOS = {"avanzar", "trabajar", "hacer", "estudiar", "ver", "revisar", "terminar",
                "seguir", "empezar", "continuar", "repasar", "preparar", "ponerse"}


def paso_vago(texto: str) -> str | None:
    """Devuelve un consejo si el paso es demasiado general; None si está bien."""
    palabras = re.findall(r"\w+", sin_tildes(texto.lower()))
    if not palabras:
        return "Sin siguiente paso. Escribe lo primero que harías al sentarte."
    if len(palabras) < 3 or (palabras[0] in VERBOS_VAGOS and len(palabras) <= 3):
        return ("Muy general. Un buen paso dice qué y dónde: «escribir la intro del informe T2», "
                "no «avanzar T2».")
    return None


# =====================================================================
# 5. Persistencia (escritura atómica: nunca queda un JSON a medias)
# =====================================================================

def cargar_datos(path: Path) -> tuple[list[Tarea], list[dict], list[str]]:
    """Devuelve (tareas, registro de horas, avisos). Nunca lanza."""
    avisos: list[str] = []
    if not path.exists():
        return [], [], avisos
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("no es un objeto JSON")
    except Exception as exc:
        respaldo = path.with_name(f"{path.stem}.corrupto-{time.strftime('%Y%m%d-%H%M%S')}.json")
        try:
            path.replace(respaldo)
            avisos.append(f"{path.name} estaba dañado ({exc}); lo moví a {respaldo.name} y empecé vacío.")
        except Exception:
            avisos.append(f"{path.name} está dañado ({exc}) y no pude moverlo.")
        return [], [], avisos
    tareas = []
    for i, d in enumerate(data.get("tareas", [])):
        try:
            tareas.append(Tarea.desde_dict(d))
        except Exception as exc:
            avisos.append(f"Tarea {i + 1} ignorada por datos inválidos: {exc}")
    registro = [r for r in data.get("registro", []) if isinstance(r, dict)]
    return tareas, registro, avisos


def guardar_datos(path: Path, tareas: list[Tarea], registro: list[dict]) -> None:
    data = {"version": 1, "tareas": [asdict(t) for t in tareas], "registro": registro}
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def horas_registradas_el(registro: list[dict], dia: datetime) -> float:
    total = 0.0
    for r in registro:
        try:
            if datetime.fromisoformat(str(r["fecha"])).date() == dia.date():
                total += float(r["horas"])
        except Exception:
            continue
    return total


def registrar_horas(tarea: Tarea, registro: list[dict], horas: float, ahora: datetime) -> None:
    tarea.horas_hechas = round(tarea.horas_hechas + horas, 4)
    registro.append({"fecha": ahora.isoformat(timespec="minutes"), "tarea": tarea.id,
                     "horas": round(horas, 4)})


# =====================================================================
# 6. Lanzadores de doble clic
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
               "Icon=x-office-calendar\n"
               "Terminal=false\n"
               "Categories=Utility;Office;\n")
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
            newline = "\r\n" if name.endswith(".bat") else "\n"
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(text if newline == "\r\n" else text.replace("\r\n", "\n"))
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
# 7. Configuración
# =====================================================================

DEFAULT_CONFIG = {"capacidad": 4.0, "mostrar_entregadas": False, "geometria": ""}


def load_config(path: Path = CONFIG_PATH) -> dict:
    data = dict(DEFAULT_CONFIG)
    try:
        if path.exists():
            saved = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                for k, v in saved.items():
                    if k in DEFAULT_CONFIG and isinstance(v, type(DEFAULT_CONFIG[k])):
                        data[k] = v
                    elif k in DEFAULT_CONFIG and isinstance(DEFAULT_CONFIG[k], float) \
                            and isinstance(v, int) and not isinstance(v, bool):
                        data[k] = float(v)
    except Exception:
        pass
    if not (0.25 <= data["capacidad"] <= 16):
        data["capacidad"] = DEFAULT_CONFIG["capacidad"]
    return data


def save_config(data: dict, path: Path = CONFIG_PATH) -> None:
    try:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


# =====================================================================
# 8. Autoprueba (--selftest)
# =====================================================================

def run_selftest() -> int:
    checks: list[tuple[bool, str]] = []

    def check(cond: bool, label: str) -> None:
        checks.append((bool(cond), label))

    # viernes 9 de octubre de 2026, 15:20
    ahora = datetime(2026, 10, 9, 15, 20)

    # --- lectura de fechas ---
    casos = {
        "15-10": datetime(2026, 10, 15, 23, 59),
        "15/10 18:00": datetime(2026, 10, 15, 18, 0),
        "15.10.2026 9h": datetime(2026, 10, 15, 9, 0),
        "15-10-27 9h30": datetime(2027, 10, 15, 9, 30),
        "2026-12-01": datetime(2026, 12, 1, 23, 59),
        "2026-12-01 08:15": datetime(2026, 12, 1, 8, 15),
        "hoy": datetime(2026, 10, 9, 23, 59),
        "Mañana 14:00": datetime(2026, 10, 10, 14, 0),
        "pasado mañana": datetime(2026, 10, 11, 23, 59),
        "viernes": datetime(2026, 10, 9, 23, 59),            # hoy es viernes y aún no pasa
        "viernes 10:00": datetime(2026, 10, 16, 10, 0),      # hoy a las 10 ya pasó
        "el lunes 8h30": datetime(2026, 10, 12, 8, 30),
        "próximo miércoles": datetime(2026, 10, 14, 23, 59),
        "en 3 días": datetime(2026, 10, 12, 23, 59),
        "en 2 semanas": datetime(2026, 10, 23, 23, 59),
        "18:00": datetime(2026, 10, 9, 18, 0),
        "9:00": datetime(2026, 10, 10, 9, 0),                # ya pasó hoy: mañana
        "05-01": datetime(2027, 1, 5, 23, 59),               # ya pasó este año: el próximo
        "09-10": datetime(2026, 10, 9, 23, 59),              # hoy no es pasado
        "  15-10   a las 18:00 ": datetime(2026, 10, 15, 18, 0),
        "15-10 18:00 hrs": datetime(2026, 10, 15, 18, 0),
    }
    for texto, esperado in casos.items():
        try:
            obtenido = parse_entrega(texto, ahora)
        except Exception as exc:
            obtenido = exc
        check(obtenido == esperado, f"fecha «{texto}» → {esperado:%Y-%m-%d %H:%M} (obtuve {obtenido})")
    for malo in ("", "31-02", "15-13", "25:00", "el día del juicio", "15-10 24:00"):
        try:
            parse_entrega(malo, ahora)
            check(False, f"fecha inválida «{malo}» rechazada")
        except ValueError as exc:
            check(bool(str(exc)), f"fecha inválida «{malo}» rechazada con mensaje")

    check(formato_entrega(datetime(2026, 10, 15, 18, 0), ahora) == "jue 15-10 18:00", "formato de entrega")
    check(formato_entrega(datetime(2027, 1, 5, 9, 5), ahora) == "mar 05-01-2027 09:05",
          "formato de entrega con año distinto")
    check(formato_reloj(76.5) == "3 d 4 h", f"reloj 76,5 h: {formato_reloj(76.5)}")
    check(formato_reloj(5 + 20 / 60) == "5 h 20 min", "reloj 5 h 20 min")
    check(formato_reloj(0.25) == "15 min", "reloj 15 min")
    check(formato_reloj(-2) == "vencida hace 2 h 0 min", f"reloj vencido: {formato_reloj(-2)}")
    check(formato_horas(2.5) == "2,5 h" and formato_horas(2.0) == "2 h" and formato_horas(0.5) == "30 min",
          "formato de horas de trabajo con coma decimal")

    for texto, esperado in {"2": 2.0, "2,5": 2.5, "2.5": 2.5, "1h30": 1.5, "1 h 30 min": 1.5,
                            "90 min": 1.5, "45m": 0.75, "3 horas": 3.0}.items():
        try:
            obtenido = parse_horas(texto)
        except Exception as exc:
            obtenido = exc
        check(obtenido == esperado, f"horas «{texto}» → {esperado} (obtuve {obtenido})")
    for h in (0.0, 0.25, 25 / 60, 1.75, 2.0, 7.5, 1.1):
        check(abs(parse_horas(horas_editables(h)) - round(h * 60) / 60) < 1e-9,
              f"horas editables {h} → «{horas_editables(h)}» vuelve exacta al minuto")
    for dt in (datetime(2026, 10, 8, 23, 59), datetime(2026, 10, 15, 18, 0), datetime(2027, 3, 1, 9, 5)):
        check(parse_entrega(fecha_editable(dt), ahora) == dt,
              f"fecha editable «{fecha_editable(dt)}» vuelve igual (aunque esté vencida)")
    for malo in ("", "mucho", "-2", "1h75"):
        try:
            parse_horas(malo)
            check(False, f"horas inválidas «{malo}» rechazadas")
        except ValueError:
            check(True, f"horas inválidas «{malo}» rechazadas")

    # --- análisis de presión ---
    def tarea(nombre, en_horas, est, hechas=0.0, **kw):
        return Tarea(nombre=nombre, entrega=(ahora + timedelta(hours=en_horas)).isoformat(timespec="minutes"),
                     horas_estimadas=est, horas_hechas=hechas, **kw)

    cap = 4.0
    a = analizar(tarea("holgada", 240, 10), ahora, cap)       # 10 días, 10 h → 1 h/día
    check(a.estado == "verde" and abs(a.hoy - 1.0) < 1e-9, f"10 h en 10 días: verde, 1 h hoy ({a})")
    check(a.si_postergas is not None and abs(a.si_postergas - 10 / 9) < 1e-9,
          "postergar un día sube a 10/9 h por día")
    a = analizar(tarea("ajustada", 72, 9), ahora, cap)         # 3 días, 9 h → 3 h/día
    check(a.estado == "amarillo" and abs(a.hoy - 3.0) < 1e-9, f"9 h en 3 días con 4 h/día: amarillo ({a.estado})")
    check(abs(a.si_postergas - 4.5) < 1e-9, "postergar 9 h a 2 días: 4,5 h/día")
    a = analizar(tarea("roja", 48, 10), ahora, cap)            # 2 días, 10 h → 5 h/día
    check(a.estado == "rojo", f"10 h en 2 días: rojo ({a.estado})")
    a = analizar(tarea("hoy", 6, 2), ahora, cap)               # quedan 6 h de reloj
    check(abs(a.hoy - 2.0) < 1e-9 and a.si_postergas is None,
          "con menos de un día, todo lo que falta toca hoy y postergar la pierde")
    a = analizar(tarea("imposible", 5, 8), ahora, cap)
    check(a.estado == "imposible", "8 h de trabajo en 5 h de reloj: imposible")
    a = analizar(tarea("vencida", -3, 5), ahora, cap)
    check(a.estado == "vencida" and a.horas_reloj < 0, "entrega pasada: vencida")
    a = analizar(tarea("lista", 24, 5, hechas=5), ahora, cap)
    check(a.estado == "lista" and a.faltan == 0, "horas hechas cubren lo estimado: lista")
    a = analizar(tarea("pasada", 24, 5, hechas=7), ahora, cap)
    check(a.estado == "lista" and a.faltan == 0, "más horas que lo estimado no da faltan negativo")
    a = analizar(tarea("frontera", 72, 6), ahora, cap)         # 2 h/día = exactamente 50 %
    check(a.estado == "verde", "carga exactamente 50 % sigue verde")
    a = analizar(tarea("sin capacidad", 72, 6), ahora, 0)
    check(a.estado == "rojo", "capacidad 0 no divide por cero: rojo")

    tareas = [tarea("A", 240, 10), tarea("B", 72, 9), tarea("C", 6, 2), tarea("D", -3, 5),
              tarea("E", 24, 5, hechas=5), tarea("F", 48, 4, entregada=True)]
    r = resumir(tareas, ahora, cap)
    check(abs(r.hoy_total - (1 + 3 + 2)) < 1e-9, f"total de hoy suma solo entregas vivas ({r.hoy_total})")
    check(abs(r.manana_total - (10 / 9 + 4.5)) < 1e-9, f"total si postergas ({r.manana_total})")
    check(r.se_pierden == 1 and r.vencidas == 1 and r.activas == 3, "conteos del resumen")
    l1, l2 = texto_resumen(r)
    check("6 h" in l1 and "4 h" in l1, f"línea 1 del resumen: {l1}")
    check("1 entrega(s) vencerían" in l2 and "5,6 h" in l2, f"línea 2 del resumen: {l2}")
    l1, l2 = texto_resumen(resumir([], ahora, cap))
    check("Nada pendiente" in l1 and "Nueva entrega" in l2, "resumen vacío invita a agregar")

    orden = [t.nombre for t in ordenar(tareas, ahora, cap)]
    check(orden == ["D", "C", "B", "A", "E", "F"], f"orden: vencidas, por fecha, listas, entregadas ({orden})")

    # --- siguiente paso ---
    check(paso_vago("") is not None, "paso vacío: aviso")
    check(paso_vago("avanzar T2") is not None, "«avanzar T2»: vago")
    check(paso_vago("Estudiar") is not None, "«Estudiar»: vago")
    check(paso_vago("Avanzar informe T2") is not None, "«Avanzar informe T2»: vago")
    check(paso_vago("leer paper CLRNet") is None, "«leer paper CLRNet»: concreto")
    check(paso_vago("revisar la ecuación 3 del enunciado") is None, "paso largo con verbo genérico: concreto")

    # --- persistencia ---
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "datos.json"
        t1 = tarea("Informe T2 «redes»", 72, 9, curso="IEE2544", siguiente_paso="escribir intro, sección 1")
        reg: list[dict] = []
        registrar_horas(t1, reg, 1.5, ahora)
        registrar_horas(t1, reg, 0.5, ahora - timedelta(days=1))
        guardar_datos(p, [t1], reg)
        check(not (Path(tmp) / "datos.json.tmp").exists(), "escritura atómica no deja .tmp")
        tareas2, reg2, avisos = cargar_datos(p)
        check(len(tareas2) == 1 and tareas2[0] == t1 and not avisos, "ida y vuelta JSON idéntica")
        check(tareas2[0].horas_hechas == 2.0, "horas registradas se suman a la tarea")
        check(horas_registradas_el(reg2, ahora) == 1.5, "horas de hoy salen del registro")
        check(cargar_datos(Path(tmp) / "no-existe.json") == ([], [], []), "sin archivo: vacío y sin avisos")

        p.write_text('{"tareas": [{"nombre": "ok", "entrega": "2026-10-20T10:00", "horas_estimadas": 2},'
                     ' {"nombre": "mala", "entrega": "ayer", "horas_estimadas": 2},'
                     ' {"nombre": "", "entrega": "2026-10-20T10:00", "horas_estimadas": 2}]}', encoding="utf-8")
        tareas3, _, avisos = cargar_datos(p)
        check(len(tareas3) == 1 and len(avisos) == 2, f"tareas inválidas se saltan con aviso ({avisos})")

        p.write_text("{esto no es json", encoding="utf-8")
        tareas4, _, avisos = cargar_datos(p)
        respaldos = list(Path(tmp).glob("datos.corrupto-*.json"))
        check(tareas4 == [] and len(respaldos) == 1 and avisos,
              "JSON dañado se aparta a un respaldo en vez de perderse")

        cfg = Path(tmp) / "cfg.json"
        cfg.write_text('{"capacidad": 6, "mostrar_entregadas": "si", "otra": 1}', encoding="utf-8")
        c = load_config(cfg)
        check(c["capacidad"] == 6.0 and c["mostrar_entregadas"] is False and "otra" not in c,
              f"config: acepta enteros, ignora tipos malos y claves extra ({c})")
        cfg.write_text('{"capacidad": 99}', encoding="utf-8")
        check(load_config(cfg)["capacidad"] == 4.0, "config: capacidad absurda vuelve al valor por omisión")

        # --- lanzadores ---
        created, problems = create_launchers(Path(tmp), desktop=False)
        names = {c.name for c in created}
        check(names == {"plazos.bat", "plazos.sh", "plazos.desktop"}, f"lanzadores creados: {sorted(names)}")
        check(not problems, f"lanzadores sin problemas: {problems}")
        bat = (Path(tmp) / "plazos.bat").read_bytes()
        check(b"\r\n" in bat and b"plazos.py" in bat, "el .bat usa CRLF y apunta a plazos.py")
        sh = (Path(tmp) / "plazos.sh").read_bytes()
        check(b"\r\n" not in sh and sh.startswith(b"#!/bin/sh"), "el .sh usa LF y shebang")
        if not IS_WINDOWS:
            check(os.access(Path(tmp) / "plazos.sh", os.X_OK), "el .sh queda ejecutable")

    fallidas = [label for ok, label in checks if not ok]
    for label in fallidas:
        print(f"FALLA: {label}")
    print(f"{len(checks) - len(fallidas)}/{len(checks)} comprobaciones correctas.")
    return 0 if not fallidas else 1


# =====================================================================
# 9. Interfaz gráfica (tkinter)
# =====================================================================

COLORES = {  # fondo, texto
    "vencida": ("#e4e4e4", "#6b6b6b"),
    "imposible": ("#f4b6ae", "#5c0b00"),
    "rojo": ("#fbd5cf", "#6e1404"),
    "amarillo": ("#fff0c2", "#5a4500"),
    "verde": ("#dcf1d8", "#1d4d16"),
    "lista": ("#e5eefb", "#1f3b63"),
    "entregada": ("#f3f3f3", "#9a9a9a"),
}
ESTADO_TEXTO = {"vencida": "vencida", "imposible": "no alcanza", "rojo": "sobre tu ritmo",
                "amarillo": "ajustada", "verde": "holgada", "lista": "lista"}


def _datos_ejemplo(ahora: datetime) -> list[Tarea]:
    def iso(h):
        return (ahora + timedelta(hours=h)).isoformat(timespec="minutes")
    return [
        Tarea("Informe T2", iso(70), 9, 2, "IEE2544", "escribir la sección de resultados con los 3 gráficos"),
        Tarea("Control 2", iso(30), 6, 1, "IEE3951", "hacer los 4 ejercicios de la guía 5"),
        Tarea("Tarea 3", iso(200), 8, 0, "IEE2544", ""),
        Tarea("Lectura paper", iso(-5), 2, 0, "", "leer secciones 1 y 2"),
    ]


def run_gui(smoke_ms: int = 0, data_path: Path | None = None, config_path: Path | None = None) -> int:
    """smoke_ms > 0: abre la ventana, informa su tamaño y la cierra sola (diagnóstico)."""
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

    data_path = data_path or DATA_PATH
    config_path = config_path or CONFIG_PATH
    cfg = load_config(config_path)
    tareas, registro, avisos_carga = cargar_datos(data_path)

    root = tk.Tk()
    root.title(APP_NAME)
    try:
        root.tk.call("tk", "scaling", root.winfo_fpixels("1i") / 72.0)
    except Exception:
        pass
    root.minsize(760, 460)
    if cfg["geometria"] and not smoke_ms:
        try:
            root.geometry(cfg["geometria"])
        except Exception:
            root.geometry("980x600")
    else:
        root.geometry("980x600")

    base = tkfont.nametofont("TkDefaultFont")
    f_grande = base.copy()
    f_grande.configure(size=max(13, int(base.cget("size")) + 4), weight="bold")
    f_titulo = base.copy()
    f_titulo.configure(size=max(11, int(base.cget("size")) + 2), weight="bold")
    style = ttk.Style(root)
    try:
        if IS_WINDOWS:
            style.theme_use("vista")
        elif "clam" in style.theme_names():
            style.theme_use("clam")
    except Exception:
        pass
    style.configure("Treeview", rowheight=int(base.metrics("linespace") * 1.6))

    estado = {"sel": None, "after": None}

    def guardar() -> None:
        try:
            guardar_datos(data_path, tareas, registro)
        except Exception as exc:
            write_error_log("No se pudo guardar", traceback.format_exc())
            messagebox.showerror(APP_NAME, f"No se pudo guardar {data_path}:\n{exc}")

    # ---------- resumen ----------
    top = ttk.Frame(root, padding=(14, 12, 14, 4))
    top.pack(fill="x")
    lbl_hoy = ttk.Label(top, font=f_grande)
    lbl_hoy.pack(anchor="w")
    lbl_post = ttk.Label(top)
    lbl_post.pack(anchor="w", pady=(2, 0))
    lbl_reg = ttk.Label(top, foreground="#555")
    lbl_reg.pack(anchor="w")

    # ---------- barra ----------
    bar = ttk.Frame(root, padding=(14, 6))
    bar.pack(fill="x")
    ttk.Button(bar, text="Nueva entrega…", command=lambda: editar(None)).pack(side="left")
    ttk.Label(bar, text="   Capacidad diaria:").pack(side="left")
    var_cap = tk.StringVar(value=f"{cfg['capacidad']:g}")
    spin = ttk.Spinbox(bar, from_=0.5, to=16, increment=0.5, width=5, textvariable=var_cap,
                       command=lambda: cambiar_capacidad())
    spin.pack(side="left", padx=(4, 2))
    ttk.Label(bar, text="h").pack(side="left")
    var_mostrar = tk.BooleanVar(value=cfg["mostrar_entregadas"])
    ttk.Checkbutton(bar, text="Mostrar entregadas", variable=var_mostrar,
                    command=lambda: (cfg.__setitem__("mostrar_entregadas", var_mostrar.get()),
                                     save_config(cfg, config_path), refrescar())).pack(side="right")

    def cambiar_capacidad(*_):
        try:
            v = parse_horas(var_cap.get())
            if 0.25 <= v <= 16:
                cfg["capacidad"] = v
                save_config(cfg, config_path)
                refrescar()
        except ValueError:
            pass
    spin.bind("<Return>", cambiar_capacidad)
    spin.bind("<FocusOut>", cambiar_capacidad)

    # ---------- tabla ----------
    mid = ttk.Frame(root, padding=(14, 0))
    mid.pack(fill="both", expand=True)
    cols = ("entrega", "tarea", "queda", "falta", "hoy", "estado", "paso")
    tree = ttk.Treeview(mid, columns=cols, show="headings", selectmode="browse")
    for c, titulo, ancho, estira in (("entrega", "Entrega", 130, False), ("tarea", "Tarea", 190, True),
                                     ("queda", "Queda", 115, False), ("falta", "Falta", 70, False),
                                     ("hoy", "Hoy", 70, False), ("estado", "Estado", 100, False),
                                     ("paso", "Siguiente paso", 280, True)):
        tree.heading(c, text=titulo, anchor="w")
        tree.column(c, width=ancho, stretch=estira, anchor="w")
    sb = ttk.Scrollbar(mid, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    tree.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    for tag, (bg, fg) in COLORES.items():
        tree.tag_configure(tag, background=bg, foreground=fg)

    # ---------- detalle ----------
    det = ttk.Frame(root, padding=(14, 8, 14, 12))
    det.pack(fill="x")
    lbl_tit = ttk.Label(det, font=f_titulo, text="Elige una entrega de la lista.")
    lbl_tit.pack(anchor="w")
    lbl_info = ttk.Label(det, foreground="#444")
    lbl_info.pack(anchor="w")
    lbl_paso = ttk.Label(det, wraplength=900, justify="left")
    lbl_paso.pack(anchor="w", pady=(4, 0))
    lbl_aviso = ttk.Label(det, foreground="#9a4a00", wraplength=900, justify="left")
    lbl_aviso.pack(anchor="w")
    botones = ttk.Frame(det)
    botones.pack(anchor="w", pady=(8, 0))

    def seleccionada() -> Tarea | None:
        sel = tree.selection()
        if not sel:
            return None
        return next((t for t in tareas if t.id == sel[0]), None)

    def sumar(horas: float):
        t = seleccionada()
        if t:
            registrar_horas(t, registro, horas, datetime.now())
            guardar()
            refrescar()

    b_25 = ttk.Button(botones, text="+25 min", command=lambda: sumar(25 / 60))
    b_1h = ttk.Button(botones, text="+1 h", command=lambda: sumar(1.0))
    b_paso = ttk.Button(botones, text="Paso hecho…", command=lambda: paso_hecho())
    b_edit = ttk.Button(botones, text="Editar…", command=lambda: editar(seleccionada()))
    b_entr = ttk.Button(botones, text="Marcar entregada", command=lambda: alternar_entregada())
    b_del = ttk.Button(botones, text="Eliminar", command=lambda: eliminar())
    for b in (b_25, b_1h, b_paso, b_edit, b_entr, b_del):
        b.pack(side="left", padx=(0, 6))

    def mostrar_detalle():
        t = seleccionada()
        activos = "!disabled" if t else "disabled"
        for b in (b_25, b_1h, b_paso, b_edit, b_entr, b_del):
            b.state([activos])
        if not t:
            lbl_tit.configure(text="Elige una entrega de la lista." if tareas else "")
            lbl_info.configure(text="")
            lbl_paso.configure(text="")
            lbl_aviso.configure(text="")
            return
        ahora = datetime.now()
        a = analizar(t, ahora, cfg["capacidad"])
        b_entr.configure(text="Reabrir" if t.entregada else "Marcar entregada")
        lbl_tit.configure(text=t.nombre + (f"  ·  {t.curso}" if t.curso else ""))
        info = (f"Entrega {formato_entrega(t.entrega_dt, ahora)} ({formato_reloj(a.horas_reloj)})  ·  "
                f"llevas {formato_horas(t.horas_hechas) if t.horas_hechas else '0 h'} de "
                f"{formato_horas(t.horas_estimadas)}")
        if a.estado not in ("lista", "vencida") and not t.entregada:
            info += f"  ·  hoy: {formato_horas(a.hoy)}"
            info += (f", si postergas: {formato_horas(a.si_postergas)}/día" if a.si_postergas is not None
                     else ", si postergas: no alcanza")
        lbl_info.configure(text=info)
        lbl_paso.configure(text=f"Siguiente paso: {t.siguiente_paso or '—'}")
        aviso = "" if (t.entregada or a.estado == "lista") else (paso_vago(t.siguiente_paso) or "")
        if a.estado == "vencida" and not t.entregada:
            aviso = "Venció. Si ya la entregaste, márcala; si te dieron prórroga, edita la fecha."
        elif a.estado == "imposible":
            aviso = ("Con lo que estimaste no alcanza ni trabajando sin parar. Decide hoy qué recortar "
                     "o pide prórroga; esperar no lo arregla.")
        lbl_aviso.configure(text=aviso)

    def refrescar():
        ahora = datetime.now()
        cap = cfg["capacidad"]
        visibles = [t for t in tareas if var_mostrar.get() or not t.entregada]
        sel = tree.selection()
        scroll = tree.yview()[0]
        tree.delete(*tree.get_children())
        for t in ordenar(visibles, ahora, cap):
            a = analizar(t, ahora, cap)
            tag = "entregada" if t.entregada else a.estado
            paso = t.siguiente_paso or "⚠ define el siguiente paso"
            hoy = formato_horas(a.hoy) if a.estado not in ("lista", "vencida") and not t.entregada else ""
            tree.insert("", "end", iid=t.id, tags=(tag,), values=(
                formato_entrega(t.entrega_dt, ahora),
                t.nombre + (f" ({t.curso})" if t.curso else ""),
                "entregada" if t.entregada else formato_reloj(a.horas_reloj).replace("vencida ", ""),
                formato_horas(a.faltan) if a.faltan else "—",
                hoy,
                "entregada" if t.entregada else ESTADO_TEXTO[a.estado],
                paso))
        if sel and tree.exists(sel[0]):
            tree.selection_set(sel[0])
        tree.yview_moveto(scroll)
        r = resumir(tareas, ahora, cap)
        l1, l2 = texto_resumen(r)
        color = "#1d4d16" if r.hoy_total <= cap * 0.5 else ("#5a4500" if r.hoy_total <= cap else "#8a1b07")
        lbl_hoy.configure(text=l1, foreground=color if r.activas else "#333")
        lbl_post.configure(text=l2)
        hechas = horas_registradas_el(registro, ahora)
        lbl_reg.configure(text=f"Hoy registraste {formato_horas(hechas)}." if hechas else
                          "Hoy no has registrado horas todavía.")
        root.title(f"{APP_NAME} — hoy {formato_horas(r.hoy_total)}" if r.activas else APP_NAME)
        mostrar_detalle()

    def tic():
        refrescar()
        estado["after"] = root.after(30_000, tic)

    tree.bind("<<TreeviewSelect>>", lambda e: mostrar_detalle())
    tree.bind("<Double-1>", lambda e: editar(seleccionada()))
    tree.bind("<Delete>", lambda e: eliminar())

    # ---------- diálogos ----------
    def formulario(titulo: str, campos: list[tuple], al_aceptar) -> None:
        """campos: (clave, etiqueta, valor inicial, pista(texto)->str|None).
        al_aceptar(valores) devuelve un mensaje de error o None si todo bien."""
        dlg = tk.Toplevel(root)
        dlg.title(titulo)
        dlg.transient(root)
        dlg.resizable(True, False)
        frm = ttk.Frame(dlg, padding=14)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)
        vars_: dict[str, tk.StringVar] = {}
        fila = 0
        primero = None
        for clave, etiqueta, inicial, pista in campos:
            ttk.Label(frm, text=etiqueta).grid(row=fila, column=0, sticky="w", pady=(6, 0), padx=(0, 10))
            v = tk.StringVar(value=inicial)
            e = ttk.Entry(frm, textvariable=v, width=48)
            e.grid(row=fila, column=1, sticky="we", pady=(6, 0))
            primero = primero or e
            vars_[clave] = v
            fila += 1
            if pista:
                lp = ttk.Label(frm, foreground="#666", wraplength=420, justify="left")
                lp.grid(row=fila, column=1, sticky="w")
                fila += 1

                def actualizar(*_, v=v, lp=lp, pista=pista):
                    try:
                        lp.configure(text=pista(v.get()) or "")
                    except Exception as exc:
                        lp.configure(text=str(exc))
                v.trace_add("write", actualizar)
                actualizar()
        lbl_err = ttk.Label(frm, foreground="#a00", wraplength=520, justify="left")
        lbl_err.grid(row=fila, column=0, columnspan=2, sticky="w", pady=(8, 0))
        fila += 1
        bb = ttk.Frame(frm)
        bb.grid(row=fila, column=0, columnspan=2, sticky="e", pady=(10, 0))

        def aceptar(*_):
            err = al_aceptar({k: v.get() for k, v in vars_.items()})
            if err:
                lbl_err.configure(text=err)
            else:
                dlg.destroy()
        ttk.Button(bb, text="Cancelar", command=dlg.destroy).pack(side="right")
        ttk.Button(bb, text="Guardar", command=aceptar).pack(side="right", padx=(0, 6))
        dlg.bind("<Return>", aceptar)
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        dlg.update_idletasks()
        x = root.winfo_rootx() + (root.winfo_width() - dlg.winfo_width()) // 2
        y = root.winfo_rooty() + 60
        dlg.geometry(f"+{max(0, x)}+{max(0, y)}")
        if primero:
            primero.focus_set()
        try:
            dlg.grab_set()
        except Exception:
            pass

    def pista_fecha(txt: str) -> str:
        if not txt.strip():
            return "Ej.: 15-10 18:00 · viernes · mañana 14:00 · en 3 días"
        ahora = datetime.now()
        dt = parse_entrega(txt, ahora)
        return f"→ {formato_entrega(dt, ahora)} (en {formato_reloj((dt - ahora).total_seconds() / 3600)})"

    def pista_horas(txt: str) -> str:
        if not txt.strip():
            return "Tu mejor estimación. Ej.: 6 · 2,5 · 1h30. Súmale un tercio: casi siempre toma más."
        return f"→ {formato_horas(parse_horas(txt))}"

    def editar(t: Tarea | None):
        nueva = t is None
        campos = [
            ("nombre", "Entrega", "" if nueva else t.nombre, None),
            ("curso", "Curso (opcional)", "" if nueva else t.curso, None),
            ("entrega", "Fecha de entrega", "" if nueva else fecha_editable(t.entrega_dt), pista_fecha),
            ("estimadas", "Horas de trabajo en total", "" if nueva else horas_editables(t.horas_estimadas),
             pista_horas),
            ("hechas", "Horas ya trabajadas", "0" if nueva else horas_editables(t.horas_hechas), None),
            ("paso", "Siguiente paso", "" if nueva else t.siguiente_paso,
             lambda s: paso_vago(s) or "Bien: concreto y empezable."),
        ]

        def aceptar(v: dict) -> str | None:
            nombre = v["nombre"].strip()
            if not nombre:
                return "Ponle nombre a la entrega."
            try:
                dt = parse_entrega(v["entrega"], datetime.now())
                est = parse_horas(v["estimadas"])
                hechas = parse_horas(v["hechas"] or "0")
            except ValueError as exc:
                return str(exc)
            if est <= 0:
                return "Las horas totales tienen que ser más que cero."
            if nueva:
                tareas.append(Tarea(nombre=nombre, entrega=dt.isoformat(timespec="minutes"),
                                    horas_estimadas=est, horas_hechas=hechas, curso=v["curso"].strip(),
                                    siguiente_paso=v["paso"].strip()))
                if hechas:
                    registro.append({"fecha": datetime.now().isoformat(timespec="minutes"),
                                     "tarea": tareas[-1].id, "horas": hechas, "inicial": True})
                nuevo_id = tareas[-1].id
            else:
                t.nombre, t.curso = nombre, v["curso"].strip()
                t.entrega = dt.isoformat(timespec="minutes")
                t.horas_estimadas, t.horas_hechas = est, hechas
                t.siguiente_paso = v["paso"].strip()
                nuevo_id = t.id
            guardar()
            refrescar()
            if tree.exists(nuevo_id):
                tree.selection_set(nuevo_id)
                tree.see(nuevo_id)
            return None
        formulario("Nueva entrega" if nueva else "Editar entrega", campos, aceptar)

    def paso_hecho():
        t = seleccionada()
        if not t:
            return
        campos = [
            ("tiempo", "¿Cuánto le dedicaste? (opcional)", "", lambda s: "" if not s.strip()
             else f"→ se suman {formato_horas(parse_horas(s))}"),
            ("paso", "¿Cuál es el siguiente paso?", "",
             lambda s: paso_vago(s) or "Bien: concreto y empezable."),
        ]

        def aceptar(v: dict) -> str | None:
            try:
                horas = parse_horas(v["tiempo"]) if v["tiempo"].strip() else 0.0
            except ValueError as exc:
                return str(exc)
            if horas:
                registrar_horas(t, registro, horas, datetime.now())
            t.siguiente_paso = v["paso"].strip()
            guardar()
            refrescar()
            return None
        formulario(f"Paso hecho — {t.nombre}", campos, aceptar)

    def alternar_entregada():
        t = seleccionada()
        if t:
            t.entregada = not t.entregada
            guardar()
            refrescar()

    def eliminar():
        t = seleccionada()
        if t and messagebox.askyesno(APP_NAME, f"¿Eliminar «{t.nombre}»? No se puede deshacer.",
                                     parent=root):
            tareas.remove(t)
            guardar()
            refrescar()

    def al_cerrar():
        try:
            cfg["geometria"] = root.geometry()
            save_config(cfg, config_path)
        finally:
            root.destroy()

    root.protocol("WM_DELETE_WINDOW", al_cerrar)
    tic()
    if avisos_carga:
        root.after(300, lambda: messagebox.showwarning(APP_NAME, "\n\n".join(avisos_carga), parent=root))

    fallas: list[str] = []

    def reportar_excepcion(exc, val, tb):
        texto = "".join(traceback.format_exception(exc, val, tb))
        fallas.append(f"excepción en la interfaz: {val!r}")
        write_error_log("Excepción en la interfaz", texto)
        print(texto, file=sys.stderr)
    root.report_callback_exception = reportar_excepcion

    if smoke_ms:
        # Recorre la interfaz como lo haría una persona: crea una entrega,
        # marca un paso hecho y suma horas, rellenando los diálogos de verdad.
        def rellenar_dialogo(valores: list) -> None:
            dlgs = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
            if not dlgs:
                fallas.append("no se abrió el diálogo")
                return
            entradas, botones = [], []

            def recorrer(w):
                for c in w.winfo_children():
                    if isinstance(c, ttk.Entry):
                        entradas.append(c)
                    elif isinstance(c, ttk.Button):
                        botones.append(c)
                    recorrer(c)
            recorrer(dlgs[-1])
            for e, val in zip(entradas, valores):
                if val is not None:
                    e.delete(0, "end")
                    e.insert(0, val)
            next(b for b in botones if b.cget("text") == "Guardar").invoke()
            if dlgs[-1].winfo_exists():
                fallas.append(f"el diálogo no aceptó {valores}")
                dlgs[-1].destroy()

        def por_nombre(nombre: str) -> Tarea | None:
            return next((t for t in tareas if t.nombre == nombre), None)

        def paso1():
            editar(None)
            rellenar_dialogo(["Proyecto final", "IEE9999", "en 5 días 18:00", "10", "0",
                              "armar el índice del informe final"])
            t = por_nombre("Proyecto final")
            if not t or t.horas_estimadas != 10 or t.entrega_dt.hour != 18:
                fallas.append(f"la entrega nueva no quedó bien: {t}")

        def paso2():
            t = por_nombre("Tarea 3")
            tree.selection_set(t.id)
            root.update()
            if "Tarea 3" not in lbl_tit.cget("text"):
                fallas.append("el detalle no mostró la entrega elegida")
            paso_hecho()
            rellenar_dialogo(["45 min", "leer el enunciado completo y anotar dudas"])
            b_1h.invoke()
            if abs(t.horas_hechas - 1.75) > 1e-9 or not t.siguiente_paso.startswith("leer"):
                fallas.append(f"paso hecho / +1 h no se registraron: {t}")
            if horas_registradas_el(registro, datetime.now()) < 1.75 - 1e-9:
                fallas.append("el registro de hoy no sumó las horas")
            guardadas, _, _ = cargar_datos(data_path)
            if len(guardadas) != len(tareas):
                fallas.append("los cambios no quedaron guardados en disco")

        def paso3():
            # Editar y guardar sin tocar nada no debe mover nada, ni en una entrega vencida.
            t = por_nombre("Lectura paper")
            t.entrega = (datetime.now() - timedelta(days=3)).isoformat(timespec="minutes")
            t.horas_hechas = 1.75
            antes = (t.entrega, t.horas_estimadas, t.horas_hechas)
            tree.selection_set(t.id)
            editar(t)
            rellenar_dialogo([None] * 6)
            if (t.entrega, t.horas_estimadas, t.horas_hechas) != antes:
                fallas.append(f"editar sin cambios movió datos: {antes} → "
                              f"{(t.entrega, t.horas_estimadas, t.horas_hechas)}")

        def informe():
            root.update_idletasks()
            print(f"ventana {root.winfo_width()}x{root.winfo_height()}, "
                  f"{len(tree.get_children())} filas, resumen: {lbl_hoy.cget('text')}")
            print(f"detalle: {lbl_info.cget('text')}")
            for f in fallas:
                print(f"FALLA: {f}")
            print("interfaz: " + ("sin fallas." if not fallas else f"{len(fallas)} falla(s)."))
            root.destroy()
        root.after(400, paso1)
        root.after(800, paso2)
        root.after(1100, paso3)
        root.after(max(smoke_ms, 1500), informe)
    root.mainloop()
    return 1 if fallas else 0


# =====================================================================
# 10. Entrada
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
        ms = int(rest[0]) if rest and rest[0].isdigit() else 4000
        with tempfile.TemporaryDirectory() as tmp:
            datos = Path(tmp) / "datos.json"
            guardar_datos(datos, _datos_ejemplo(datetime.now()), [])
            return run_gui(smoke_ms=ms, data_path=datos, config_path=Path(tmp) / "cfg.json")
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
