"""Genera DOCUMENTACION/diagramas/arquitectura_completa.svg y EVIDENCIAS_TEST/diagramas/arquitectura_completa.png
(requiere playwright + Chrome).

Uso:  python -m scripts.diagrama_arquitectura      (CHROME_PATH opcional)
"""
from html import escape
from pathlib import Path

W, H = 2000, 1330
out = []
A = out.append

C = {
    "panel": ("#F4F6F8", "#C9D1D9"), "agente": ("#E8F0FB", "#2B6CC4"), "llm": ("#FDECE4", "#E07A2E"),
    "dato": ("#E6F4EC", "#2E8B57"), "proc": ("#FFF3D6", "#D4A017"), "morado": ("#EEEAF8", "#5B3FA0"),
    "blanco": ("#FFFFFF", "#4A5560"), "humano": ("#FFF6E0", "#E0A100"),
}
TXT, GRIS = "#1F2A2E", "#4A5560"


def texto(x, y, lineas, size=17, anchor="middle", bold_primera=False, color=TXT, alto=None, mono=False):
    alto = alto or size * 1.32
    fam = "DejaVu Sans Mono, Courier New, monospace" if mono else "DejaVu Sans, Arial, sans-serif"
    for i, l in enumerate(lineas):
        peso = "700" if (bold_primera and i == 0) else "400"
        A(f'<text x="{x}" y="{y + i * alto}" font-family="{fam}" font-size="{size}" font-weight="{peso}" '
          f'fill="{color}" text-anchor="{anchor}">{escape(l)}</text>')


