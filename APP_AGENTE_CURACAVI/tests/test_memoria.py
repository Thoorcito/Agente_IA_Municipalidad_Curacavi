"""Memoria de corto plazo (hilo), largo plazo (registro) y semántica, con los adaptadores locales.

Las mismas pruebas de contrato contra PostgreSQL + pgvector están en tests/integracion/.
"""
from datetime import date

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage

from agente.aplicacion.orquestador import AgenteTramites
from agente.dominio.modelo import dia_de_atencion_licencias
from agente.adaptadores.salida.memoria.ingesta import HashingEmbeddings, cargar_documentos, fragmentar, limpiar_texto_ley
from agente.adaptadores.salida.local.indice_chroma import IndiceChroma
from agente.adaptadores.salida.memoria.conversaciones import crear_checkpointer
from agente.aplicacion.resumen import resumir
from tests.conftest import LLMSimulado

LICENCIA_INCOMPLETA = ("Quiero sacar mi primera licencia de conducir clase B. Tengo mi cédula, dos fotos, el certificado "
                       "de antecedentes y el certificado de residencia de la junta de vecinos.")


# --- Largo plazo ---------------------------------------------------------------------------------------

def test_base_inicial_y_agenda_respetan_los_dias_de_atencion(contenedor):
    # Act
    cupos = contenedor.registro.cupos_disponibles(limite=500)

    # Assert
    assert len(contenedor.registro.todas_las_solicitudes()) == 30
    assert all(dia_de_atencion_licencias(date.fromisoformat(c["fecha"])) for c in cupos)
    assert min(c["fecha"] for c in cupos) >= "2026-11-24"   # 20 días de anticipación


def test_decisiones_quedan_en_memoria_de_largo_plazo(agente, contenedor):
    # Act
    agente.conversar("¿Me pueden ayudar a sacar el pasaporte?", "hilo-1", "V-005")

    # Assert
    decision = contenedor.registro.decisiones("V-005")[-1]
    assert decision["regla"] == "R2" and decision["thread_id"] == "hilo-1"


# --- Corto plazo -----------------------------------------------------------------------------------------

def test_el_tramite_se_retoma_despues_de_cerrar_la_app(contenedor, tmp_path):
    # Arrange: primer turno con un agente y memoria en disco
    ruta = tmp_path / "memoria.sqlite"
    primero = AgenteTramites(contenedor, checkpointer=crear_checkpointer(ruta))
    r1 = primero.conversar(LICENCIA_INCOMPLETA, "hilo-licencia", "V-002")

    # Act: "se cierra la app" y un agente NUEVO lee la misma memoria
    segundo = AgenteTramites(contenedor, checkpointer=crear_checkpointer(ruta))
    r2 = segundo.conversar("Ya tengo el certificado de estudios de 8° básico.", "hilo-licencia", "V-002")

    # Assert
    assert r1["decision"]["accion"] == "solicitar_antecedentes"
    assert r2["percepcion"]["intencion"] == "aportar_antecedentes"
    assert r2["folio_en_curso"] == r1["folio_en_curso"]
    assert r2["decision"]["accion"] == "registrar_tramite" and r2["esperando"] is None
    primero.checkpointer.conn.close()
    segundo.checkpointer.conn.close()


def test_conversacion_larga_se_resume(agente):
    # Arrange
    for i in range(5):
        agente.conversar("hola", "hilo-largo", "V-012")

    # Act
    estado = agente.estado("hilo-largo")

    # Assert: quedan los últimos mensajes y un resumen con lo anterior
    assert len(estado["messages"]) <= 8
    assert "mensajes anteriores condensados" in estado["resumen"]


def test_resumen_con_llm_y_respaldo_sin_llm():
    # Arrange
    mensajes = [HumanMessage(content="quiero la licencia"), AIMessage(content="faltan estudios")]
    memoria = {"tramite_activo": "primera_licencia_b", "folio_en_curso": "SOL-2026-0031", "documentos": ["cedula"],
               "ultima_accion": "solicitar_antecedentes"}

    # Act
    con_llm = resumir(mensajes, "", memoria, LLMSimulado(respuestas=["Vecino pide licencia B; faltan estudios."]))
    llm_caido = resumir(mensajes, "previo.", memoria, LLMSimulado(respuestas=["x"], falla=True))

    # Assert
    assert con_llm == "Vecino pide licencia B; faltan estudios."
    assert llm_caido.startswith("previo.") and "SOL-2026-0031" in llm_caido and "cedula" in llm_caido


