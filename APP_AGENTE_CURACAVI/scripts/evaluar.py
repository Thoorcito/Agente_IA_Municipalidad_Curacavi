"""Evaluación desde la terminal. Los resultados quedan en EVIDENCIAS_TEST/evaluaciones/ (raíz del repositorio).

Uso (desde la raíz del proyecto):
    python -m scripts.evaluar escenarios --offline     # decisiones del agente (sin LLM)
    python -m scripts.evaluar recuperacion              # antes/después de la recuperación (MiniLM)
    python -m scripts.evaluar recuperacion --calibrar   # además guarda data/umbrales.json
    python -m scripts.evaluar respuestas --juez         # requiere la clave de OpenRouter (y la de Gemini si JUEZ_PROVIDER=google)
"""
import argparse
import json
import tempfile
from pathlib import Path

from agente.adaptadores.entrada import evaluacion as ev
from agente.configuracion.contenedor import crear_agente as armar_agente
from agente.configuracion.contenedor import crear_contenedor
from agente.adaptadores.salida.llm.cliente import crear_juez, llm_del_agente
from agente.adaptadores.salida.memoria.ingesta import crear_embeddings
from agente.configuracion import settings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tipo", choices=["escenarios", "recuperacion", "respuestas"])
    parser.add_argument("--offline", action="store_true", help="Sin LLM y con embeddings por hashing")
    parser.add_argument("--calibrar", action="store_true", help="Calibra y guarda los umbrales por índice")
    parser.add_argument("--juez", action="store_true", help="Evalúa correctness/faithfulness con el juez (settings.JUEZ_MODEL)")
    args = parser.parse_args(argv)
    settings.EVIDENCE_DIR.mkdir(exist_ok=True)
    proveedor = "offline" if args.offline else settings.EMBEDDINGS_PROVIDER

    if args.tipo == "recuperacion":
        emb = crear_embeddings(proveedor)
        # ignore_cleanup_errors: en Windows Chroma deja abierto su archivo SQLite y la carpeta temporal
        # no se puede borrar al salir (WinError 32). El resultado no cambia; Windows limpia Temp después.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            detalle, resumen = ev.evaluar_recuperacion(emb, Path(tmp), umbrales=settings.umbrales(proveedor))
            if args.calibrar:
                s = crear_contenedor(proveedor_embeddings=proveedor)
                calibrados = ev.calibrar_umbrales(s.indice)
                datos = json.loads(settings.UMBRALES_PATH.read_text(encoding="utf-8")) if settings.UMBRALES_PATH.exists() else {}
                datos[proveedor] = {c: v["umbral"] for c, v in calibrados.items()}
                settings.UMBRALES_PATH.write_text(json.dumps(datos, indent=1), encoding="utf-8")
                print("Umbrales calibrados:", calibrados)
        detalle.to_csv(settings.EVIDENCE_DIR / f"recuperacion_detalle_{proveedor}.csv", index=False)
        resumen.to_csv(settings.EVIDENCE_DIR / f"recuperacion_resumen_{proveedor}.csv", index=False)
        print(resumen.to_string(index=False))
        return resumen

    s = crear_contenedor(proveedor_embeddings=proveedor)
    llm = None if args.offline else llm_del_agente()

    def crear_agente(checkpointer=None):
        return armar_agente(s, llm=llm, checkpointer=checkpointer)

    if args.tipo == "escenarios":
        df = ev.evaluar_escenarios(s, crear_agente)
        df.to_csv(settings.EVIDENCE_DIR / f"escenarios_{'offline' if args.offline else 'llm'}.csv", index=False)
        print(df[["id", "regla", "accion", "regla_ok", "accion_ok", "herramientas_ok", "escrituras_ok", "replanificaciones"]].to_string(index=False))
        print(f"\nExactitud de decisión: {df['accion_ok'].mean():.0%} (n={len(df)})")
        return df

    juez = crear_juez() if args.juez else None
    df = ev.evaluar_respuestas(crear_agente, s, juez=juez, etiqueta="offline" if args.offline else "llm")
    df.to_csv(settings.EVIDENCE_DIR / f"respuestas_{'offline' if args.offline else 'llm'}.csv", index=False)
    print(df.drop(columns=["respuesta"]).to_string(index=False))
    return df


if __name__ == "__main__":
    main()