def caja(x, y, w, h, lineas, estilo="blanco", size=17, bold=True, r=10, dash=False, mono=False, anchor="middle"):
    f, s = C[estilo]
    d = ' stroke-dasharray="7 5"' if dash else ""
    A(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{f}" stroke="{s}" stroke-width="2.4"{d}/>')
    alto = size * 1.32
    y0 = y + h / 2 - (len(lineas) - 1) * alto / 2 + size * 0.35
    tx = x + w / 2 if anchor == "middle" else x + 16
    texto(tx, y0, lineas, size, anchor=anchor, bold_primera=bold, mono=mono)


def cilindro(x, y, w, h, lineas, estilo="dato", size=16):
    f, s = C[estilo]
    e = 14
    A(f'<path d="M{x},{y + e} L{x},{y + h - e} A{w / 2},{e} 0 0 0 {x + w},{y + h - e} L{x + w},{y + e}" '
      f'fill="{f}" stroke="{s}" stroke-width="2.4"/>')
    A(f'<ellipse cx="{x + w / 2}" cy="{y + e}" rx="{w / 2}" ry="{e}" fill="{f}" stroke="{s}" stroke-width="2.4"/>')
    alto = size * 1.3
    y0 = y + e + (h - e) / 2 - (len(lineas) - 1) * alto / 2 + size * 0.35
    texto(x + w / 2, y0, lineas, size, bold_primera=True)


def panel(x, y, w, h, titulo, dash=False, estilo="panel"):
    f, s = C[estilo]
    d = ' stroke-dasharray="8 6"' if dash else ""
    A(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="16" fill="{f if not dash else "none"}" stroke="{s}" stroke-width="2"{d}/>')
    texto(x + 22, y + 36, [titulo], 19, anchor="start", bold_primera=True, color=GRIS)


def flecha(puntos, dash=False, color="#3A444C"):
    d = ' stroke-dasharray="8 6"' if dash else ""
    p = " ".join(f"{x},{y}" for x, y in puntos)
    A(f'<polyline points="{p}" fill="none" stroke="{color}" stroke-width="2.6"{d} marker-end="url(#punta)"/>')


def etiqueta(x, y, t, size=15):
    w = len(t) * size * 0.58 + 16
    A(f'<rect x="{x - w / 2}" y="{y - size}" width="{w}" height="{size * 1.55}" rx="4" fill="#FFFFFF"/>')
    texto(x, y + 2, [t], size, color=GRIS)


def pastilla(x, y, w, t):
    A(f'<rect x="{x}" y="{y}" width="{w}" height="46" rx="23" fill="#FFFFFF" stroke="#7A8590" stroke-width="2"/>')
    texto(x + w / 2, y + 29, [t], 15)


A(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">')
A('<defs><marker id="punta" markerUnits="userSpaceOnUse" markerWidth="14" markerHeight="14" refX="13" refY="7" orient="auto">'
  '<path d="M0,0 L14,7 L0,14 z" fill="#3A444C"/></marker></defs>')
A(f'<rect width="{W}" height="{H}" fill="#FFFFFF"/>')

# ============ OPERACIÓN EN LÍNEA ============
panel(20, 20, 1960, 790, "OPERACIÓN EN LÍNEA · Docker Compose: app (Streamlit + agente) + db (PostgreSQL 16 + pgvector) · notebook §10–12")

# Actores
A('<rect x="40" y="150" width="175" height="90" rx="45" fill="#FFFFFF" stroke="#1F2A2E" stroke-width="2.6"/>')
texto(127, 202, ["Vecino/a"], 21, bold_primera=True)
A(f'<rect x="40" y="320" width="175" height="80" rx="40" fill="{C["humano"][0]}" stroke="{C["humano"][1]}" stroke-width="2.6"/>')
texto(127, 355, ["Funcionario/a", "aprueba o rechaza"], 16, bold_primera=True)

# Agente
f, s = C["agente"]
A(f'<rect x="260" y="105" width="480" height="575" rx="12" fill="{f}" stroke="{s}" stroke-width="2.8"/>')
texto(500, 138, ["AGENTE · LangGraph · aplicacion/"], 19, bold_primera=True)
nodos = [("percibir", "intención · trámite · folio · riesgos", "blanco"),
         ("diagnosticar", "reúne hechos con herramientas", "blanco"),
         ("planificar", "10 reglas priorizadas (R1 → R10)", "blanco"),
         ("aprobación humana", "interrupt · solo escalamientos", "humano"),
         ("ejecutar", "plan de pasos (escrituras)", "blanco"),
         ("responder", "citas por tipo de fuente", "blanco"),
         ("memorizar", "decisión · caso · resumen", "blanco")]
for i, (n, d, est) in enumerate(nodos):
    y = 158 + i * 64
    ff, ss = C[est]
    A(f'<rect x="290" y="{y}" width="360" height="50" rx="8" fill="{ff}" stroke="{ss}" stroke-width="2"/>')
    texto(306, y + 22, [n], 16, anchor="start", bold_primera=True, mono=True)
    texto(306, y + 42, [d], 14, anchor="start", color=GRIS)
    if i < len(nodos) - 1:
        flecha([(610, y + 50), (610, y + 64)])
# bucle de replanificación (ejecutar -> diagnosticar)
flecha([(650, 4 * 64 + 183), (678, 4 * 64 + 183), (678, 64 + 183), (652, 64 + 183)], dash=True)
A(f'<text x="697" y="{2.5 * 64 + 183}" font-family="DejaVu Sans, Arial" font-size="14" fill="{GRIS}" '
  f'transform="rotate(90 697 {2.5 * 64 + 183})" text-anchor="middle">replanificar si cambia una condición</text>')
texto(500, 640, ["estado tipado · recursion_limit · máx. 2 replanificaciones"], 14, color=GRIS)
texto(500, 660, ["modo offline: funciona sin LLM (plan B)"], 14, color=GRIS)

# Flechas con actores
flecha([(215, 183), (288, 183)])
etiqueta(250, 168, "controlador")
flecha([(290, 503), (238, 503), (238, 222), (217, 222)])
etiqueta(135, 470, "respuesta + Fuentes")
flecha([(215, 360), (288, 360)])

# Memoria de corto plazo
cilindro(40, 560, 190, 140, ["Corto plazo", "PostgresSaver /", "SqliteSaver", "+ resumen > 8 msj"], "morado", 14)
flecha([(290, 567), (250, 567), (250, 545), (135, 545), (135, 562)])

# Módulo de generación
caja(260, 700, 480, 92, ["MÓDULO DE GENERACIÓN · LLM gratuito vía OpenRouter",
                         "temp. 0.1 · salida estructurada · prompt con reglas + ejemplo",
                         "solo: mensajes ambiguos y preguntas abiertas"], "llm", 14)
flecha([(380, 680), (380, 698)], dash=True)
flecha([(620, 698), (620, 682)], dash=True)
etiqueta(380, 692, "1 · interpreta", 13)
etiqueta(620, 692, "5 · redacta", 13)

# Herramientas
panel(780, 105, 420, 690, "HERRAMIENTAS (17) · adaptadores/entrada", dash=True)
caja(800, 150, 380, 205, ["Escritura · 6", "registrar_solicitud", "actualizar_solicitud",
                          "agendar_hora · derivar_o_escalar", "inscribir_lista_espera", "notificar_vecino"], "blanco", 15)
caja(800, 370, 380, 245, ["Consulta · 7", "buscar_normativa_nacional", "buscar_informacion_municipal",
                          "buscar_orientacion_chileatiende", "buscar_casos_similares", "consultar_estado_solicitud",
                          "consultar_historial_vecino", "consultar_agenda"], "blanco", 15)
caja(800, 630, 380, 150, ["Razonamiento · 4", "verificar_requisitos", "calcular_plazo_habil",
                          "contrastar_fuentes · fecha_actual"], "blanco", 15)
flecha([(740, 250), (798, 250)])
etiqueta(769, 236, "4 · escribe", 14)
flecha([(740, 490), (798, 490)])
etiqueta(769, 476, "2 · invoca", 14)
flecha([(740, 660), (798, 660)])
etiqueta(769, 646, "razona", 14)

# Datos
cilindro(1245, 115, 330, 170, ["Registro municipal · largo plazo", "PostgreSQL (Docker) · SQLite (local)",
                               "solicitudes · bitácora · agenda",
                               "notificaciones · escalamientos · decisiones"], "dato", 15)
panel(1232, 298, 356, 405, "", dash=True, estilo="dato")
texto(1410, 690, ["pgvector + texto completo · Chroma + BM25"], 14, color=GRIS)
for i, (t, d) in enumerate([("leyes", "133 fragmentos por artículo"), ("municipal", "66 · guías + procedimiento (sim.)"),
                            ("chileatiende", "18 · fichas de orientación"), ("casos_resueltos", "memoria episódica")]):
    cilindro(1250, 310 + i * 88, 320, 80, [t, d], "dato", 14)
caja(1245, 715, 260, 70, ["requisitos.json · catálogo", "feriados de Chile"], "dato", 14, bold=False)
flecha([(1180, 230), (1243, 230)])
flecha([(1180, 400), (1212, 400), (1212, 265), (1243, 265)])
flecha([(1180, 445), (1248, 445)])
flecha([(1180, 750), (1243, 750)])

# Procesamiento
caja(1630, 150, 335, 630, ["MÓDULO DE", "RECUPERACIÓN Y CITAS", "", "búsqueda híbrida:", "vectorial (coseno) +", "palabras (texto completo/BM25)",
                           "fusión RRF", "top-k = 4 por índice", "umbral por índice", "(calibrado con datos)",
                           "prioridad por trámite", "", "sin contexto →", "SIN_RESULTADOS", "",
                           "etiquetas [L] [M] [O] [S]", "cita canónica del catálogo", "validador de citas"], "proc", 16)
for i in range(4):
    flecha([(1570, 355 + i * 88), (1628, 355 + i * 88)])
flecha([(1575, 200), (1628, 200)])
# 3 · contexto de vuelta al agente
flecha([(1797, 150), (1797, 78), (500, 78), (500, 103)])
etiqueta(1150, 82, "3 · contexto con fuentes etiquetadas, hechos del registro y cálculos")

# ============ INGESTA ============
panel(20, 830, 1300, 230, "INGESTA RAG (se ejecuta una vez) · scripts/preparar_datos.py · notebook §5")
pasos = [(45, 255, ["Documentos (11)", "4 leyes (BCN) · 3 guías +", "web patentes · 2 ChileAtiende",
                    "· procedimiento (simulado)"], "blanco"),
         (330, 215, ["Carga y limpieza", "PDF por página", "quita encabezados BCN", "y notas del D.O."], "blanco"),
         (575, 225, ["Chunking", "800 car. · solape 120", "corte por artículo", "solo arts. pertinentes"], "blanco"),
         (830, 200, ["Metadatos", "fuente · nivel ·", "artículo · página ·", "trámite"], "blanco"),
         (1060, 240, ["Embeddings", "MiniLM multilingüe", "local · 384 dim", "normalizados"], "llm")]
for i, (x, w, ls, est) in enumerate(pasos):
    caja(x, 880, w, 125, ls, est, 15)
    if i < len(pasos) - 1:
        flecha([(x + w, 942), (pasos[i + 1][0] - 2, 942)])
flecha([(1180, 878), (1180, 812), (1550, 812), (1550, 705)], dash=True)
etiqueta(1360, 816, "construye índices", 14)
texto(670, 1040, ["solicitudes.csv + vecinos.csv (simulados, sin datos personales) → registro municipal · agenda generada"], 14, color=GRIS)

# ============ CONTROL ============
panel(20, 1080, 1300, 230, "CONTROL DE CONTEXTO Y SEGURIDAD")
p1 = [(45, 290, "top-k 4 + umbral por índice"), (350, 300, "SIN_RESULTADOS → extractiva"),
      (665, 300, "R1: sin datos de terceros"), (980, 315, "anti-inyección de prompts")]
p2 = [(45, 290, "escalar = aprobación humana"), (350, 300, "citas validadas vs. catálogo"),
      (665, 300, "cuota: caché + reintento 429"), (980, 315, "máx. 2 replanificaciones")]
for x, w, t in p1:
    pastilla(x, 1140, w, t)
for x, w, t in p2:
    pastilla(x, 1215, w, t)

# ============ EVALUACIÓN ============
panel(1345, 830, 635, 480, "EVALUACIÓN · adaptadores/entrada/evaluacion.py · notebook")
caja(1375, 880, 575, 80, ["Datasets: 18 preguntas · 22 escenarios", "con decisión, herramientas y fuentes esperadas"], "blanco", 15)
caja(1375, 990, 280, 150, ["Deterministas", "decisión · herramientas", "recall@4 · MRR", "cita válida · tipo de fuente",
                           "privacidad · latencia"], "blanco", 14)
caja(1670, 990, 280, 150, ["Juez de otra empresa", "flint (OpenRouter)", "correctness", "faithfulness", "+ LLM puro vs. híbrido"], "llm", 14)
flecha([(1515, 960), (1515, 988)])
flecha([(1810, 960), (1810, 988)])
cilindro(1505, 1175, 320, 110, ["EVIDENCIAS_TEST/", "CSV · gráficos · caché", "LangSmith (opcional)"], "morado", 14)
flecha([(1515, 1140), (1580, 1178)])
flecha([(1810, 1140), (1750, 1178)])

A("</svg>")
REPO = Path(__file__).resolve().parents[2]
destino = REPO / "DOCUMENTACION" / "diagramas" / "arquitectura_completa.svg"
destino.write_text("\n".join(out), encoding="utf-8")

from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    import os
    b = p.chromium.launch(executable_path=os.getenv("CHROME_PATH") or None)
    pg = b.new_page(viewport={"width": W, "height": H}, device_scale_factor=1.6)
    pg.goto(destino.as_uri())
    pg.screenshot(path=str(REPO / "EVIDENCIAS_TEST" / "diagramas" / "arquitectura_completa.png"))
    b.close()
print("ok")
