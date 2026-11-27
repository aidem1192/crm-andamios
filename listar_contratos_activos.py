"""Script temporal de un solo uso: lista los contratos activos para confirmar antes de borrarlos."""
import os
from sqlalchemy import create_engine, text

url = os.environ["DATABASE_URL"]
if url.startswith("postgres://"):
    url = url.replace("postgres://", "postgresql+psycopg://", 1)
elif url.startswith("postgresql://"):
    url = url.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(url, connect_args={"prepare_threshold": None})

with engine.connect() as conn:
    rows = conn.execute(text("""
        SELECT c.id, c.folio, cl.nombre, c.fecha_inicio, c.fecha_fin, c.created_at
        FROM contratos c
        LEFT JOIN clientes cl ON cl.id = c.cliente_id
        WHERE c.estado = 'activo'
        ORDER BY c.id
    """)).fetchall()

print(f"TOTAL CONTRATOS ACTIVOS: {len(rows)}", flush=True)
for r in rows:
    print(f"  id={r[0]} folio={r[1]} cliente={r[2]} inicio={r[3]} fin={r[4]} creado={r[5]}", flush=True)
