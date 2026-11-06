"""Resumen de conversaciones largas (memoria de corto plazo).

Para que la conversación no crezca sin límite, los mensajes antiguos se condensan en un resumen y se
eliminan del historial (se conservan los últimos turnos). Con LLM se redacta; sin LLM se arma con los
hechos clave del trámite.
"""
from agente.aplicacion.llm_utilidades import texto_de


def resumir(mensajes: list, resumen_previo: str, memoria: dict, llm=None) -> str:
    """Condensa los mensajes antiguos. Con LLM redacta un resumen; sin LLM arma uno con los hechos clave."""
    if llm is not None:
        try:
            historial = "\n".join(f"{m.type}: {texto_de(m)[:400]}" for m in mensajes)
            r = llm.invoke("Resume en 3 líneas, en español, esta conversación entre un vecino y el asistente "
                           f"municipal. Conserva trámite, folio, documentos y pendientes.\nResumen previo: {resumen_previo}\n{historial}")
            return texto_de(r).strip()
        except Exception:  # si el LLM falla se usa el resumen determinista
            pass
    partes = [resumen_previo] if resumen_previo else []
    partes.append(f"{len(mensajes)} mensajes anteriores condensados.")
    if memoria.get("tramite_activo"):
        partes.append(f"Trámite en curso: {memoria['tramite_activo']}.")
    if memoria.get("folio_en_curso"):
        partes.append(f"Folio: {memoria['folio_en_curso']}.")
    if memoria.get("documentos"):
        partes.append(f"Documentos declarados: {', '.join(memoria['documentos'])}.")
    if memoria.get("ultima_accion"):
        partes.append(f"Última decisión: {memoria['ultima_accion']}.")
    return " ".join(partes)
