"""bloqueo — bloquea sitios y cierra apps que distraen, por un tiempo fijo.

Los sitios se bloquean en el archivo hosts del sistema, dentro de una sección
marcada que se quita sola al vencer y deja el archivo exactamente como estaba.
Las apps de la lista se cierran cada vez que se abren mientras dure el bloqueo.
Salir antes es posible, pero a propósito incómodo: hay que escribir una frase
y esperar 30 segundos.

Necesita permisos de administrador (Windows) o root (Linux) para tocar hosts;
en Windows la app los pide sola al abrir.

Uso:
    python bloqueo.py              # interfaz gráfica
    python bloqueo.py --accesos    # crea los lanzadores de doble clic
    python bloqueo.py --estado     # dice si hay un bloqueo activo y hasta cuándo
    python bloqueo.py --limpiar    # quita un bloqueo ya vencido (no uno activo)
    python bloqueo.py --selftest   # prueba toda la lógica interna, sin GUI
    python bloqueo.py --guitest    # recorre la interfaz sobre un hosts de prueba

Si la aplicación no arranca, el detalle queda en bloqueo_error.log,
junto a este archivo.
"""

from __future__ import annotations

import base64
import csv
import io
import json
import os
import queue
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

APP_NAME = "bloqueo"
APP_VERSION = "1.0"
APP_COMMENT = "Bloquea sitios y apps que distraen por un tiempo fijo"
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
RESPALDO_PATH = DATA_DIR / f"{APP_NAME}_hosts_respaldo.txt"
ERROR_LOG_PATH = DATA_DIR / f"{APP_NAME}_error.log"


def hosts_path() -> Path:
    """El hosts del sistema. BLOQUEO_HOSTS lo reemplaza (solo para pruebas)."""
    if os.environ.get("BLOQUEO_HOSTS"):
        return Path(os.environ["BLOQUEO_HOSTS"])
    if IS_WINDOWS:
        # drivers\etc está exento de la redirección WOW64: vale también con Python de 32 bits
        return Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "drivers" / "etc" / "hosts"
    return Path("/etc/hosts")


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
# 2. El archivo hosts: una sección marcada que entra y sale sin tocar
#    nada más. Quitarla devuelve el archivo idéntico, byte a byte.
# =====================================================================

MARCA_INICIO = "# >>> bloqueo-anti-procrastinacion"
MARCA_FIN = "# <<< bloqueo-anti-procrastinacion <<<"
COMENTARIO = "# Bloqueo temporal de bloqueo.py: se quita solo al vencer. Para salir antes, usa la app."
_ENTRADA = re.compile(r"^(?:0\.0\.0\.0|::)\s+(\S+)\s*$")
_ATRIBUTO = re.compile(r"(\w+)=(\S+)")


def detectar_eol(texto: str) -> str:
    if "\r\n" in texto:
        return "\r\n"
    if "\n" in texto:
        return "\n"
    return "\r\n" if IS_WINDOWS else "\n"


def quitar_bloqueo(texto: str) -> tuple[str, dict | None]:
    """Quita la(s) sección(es) de bloqueo. Devuelve (texto limpio, info de la última).

    info = {"hasta": datetime | None, "desde": datetime | None, "dominios": [...]}.
    Si alguien borró la marca de fin, solo se quitan las líneas que son
    claramente de esta app, nunca lo que venga después.
    """
    lineas = texto.splitlines(keepends=True)
    out: list[str] = []
    info: dict | None = None
    i = 0
    while i < len(lineas):
        if not lineas[i].strip().startswith(MARCA_INICIO):
            out.append(lineas[i])
            i += 1
            continue
        attrs = dict(_ATRIBUTO.findall(lineas[i]))
        fin = next((j for j in range(i + 1, len(lineas)) if lineas[j].strip() == MARCA_FIN), None)
        if fin is None:
            fin = i
            while fin + 1 < len(lineas) and (_ENTRADA.match(lineas[fin + 1].strip())
                                            or lineas[fin + 1].strip() == COMENTARIO):
                fin += 1
        dominios: list[str] = []
        for ln in lineas[i + 1:fin + 1]:
            m = _ENTRADA.match(ln.strip())
            if m and m.group(1) not in dominios:
                dominios.append(m.group(1))
        info = {"hasta": _fecha_o_none(attrs.get("hasta")), "desde": _fecha_o_none(attrs.get("desde")),
                "dominios": dominios}
        if attrs.get("nl") == "1" and out:
            # al bloquear se agregó un salto a la última línea original: se devuelve
            if out[-1].endswith("\r\n"):
                out[-1] = out[-1][:-2]
            elif out[-1].endswith("\n"):
                out[-1] = out[-1][:-1]
        i = fin + 1
    return "".join(out), info


