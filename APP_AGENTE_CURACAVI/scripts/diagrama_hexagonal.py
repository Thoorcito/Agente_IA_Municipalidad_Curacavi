"""Genera el diagrama de la arquitectura hexagonal (puertos y adaptadores).

Salidas: DOCUMENTACION/diagramas/arquitectura_hexagonal.svg (editable) y EVIDENCIAS_TEST/diagramas/arquitectura_hexagonal.png
Uso:     python -m scripts.diagrama_hexagonal      (requiere playwright + Chrome; CHROME_PATH opcional)
"""
import math
import os
from html import escape
from pathlib import Path

W, H = 2040, 1230
out = []
A = out.append
TXT, GRIS = "#1F2A2E", "#4A5560"
C = {"dominio": ("#12355B", "#12355B"), "app": ("#E8F0FB", "#2B6CC4"), "puerto": ("#FFFFFF", "#12355B"),
     "docker": ("#E6F4EC", "#2E8B57"), "local": ("#F1EEF9", "#5B3FA0"), "entrada": ("#FFF3D6", "#D4A017"),
     "llm": ("#FDECE4", "#E07A2E"), "blanco": ("#FFFFFF", "#4A5560"), "gris": ("#F4F6F8", "#C9D1D9")}


def texto(x, y, lineas, size=16, anchor="middle", bold_primera=False, color=TXT, mono=False):
    fam = "DejaVu Sans Mono, Courier New, monospace" if mono else "DejaVu Sans, Arial, sans-serif"
    for i, linea in enumerate(lineas):
        peso = "700" if bold_primera and i == 0 else "400"
        A(f'<text x="{x}" y="{y + i * size * 1.32}" font-family="{fam}" font-size="{size}" font-weight="{peso}" '
          f'fill="{color}" text-anchor="{anchor}">{escape(linea)}</text>')


