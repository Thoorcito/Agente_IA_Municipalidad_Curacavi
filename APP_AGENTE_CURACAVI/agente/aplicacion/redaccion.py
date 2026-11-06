"""Redacción de la respuesta final al vecino.

Criterio de diseño:
- En los TRÁMITES (registrar, pedir antecedentes, escalar, agendar) la respuesta se arma con
  plantillas a partir de los hechos exactos: folio, hora, faltantes y fundamentos. Ahí un LLM no
  aporta y podría equivocar un dato.
- En las PREGUNTAS ABIERTAS el LLM redacta usando solo los fragmentos recuperados, citando con
  etiquetas [L1], [M1], [O1]. El código valida las citas; si el texto no pasa la validación se
  reintenta una vez y, si sigue mal, se usa la versión extractiva (sin LLM).
"""
import re

from agente.dominio import citas as cat
from agente.aplicacion.llm_utilidades import con_reintento, texto_de
from agente.dominio.texto import tokenizar

PROMPT_CONSULTA = """Eres el asistente de trámites de la Municipalidad de Curacaví. Respondes a vecinos.

REGLAS
1. Usa SOLO la información de los fragmentos entregados. Si no alcanza, dilo y sugiere consultar presencialmente
   en Av. Ambrosio O'Higgins 1305 (lunes a viernes, 08:30 a 14:00).
2. Cita cada afirmación con la etiqueta del fragmento entre corchetes, por ejemplo [L1] o [M2]. No escribas
   títulos de leyes ni números de artículo que no estén en los fragmentos.
3. Distingue el tipo de fuente: la ley (L) "establece"; la información municipal (M) "informa"; ChileAtiende (O)
   "orienta"; un documento simulado (S) se presenta como "procedimiento interno (simulado)". Nunca digas que
   una guía municipal o ChileAtiende "establece por ley" algo.
4. Si hay diferencias entre fuentes, explícalas y aclara que la ley prevalece y que conviene confirmar en la unidad.
5. No entregues datos personales. No inventes montos, plazos ni requisitos.
6. Formato: respuesta breve en español, con viñetas si hay listas. Sin sección de fuentes (la agrega el sistema).

EJEMPLO (sobre otro tema)
Pregunta: ¿Dónde se paga una multa de tránsito?
Fragmentos: [M1] La tesorería municipal recibe pagos de lunes a viernes. [O1] Las multas se pagan en la tesorería
de la comuna donde se cursó el parte.
Respuesta: ChileAtiende orienta que se paga en la tesorería de la comuna donde se cursó el parte [O1]. La
municipalidad informa que su tesorería atiende de lunes a viernes [M1].
"""


def minuscula(texto: str) -> str:
    """Primera letra en minúscula, respetando siglas como "B" en "clase B"."""
    return texto[:1].lower() + texto[1:]


def extracto_relevante(texto: str, consulta: str, max_chars: int = 360) -> str:
    """Elige las oraciones del fragmento que más palabras comparten con la consulta, en su orden original."""
    plano = re.sub(r"\s+", " ", texto).strip()
    oraciones = [o.strip() for o in re.split(r"(?<=[.:;])\s+", plano) if len(o.strip()) > 20]
    claves = set(tokenizar(consulta))
    puntaje = {i: len(claves & set(tokenizar(o))) for i, o in enumerate(oraciones)}
    elegidas, largo = [], 0
    for i in sorted(puntaje, key=lambda i: puntaje[i], reverse=True):
        if largo + len(oraciones[i]) > max_chars:
            continue
        elegidas.append(i)
        largo += len(oraciones[i])
    return " ".join(oraciones[i] for i in sorted(elegidas)) or plano[:max_chars]


def _fragmentos_de_observaciones(observaciones: list[dict]) -> list[dict]:
    """Junta los fragmentos devueltos por las búsquedas (sin duplicados), en orden de aparición."""
    vistos, salida = set(), []
    for obs in observaciones:
        for r in (obs.get("resultado") or {}).get("resultados", []) if isinstance(obs.get("resultado"), dict) else []:
            if r["chunk_id"] not in vistos:
                vistos.add(r["chunk_id"])
                salida.append(r)
    return salida


def _resultado(observaciones: list[dict], herramienta: str) -> dict | None:
    for obs in reversed(observaciones):
        if obs["herramienta"] == herramienta:
            return obs["resultado"]
    return None