def _fecha_o_none(s: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(s) if s else None
    except ValueError:
        return None


def aplicar_bloqueo(texto: str, dominios: list[str], desde: datetime, hasta: datetime) -> str:
    """Agrega la sección al final (reemplazando una anterior si la hay)."""
    base, _ = quitar_bloqueo(texto)
    eol = detectar_eol(base)
    nl = "1" if base and not base.endswith("\n") else "0"
    lineas = [f"{MARCA_INICIO} desde={desde.isoformat(timespec='seconds')} "
              f"hasta={hasta.isoformat(timespec='seconds')} nl={nl} >>>", COMENTARIO]
    for d in dominios:
        lineas += [f"0.0.0.0 {d}", f":: {d}"]  # también IPv6, si no el navegador lo intenta por ahí
    lineas.append(MARCA_FIN)
    return base + (eol if nl == "1" else "") + eol.join(lineas) + eol


def estado_bloqueo(texto: str) -> dict | None:
    return quitar_bloqueo(texto)[1]


def leer_hosts(path: Path) -> str:
    # latin-1 ida y vuelta conserva cualquier byte: nunca se «corrige» la codificación del original
    return Path(path).read_bytes().decode("latin-1")


def escribir_hosts(path: Path, texto: str) -> None:
    """Escribe en el mismo archivo (conserva permisos y ACL; no crea uno nuevo)."""
    data = texto.encode("latin-1")
    with open(path, "r+b") as fh:
        fh.seek(0)
        fh.write(data)
        fh.truncate()


def puede_escribir(path: Path) -> bool:
    """Abre para escritura sin escribir nada: la prueba más honesta en Windows y Linux."""
    try:
        with open(path, "r+b"):
            return True
    except OSError:
        return False


def bloquear_archivo(path: Path, dominios: list[str], desde: datetime, hasta: datetime,
                     respaldo: Path | None = None) -> None:
    original = leer_hosts(path)
    if respaldo is not None and estado_bloqueo(original) is None:
        try:
            respaldo.write_bytes(original.encode("latin-1"))
        except Exception:
            pass
    escribir_hosts(path, aplicar_bloqueo(original, dominios, desde, hasta))


def desbloquear_archivo(path: Path) -> dict | None:
    texto = leer_hosts(path)
    limpio, info = quitar_bloqueo(texto)
    if info is not None:
        escribir_hosts(path, limpio)
    return info


def limpiar_si_vencido(path: Path, ahora: datetime) -> dict | None:
    """Quita el bloqueo solo si ya venció (o si su fecha es ilegible). Devuelve su info."""
    info = estado_bloqueo(leer_hosts(path))
    if info is None:
        return None
    if info["hasta"] is None or info["hasta"] <= ahora:
        return desbloquear_archivo(path)
    return None


def vaciar_cache_dns() -> bool:
    if not IS_WINDOWS and not es_admin():
        return False  # sin root no se puede, y resolvectl podría quedarse esperando una contraseña
    cmds = [["ipconfig", "/flushdns"]] if IS_WINDOWS else \
        [["resolvectl", "flush-caches"], ["systemd-resolve", "--flush-caches"]]
    for c in cmds:
        try:
            if subprocess.run(c, capture_output=True, timeout=20, creationflags=NO_WINDOW).returncode == 0:
                return True
        except Exception:
            continue
    return False


# =====================================================================
# 3. Sitios: de lo que pega una persona a un dominio limpio
# =====================================================================

SITIOS_POR_OMISION = ["instagram.com", "tiktok.com", "x.com", "reddit.com", "facebook.com", "twitch.tv"]
# hosts no acepta comodines: los subdominios que importan se agregan a mano.
EXTRAS = {
    "youtube.com": ["youtu.be", "music.youtube.com"],
    "x.com": ["twitter.com", "www.twitter.com", "mobile.twitter.com", "mobile.x.com"],
    "twitter.com": ["x.com", "www.x.com", "mobile.twitter.com", "mobile.x.com"],
    "reddit.com": ["old.reddit.com", "new.reddit.com", "np.reddit.com"],
    "facebook.com": ["web.facebook.com", "fb.com", "www.fb.com"],
    "instagram.com": ["l.instagram.com"],
    "tiktok.com": ["vm.tiktok.com"],
    "twitch.tv": ["clips.twitch.tv"],
}
_ETIQUETA = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")


def normalizar_dominio(texto: str) -> str:
    t = texto.strip().lower()
    if not t:
        raise ValueError("Escribe un sitio, por ejemplo instagram.com.")
    t = re.sub(r"^[a-z][a-z0-9+.-]*://", "", t)
    t = re.split(r"[/?#]", t, maxsplit=1)[0]
    t = t.rsplit("@", 1)[-1]
    t = re.sub(r":\d+$", "", t).strip(".")
    for pref in ("www.", "m."):
        if t.startswith(pref) and t.count(".") >= 2:
            t = t[len(pref):]
    try:
        t = t.encode("idna").decode("ascii")
    except UnicodeError:
        raise ValueError(f"«{texto.strip()}» no parece un sitio web.") from None
    etiquetas = t.split(".")
    if len(etiquetas) < 2 or not all(_ETIQUETA.match(e) for e in etiquetas) or etiquetas[-1].isdigit():
        raise ValueError(f"«{texto.strip()}» no parece un sitio web.")
    if t in ("localhost", "localdomain"):
        raise ValueError("localhost no se bloquea: rompería programas del propio equipo.")
    return t


def expandir(dominio: str) -> list[str]:
    out: list[str] = []
    for d in [dominio, "www." + dominio, "m." + dominio] + EXTRAS.get(dominio, []):
        if d not in out:
            out.append(d)
    return out


def expandir_todos(dominios: list[str]) -> list[str]:
    out: list[str] = []
    for d in dominios:
        for e in expandir(d):
            if e not in out:
                out.append(e)
    return out


# =====================================================================
# 4. Procesos: listar, elegir y cerrar (por PID, nunca por nombre a ciegas)
# =====================================================================

PROTEGIDOS = {"explorer", "svchost", "csrss", "winlogon", "wininit", "lsass", "services", "smss", "dwm",
              "system", "registry", "taskmgr", "conhost", "fontdrvhost", "sihost", "ctfmon",
              "python", "pythonw", "py", "pyw", "cmd", "powershell", "pwsh", "windowsterminal",
              "systemd", "init", "xorg", "xwayland", "gnome-shell", "kwin_x11", "kwin_wayland",
              "plasmashell", "sshd", "bash", "sh", "zsh", "fish", "login", "sudo", "dbus-daemon"}


def nombre_base(nombre: str) -> str:
    n = Path(nombre.strip().strip('"').replace("\\", "/")).name.lower()
    return n[:-4] if n.endswith(".exe") else n


def validar_app(texto: str) -> str:
    n = nombre_base(texto)
    if not n:
        raise ValueError("Escribe el nombre del programa, por ejemplo discord o steam.exe.")
    if not re.fullmatch(r"[\w .+-]{1,80}", n):
        raise ValueError(f"«{texto.strip()}» no parece un nombre de programa.")
    if n in PROTEGIDOS:
        raise ValueError(f"«{n}» es parte del sistema o de esta misma app: cerrarlo rompería algo.")
    return n


def parse_tasklist_csv(texto: str) -> list[tuple[int, str]]:
    """Salida de «tasklist /FO CSV /NH»: "imagen","PID","sesión","#","memoria"."""
    out = []
    for fila in csv.reader(io.StringIO(texto)):
        if len(fila) >= 2 and fila[1].strip().isdigit():
            out.append((int(fila[1]), fila[0]))
    return out


def parse_ps(texto: str) -> list[tuple[int, str]]:
    """Salida de «ps -A -o pid=,comm=»."""
    out = []
    for ln in texto.splitlines():
        partes = ln.strip().split(None, 1)
        if len(partes) == 2 and partes[0].isdigit():
            out.append((int(partes[0]), partes[1].strip()))
    return out


def listar_procesos() -> list[tuple[int, str]]:
    if IS_WINDOWS:
        r = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, timeout=30,
                           creationflags=NO_WINDOW)
        for cod in ("oem", "mbcs", "latin-1"):
            try:
                return parse_tasklist_csv(r.stdout.decode(cod, errors="replace"))
            except LookupError:
                continue
        return []
    r = subprocess.run(["ps", "-A", "-o", "pid=,comm="], capture_output=True, timeout=30)
    return parse_ps(r.stdout.decode("utf-8", errors="replace"))


def a_cerrar(procesos: list[tuple[int, str]], objetivos: list[str], excluir: set[int]) -> list[tuple[int, str]]:
    """Qué PIDs cerrar. En Linux «comm» se corta a 15 caracteres: se compara igual."""
    obj = {nombre_base(o) for o in objetivos}
    out = []
    for pid, nombre in procesos:
        if pid in excluir:
            continue
        n = nombre_base(nombre)
        if n in PROTEGIDOS:
            continue
        if n in obj or (len(n) == 15 and any(o.startswith(n) for o in obj)):
            out.append((pid, nombre))
    return out


def cerrar_pid(pid: int) -> bool:
    try:
        if IS_WINDOWS:
            r = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=30,
                               creationflags=NO_WINDOW)
            return r.returncode == 0
        os.kill(pid, signal.SIGTERM)
        return True
    except Exception:
        return False


def es_admin() -> bool:
    try:
        if IS_WINDOWS:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        return os.geteuid() == 0
    except Exception:
        return False


def relanzar_como_admin() -> bool:
    """Windows: vuelve a abrir la app pidiendo permisos (UAC). True si se aceptó."""
    if not IS_WINDOWS:
        return False
    try:
        import ctypes
        _, exe_w = _interpretes()
        r = ctypes.windll.shell32.ShellExecuteW(None, "runas", str(exe_w or sys.executable),
                                                f'"{Path(__file__).resolve()}"', str(APP_DIR), 1)
        return int(r) > 32
    except Exception:
        return False


# =====================================================================
# 5. La salida de emergencia: posible, pero con fricción
# =====================================================================

FRASE = "Prefiero distraerme ahora aunque después me pese"


def normalizar_frase(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^\w\s]", " ", s).split())


def frase_correcta(escrito: str) -> bool:
    return normalizar_frase(escrito) == normalizar_frase(FRASE)


