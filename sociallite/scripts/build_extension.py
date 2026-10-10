#!/usr/bin/env python3
"""Arma la extensión en dist/extension/ y la empaqueta para Chromium y Firefox.

El manifest cita "shared/filter.js" y "extension/...": el paquete reproduce esa forma,
con manifest.json en la raíz. filter.js se copia desde shared/ (nunca se duplica a mano).

    python scripts/build_extension.py
    → dist/extension/                 (para «Cargar descomprimida» o about:debugging)
    → dist/sociallite-chromium.zip
    → dist/sociallite-firefox.xpi     (sin firmar)

Los zip son deterministas: mismo contenido, mismos bytes.
"""
import json
import shutil
import sys
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DIST = RAIZ / "dist"
PAQUETE = DIST / "extension"
ARCHIVOS_EXTENSION = ["habits.js", "content.js", "popup.html", "popup.js", "popup.css"]
FECHA_FIJA = (2024, 1, 1, 0, 0, 0)


def rutas_del_manifest(m: dict) -> list:
    rutas = []
    for cs in m.get("content_scripts", []):
        rutas += cs.get("js", []) + cs.get("css", [])
    accion = m.get("action", {})
    if "default_popup" in accion:
        rutas.append(accion["default_popup"])
    rutas += list(accion.get("default_icon", {}).values())
    rutas += list(m.get("icons", {}).values())
    return rutas


def armar() -> list:
    if PAQUETE.exists():
        shutil.rmtree(PAQUETE)
    (PAQUETE / "shared").mkdir(parents=True)
    (PAQUETE / "extension" / "icons").mkdir(parents=True)

    manifest = json.loads((RAIZ / "extension" / "manifest.json").read_text(encoding="utf-8"))
    shutil.copy2(RAIZ / "extension" / "manifest.json", PAQUETE / "manifest.json")
    shutil.copy2(RAIZ / "shared" / "filter.js", PAQUETE / "shared" / "filter.js")
    for nombre in ARCHIVOS_EXTENSION:
        shutil.copy2(RAIZ / "extension" / nombre, PAQUETE / "extension" / nombre)
    for icono in sorted((RAIZ / "extension" / "icons").glob("*.png")):
        shutil.copy2(icono, PAQUETE / "extension" / "icons" / icono.name)

    faltan = [r for r in rutas_del_manifest(manifest) if not (PAQUETE / r).is_file()]
    if faltan:
        raise SystemExit(f"El manifest cita archivos que no están en el paquete: {faltan}")
    permisos = manifest.get("permissions", [])
    if permisos != ["storage"] or "host_permissions" in manifest or "background" in manifest:
        raise SystemExit("La extensión solo debe pedir «storage», sin host_permissions ni background.")
    return sorted(p for p in PAQUETE.rglob("*") if p.is_file())


def comprimir(archivos: list, destino: Path) -> None:
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
        for p in archivos:
            info = zipfile.ZipInfo(p.relative_to(PAQUETE).as_posix(), FECHA_FIJA)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, p.read_bytes())


def main() -> int:
    archivos = armar()
    comprimir(archivos, DIST / "sociallite-chromium.zip")
    comprimir(archivos, DIST / "sociallite-firefox.xpi")
    for nombre in ("sociallite-chromium.zip", "sociallite-firefox.xpi"):
        print(f"{nombre}: {(DIST / nombre).stat().st_size} bytes, {len(archivos)} archivos")
    return 0


if __name__ == "__main__":
    sys.exit(main())