# --- Semántica -------------------------------------------------------------------------------------------

def test_leyes_se_cortan_por_articulo_y_se_acotan():
    # Arrange
    documentos = cargar_documentos()

    # Act
    acotado = fragmentar(documentos)
    completo = fragmentar(documentos, acotar_leyes=False, separar_externas=False)

    # Assert
    assert set(acotado) == {"leyes", "municipal", "chileatiende"}
    assert set(completo) == {"externa", "municipal"}
    assert len(acotado["leyes"]) < len(completo["externa"]) / 4
    assert all(d.metadata["articulo"] for d in acotado["leyes"])


def test_limpieza_quita_anotaciones_del_diario_oficial():
    # Act
    limpio = limpiar_texto_ley("Artículo 12.- Las resoluciones D.O. 03.05.2002\nLey 21180 se denominarán ordenanzas")

    # Assert
    assert "D.O." not in limpio and "21180" not in limpio and "ordenanzas" in limpio


def test_umbral_por_indice_y_prioridad_por_tramite(tmp_path):
    # Arrange
    indice = IndiceChroma(tmp_path, HashingEmbeddings(), umbrales={"pruebas": 0.99})
    docs = [Document(page_content="Requisitos para la licencia de conducir clase B en la comuna",
                     metadata={"chunk_id": "a", "fuente_id": "guia_licencias", "tramites": "primera_licencia_b", "nivel": 3}),
            Document(page_content="Requisitos para la licencia de conducir profesional y permisos",
                     metadata={"chunk_id": "b", "fuente_id": "guia_licencias", "tramites": "patente_comercial", "nivel": 3})]
    # Documentos de relleno: BM25 necesita varios textos para estimar qué palabras son poco frecuentes
    docs += [Document(page_content=t, metadata={"chunk_id": f"r{i}", "tramites": "otro"}) for i, t in enumerate(
        ["Horario de atención de la tesorería municipal", "Pago del impuesto territorial y contribuciones",
         "Reclamos y sugerencias en la oficina OIRS", "Certificados de la dirección de obras"])]
    indice.construir({"pruebas": docs})

    # Act
    solo_vectorial = indice.buscar("pruebas", "requisitos licencia de conducir", hibrida=False)
    hibrida = indice.buscar("pruebas", "requisitos licencia de conducir", tramite="patente_comercial")

    # Assert: con umbral 0.99 la vectorial no deja pasar nada; BM25 sí, y prioriza el trámite indicado
    assert solo_vectorial == []
    assert hibrida[0]["chunk_id"] == "b"


def test_memoria_episodica_agrega_y_recupera_casos(tmp_path):
    # Arrange
    indice = IndiceChroma(tmp_path, HashingEmbeddings(), umbrales={"casos_resueltos": 0.2})
    indice.construir({"casos_resueltos": [Document(page_content="Caso inicial de patente comercial",
                                                   metadata={"chunk_id": "c0", "tramites": "*"})]})

    # Act
    indice.agregar("casos_resueltos", "Caso SOL-2026-0040: licencia en lista de espera por falta de horas", {"tramites": "*"})
    recargado = IndiceChroma(tmp_path, HashingEmbeddings(), umbrales={"casos_resueltos": 0.2})
    r = recargado.buscar("casos_resueltos", "lista de espera licencia falta de horas")

    # Assert: el caso persiste en disco y se recupera por similitud
    assert r[0]["texto"].startswith("Caso SOL-2026-0040")
    assert recargado.conteo()["casos_resueltos"] == 2


def test_coleccion_inexistente_devuelve_lista_vacia(tmp_path):
    indice = IndiceChroma(tmp_path, HashingEmbeddings())
    assert indice.buscar("no_existe", "algo") == [] and indice.conteo() == {}