def calcular_hasta(ahora: datetime, minutos: int | None = None, hora: str | None = None) -> datetime:
    """Fin del bloqueo por duración o por «hasta las HH:MM» (si ya pasó, es mañana)."""
    if hora:
        m = re.fullmatch(r"\s*(\d{1,2})(?::|h|\.)(\d{2})\s*", hora)
        if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
            raise ValueError("Escribe la hora como 18:30.")
        fin = ahora.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
        if fin <= ahora:
            fin += timedelta(days=1)
    else:
        fin = ahora + timedelta(minutes=minutos or 0)
    duracion = (fin - ahora).total_seconds() / 60
    if duracion < 1:
        raise ValueError("El bloqueo tiene que durar al menos un minuto.")
    if duracion > 12 * 60:
        raise ValueError("Máximo 12 horas: un error de tipeo no debería dejarte sin internet hasta mañana.")
    return fin


# =====================================================================
# 6. Registro (CSV con «;», que es lo que Excel en español abre directo)
# =====================================================================

CAMPOS = ["inicio", "fin_planeado", "fin_real", "minutos", "salida", "sitios", "apps", "apps_cerradas"]


def anotar_bloqueo(path: Path, fila: dict) -> None:
    nuevo = not path.exists() or path.stat().st_size == 0
    with open(path, "a", encoding="utf-8-sig" if nuevo else "utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CAMPOS, delimiter=";", extrasaction="ignore")
        if nuevo:
            w.writeheader()
        w.writerow({k: fila.get(k, "") for k in CAMPOS})


def leer_registro(path: Path) -> list[dict]:
    try:
        with open(path, encoding="utf-8-sig", newline="") as fh:
            return [r for r in csv.DictReader(fh, delimiter=";") if r.get("salida")]
    except Exception:
        return []


# =====================================================================
# 7. Lanzadores de doble clic
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
        "rem La app pide permisos de administrador sola (los necesita para el archivo hosts).\r\n"
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
          "# Necesita root para /etc/hosts: lo pide con pkexec si esta disponible.\n"
          'cd "$(dirname "$0")" || exit 1\n'
          'if [ "$(id -u)" -ne 0 ] && command -v pkexec >/dev/null 2>&1; then\n'
          '  exec pkexec env DISPLAY="$DISPLAY" XAUTHORITY="$XAUTHORITY" '
          f'python3 "$(pwd)/{app.name}" "$@"\n'
          "fi\n"
          f'exec python3 "{app.name}" "$@"\n')
    desktop = ("[Desktop Entry]\n"
               "Type=Application\n"
               f"Name={APP_NAME}\n"
               f"Comment={APP_COMMENT}\n"
               f"Exec=\"{folder / (APP_NAME + '.sh')}\"\n"
               f"Path={folder}\n"
               "Icon=security-high\n"
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


def marcar_lnk_como_admin(link: Path) -> bool:
    """Activa «Ejecutar como administrador» en un .lnk: bit SLDF_RUNAS_USER (0x2000)
    de LinkFlags, que vive en el byte 0x15 del archivo."""
    try:
        data = bytearray(link.read_bytes())
        if len(data) < 0x16 or data[:4] != b"\x4c\x00\x00\x00":
            return False
        data[0x15] |= 0x20
        link.write_bytes(bytes(data))
        return True
    except Exception:
        return False


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
    if not link.exists():
        return None
    marcar_lnk_como_admin(link)
    return link


def create_launchers(folder: Path | None = None, desktop: bool = True) -> tuple[list[Path], list[str]]:
    """Windows: .bat (arranca con pythonw, sin consola) + acceso directo en el
    Escritorio que ya abre como administrador. Linux: .sh + .desktop."""
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
# 8. Configuración
# =====================================================================

DEFAULT_CONFIG = {"sitios": list(SITIOS_POR_OMISION), "apps": [], "minutos": 50,
                  "apps_bloque": [], "geometria": ""}


def load_config(path: Path = CONFIG_PATH) -> dict:
    data = json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        if path.exists():
            saved = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                for k, v in saved.items():
                    if k in DEFAULT_CONFIG and type(v) is type(DEFAULT_CONFIG[k]):
                        data[k] = v
    except Exception:
        pass
    sitios = []
    for s in data["sitios"]:
        try:
            d = normalizar_dominio(str(s))
            if d not in sitios:
                sitios.append(d)
        except ValueError:
            continue
    data["sitios"] = sitios
    for clave in ("apps", "apps_bloque"):
        apps = []
        for a in data[clave]:
            try:
                n = validar_app(str(a))
                if n not in apps:
                    apps.append(n)
            except ValueError:
                continue
        data[clave] = apps
    if not 1 <= data["minutos"] <= 720:
        data["minutos"] = DEFAULT_CONFIG["minutos"]
    return data


def save_config(data: dict, path: Path = CONFIG_PATH) -> None:
    try:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


# =====================================================================
# 9. Autoprueba (--selftest)
# =====================================================================

def run_selftest() -> int:
    checks: list[tuple[bool, str]] = []

    def check(cond: bool, label: str) -> None:
        checks.append((bool(cond), label))

    # --- dominios ---
    for texto, esperado in {"instagram.com": "instagram.com", "https://www.YouTube.com/watch?v=x": "youtube.com",
                            "m.facebook.com/": "facebook.com", "http://user@reddit.com:443/r/x": "reddit.com",
                            " www.x.com ": "x.com", "ñandú.cl": "xn--and-6ma2c.cl", "news.ycombinator.com":
                            "news.ycombinator.com", "www.bbc.co.uk": "bbc.co.uk"}.items():
        try:
            obtenido = normalizar_dominio(texto)
        except Exception as exc:
            obtenido = exc
        check(obtenido == esperado, f"dominio «{texto}» → {esperado} (obtuve {obtenido})")
    for malo in ("", "youtube", "192.168.0.1", "localhost", "-malo-.com", "con espacio.com", "a..com"):
        try:
            normalizar_dominio(malo)
            check(False, f"dominio inválido «{malo}» rechazado")
        except ValueError:
            check(True, f"dominio inválido «{malo}» rechazado")
    check(expandir("x.com")[:3] == ["x.com", "www.x.com", "m.x.com"] and "twitter.com" in expandir("x.com"),
          "x.com se expande con www, m y twitter.com")
    todos = expandir_todos(["x.com", "twitter.com"])
    check(len(todos) == len(set(todos)), "expandir varios no repite dominios")

    # --- hosts: ida y vuelta exacta ---
    desde = datetime(2026, 10, 9, 15, 0, 0)
    hasta = datetime(2026, 10, 9, 15, 50, 0)
    originales = {
        "vacío": "",
        "LF": "127.0.0.1 localhost\n::1 localhost\n",
        "LF sin salto final": "127.0.0.1 localhost\n::1 localhost",
        "CRLF": "# Copyright (c) Microsoft Corp.\r\n#\r\n127.0.0.1 localhost\r\n",
        "CRLF sin salto final": "# Copyright\r\n127.0.0.1 localhost",
        "una línea sin salto": "127.0.0.1 localhost",
        "bytes raros": "# caf\xe9 \xf1and\xfa \xff\n10.0.0.5 nas.local  # mi NAS\n",
        "líneas en blanco al final": "127.0.0.1 localhost\n\n\n",
    }
    sitios = expandir_todos(["instagram.com", "x.com"])
    for nombre, orig in originales.items():
        bloqueado = aplicar_bloqueo(orig, sitios, desde, hasta)
        info = estado_bloqueo(bloqueado)
        check(info is not None and info["hasta"] == hasta and info["desde"] == desde,
              f"[{nombre}] la sección guarda desde y hasta")
        check(info is not None and info["dominios"] == sitios, f"[{nombre}] la sección lista los dominios")
        check(bloqueado.startswith(orig.rstrip("\r\n")), f"[{nombre}] lo original queda intacto arriba")
        eol = detectar_eol(orig)
        if orig:
            check(eol not in ("\r\n",) or "\n" not in bloqueado.replace("\r\n", ""),
                  f"[{nombre}] respeta el fin de línea del archivo")
        dos_veces = aplicar_bloqueo(bloqueado, sitios, desde, hasta + timedelta(minutes=25))
        check(dos_veces.count(MARCA_INICIO) == 1 and estado_bloqueo(dos_veces)["hasta"] ==
              hasta + timedelta(minutes=25), f"[{nombre}] extender reemplaza la sección, no la duplica")
        limpio, _ = quitar_bloqueo(dos_veces)
        check(limpio == orig, f"[{nombre}] quitar el bloqueo devuelve el archivo byte a byte")
    check(quitar_bloqueo("127.0.0.1 localhost\n") == ("127.0.0.1 localhost\n", None),
          "sin sección: no cambia nada")

    orig = "127.0.0.1 localhost\n"
    b = aplicar_bloqueo(orig, sitios, desde, hasta) + "10.0.0.9 impresora\n"
    check(quitar_bloqueo(b)[0] == orig + "10.0.0.9 impresora\n",
          "líneas agregadas después del bloqueo por otra persona se conservan")
    sin_fin = aplicar_bloqueo(orig, sitios, desde, hasta).replace(MARCA_FIN + "\n", "") + "10.0.0.9 impresora\n"
    check(quitar_bloqueo(sin_fin)[0] == orig + "10.0.0.9 impresora\n",
          "si borraron la marca de fin, solo se quitan las líneas propias")
    check("0.0.0.0 instagram.com" in b and ":: instagram.com" in b, "bloquea por IPv4 y por IPv6")

    # --- hosts: sobre archivos reales en una carpeta temporal ---
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        h = tmp / "hosts"
        original = "# Copyright\r\n127.0.0.1 localhost\r\n\xe9".encode("latin-1")
        h.write_bytes(original)
        respaldo = tmp / "respaldo.txt"
        check(puede_escribir(h), "puede_escribir en un archivo propio")
        check(not puede_escribir(tmp / "no-existe"), "puede_escribir no crea archivos")
        bloquear_archivo(h, sitios, desde, hasta, respaldo)
        check(respaldo.read_bytes() == original, "se guarda un respaldo del hosts original")
        check(estado_bloqueo(leer_hosts(h))["hasta"] == hasta, "el archivo queda bloqueado")
        bloquear_archivo(h, sitios, desde, hasta + timedelta(minutes=5), respaldo)
        check(respaldo.read_bytes() == original, "extender no pisa el respaldo con un hosts ya bloqueado")
        check(limpiar_si_vencido(h, hasta - timedelta(seconds=1)) is None
              and estado_bloqueo(leer_hosts(h)) is not None, "antes de vencer, limpiar no toca nada")
        info = limpiar_si_vencido(h, hasta + timedelta(minutes=5))
        check(info is not None and h.read_bytes() == original, "al vencer se quita y el archivo vuelve idéntico")
        check(limpiar_si_vencido(h, hasta + timedelta(days=1)) is None, "limpiar dos veces no hace nada")
        bloquear_archivo(h, sitios, desde, hasta)
        check(desbloquear_archivo(h) is not None and h.read_bytes() == original, "desbloqueo manual exacto")
        h.write_bytes(original + f"\r\n{MARCA_INICIO} hasta=basura nl=0 >>>\r\n0.0.0.0 x.com\r\n{MARCA_FIN}\r\n"
                      .encode("latin-1"))
        check(limpiar_si_vencido(h, desde) is not None and h.read_bytes() == original + b"\r\n",
              "una sección con fecha ilegible se considera vencida")
        if IS_WINDOWS or os.geteuid() != 0:  # root escribe aunque el archivo sea de solo lectura
            ro = tmp / "solo_lectura"
            ro.write_text("x")
            os.chmod(ro, 0o444)
            check(not puede_escribir(ro), "puede_escribir detecta un archivo de solo lectura")
            os.chmod(ro, 0o644)

        # --- registro ---
        reg = tmp / "registro.csv"
        anotar_bloqueo(reg, {"inicio": desde.isoformat(), "fin_planeado": hasta.isoformat(),
                             "fin_real": hasta.isoformat(), "minutos": 50, "salida": "completo",
                             "sitios": "x.com instagram.com", "apps": "discord", "apps_cerradas": 2})
        anotar_bloqueo(reg, {"inicio": desde.isoformat(), "salida": "emergencia", "sitios": "a; b"})
        filas = leer_registro(reg)
        check([f["salida"] for f in filas] == ["completo", "emergencia"] and filas[1]["sitios"] == "a; b",
              "registro CSV de bloqueos ida y vuelta")
        check(reg.read_bytes().count(b"\xef\xbb\xbf") == 1, "el CSV lleva un solo BOM")

        # --- config ---
        cfg = tmp / "cfg.json"
        cfg.write_text(json.dumps({"sitios": ["https://www.Instagram.com/", "instagram.com", "malo", 3],
                                   "apps": ["Discord.exe", "explorer", "C:\\Games\\Steam\\steam.exe"],
                                   "minutos": 5000}), encoding="utf-8")
        c = load_config(cfg)
        check(c["sitios"] == ["instagram.com"] and c["apps"] == ["discord", "steam"] and c["minutos"] == 50,
              f"config se limpia al cargar ({c})")

        # --- lanzadores ---
        created, problems = create_launchers(tmp, desktop=False)
        names = {c.name for c in created}
        check(names == {"bloqueo.bat", "bloqueo.sh", "bloqueo.desktop"}, f"lanzadores creados: {sorted(names)}")
        check(not problems, f"lanzadores sin problemas: {problems}")
        check(b"\r\n" in (tmp / "bloqueo.bat").read_bytes(), "el .bat usa CRLF")
        sh = (tmp / "bloqueo.sh").read_text()
        check("pkexec" in sh and "\r" not in sh, "el .sh pide root con pkexec")
        lnk = tmp / "falso.lnk"
        lnk.write_bytes(b"\x4c\x00\x00\x00" + bytes(0x20))
        check(marcar_lnk_como_admin(lnk) and lnk.read_bytes()[0x15] & 0x20, "el .lnk queda marcado como admin")
        lnk.write_bytes(b"no es un lnk")
        check(not marcar_lnk_como_admin(lnk), "un archivo que no es .lnk no se toca")

    # --- procesos ---
    tl = ('"System Idle Process","0","Services","0","8 K"\r\n'
          '"Discord.exe","4242","Console","1","120.000 K"\r\n'
          '"Some, App.exe","77","Console","1","1.000 K"\r\n'
          '"explorer.exe","900","Console","1","90.000 K"\r\n'
          'INFO: basura\r\n')
    procs = parse_tasklist_csv(tl)
    check(procs == [(0, "System Idle Process"), (4242, "Discord.exe"), (77, "Some, App.exe"),
                    (900, "explorer.exe")], f"lee la salida de tasklist ({procs})")
    ps = "    1 systemd\n 4242 Discord\n 5000 steamwebhelper\n 6001 un_nombre_muy_l\n basura\n"
    procs_l = parse_ps(ps)
    check(procs_l == [(1, "systemd"), (4242, "Discord"), (5000, "steamwebhelper"), (6001, "un_nombre_muy_l")],
          f"lee la salida de ps ({procs_l})")
    objetivo = a_cerrar(procs + procs_l, ["discord", "steam", "un_nombre_muy_largo", "explorer"], {77})
    check(objetivo == [(4242, "Discord.exe"), (4242, "Discord"), (6001, "un_nombre_muy_l")],
          f"elige qué cerrar: sin mayúsculas, sin .exe, nombres cortados por Linux, nunca explorer ({objetivo})")
    check(a_cerrar([(os.getpid(), "discord")], ["discord"], {os.getpid()}) == [], "nunca se cierra a sí misma")
    for texto, esperado in {"Discord.exe": "discord", "C:\\Program Files\\Steam\\steam.exe": "steam",
                            "  lol  ": "lol", "/usr/bin/spotify": "spotify"}.items():
        check(validar_app(texto) == esperado, f"app «{texto}» → {esperado}")
    for malo in ("", "explorer.exe", "python", "svchost", "a|b"):
        try:
            validar_app(malo)
            check(False, f"app «{malo}» rechazada")
        except ValueError:
            check(True, f"app «{malo}» rechazada")

    # De verdad: el sistema lista procesos, y un proceso hijo se encuentra y se cierra por PID.
    try:
        reales = listar_procesos()
        check(any(pid == os.getpid() for pid, _ in reales), f"listar_procesos encuentra este proceso "
                                                             f"({len(reales)} procesos)")
        hijo = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                creationflags=NO_WINDOW)
        try:
            check(any(pid == hijo.pid for pid, _ in listar_procesos()), "listar_procesos ve un proceso nuevo")
            check(cerrar_pid(hijo.pid), "cerrar_pid informa éxito")
            try:
                hijo.wait(timeout=15)
                check(True, "el proceso cerrado terminó de verdad")
            except subprocess.TimeoutExpired:
                check(False, "el proceso cerrado terminó de verdad")
        finally:
            if hijo.poll() is None:
                hijo.kill()
    except Exception as exc:
        check(False, f"procesos reales: {exc!r}")

    # --- emergencia y duración ---
    check(frase_correcta(FRASE), "la frase exacta sirve")
    check(frase_correcta("  prefiero DISTRAERME ahora, aunque despues   me pese. "),
          "la frase sin tildes, con mayúsculas, comas y espacios de más también")
    check(not frase_correcta("prefiero distraerme ahora"), "media frase no sirve")
    check(not frase_correcta(""), "vacío no sirve")
    ahora = datetime(2026, 10, 9, 15, 20, 30)
    check(calcular_hasta(ahora, minutos=50) == datetime(2026, 10, 9, 16, 10, 30), "50 minutos desde ahora")
    check(calcular_hasta(ahora, hora="18:30") == datetime(2026, 10, 9, 18, 30), "hasta las 18:30 de hoy")
    check(calcular_hasta(ahora, hora="1h00") == datetime(2026, 10, 10, 1, 0), "hasta la 1:00 de mañana")
    for kw in ({"minutos": 0}, {"minutos": 721}, {"hora": "25:00"}, {"hora": "15:20"}, {"hora": "mañana"},
               {"hora": "9:00"}):
        try:
            calcular_hasta(ahora, **kw)
            check(False, f"duración inválida {kw} rechazada")
        except ValueError:
            check(True, f"duración inválida {kw} rechazada")

    fallidas = [label for ok, label in checks if not ok]
    for label in fallidas:
        print(f"FALLA: {label}")
    print(f"{len(checks) - len(fallidas)}/{len(checks)} comprobaciones correctas.")
    return 0 if not fallidas else 1


