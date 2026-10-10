#!/usr/bin/env python3
"""Genera los íconos de SocialLite sin dependencias (PNG escrito a mano con zlib).

Dibujo: fondo degradado morado→rosado y una burbuja de mensaje blanca: los mensajes
son lo único que la app deja libre. Se corre una vez; los PNG quedan versionados.

    python scripts/make_icons.py
"""
import math
import struct
import sys
import zlib
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def png(n: int, ruta: Path, esquinas: bool) -> None:
    arriba, abajo = (88, 81, 219), (225, 48, 108)
    r_esquina = n * 0.22 if esquinas else 0
    filas = []
    for y in range(n):
        fila = bytearray([0])
        for x in range(n):
            cubierto, fondo_a = 0.0, 0.0
            for ox, oy in ((0.25, 0.25), (0.75, 0.25), (0.25, 0.75), (0.75, 0.75)):
                px, py = (x + ox) / n, (y + oy) / n
                # esquinas redondeadas (solo extensión; iOS redondea solo)
                dentro = True
                if r_esquina:
                    rx = min(max(px * n, r_esquina), n - r_esquina)
                    ry = min(max(py * n, r_esquina), n - r_esquina)
                    dentro = math.hypot(px * n - rx, py * n - ry) <= r_esquina
                if dentro:
                    fondo_a += 0.25
                    # burbuja: elipse + cola abajo a la izquierda
                    elipse = ((px - 0.5) / 0.33) ** 2 + ((py - 0.47) / 0.27) ** 2 <= 1
                    cola = 0.25 <= px <= 0.42 and 0.62 <= py <= 0.80 and (py - 0.62) <= (0.42 - px) * 1.1
                    if elipse or cola:
                        cubierto += 0.25
            t = y / max(1, n - 1)
            base = tuple(arriba[i] * (1 - t) + abajo[i] * t for i in range(3))
            a_blanco = cubierto / fondo_a if fondo_a else 0
            rgb = [round(base[i] * (1 - a_blanco) + 255 * a_blanco) for i in range(3)]
            fila += bytes(rgb + [round(255 * fondo_a)])
        filas.append(bytes(fila))
    crudo = b"".join(filas)

    def chunk(tipo, datos):
        return struct.pack(">I", len(datos)) + tipo + datos + struct.pack(">I", zlib.crc32(tipo + datos) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", n, n, 8, 6, 0, 0, 0)  # RGBA
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(crudo, 9))
                     + chunk(b"IEND", b""))


def png_sin_alfa(n: int, ruta: Path) -> None:
    """El ícono de iOS no debe tener transparencia (iOS redondea las esquinas solo)."""
    arriba, abajo = (88, 81, 219), (225, 48, 108)
    filas = []
    for y in range(n):
        fila = bytearray([0])
        for x in range(n):
            cubierto = 0.0
            for ox, oy in ((0.25, 0.25), (0.75, 0.25), (0.25, 0.75), (0.75, 0.75)):
                px, py = (x + ox) / n, (y + oy) / n
                elipse = ((px - 0.5) / 0.33) ** 2 + ((py - 0.47) / 0.27) ** 2 <= 1
                cola = 0.25 <= px <= 0.42 and 0.62 <= py <= 0.80 and (py - 0.62) <= (0.42 - px) * 1.1
                if elipse or cola:
                    cubierto += 0.25
            t = y / max(1, n - 1)
            fila += bytes(round((arriba[i] * (1 - t) + abajo[i] * t) * (1 - cubierto) + 255 * cubierto)
                          for i in range(3))
        filas.append(bytes(fila))

    def chunk(tipo, d):
        return struct.pack(">I", len(d)) + tipo + d + struct.pack(">I", zlib.crc32(tipo + d) & 0xFFFFFFFF)

    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", n, n, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(b"".join(filas), 9)) + chunk(b"IEND", b""))


def main() -> int:
    for n in (16, 32, 48, 128):
        png(n, RAIZ / "extension" / "icons" / f"icon-{n}.png", esquinas=True)
    png_sin_alfa(1024, RAIZ / "ios" / "SocialLite" / "Assets.xcassets" / "AppIcon.appiconset" / "icon.png")
    print("íconos generados")
    return 0


if __name__ == "__main__":
    sys.exit(main())