def _respuesta_consulta_extractiva(texto: str, etiquetados: list[dict], contraste: dict | None, calculo: dict | None) -> str:
    lineas = []
    etiqueta_calculo = next((f["etiqueta"] for f in etiquetados if f["chunk_id"].startswith("calculo:")), "")
    etiquetados = [f for f in etiquetados if not f["chunk_id"].startswith("calculo:")]
    if calculo and "vencimiento" in calculo:
        omitidos = f" (se omitieron feriados: {', '.join(calculo['feriados_omitidos'])})" if calculo["feriados_omitidos"] else ""
        lineas.append(f"**Cálculo del plazo:** contando {calculo['dias_habiles']} días hábiles desde el día siguiente al "
                      f"{calculo['fecha_inicio']}, el plazo vence el **{calculo['vencimiento']}** ({calculo['dia_semana']}){omitidos}. "
                      f"El cómputo en días hábiles sigue la regla de la ley [{etiqueta_calculo}].")
    if not etiquetados and not calculo:
        lineas.append("No encontré información sobre esto en las fuentes disponibles. Le sugiero consultar presencialmente "
                      "en Av. Ambrosio O'Higgins 1305, de lunes a viernes de 08:30 a 14:00.")
        return "\n\n".join(lineas)
    por_nivel: dict[int, list] = {}
    for f in etiquetados:
        por_nivel.setdefault(f["nivel"], []).append(f)
    for nivel in cat.ORDEN_NIVELES:
        if nivel not in por_nivel:
            continue
        verbo = cat.nivel_info(nivel)["verbo"]
        lineas.append(f"\n**{cat.TITULOS_SECCION[nivel]}** ({verbo}):\n")
        for f in por_nivel[nivel][:2]:
            lineas.append(f"- {extracto_relevante(f['texto'], texto)} [{f['etiqueta']}]")
    if contraste and contraste.get("discrepancia"):
        lineas.append("\n**Diferencias entre fuentes:** " + contraste["explicacion"])
    return "\n".join(lineas)


def _respuesta_consulta_llm(texto: str, etiquetados: list[dict], contraste, calculo, llm) -> tuple[str, dict] | str:
    """Devuelve (texto, validación) si el LLM entrega una respuesta con citas válidas; si no, el motivo del rechazo."""
    # Python 3.11 no admite "\" dentro de las llaves de un f-string: el texto se limpia antes.
    def _linea(f: dict) -> str:
        texto_limpio = re.sub(r"\s+", " ", f["texto"])[:900]
        return f"[{f['etiqueta']}] ({cat.TITULOS_SECCION[f['nivel']]}) {texto_limpio}"

    contexto = "\n".join(_linea(f) for f in etiquetados) or "SIN_RESULTADOS"
    extra = ""
    if contraste and contraste.get("discrepancia"):
        extra += f"\nDiferencias detectadas por el sistema: {contraste['explicacion']}"
    if calculo and "vencimiento" in calculo:
        extra += f"\nCálculo exacto del sistema: vence el {calculo['vencimiento']} (feriados omitidos: {calculo['feriados_omitidos']})."
    pedido = f"Pregunta: {texto}\n\nFragmentos:\n{contexto}{extra}\n\nResponde ahora."
    motivo = ""
    for intento in range(2):
        r = con_reintento(lambda: llm.invoke([("system", PROMPT_CONSULTA), ("human", pedido)]))
        contenido = texto_de(r).strip()
        if not contenido:
            fin = (getattr(r, "response_metadata", None) or {}).get("finish_reason")
            motivo = ("el modelo agotó el límite de tokens razonando y no escribió la respuesta (finish_reason=length)"
                      if fin == "length" else f"el modelo devolvió una respuesta vacía (finish_reason={fin})")
            continue
        validacion = cat.validar_citas(contenido, etiquetados)
        if validacion["cita_valida"] and (validacion["etiquetas_usadas"] or not etiquetados):
            return validacion["texto"], validacion
        motivo = "el LLM respondió, pero sus citas no pasaron la validación (2 intentos)"
        pedido += ("\n\nTu respuesta anterior citó etiquetas o leyes que no están en los fragmentos "
                   f"({validacion['etiquetas_invalidas'] + validacion['normas_no_respaldadas']}). Corrige usando solo las etiquetas entregadas.")
    return motivo