def caja(x, y, w, h, lineas, estilo="blanco", size=15, bold=True, r=10, dash=False, color=TXT):
    f, s = C[estilo]
    d = ' stroke-dasharray="7 5"' if dash else ""
    A(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{f}" stroke="{s}" stroke-width="2.4"{d}/>')
    y0 = y + h / 2 - (len(lineas) - 1) * size * 1.32 / 2 + size * 0.35
    texto(x + w / 2, y0, lineas, size, bold_primera=bold, color=color)


def cilindro(x, y, w, h, lineas, estilo, size=15):
    f, s = C[estilo]
    e = 13
    A(f'<path d="M{x},{y + e} L{x},{y + h - e} A{w / 2},{e} 0 0 0 {x + w},{y + h - e} L{x + w},{y + e}" '
      f'fill="{f}" stroke="{s}" stroke-width="2.4"/>')
    A(f'<ellipse cx="{x + w / 2}" cy="{y + e}" rx="{w / 2}" ry="{e}" fill="{f}" stroke="{s}" stroke-width="2.4"/>')
    y0 = y + e + (h - e) / 2 - (len(lineas) - 1) * size * 1.3 / 2 + size * 0.35
    texto(x + w / 2, y0, lineas, size, bold_primera=True)


def flecha(puntos, dash=False, color="#3A444C"):
    d = ' stroke-dasharray="8 6"' if dash else ""
    p = " ".join(f"{x},{y}" for x, y in puntos)
    A(f'<polyline points="{p}" fill="none" stroke="{color}" stroke-width="2.4"{d} marker-end="url(#punta)"/>')


def hexagono(cx, cy, r, relleno, borde, ancho=3):
    pts = " ".join(f"{cx + r * math.cos(math.radians(a)):.1f},{cy + r * math.sin(math.radians(a)):.1f}"
                   for a in range(0, 360, 60))
    A(f'<polygon points="{pts}" fill="{relleno}" stroke="{borde}" stroke-width="{ancho}"/>')


A(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">')
A('<defs><marker id="punta" markerUnits="userSpaceOnUse" markerWidth="13" markerHeight="13" refX="12" refY="6.5" '
  'orient="auto"><path d="M0,0 L13,6.5 L0,13 z" fill="#3A444C"/></marker></defs>')
A(f'<rect width="{W}" height="{H}" fill="#FFFFFF"/>')
texto(W / 2, 50, ["Arquitectura hexagonal del agente · puertos y adaptadores"], 26, bold_primera=True)
texto(W / 2, 82, ["El núcleo no conoce la tecnología de afuera: cambiar SQLite/Chroma por PostgreSQL/pgvector no cambia "
                  "ninguna decisión (22/22 escenarios con ambos)"], 16, color=GRIS)

# ---------- Núcleo: aplicación + dominio ----------
CX, CY, R, RD = 940, 560, 380, 195
APOTEMA = R * math.sqrt(3) / 2


def borde_x(y: float, lado: int) -> float | None:
    """x del borde del hexágono exterior a la altura y (lado -1 izquierda, +1 derecha)."""
    d = abs(y - CY)
    if d >= APOTEMA:
        return None
    return CX + lado * (R - d / APOTEMA * R / 2)


# Conectores de los puertos (se dibujan antes que las cajas para quedar debajo)
PUERTOS_Y = [260, 365, 470, 755, 865]
for y in PUERTOS_Y:
    xb = borde_x(y, 1)
    if xb is not None:
        A(f'<line x1="{xb:.0f}" y1="{y}" x2="1300" y2="{y}" stroke="#12355B" stroke-width="3"/>')

hexagono(CX, CY, R, C["app"][0], C["app"][1])
hexagono(CX, CY, RD, C["dominio"][0], C["dominio"][1])
texto(CX, 266, ["APLICACIÓN · agente/aplicacion/"], 17, bold_primera=True, color="#2B6CC4")
texto(CX, 296, ["Orquestador LangGraph · orquestador.py"], 16, bold_primera=True)
texto(CX, 322, ["percibir → diagnosticar → planificar →", "ejecutar → responder → memorizar"], 14, color=GRIS)
texto(CX - 278, 520, ["NLU", "nlu.py"], 15, bold_primera=True)
texto(CX - 278, 610, ["Redacción", "con citas", "redaccion.py"], 15, bold_primera=True)
texto(CX, 800, ["Puertos · puertos.py"], 16, bold_primera=True)
texto(CX, 825, ["interfaces que el núcleo necesita;", "resumen de conversaciones · resumen.py"], 14, color=GRIS)
texto(CX, 428, ["DOMINIO"], 18, bold_primera=True, color="#FFFFFF")
texto(CX, 448, ["agente/dominio/"], 13, color="#D6E2F0")
texto(CX, 478, ["modelo.py", "Solicitud · EstadoSolicitud", "Folio · Cupo"], 15, bold_primera=True, color="#FFFFFF")
texto(CX, 570, ["planner.py · 10 reglas", "plazos · requisitos · citas"], 15, bold_primera=True, color="#FFFFFF")
texto(CX, 640, ["sin LangChain ni bases de datos", "(verificado con pruebas)"], 13, color="#D6E2F0")

# ---------- Adaptadores de entrada (izquierda) ----------
A(f'<rect x="30" y="130" width="440" height="830" rx="16" fill="{C["gris"][0]}" stroke="{C["gris"][1]}" stroke-width="2"/>')
texto(52, 166, ["ADAPTADORES DE ENTRADA"], 18, anchor="start", bold_primera=True, color=GRIS)
texto(52, 190, ["agente/adaptadores/entrada/"], 14, anchor="start", color=GRIS)
entradas = [
    (215, ["Vecino/a · Funcionario/a", "Streamlit (app.py, solo vista)", "→ ControladorAtencion"], "entrada"),
    (365, ["17 herramientas @tool (LangChain)", "consulta · escritura · razonamiento", "las usa el grafo o un LLM"], "llm"),
    (515, ["Notebook de Google Colab", "DOCUMENTACION/agente_tramites_colab"], "entrada"),
    (645, ["Evaluación y scripts", "evaluacion.py · preparar_datos · evaluar"], "entrada"),
    (775, ["Pruebas pytest", "dobles de prueba (mocks)", "LLMSimulado · HashingEmbeddings"], "entrada"),
]
for y, lineas, est in entradas:
    alto = 110 if len(lineas) == 3 else 90
    caja(55, y, 390, alto, lineas, est, 15)
    yc = y + alto / 2
    flecha([(445, yc), ((borde_x(yc, -1) or CX - R / 2) - 6, yc)])
texto(250, 935, ["≈ @RestController en Spring"], 14, color=GRIS)

# ---------- Puertos y adaptadores de salida (derecha) ----------
texto(1405, 166, ["PUERTOS · aplicacion/puertos.py"], 17, bold_primera=True, color="#12355B")
texto(1405, 190, ["interfaces (Protocol)"], 14, color=GRIS)
A(f'<rect x="1555" y="130" width="225" height="555" rx="16" fill="none" stroke="{C["docker"][1]}" stroke-width="2" stroke-dasharray="8 6"/>')
A(f'<rect x="1795" y="130" width="225" height="555" rx="16" fill="none" stroke="{C["local"][1]}" stroke-width="2" stroke-dasharray="8 6"/>')
texto(1667, 164, ["salida/postgres/"], 17, bold_primera=True, color=C["docker"][1])
texto(1667, 188, ["Docker (PERSISTENCIA)"], 13, color=GRIS)
texto(1907, 164, ["salida/local/"], 17, bold_primera=True, color=C["local"][1])
texto(1907, 188, ["Colab y venv"], 13, color=GRIS)
filas = [
    (PUERTOS_Y[0], "RegistroMunicipal", "largo plazo", ["RegistroPostgres"], ["RegistroSQLite"]),
    (PUERTOS_Y[1], "BuscadorFuentes", "memoria semántica", ["IndicePgvector", "pgvector + texto", "completo (español)"],
     ["IndiceChroma", "Chroma + BM25"]),
    (PUERTOS_Y[2], "Memoria de", "conversación", ["PostgresSaver", "(LangGraph)"], ["SqliteSaver", "(LangGraph)"]),
]
for y, p1, p2, docker, local in filas:
    caja(1300, y - 40, 210, 80, [p1, p2], "puerto", 15)
    caja(1570, y - 45, 195, 90, docker, "docker", 14)
    caja(1810, y - 45, 195, 90, local, "local", 14)
    flecha([(1510, y), (1568, y)])
cilindro(1572, 545, 190, 125, ["PostgreSQL 16", "+ pgvector", "contenedor db"], "docker", 14)
cilindro(1812, 545, 190, 125, ["SQLite + Chroma", "archivos en", "data/runtime/"], "local", 14)
caja(1300, PUERTOS_Y[3] - 40, 210, 80, ["ModeloLenguaje", "LLM"], "puerto", 15)
caja(1570, PUERTOS_Y[3] - 50, 450, 100, ["salida/llm/ · ChatOpenAI → OpenRouter", "agente: Nemotron · juez: flint (otra empresa)",
                                         "o None: modo offline con plantillas"], "llm", 14)
flecha([(1510, PUERTOS_Y[3]), (1568, PUERTOS_Y[3])])
caja(1300, PUERTOS_Y[4] - 35, 210, 70, ["Reloj"], "puerto", 15)
caja(1570, PUERTOS_Y[4] - 40, 450, 80, ["fecha del sistema (zona horaria de Chile)", "o FECHA_REFERENCIA fija (demos y pruebas)"],
     "blanco", 14, bold=False)
flecha([(1510, PUERTOS_Y[4]), (1568, PUERTOS_Y[4])])

# ---------- Contenedor (composición) ----------
caja(30, 990, 1990, 92, ["agente/configuracion/contenedor.py · composición (≈ @Configuration de Spring con perfiles)",
                         "lee PERSISTENCIA, crea los adaptadores y los inyecta por constructor en el agente, las herramientas "
                         "y el controlador · nada usa variables globales"], "blanco", 16)
flecha([(CX, 990), (CX, 944)], dash=True)
texto(1540, 965, ["elige los adaptadores de un lado o del otro"], 14, color=GRIS)

# ---------- Equivalencias con Spring ----------
leyenda = [("dominio", "Dominio ≈ @Entity y servicios de dominio"), ("puerto", "Puerto ≈ interfaz ...Repository"),
           ("docker", "Adaptador de salida ≈ implementación @Repository"), ("entrada", "Adaptador de entrada ≈ @RestController")]
x = 40
for est, t in leyenda:
    f, s = C[est]
    A(f'<rect x="{x}" y="1120" width="30" height="30" rx="6" fill="{f}" stroke="{s}" stroke-width="2.4"/>')
    texto(x + 42, 1141, [t], 15, anchor="start")
    x += 500
texto(W / 2, 1200, ["Las pruebas de contrato (tests/integracion/) corren la misma batería contra ambos adaptadores de cada puerto."],
      15, color=GRIS)

A("</svg>")
REPO = Path(__file__).resolve().parents[2]
destino = REPO / "DOCUMENTACION" / "diagramas" / "arquitectura_hexagonal.svg"
destino.write_text("\n".join(out), encoding="utf-8")

if __name__ == "__main__":
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        navegador = p.chromium.launch(executable_path=os.getenv("CHROME_PATH") or None)
        pagina = navegador.new_page(viewport={"width": W, "height": H}, device_scale_factor=1.6)
        pagina.goto(destino.as_uri())
        pagina.screenshot(path=str(REPO / "EVIDENCIAS_TEST" / "diagramas" / "arquitectura_hexagonal.png"))
        navegador.close()
    print("ok")
