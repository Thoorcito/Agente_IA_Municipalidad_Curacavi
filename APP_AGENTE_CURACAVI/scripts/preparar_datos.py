"""Prepara la base de datos y los índices del RAG (paso obligatorio antes de usar el agente).

Uso (desde la raíz del proyecto):
    python -m scripts.preparar_datos              # embeddings locales (MiniLM), deja la demo en su estado inicial
    python -m scripts.preparar_datos --offline    # sin descargas (embeddings por hashing)
    python -m scripts.preparar_datos --si-falta   # solo crea lo que no existe (lo usa Docker al arrancar)

La persistencia se elige con PERSISTENCIA (local = SQLite + Chroma; postgres = PostgreSQL + pgvector).
"""
import argparse

from agente.configuracion.contenedor import crear_contenedor
from agente.configuracion import settings


def main(argv=None) -> dict:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="Usa embeddings por hashing (sin internet)")
    parser.add_argument("--si-falta", action="store_true", help="No reinicia datos ni índices que ya existen")
    args = parser.parse_args(argv)
    proveedor = "offline" if args.offline else settings.EMBEDDINGS_PROVIDER
    c = crear_contenedor(proveedor_embeddings=proveedor, reiniciar=not args.si_falta)
    resumen = {"solicitudes": len(c.registro.todas_las_solicitudes()), "fragmentos": c.indice.conteo(),
               "cupos_disponibles": len(c.registro.cupos_disponibles(limite=1000))}
    print(f"✅ Persistencia: {c.descripcion()}")
    print(f"✅ Solicitudes: {resumen['solicitudes']} · cupos de agenda disponibles: {resumen['cupos_disponibles']}")
    print(f"✅ Índices ({proveedor}): {resumen['fragmentos']}")
    return resumen


if __name__ == "__main__":
    main()
