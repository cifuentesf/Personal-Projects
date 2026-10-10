#!/usr/bin/env python3
"""Genera ios/SocialLite/Sources/FilterScript.swift a partir de shared/filter.js.

El JS va dentro de un string crudo de Swift (#\"\"\" … \"\"\"#), así no hay que escapar
nada. Lo único que rompería ese string es que el JS contenga «\"\"\"#» (lo cerraría
antes de tiempo) o «\\#» (Swift lo leería como escape): en ese caso falla con un
mensaje claro en vez de generar un archivo que no compila.

    python scripts/embed_filter.py
"""
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ORIGEN = RAIZ / "shared" / "filter.js"
DESTINO = RAIZ / "ios" / "SocialLite" / "Sources" / "FilterScript.swift"


def generar(js: str) -> str:
    for prohibido, motivo in (('"""#', "cerraría el string crudo de Swift"),
                              ("\\#", "Swift lo interpretaría como una secuencia de escape")):
        if prohibido in js:
            linea = js[: js.index(prohibido)].count("\n") + 1
            raise ValueError(f"shared/filter.js contiene «{prohibido}» en la línea {linea}: {motivo}. "
                             "Cámbialo (por ejemplo, separando los caracteres) y vuelve a generar.")
    if not js.endswith("\n"):
        js += "\n"
    return ("// GENERADO por scripts/embed_filter.py desde shared/filter.js. No editar a mano:\n"
            "// cambia shared/filter.js y vuelve a correr el script.\n\n"
            "enum FilterScript {\n"
            "    static let source = #\"\"\"\n"
            f"{js}"
            "\"\"\"#\n"
            "}\n")


def main() -> int:
    try:
        swift = generar(ORIGEN.read_text(encoding="utf-8"))
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    DESTINO.write_text(swift, encoding="utf-8", newline="\n")
    print(f"generado {DESTINO.relative_to(RAIZ)} ({len(swift)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