# =====================================================================
# 10. Interfaz gráfica (tkinter)
# =====================================================================

def run_gui(smoke_ms: int = 0, dir_datos: Path | None = None, seg_por_min: float = 60.0) -> int:
    """smoke_ms > 0: recorre la interfaz sobre un hosts de prueba y se cierra sola.
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

    hosts = hosts_path()
    # Sin permisos en Windows: pedirlos de entrada (UAC) en vez de dejar a medias.
    if IS_WINDOWS and not smoke_ms and not puede_escribir(hosts) and not es_admin():
        if relanzar_como_admin():
            return 0

    if IS_WINDOWS:
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    if dir_datos:
        config_path, registro_path, respaldo_path = (dir_datos / "cfg.json", dir_datos / "registro.csv",
                                                     dir_datos / "respaldo.txt")
    else:
        config_path, registro_path, respaldo_path = CONFIG_PATH, REGISTRO_PATH, RESPALDO_PATH
    cfg = load_config(config_path)
    espera_emergencia = 30 * seg_por_min / 60  # 30 s reales

    root = tk.Tk()
    root.title(APP_NAME)
    try:
        root.tk.call("tk", "scaling", root.winfo_fpixels("1i") / 72.0)
    except Exception:
        pass
    root.minsize(600, 600)
    root.geometry(cfg["geometria"] if (cfg["geometria"] and not smoke_ms) else "660x700")
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
    f_estado = base.copy()
    f_estado.configure(size=tam + 6, weight="bold")
    f_frase = base.copy()
    f_frase.configure(size=tam + 1, slant="italic")
    fondo = style.lookup("TFrame", "background") or root.cget("bg")

    st = {"activo": False, "desde": None, "hasta": None, "cerradas": 0, "hilo": False,
          "emergencia_fin": None, "ultimo_vigilar": 0.0, "reintento": 0.0}
    cola: queue.Queue = queue.Queue()
    fallas: list[str] = []

    # ---------- aviso de permisos ----------
    aviso = tk.Frame(root, bg="#fde7c2", padx=12, pady=8)
    lbl_aviso = tk.Label(aviso, bg="#fde7c2", fg="#5a3900", justify="left", wraplength=560)
    lbl_aviso.pack(side="left", fill="x", expand=True)
    b_admin = ttk.Button(aviso, text="Abrir como administrador", command=lambda: pedir_admin())

    def pedir_admin():
        if relanzar_como_admin():
            root.destroy()

    def revisar_permisos() -> bool:
        ok = puede_escribir(hosts)
        if ok:
            aviso.pack_forget()
            return True
        if IS_WINDOWS:
            txt = (f"Sin permiso para modificar {hosts}. Para bloquear sitios, la app necesita "
                   "abrirse como administrador. Si ya lo es, puede que el archivo esté marcado como "
                   "de solo lectura o que un antivirus lo proteja.")
            b_admin.pack(side="right", padx=(10, 0))
        else:
            txt = (f"Sin permiso para modificar {hosts}. Ábrela con el lanzador bloqueo.sh "
                   "(pide la contraseña) o con: sudo -E python3 bloqueo.py")
        lbl_aviso.configure(text=txt)
        aviso.pack(fill="x", before=cab)
        return False

    # ---------- estado ----------
    cab = ttk.Frame(root, padding=(16, 12, 16, 4))
    cab.pack(fill="x")
    lbl_estado = tk.Label(cab, font=f_estado, bg=fondo, fg="#333", anchor="w")
    lbl_estado.pack(fill="x")
    lbl_sub = ttk.Label(cab, foreground="#555", wraplength=620, justify="left")
    lbl_sub.pack(fill="x")

    # ---------- listas ----------
    listas = ttk.Frame(root, padding=(16, 6))
    listas.pack(fill="both", expand=True)
    listas.columnconfigure(0, weight=1, uniform="col")
    listas.columnconfigure(1, weight=1, uniform="col")
    listas.rowconfigure(0, weight=1)

    def columna(col: int, titulo: str, pista: str):
        marco = ttk.LabelFrame(listas, text=titulo, padding=8)
        marco.grid(row=0, column=col, sticky="nsew", padx=(0, 8) if col == 0 else (8, 0))
        lb = tk.Listbox(marco, height=8, activestyle="none", exportselection=False)
        lb.pack(fill="both", expand=True)
        var = tk.StringVar()
        entrada = ttk.Combobox(marco, textvariable=var) if col == 1 else ttk.Entry(marco, textvariable=var)
        entrada.pack(fill="x", pady=(6, 0))
        lbl_p = ttk.Label(marco, text=pista, foreground="#666", wraplength=270, justify="left")
        lbl_p.pack(fill="x")
        fila = ttk.Frame(marco)
        fila.pack(fill="x", pady=(4, 0))
        b_add = ttk.Button(fila, text="Agregar")
        b_add.pack(side="left")
        b_del = ttk.Button(fila, text="Quitar")
        b_del.pack(side="left", padx=(6, 0))
        return lb, var, entrada, lbl_p, b_add, b_del

    lb_sitios, var_sitio, e_sitio, lbl_ps, b_add_s, b_del_s = columna(
        0, "Sitios", "Pega una dirección o escribe el dominio. Se bloquean también www. y m.")
    lb_apps, var_app, e_app, lbl_pa, b_add_a, b_del_a = columna(
        1, "Apps que se cierran", "Nombre del programa (discord, steam). Despliega para ver los abiertos.")

    def pintar_listas():
        lb_sitios.delete(0, "end")
        for s in cfg["sitios"]:
            lb_sitios.insert("end", s)
        lb_apps.delete(0, "end")
        for a in (cfg["apps_bloque"] if st["activo"] else cfg["apps"]):
            lb_apps.insert("end", a)

    def agregar(tipo: str):
        var, lbl, fn, clave, pista = ((var_sitio, lbl_ps, normalizar_dominio, "sitios", "Agregado.")
                                      if tipo == "sitio" else (var_app, lbl_pa, validar_app, "apps", "Agregada."))
        try:
            valor = fn(var.get())
        except ValueError as exc:
            lbl.configure(text=str(exc), foreground="#a00")
            return
        if valor not in cfg[clave]:
            cfg[clave].append(valor)
            save_config(cfg, config_path)
        var.set("")
        lbl.configure(text=f"{pista} ({valor})", foreground="#2c7a3f")
        pintar_listas()

    def quitar(tipo: str):
        lb, clave = (lb_sitios, "sitios") if tipo == "sitio" else (lb_apps, "apps")
        sel = lb.curselection()
        if sel:
            del cfg[clave][sel[0]]
            save_config(cfg, config_path)
            pintar_listas()

    b_add_s.configure(command=lambda: agregar("sitio"))
    b_del_s.configure(command=lambda: quitar("sitio"))
    b_add_a.configure(command=lambda: agregar("app"))
    b_del_a.configure(command=lambda: quitar("app"))
    e_sitio.bind("<Return>", lambda e: agregar("sitio"))
    e_app.bind("<Return>", lambda e: agregar("app"))

    def abiertos():
        try:
            nombres = sorted({nombre_base(n) for _, n in listar_procesos()} - PROTEGIDOS)
        except Exception:
            nombres = []
        e_app.configure(values=nombres)
    e_app.configure(postcommand=abiertos)

    # ---------- duración ----------
    dur = ttk.LabelFrame(root, text="Duración", padding=(10, 6))
    dur.pack(fill="x", padx=16, pady=(4, 0))
    var_modo = tk.StringVar(value=str(cfg["minutos"]) if cfg["minutos"] in (25, 50, 90, 120) else "50")
    for m in (25, 50, 90, 120):
        ttk.Radiobutton(dur, text=f"{m} min", value=str(m), variable=var_modo).pack(side="left", padx=(0, 10))
    ttk.Radiobutton(dur, text="hasta las", value="hora", variable=var_modo).pack(side="left")
    var_hora = tk.StringVar(value="")
    e_hora = ttk.Entry(dur, textvariable=var_hora, width=6)
    e_hora.pack(side="left", padx=(4, 0))
    e_hora.bind("<FocusIn>", lambda e: var_modo.set("hora"))

    # ---------- acciones ----------
    acc = ttk.Frame(root, padding=(16, 10, 16, 4))
    acc.pack(fill="x")
    b_bloquear = ttk.Button(acc, text="Bloquear ahora", command=lambda: bloquear())
    b_bloquear.pack(side="left")
    b_extender = ttk.Button(acc, text="+25 min", command=lambda: extender(25))
    b_emerg = ttk.Button(acc, text="Desbloqueo de emergencia…", command=lambda: abrir_emergencia())
    lbl_err = ttk.Label(acc, foreground="#a00", wraplength=420, justify="left")
    lbl_err.pack(side="left", padx=(12, 0))

    # ---------- emergencia ----------
    emerg = ttk.Frame(root, padding=(16, 4, 16, 4))
    ttk.Label(emerg, text="Para salir antes, escribe (sin pegar):").pack(anchor="w")
    tk.Label(emerg, text=f"«{FRASE}»", font=f_frase, bg=fondo, fg="#6e1404").pack(anchor="w", pady=(2, 4))
    var_frase = tk.StringVar()
    e_frase = ttk.Entry(emerg, textvariable=var_frase)
    e_frase.pack(fill="x")
    for sec in ("<<Paste>>", "<Control-v>", "<Control-V>", "<Shift-Insert>", "<Button-2>"):
        e_frase.bind(sec, lambda e: "break")
    fila_e = ttk.Frame(emerg)
    fila_e.pack(fill="x", pady=(6, 0))
    b_conf = ttk.Button(fila_e, text="Confirmar", command=lambda: confirmar_emergencia())
    b_conf.pack(side="left")
    ttk.Button(fila_e, text="Mejor sigo", command=lambda: cerrar_emergencia()).pack(side="left", padx=(6, 0))
    lbl_cuenta = ttk.Label(fila_e, foreground="#6e1404")
    lbl_cuenta.pack(side="left", padx=(12, 0))
    e_frase.bind("<Return>", lambda e: confirmar_emergencia())

    # ---------- pie ----------
    pie = ttk.Frame(root, padding=(16, 4, 16, 12))
    pie.pack(fill="x", side="bottom")
    lbl_pie = ttk.Label(pie, foreground="#555", wraplength=620, justify="left")
    lbl_pie.pack(fill="x")

    def texto_pie():
        filas = leer_registro(registro_path)
        semana = [f for f in filas if f.get("inicio", "") >= (datetime.now() - timedelta(days=7)).isoformat()]
        completos = sum(1 for f in semana if f["salida"] == "completo")
        emergencias = sum(1 for f in semana if f["salida"] == "emergencia")
        txt = f"Últimos 7 días: {completos} bloqueo(s) completos"
        if emergencias:
            txt += f", {emergencias} salida(s) de emergencia"
        lbl_pie.configure(text=txt + ". Si un sitio sigue abriendo, cierra y vuelve a abrir el navegador: "
                                     "guarda direcciones en caché por unos minutos.")

    # ---------- lógica ----------
    def editable(si: bool):
        estado_w = ["!disabled"] if si else ["disabled"]
        for w in (b_add_s, b_del_s, b_add_a, b_del_a, e_sitio, e_app, e_hora):
            w.state(estado_w)
        for w in dur.winfo_children():
            try:
                w.state(estado_w)
            except Exception:
                pass

    def mostrar_inactivo(mensaje: str = ""):
        st.update(activo=False, desde=None, hasta=None)
        lbl_estado.configure(text="Sin bloqueo", fg="#333")
        lbl_sub.configure(text=mensaje or "Elige qué bloquear y por cuánto tiempo.")
        b_extender.pack_forget()
        b_emerg.pack_forget()
        b_bloquear.pack(side="left", before=lbl_err)
        cerrar_emergencia()
        editable(True)
        pintar_listas()
        texto_pie()
        root.title(APP_NAME)

    def mostrar_activo():
        b_bloquear.pack_forget()
        b_extender.pack(side="left", before=lbl_err)
        b_emerg.pack(side="left", padx=(8, 0), before=lbl_err)
        editable(False)
        pintar_listas()
        actualizar_reloj()

    def actualizar_reloj():
        if not st["activo"]:
            return
        resto = max(0.0, (st["hasta"] - ahora()).total_seconds())
        m, s = divmod(int(resto + 0.999), 60)
        h, m = divmod(m, 60)
        reloj = f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
        lbl_estado.configure(text=f"Bloqueado · quedan {reloj}", fg="#8a1b07")
        apps = cfg["apps_bloque"]
        lbl_sub.configure(text=f"Hasta las {st['hasta']:%H:%M}. {len(cfg['sitios'])} sitio(s)"
                               + (f", {len(apps)} app(s) vigiladas, {st['cerradas']} cierre(s)" if apps else "")
                               + ". La lista no se puede editar hasta que termine.")
        root.title(f"{reloj} · {APP_NAME}")

    # El reloj de la prueba corre acelerado; en uso normal es la hora real.
    t0_real, t0_falso = time.monotonic(), datetime.now()

    def ahora() -> datetime:
        if seg_por_min == 60:
            return datetime.now()
        return t0_falso + timedelta(seconds=(time.monotonic() - t0_real) * 60 / seg_por_min)

    def bloquear():
        lbl_err.configure(text="")
        if not cfg["sitios"] and not cfg["apps"]:
            lbl_err.configure(text="Agrega al menos un sitio o una app.")
            return
        if not revisar_permisos():
            lbl_err.configure(text="Sin permisos para el archivo hosts (ver aviso arriba).")
            return
        t = ahora()
        try:
            if var_modo.get() == "hora":
                hasta = calcular_hasta(t, hora=var_hora.get())
            else:
                hasta = calcular_hasta(t, minutos=int(var_modo.get()))
                cfg["minutos"] = int(var_modo.get())
        except ValueError as exc:
            lbl_err.configure(text=str(exc))
            return
        try:
            bloquear_archivo(hosts, expandir_todos(cfg["sitios"]), t.replace(microsecond=0),
                             hasta.replace(microsecond=0), respaldo_path)
        except Exception as exc:
            write_error_log("No se pudo bloquear", traceback.format_exc())
            lbl_err.configure(text=f"No se pudo escribir el archivo hosts: {exc}")
            return
        vaciar_cache_dns()
        cfg["apps_bloque"] = list(cfg["apps"])
        save_config(cfg, config_path)
        st.update(activo=True, desde=t.replace(microsecond=0), hasta=hasta.replace(microsecond=0), cerradas=0)
        mostrar_activo()

    def extender(minutos: int):
        if not st["activo"]:
            return
        nuevo = st["hasta"] + timedelta(minutes=minutos)
        if (nuevo - ahora()).total_seconds() > 12 * 3600:
            lbl_err.configure(text="Máximo 12 horas por bloqueo.")
            return
        try:
            bloquear_archivo(hosts, expandir_todos(cfg["sitios"]), st["desde"], nuevo, respaldo_path)
        except Exception as exc:
            lbl_err.configure(text=f"No se pudo extender: {exc}")
            return
        st["hasta"] = nuevo
        actualizar_reloj()

    def terminar(salida: str):
        try:
            desbloquear_archivo(hosts)
        except Exception as exc:
            # Reintenta cada 30 s, no en cada tic: si no, el log crece sin parar.
            if not st["reintento"]:
                write_error_log("No se pudo desbloquear", traceback.format_exc())
            st["reintento"] = time.monotonic() + 30
            lbl_err.configure(text=f"No se pudo quitar el bloqueo del archivo hosts: {exc}. "
                                   "Vuelve a abrir la app como administrador.")
            return
        st["reintento"] = 0.0
        vaciar_cache_dns()
        fin = ahora().replace(microsecond=0)
        anotar_bloqueo(registro_path, {
            "inicio": st["desde"].isoformat() if st["desde"] else "", "fin_planeado": st["hasta"].isoformat(),
            "fin_real": fin.isoformat(),
            "minutos": int(round(((min(fin, st["hasta"]) - st["desde"]).total_seconds() / 60))) if st["desde"] else "",
            "salida": salida, "sitios": " ".join(cfg["sitios"]), "apps": " ".join(cfg["apps_bloque"]),
            "apps_cerradas": st["cerradas"]})
        cfg["apps_bloque"] = []
        save_config(cfg, config_path)
        if salida == "completo":
            if not smoke_ms:
                root.bell()
            mostrar_inactivo("Bloqueo cumplido completo. Bien.")
        else:
            mostrar_inactivo("Bloqueo terminado antes de tiempo. Quedó anotado.")

    def abrir_emergencia():
        var_frase.set("")
        lbl_cuenta.configure(text="")
        b_conf.state(["!disabled"])
        e_frase.state(["!disabled"])
        st["emergencia_fin"] = None
        emerg.pack(fill="x", before=pie)
        e_frase.focus_set()

    def cerrar_emergencia():
        st["emergencia_fin"] = None
        emerg.pack_forget()

    def confirmar_emergencia():
        if not frase_correcta(var_frase.get()):
            lbl_cuenta.configure(text="No coincide. Escríbela completa.")
            return
        st["emergencia_fin"] = time.monotonic() + espera_emergencia
        b_conf.state(["disabled"])
        e_frase.state(["disabled"])

    def vigilar():
        if not st["activo"] or not cfg["apps_bloque"] or st["hilo"]:
            return
        st["hilo"] = True
        objetivos = list(cfg["apps_bloque"])

        def trabajo():
            try:
                pids = a_cerrar(listar_procesos(), objetivos, {os.getpid(), os.getppid()})
                cola.put(("cerradas", sum(1 for pid, _ in pids if cerrar_pid(pid))))
            except Exception:
                write_error_log("Fallo vigilando apps", traceback.format_exc())
                cola.put(("cerradas", 0))
        threading.Thread(target=trabajo, daemon=True).start()

    def tic():
        while True:
            try:
                tipo, valor = cola.get_nowait()
            except queue.Empty:
                break
            if tipo == "cerradas":
                st["hilo"] = False
                st["cerradas"] += valor
        if st["activo"] and time.monotonic() < st["reintento"]:
            pass
        elif st["activo"]:
            if ahora() >= st["hasta"]:
                terminar("completo")
            else:
                if st["emergencia_fin"] is not None:
                    falta = st["emergencia_fin"] - time.monotonic()
                    if falta <= 0:
                        terminar("emergencia")
                    else:
                        lbl_cuenta.configure(text=f"Se desbloquea en {int(falta * 60 / seg_por_min) + 1} s. "
                                                  "Todavía puedes arrepentirte.")
                if st["activo"]:
                    actualizar_reloj()
                    if time.monotonic() - st["ultimo_vigilar"] >= (5 if not smoke_ms else 0.2):
                        st["ultimo_vigilar"] = time.monotonic()
                        vigilar()
        root.after(100 if smoke_ms else 500, tic)

    def al_cerrar():
        if st["activo"] and not smoke_ms:
            if not messagebox.askyesno(APP_NAME, (
                    f"El bloqueo sigue hasta las {st['hasta']:%H:%M}. Si cierras la app, los sitios siguen "
                    "bloqueados pero las apps ya no se cierran, y el bloqueo se quita la próxima vez que abras "
                    "la app después de esa hora.\n\n¿Cerrar igual?"), parent=root):
                return
        try:
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

    # ---------- arranque: ¿hay un bloqueo de antes? ----------
    escribible = revisar_permisos()
    try:
        info = estado_bloqueo(leer_hosts(hosts))
    except Exception as exc:
        info = None
        lbl_err.configure(text=f"No se pudo leer {hosts}: {exc}")
    if info and (info["hasta"] is None or info["hasta"] <= ahora()):
        if escribible:
            limpiar_si_vencido(hosts, ahora())
            vaciar_cache_dns()
            anotar_bloqueo(registro_path, {"inicio": info["desde"].isoformat() if info["desde"] else "",
                                           "fin_planeado": info["hasta"].isoformat() if info["hasta"] else "",
                                           "fin_real": ahora().replace(microsecond=0).isoformat(),
                                           "salida": "limpieza", "sitios": " ".join(info["dominios"])})
            cfg["apps_bloque"] = []
            save_config(cfg, config_path)
            mostrar_inactivo("Había un bloqueo vencido de antes; ya lo quité.")
        else:
            mostrar_inactivo("Hay un bloqueo vencido en el archivo hosts. Ábreme con permisos para quitarlo.")
    elif info:
        st.update(activo=True, desde=info["desde"], hasta=info["hasta"], cerradas=0)
        mostrar_activo()
    else:
        mostrar_inactivo()
    tic()

    if smoke_ms:
        _guion_de_prueba(root, st, cfg, fallas, hosts, registro_path, var_sitio, var_app, lbl_ps, lbl_pa,
                         b_add_s, b_add_a, var_modo, b_bloquear, b_emerg, var_frase, e_frase, b_conf, b_extender,
                         smoke_ms)
    root.mainloop()
    return 1 if fallas else 0


def _guion_de_prueba(root, st, cfg, fallas, hosts, registro_path, var_sitio, var_app, lbl_ps, lbl_pa, b_add_s,
                     b_add_a, var_modo, b_bloquear, b_emerg, var_frase, e_frase, b_conf, b_extender,
                     smoke_ms) -> None:
    """Recorre la interfaz sobre un hosts de prueba: agrega sitios y apps (válidos e
    inválidos), bloquea, deja vencer, vuelve a bloquear, extiende y sale por emergencia.
    Comprueba en cada paso el archivo hosts y el registro."""
    original = hosts.read_bytes()
    pasos: list = []

    def esperar(cond, accion, descripcion):
        pasos.append((cond, accion, descripcion))

    def escribir_y_agregar(var, boton, texto):
        var.set(texto)
        boton.invoke()

    def agregar_cosas():
        escribir_y_agregar(var_sitio, b_add_s, "no es un sitio")
        if "no parece" not in lbl_ps.cget("text"):
            fallas.append(f"sitio inválido sin aviso: {lbl_ps.cget('text')!r}")
        escribir_y_agregar(var_sitio, b_add_s, "https://www.Example.org/ruta?x=1")
        escribir_y_agregar(var_app, b_add_a, "explorer.exe")
        if "sistema" not in lbl_pa.cget("text"):
            fallas.append(f"app protegida sin aviso: {lbl_pa.cget('text')!r}")
        escribir_y_agregar(var_app, b_add_a, "app_que_no_existe.exe")
        if "example.org" not in cfg["sitios"] or cfg["apps"] != ["app_que_no_existe"]:
            fallas.append(f"listas inesperadas: {cfg['sitios']} / {cfg['apps']}")
        var_modo.set("25")
        b_bloquear.invoke()

    def bloqueado_bien():
        texto = leer_hosts(hosts)
        info = estado_bloqueo(texto)
        if not info or "www.example.org" not in info["dominios"] or not texto.startswith(original.decode("latin-1")):
            fallas.append(f"el hosts no quedó bloqueado como se esperaba: {info}")

    esperar(lambda: not st["activo"], agregar_cosas, "inactivo al abrir")
    esperar(lambda: st["activo"], bloqueado_bien, "bloqueo activo")

    def restaurado():
        if hosts.read_bytes() != original:
            fallas.append("al vencer, el hosts no volvió a ser idéntico")
        var_modo.set("50")
        b_bloquear.invoke()

    esperar(lambda: not st["activo"], restaurado, "el bloqueo vence solo")

    def emergencia():
        hasta = st["hasta"]
        b_extender.invoke()
        if st["hasta"] - hasta != timedelta(minutes=25):
            fallas.append("+25 min no extendió el bloqueo")
        b_emerg.invoke()
        e_frase.insert(0, "prefiero distraerme")
        b_conf.invoke()
        if st["emergencia_fin"] is not None:
            fallas.append("media frase activó la salida de emergencia")
        var_frase.set(FRASE.upper())
        b_conf.invoke()
        if st["emergencia_fin"] is None:
            fallas.append("la frase correcta no inició la cuenta regresiva")

    esperar(lambda: st["activo"], emergencia, "segundo bloqueo")

    def verificar():
        if hosts.read_bytes() != original:
            fallas.append("tras la emergencia, el hosts no volvió a ser idéntico")
        salidas = [f["salida"] for f in leer_registro(registro_path)]
        if salidas != ["completo", "emergencia"]:
            fallas.append(f"registro inesperado: {salidas}")
    esperar(lambda: not st["activo"], verificar, "la emergencia desbloquea tras la espera")

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
        elif time.monotonic() - estado["inicio"] > max(8.0, smoke_ms / 1000):
            fallas.append(f"se quedó esperando: {descripcion}")
            estado["i"] = len(pasos)
        root.after(50, avanzar)
    root.after(300, avanzar)


# =====================================================================
# 11. Entrada
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
    if "--estado" in argv or "--limpiar" in argv:
        h = hosts_path()
        info = estado_bloqueo(leer_hosts(h))
        ahora = datetime.now()
        if info is None:
            print(f"Sin bloqueo en {h}.")
            return 0
        vencido = info["hasta"] is None or info["hasta"] <= ahora
        cuando = f"{info['hasta']:%Y-%m-%d %H:%M}" if info["hasta"] else "fecha ilegible"
        print(f"Bloqueo {'vencido' if vencido else 'activo'} hasta {cuando}: {len(info['dominios'])} dominio(s).")
        if "--limpiar" in argv:
            if not vencido:
                print("Sigue activo: no se quita. Para salir antes, usa la app.")
                return 1
            try:
                limpiar_si_vencido(h, ahora)
            except PermissionError:
                print("Sin permisos para modificar hosts: corre esto como administrador / con sudo.")
                return 1
            vaciar_cache_dns()
            print("Quitado. El archivo hosts quedó como estaba antes del bloqueo.")
        return 0
    if "--help" in argv or "-h" in argv:
        print(__doc__)
        return 0
    if "--guitest" in argv:
        rest = argv[argv.index("--guitest") + 1:]
        ms = int(rest[0]) if rest and rest[0].isdigit() else 10000
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            h = d / "hosts"
            h.write_bytes(b"# hosts de prueba\r\n127.0.0.1 localhost\r\n::1 localhost")
            os.environ["BLOQUEO_HOSTS"] = str(h)
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
