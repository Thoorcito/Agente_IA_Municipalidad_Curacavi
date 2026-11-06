"""Interfaz web del agente (Streamlit), con aspecto de portal de atención municipal.

Ejecutar desde la raíz del proyecto:   streamlit run app.py      (o: docker compose up)

Es solo la VISTA: todo lo que hace lo pide al ControladorAtencion (agente/adaptadores/entrada/controlador.py).

- Columna izquierda: conversación con el vecino.
- Columna derecha: lo que el agente pensó e hizo (plan y decisión, traza, herramientas y memoria).
- Barra lateral: vecino, número de atención (hilo), ejemplos y condiciones de la demo.
"""
import json
import uuid

import streamlit as st

from agente.configuracion.contenedor import crear_agente, crear_contenedor
from agente.adaptadores.entrada.controlador import ControladorAtencion
from agente.adaptadores.salida.llm.cliente import llm_del_agente

st.set_page_config(page_title="Municipalidad de Curacaví · Atención de trámites", page_icon="🏛️", layout="wide")

ESTILOS = """
<style>
.encabezado {background:#12355b;color:#fff;padding:18px 26px;border-radius:10px;margin-bottom:6px}
.encabezado h1 {font-size:1.7rem;margin:0;color:#fff}
.encabezado p {margin:2px 0 0 0;color:#d6e2f0;font-size:0.95rem}
.aviso {background:#fff6e0;border-left:4px solid #e0a100;padding:6px 12px;border-radius:6px;font-size:0.85rem;margin-bottom:12px}
.etiqueta {display:inline-block;padding:1px 8px;border-radius:10px;font-size:0.75rem;font-weight:600;margin-right:6px}
.legal {background:#e3ecfa;color:#12355b} .municipal {background:#e6f4ea;color:#1e6b34}
.orientativo {background:#f1e8fb;color:#5b2b8a} .simulado {background:#f0f0f0;color:#555}
</style>
"""
EJEMPLOS = {
    "🚗 Renovar permiso de circulación": "Quiero renovar el permiso de circulación de mi auto. Tengo el permiso del año anterior, la revisión técnica, el certificado de gases y el SOAP.",
    "🪪 Primera licencia clase B": "Quiero sacar mi primera licencia de conducir clase B. Tengo mi cédula, dos fotos, el certificado de antecedentes y el certificado de residencia de la junta de vecinos.",
    "📎 Aportar documento faltante": "Ya tengo el certificado de estudios de 8° básico.",
    "🔁 Renovar licencia": "Quiero renovar mi licencia de conducir. Tengo mi licencia anterior, la cédula, comprobante de domicilio y el certificado de antecedentes.",
    "📄 Estado de mi reclamo": "¿En qué estado está mi reclamo SOL-2026-0006?",
    "⚖️ Plazo del permiso (ley vs. municipio)": "¿Cuál es el plazo para renovar el permiso de circulación según la ley y según la municipalidad?",
}


@st.cache_resource
def controlador() -> ControladorAtencion:
    """Se crea una sola vez por servidor: contenedor (base e índices), agente y controlador."""
    contenedor = crear_contenedor()
    try:
        llm = llm_del_agente()
    except ValueError:   # sin clave: el agente funciona en modo plantilla
        llm = None
    return ControladorAtencion(contenedor, crear_agente(contenedor, llm=llm, memoria_persistente=True))


def etiqueta_tipo(tipo: str) -> str:
    clase = {"legal": "legal", "municipal": "municipal", "normativa municipal": "municipal",
             "orientativo": "orientativo"}.get(tipo, "simulado")
    return f'<span class="etiqueta {clase}">{tipo}</span>'


ctl = controlador()
st.markdown(ESTILOS, unsafe_allow_html=True)
st.markdown('<div class="encabezado"><h1>Municipalidad de Curacaví</h1>'
            '<p>Atención de trámites · Asistente digital</p></div>', unsafe_allow_html=True)
st.markdown('<div class="aviso">Prototipo académico (ISY0101, Duoc UC). No es un canal oficial de la Municipalidad: '
            'los datos de solicitudes y vecinos son simulados.</div>', unsafe_allow_html=True)

# --- Barra lateral ------------------------------------------------------------------------------------
with st.sidebar:
    st.subheader("Atención")
    vecinos = [f"V-{i:03d}" for i in range(1, 13)]
    vecino = st.selectbox("Vecino/a (seudónimo)", vecinos, index=1,
                          help="V-001 tiene un permiso rechazado; V-003 tiene un reclamo sin respuesta.")
    if "hilo" not in st.session_state:
        st.session_state.hilo = f"atencion-{uuid.uuid4().hex[:6]}"
    hilo = st.text_input("N° de atención (hilo de conversación)", st.session_state.hilo,
                         help="Con el mismo número, el agente retoma la conversación aunque se cierre la app.")
    st.session_state.hilo = hilo
    if st.button("➕ Nueva atención", width="stretch"):
        st.session_state.hilo = f"atencion-{uuid.uuid4().hex[:6]}"
        st.rerun()

    st.subheader("Ejemplos")
    for etiqueta, texto in EJEMPLOS.items():
        if st.button(etiqueta, width="stretch"):
            st.session_state.pendiente = texto

    st.subheader("Condiciones de la demo")
    ctl.fijar_condiciones(agenda_sin_cupos=st.toggle("Agenda sin horas disponibles"),
                          cupo_tomado_por_otro=st.toggle("Otra persona toma la hora al agendar", key="cupo_tomado"))
    if st.button("↺ Reiniciar datos de la demo", width="stretch"):
        ctl.reiniciar_demo()
        st.success("Base de datos reiniciada")
    info = ctl.info_sistema()
    st.caption(f"Modelo: {info['modelo']}")
    st.caption(f"Persistencia: {info['persistencia']}")
    st.caption(f"Fecha del sistema: {info['fecha']}")

