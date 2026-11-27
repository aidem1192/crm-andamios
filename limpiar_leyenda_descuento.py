"""Script temporal de un solo uso: busca clientes con '% de descuento' u otras leyendas
de descuento escritas a mano en el nombre, limpia el nombre y marca descuento_autorizado=True."""
import os
import re
from sqlalchemy import create_engine, text

url = os.environ["DATABASE_URL"]
if url.startswith("postgres://"):
    url = url.replace("postgres://", "postgresql+psycopg://", 1)
elif url.startswith("postgresql://"):
    url = url.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(url, connect_args={"prepare_threshold": None})

PATRON = re.compile(r"\s*\(?\s*\d{1,3}\s*%?\s*(de)?\s*descuento\s*\)?\s*", re.IGNORECASE)

with engine.begin() as conn:
    rows = conn.execute(text("SELECT id, nombre FROM clientes WHERE nombre ILIKE '%descuento%'")).fetchall()
    print(f"ENCONTRADOS: {len(rows)}", flush=True)
    for cid, nombre in rows:
        nuevo_nombre = PATRON.sub(" ", nombre).strip()
        nuevo_nombre = re.sub(r"\s+", " ", nuevo_nombre)
        print(f"  id={cid}: {nombre!r} -> {nuevo_nombre!r}", flush=True)
        conn.execute(
            text("UPDATE clientes SET nombre = :n, descuento_autorizado = TRUE WHERE id = :id"),
            {"n": nuevo_nombre, "id": cid},
        )

print("LISTO.", flush=True)