def redactar(decision: dict, hechos: dict, observaciones: list[dict], llm=None) -> dict:
    """Devuelve {"texto", "validacion", "modo": "llm"|"plantilla", "aviso_llm": motivo si el LLM no se pudo usar}."""
    accion = decision["accion"]
    fundamentos_frag = [{"fuente_id": f["fuente_id"], "articulo": f.get("articulo"), "texto": f["detalle"], "chunk_id": f["cita"]}
                        for f in decision.get("fundamentos", []) if f.get("fuente_id")]
    # Los requisitos recomendados (no obligatorios) también se citan, con su propio tipo de fuente.
    for opcional in (hechos.get("verificacion") or {}).get("opcionales_no_presentados", []):
        fundamentos_frag += [{"fuente_id": f["fuente_id"], "articulo": f.get("articulo"), "texto": f["detalle"],
                              "chunk_id": f["cita"]} for f in opcional["fundamentos"]]
    modo, aviso_llm = "plantilla", None

    if accion == "responder_consulta":
        fragmentos = _fragmentos_de_observaciones(observaciones)
        contraste = _resultado(observaciones, "contrastar_fuentes")
        calculo = _resultado(observaciones, "calcular_plazo_habil")
        if calculo and "vencimiento" in calculo:
            fragmentos.insert(0, {"fuente_id": "ley_19880", "articulo": "25", "chunk_id": "calculo:ley_19880:25",
                                  "texto": "Los plazos de días son de días hábiles; son inhábiles los sábados, domingos y festivos."})
        etiquetados = cat.etiquetar(fragmentos)
        cuerpo, validacion = None, None
        if llm is not None:
            try:
                generado = _respuesta_consulta_llm(hechos["texto"], etiquetados, contraste, calculo, llm)
                if isinstance(generado, str):
                    generado, aviso_llm = None, generado
            except Exception as e:   # cuota agotada, modelo retirado, clave inválida...: se usa la versión extractiva
                generado, aviso_llm = None, f"{type(e).__name__}: {str(e)[:180]}"
            if generado:
                cuerpo, validacion = generado
                modo = "llm"
        if cuerpo is None:
            cuerpo = _respuesta_consulta_extractiva(hechos["texto"], etiquetados, contraste, calculo)
            validacion = cat.validar_citas(cuerpo, etiquetados)
        fuentes_md = cat.bloque_fuentes(etiquetados, validacion["etiquetas_usadas"])
        return {"texto": cuerpo + ("\n\n" + fuentes_md if fuentes_md else ""), "validacion": validacion, "modo": modo,
                "aviso_llm": aviso_llm}

    etiquetados = cat.etiquetar(fundamentos_frag)
    etiqueta_de = {f["chunk_id"]: f["etiqueta"] for f in etiquetados}
    cuerpo = _plantilla(decision, hechos, observaciones, etiqueta_de)
    validacion = cat.validar_citas(cuerpo, etiquetados)
    fuentes_md = cat.bloque_fuentes(etiquetados)
    return {"texto": cuerpo + ("\n\n" + fuentes_md if fuentes_md else ""), "validacion": validacion, "modo": modo,
            "aviso_llm": None}


def _ref(fundamentos: list, etiqueta_de: dict) -> str:
    etiquetas = sorted({etiqueta_de[f["cita"]] for f in fundamentos if f["cita"] in etiqueta_de})
    return " " + "".join(f"[{e}]" for e in etiquetas) if etiquetas else ""