# --- Conversación -------------------------------------------------------------------------------------
izquierda, derecha = st.columns([3, 2], gap="large")
estado = ctl.conversacion(hilo)
resultado = st.session_state.get("ultimo") if st.session_state.get("ultimo_hilo") == hilo else None

with izquierda:
    st.subheader("Conversación")
    if estado.get("resumen"):
        st.info(f"🧠 Resumen de la conversación anterior: {estado['resumen']}")
    for m in estado.get("messages", []):
        with st.chat_message("user" if m.type == "human" else "assistant", avatar="🙂" if m.type == "human" else "🏛️"):
            st.markdown(m.content)

    pendiente = (resultado or {}).get("pendiente_aprobacion")
    if pendiente:
        with st.container(border=True):
            st.warning("**Requiere aprobación de un funcionario** antes de ejecutar: " + pendiente["accion"])
            st.write(pendiente["motivo"])
            st.caption("Fundamentos: " + " · ".join(pendiente["fundamentos"]))
            c1, c2 = st.columns(2)
            if c1.button("✅ Aprobar", width="stretch"):
                st.session_state.ultimo = ctl.resolver_aprobacion(hilo, True)
                st.rerun()
            if c2.button("✋ Rechazar", width="stretch"):
                st.session_state.ultimo = ctl.resolver_aprobacion(hilo, False)
                st.rerun()

    texto = st.chat_input("Escriba su consulta o trámite…") or st.session_state.pop("pendiente", None)
    if texto:
        with st.spinner("El agente está revisando su solicitud…"):
            st.session_state.ultimo = ctl.enviar_mensaje(texto, hilo, vecino)
            st.session_state.ultimo_hilo = hilo
        st.rerun()

# --- Panel del agente ---------------------------------------------------------------------------------
with derecha:
    st.subheader("Cómo decidió el agente")
    if not resultado:
        st.caption("Envíe un mensaje para ver el plan, la traza y la memoria del agente.")
        with st.expander("Reglas de decisión (en orden de prioridad)"):
            for rid, nombre, condicion, accion in ctl.reglas():
                st.markdown(f"**{rid} · {nombre}** — {condicion} → `{accion}`")
    else:
        d = resultado["decision"]
        plan_tab, traza_tab, herr_tab, mem_tab = st.tabs(["Plan y decisión", "Traza", "Herramientas", "Memoria"])
        with plan_tab:
            st.markdown(f"**{d['regla_id']} · {d['regla']}** → `{d['accion']}`")
            st.write(d["motivo"])
            for f in d.get("fundamentos", []):
                st.markdown(f"{etiqueta_tipo(f['tipo'])} {f['cita']} — {f['detalle']}", unsafe_allow_html=True)
            if resultado.get("plan"):
                st.markdown("**Plan**")
                for i, paso in enumerate(resultado["plan"], 1):
                    icono = {"hecho": "✅", "fallido": "❌"}.get(paso.get("estado"), "⏳")
                    st.markdown(f"{i}. {icono} `{paso['herramienta']}`")
            redaccion = {"llm": "LLM (redacta con los fragmentos recuperados)",
                         "plantilla": "plantilla (datos exactos del sistema)"}.get(resultado.get("modo_redaccion"), "—")
            st.caption(f"Redacción: {redaccion} · Replanificaciones: {resultado.get('replanificaciones', 0)} · "
                       f"Cita válida: {(resultado.get('validacion') or {}).get('cita_valida')} · "
                       f"Latencia: {resultado.get('latencia_s')} s")
            if resultado.get("aviso_llm"):
                st.warning(f"No se pudo usar el LLM; se respondió con la versión extractiva. Motivo: {resultado['aviso_llm']}")
        with traza_tab:
            for e in resultado.get("traza", []):
                st.markdown(f"**{e['nodo']}** · {e['detalle']}")
        with herr_tab:
            iconos = {"consulta": "🔎", "escritura": "✍️", "razonamiento": "🧮"}
            for o in resultado.get("observaciones", []):
                with st.expander(f"{iconos.get(o['tipo'], '•')} {o['herramienta']} ({o['tipo']}, {o['ms']} ms)"):
                    st.code(json.dumps(o["args"], ensure_ascii=False, indent=1), language="json")
                    st.code(json.dumps(o["resultado"], ensure_ascii=False, indent=1, default=str)[:3000], language="json")
        with mem_tab:
            st.markdown("**Corto plazo (este hilo)**")
            st.write({"trámite en curso": estado.get("tramite_activo"), "esperando": estado.get("esperando"),
                      "documentos declarados": estado.get("documentos"), "folio en curso": estado.get("folio_en_curso"),
                      "turnos": estado.get("turnos")})
            st.markdown("**Largo plazo (vecino)**")
            st.dataframe(ctl.solicitudes_del_vecino(vecino), width="stretch", hide_index=True)
            avisos = ctl.notificaciones(vecino)
            if avisos:
                st.markdown("**Notificaciones enviadas**")
                for n in avisos:
                    st.caption(f"{n['fecha']} · {n['canal']} · {n['folio']}: {n['mensaje']}")
