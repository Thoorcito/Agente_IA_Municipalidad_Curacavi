# Alcance del agente

## Lo que hace
- Recibe solicitudes de vecinos en lenguaje natural para cinco trámites: renovación del permiso de circulación,
  primera licencia clase B, renovación de licencia, patente comercial y reclamos a la OIRS.
- Revisa los documentos que el vecino dice tener contra los requisitos de cada trámite y separa lo que exige la
  ley de lo que pide la municipalidad.
- **Escribe** en el sistema municipal simulado: registra folios, actualiza estados, agenda horas, inscribe en
  lista de espera, escala casos y envía notificaciones.
- Consulta el estado de una solicitud por folio y calcula si su plazo venció (en días hábiles).
- Responde preguntas sobre requisitos, plazos y normas citando la fuente según su tipo: ley, información
  municipal, ChileAtiende o documento simulado.
- Recuerda el trámite en curso entre sesiones y el historial de cada vecino.
- Cambia el plan cuando cambian las condiciones (por ejemplo, cuando la hora elegida ya no está disponible).
- Pide aprobación a un funcionario antes de escalar un caso.

## Lo que no hace
- No procesa pagos ni emite documentos oficiales.
- No entrega datos personales (RUT, teléfono, domicilio). Los vecinos se identifican con un seudónimo.
- No da asesoría legal personalizada: informa lo que dicen las fuentes y deriva a la unidad que corresponde.
- No reemplaza al funcionario: lo asiste y le deja trazabilidad.
- No atiende trámites de otros organismos (Registro Civil, SII, revisión técnica); los deriva.

## Métricas de éxito

| Objetivo | Métrica | Meta |
|---|---|---|
| Decidir bien | Exactitud de la acción en los 22 escenarios | ≥ 90 % |
| Recuperar la fuente correcta | Recall@4 de fuentes esperadas | ≥ 0,7 |
| Citar sin inventar | Respuestas con cita válida (etiqueta existente y ley respaldada) | 100 % |
| Citar el tipo de fuente correcto | Ley citada como ley, guía como información municipal | ≥ 90 % |
| Proteger datos | Respuestas sin RUT ni teléfonos en preguntas de riesgo | 100 % |
| Responder rápido | Latencia por turno | < 60 s |
