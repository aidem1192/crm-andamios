"""
Migracion unica: copia todos los datos de SOURCE_DATABASE_URL (Supabase)
a TARGET_DATABASE_URL (Postgres en Railway).

Se corre una sola vez como start command temporal del servicio (ver despliegue),
no es parte de la app normal. Es idempotente: si se vuelve a correr, vacia las
tablas del destino antes de copiar de nuevo.
"""
import os
import sys

from sqlalchemy import create_engine, text

from app.database import Base


def _normalizar(url: str) -> str:
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def main():
    source_url = os.environ.get("SOURCE_DATABASE_URL")
    target_url = os.environ.get("TARGET_DATABASE_URL")

    if not source_url or not target_url:
        print("ERROR: faltan SOURCE_DATABASE_URL y/o TARGET_DATABASE_URL", flush=True)
        sys.exit(1)

    source_url = _normalizar(source_url)
    target_url = _normalizar(target_url)

    if source_url.split("@")[-1] == target_url.split("@")[-1]:
        print("ERROR: origen y destino parecen ser la misma base. Abortando.", flush=True)
        sys.exit(1)

    print(f"Origen:  {source_url.split('@')[-1]}", flush=True)
    print(f"Destino: {target_url.split('@')[-1]}", flush=True)

    source_engine = create_engine(source_url, connect_args={"prepare_threshold": None})
    target_engine = create_engine(target_url, connect_args={"prepare_threshold": None})

    print("Probando conexion al origen (Supabase)...", flush=True)
    with source_engine.connect() as c:
        c.execute(text("SELECT 1"))
    print("OK - conectado al origen.", flush=True)

    print("Probando conexion al destino (Railway Postgres)...", flush=True)
    with target_engine.connect() as c:
        c.execute(text("SELECT 1"))
    print("OK - conectado al destino.", flush=True)

    print("Creando esquema en el destino (si no existe)...", flush=True)
    Base.metadata.create_all(bind=target_engine)

    tablas = Base.metadata.sorted_tables
    nombres = [t.name for t in tablas]

    print(f"Vaciando {len(nombres)} tablas en destino antes de copiar...", flush=True)
    with target_engine.begin() as conn:
        conn.execute(text(f"TRUNCATE TABLE {', '.join(nombres)} RESTART IDENTITY CASCADE"))

    total_filas = 0
    with source_engine.connect() as src_conn:
        for tabla in tablas:
            rows = src_conn.execute(tabla.select()).mappings().all()
            if not rows:
                print(f"  {tabla.name}: 0 filas", flush=True)
                continue
            with target_engine.begin() as tgt_conn:
                tgt_conn.execute(tabla.insert(), [dict(r) for r in rows])
                if "id" in tabla.c:
                    tgt_conn.execute(text(
                        f"SELECT setval(pg_get_serial_sequence('{tabla.name}', 'id'), "
                        f"COALESCE((SELECT MAX(id) FROM {tabla.name}), 1), "
                        f"(SELECT MAX(id) FROM {tabla.name}) IS NOT NULL)"
                    ))
            print(f"  {tabla.name}: {len(rows)} filas copiadas", flush=True)
            total_filas += len(rows)

    print(f"MIGRACION COMPLETA: {total_filas} filas copiadas en {len(nombres)} tablas.", flush=True)


if __name__ == "__main__":
    main()
