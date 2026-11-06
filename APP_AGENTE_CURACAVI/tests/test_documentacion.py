"""Coherencia entre la documentación y el código: lo que dicen el README y los diagramas debe ser verdad."""
import re

import pytest

from agente.dominio.planner import TABLA_REGLAS
from agente.adaptadores.entrada.herramientas import TIPO_DE
from agente.dominio import citas as cat
from agente.configuracion import settings
from scripts.ficha_tecnica import FIN, INICIO, tabla_markdown

RAIZ = settings.BASE_DIR                 # APP_AGENTE_CURACAVI
REPO = settings.REPO_DIR                 # raíz del repositorio
README = settings.README.read_text(encoding="utf-8")
DOCS = {p.name: p.read_text(encoding="utf-8") for p in settings.DOCUMENTACION_DIR.glob("*.md")}


def test_ficha_tecnica_del_readme_coincide_con_la_configuracion():
    # Arrange
    bloque = re.search(f"{INICIO}\n(.*?)\n{FIN}", README, re.DOTALL).group(1)

    # Act / Assert
    assert bloque == tabla_markdown()


@pytest.mark.parametrize("texto_prohibido", ["gemini-embedding", "768 dimensiones", "FAISS"])
def test_documentos_no_nombran_componentes_que_no_se_usan(texto_prohibido):
    # Act
    apariciones = [n for n, t in {"README.md": README, **DOCS}.items() if texto_prohibido in t
                   and n not in ("decisiones.md", "conceptos.md")]   # estos comparan con alternativas descartadas

    # Assert
    assert apariciones == []


def test_todas_las_herramientas_estan_documentadas():
    # Act
    faltan = [nombre for nombre in TIPO_DE if f"`{nombre}`" not in DOCS["herramientas.md"]]

    # Assert
    assert faltan == []
    assert f"({len(TIPO_DE)})" in DOCS["herramientas.md"]


def test_todas_las_reglas_estan_documentadas_en_orden():
    # Act
    posiciones = [DOCS["reglas.md"].index(f"| {rid} |") for rid, *_ in TABLA_REGLAS]

    # Assert
    assert posiciones == sorted(posiciones)


def test_imagenes_enlaces_y_fuentes_referenciadas_existen():
    # Arrange: enlaces e imágenes relativos del README (desde la raíz del repo) y de DOCUMENTACION/
    del_readme = [e for e in re.findall(r"\]\(([^)#\s]+)\)", README) if not e.startswith("http")]
    de_docs = [e for e in re.findall(r"\]\(([^)#\s]+)\)", "".join(DOCS.values())) if not e.startswith("http")]

    # Act
    faltantes = [e for e in del_readme if not (REPO / e).exists()]
    faltantes += [e for e in de_docs if not (settings.DOCUMENTACION_DIR / e).exists()]
    archivos = [f["archivo"] for f in cat.catalogo()["fuentes"].values() if not (settings.FUENTES_DIR / f["archivo"]).exists()]

    # Assert
    assert len(del_readme) > 20 and len(de_docs) > 5 and faltantes == [] and archivos == []


def test_glosario_solo_cita_archivos_y_funciones_que_existen():
    # Arrange: cada "`archivo` → `Clase.funcion()`" del glosario
    patron = re.compile(r"`([\w./]+\.(?:py|json|csv|toml|md))`(?: → `([\w.]+)(?:\(\))?`)?")
    referencias = patron.findall(DOCS["conceptos.md"])

    # Act
    faltantes = []
    for archivo, nombre in referencias:
        ruta = RAIZ / archivo if (RAIZ / archivo).exists() else REPO / archivo
        if not ruta.exists():
            faltantes.append(archivo)
            continue
        texto = ruta.read_text(encoding="utf-8")
        for parte in filter(None, (nombre or "").split(".")):
            if not re.search(rf"(def|class) {parte}\b|^{parte}\s*=", texto, re.MULTILINE):
                faltantes.append(f"{archivo} → {parte}")

    # Assert
    assert len(referencias) > 60 and faltantes == []