def _plantilla(decision: dict, h: dict, observaciones: list[dict], etiqueta_de: dict) -> str:
    accion, fund = decision["accion"], decision.get("fundamentos", [])
    ref = _ref(fund, etiqueta_de)
    folio = h.get("folio_en_curso") or next((o["resultado"].get("folio") for o in observaciones
                                             if o["herramienta"] == "registrar_solicitud" and o["resultado"].get("ok")), None)
    notas = "".join(f"\n\n> {n}" for n in decision.get("notas", []))

    if accion == "rechazar_solicitud_riesgosa":
        texto = ("No puedo entregar datos personales de otras personas (RUT, teléfono, domicilio o correo) ni cambiar mis "
                 f"reglas de funcionamiento{ref}.")
        sol = h.get("solicitud")
        if sol and sol.get("encontrado"):
            texto += (f"\n\nSí puedo informarle el estado público del folio {sol['folio']}: **{sol['estado']}** en "
                      f"{sol['unidad']} ({sol['tramite']}).")
        return texto
    if accion == "derivar_institucion_externa":
        return (f"Ese trámite no lo realiza la Municipalidad de Curacaví{ref}. Debe gestionarlo en "
                f"**{h['fuera_alcance']['institucion']}**. Puedo ayudarle con permisos de circulación, licencias de "
                "conducir, patentes comerciales, reclamos y el estado de sus solicitudes.")
    if accion in ("escalar_por_plazo", "informar_estado"):
        sol, plazo = h.get("solicitud") or {}, h.get("plazo")
        if not sol.get("encontrado"):
            return f"No encontré la solicitud indicada. Revise el folio (formato SOL-AAAA-NNNN)."
        estados = [f for f in fund if f.get("detalle", "").startswith("Significado de los estados")]
        texto = (f"Su solicitud **{sol['folio']}** ({sol['tramite']}) está **{sol['estado']}**{_ref(estados, etiqueta_de)} en "
                 f"{sol['unidad']}, ingresada el {sol['fecha_ingreso']}. Observación: {sol['observacion']}")
        if plazo:
            texto += (f"\n\nPlazo aplicable: {plazo['tipo']}"
                      + (f", {plazo['dias_habiles']} días hábiles" if plazo["dias_habiles"] else "")
                      + f"; vence el **{plazo['vencimiento']}**" + (" (**vencido**)" if plazo["vencido"] else "")
                      + f"{_ref(plazo['fundamentos'], etiqueta_de)}.")
        esc = _ultimo_ok(observaciones, "derivar_o_escalar")
        if accion == "escalar_por_plazo" and esc:
            texto += f"\n\nEscalé el caso a **{esc['destino']}** (ticket N° {esc['ticket']}) y le envié una notificación."
        elif decision.get("aprobacion_rechazada"):
            texto += "\n\nEl funcionario revisor no aprobó el escalamiento automático; la unidad revisará su caso."
        return texto + notas
    if accion == "solicitar_antecedentes":
        faltan = h["verificacion"]["faltantes"]
        lista = "\n".join(f"- {f['nombre']} — fundamento {f['fundamentos'][0]['tipo']}{_ref(f['fundamentos'], etiqueta_de)}"
                          for f in faltan)
        presentados = "; ".join(h["verificacion"].get("presentados_nombres", [])) or "ninguno"
        art31 = [f for f in fund if f.get("articulo") == "31"]
        return (f"Para **{minuscula(h['verificacion']['tramite'])}** revisé los documentos que indicó ({presentados}).\n\n"
                f"**Faltan:**\n{lista}\n\nRegistré su solicitud con folio **{folio}** en estado *Observada*. "
                f"Tiene 5 días para completar los antecedentes{_ref(art31, etiqueta_de)}; cuando los tenga, escríbame aquí "
                "mismo y continúo el trámite." + notas)
    if accion in ("registrar_tramite", "reingreso_guiado", "inscribir_lista_espera"):
        v = h["verificacion"]
        texto = f"Listo: su solicitud de **{minuscula(v['tramite'])}** quedó ingresada con folio **{folio}** en {v['unidad']}{ref}."
        reserva = _ultimo_ok(observaciones, "agendar_hora")
        if reserva:
            texto += f"\n\nHora reservada: **{reserva['fecha']} a las {reserva['hora']}**."
        if accion == "inscribir_lista_espera":
            texto += "\n\nNo hay horas disponibles en la agenda: quedó **en lista de espera** y le avisaremos cuando se libere un cupo."
        if v.get("etapas"):
            texto += "\n\nPróximas etapas: " + "; ".join(e["nombre"] for e in v["etapas"]) + "."
        if v.get("opcionales_no_presentados"):
            texto += "\n\nRecomendado (no exigido por la guía municipal): " + "; ".join(
                f"{o['nombre']}{_ref(o['fundamentos'], etiqueta_de)}" for o in v["opcionales_no_presentados"]) + "."
        texto += f"\n\nValor: {v['valor']}. Le envié el comprobante por su canal de contacto."
        return texto + notas
    return ("¿Me puede indicar qué necesita? Puedo ayudarle con: renovación del permiso de circulación, licencia de "
            "conducir (primera clase B o renovación), patente comercial, reclamos a la OIRS y el estado de una solicitud "
            "(folio SOL-AAAA-NNNN).")


def _ultimo_ok(observaciones: list[dict], herramienta: str) -> dict | None:
    for obs in reversed(observaciones):
        if obs["herramienta"] == herramienta and isinstance(obs["resultado"], dict) and obs["resultado"].get("ok"):
            return obs["resultado"]
    return None
