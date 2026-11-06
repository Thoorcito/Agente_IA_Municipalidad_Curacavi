"""Genera la ficha técnica desde agente/configuracion/settings.py y la escribe en el README (raíz del repo).

Así el README nunca queda con un modelo o una dimensión distinta a la configurada.
Uso:  python -m scripts.ficha_tecnica            # muestra la tabla
      python -m scripts.ficha_tecnica --readme   # la actualiza en README.md
"""
import argparse
import re

from agente.configuracion import settings

INICIO, FIN = "<!-- FICHA:INICIO -->", "<!-- FICHA:FIN -->"


def tabla_markdown() -> str:
    filas = ["| Componente | Valor |", "|---|---|"]
    filas += [f"| {k} | {v} |" for k, v in settings.ficha_tecnica().items()]
    return "\n".join(filas)


def actualizar_readme(ruta=settings.README) -> bool:
    texto = ruta.read_text(encoding="utf-8")
    nuevo = re.sub(f"{INICIO}.*?{FIN}", f"{INICIO}\n{tabla_markdown()}\n{FIN}", texto, flags=re.DOTALL)
    ruta.write_text(nuevo, encoding="utf-8")
    return nuevo != texto


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--readme", action="store_true")
    if parser.parse_args().readme:
        print("README actualizado" if actualizar_readme() else "README ya estaba al día")
    else:
        print(tabla_markdown())
