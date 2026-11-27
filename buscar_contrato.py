"""Script temporal de un solo uso: borra el contrato id=1 (AARON CARMONA ESTRADA, de prueba) y registros ligados."""
import os
from sqlalchemy import create_engine, text

url = os.environ["DATABASE_URL"]
if url.startswith("postgres://"):
    url = url.replace("postgres://", "postgresql+psycopg://", 1)
elif url.startswith("postgresql://"):
    url = url.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(url, connect_args={"prepare_threshold": None})

CONTRATO_ID = 1

with engine.begin() as conn:
    row = conn.execute(text("""
        SELECT c.folio, cl.nombre FROM contratos c
        LEFT JOIN clientes cl ON cl.id = c.cliente_id
        WHERE c.id = :id
    """), {"id": CONTRATO_ID}).fetchone()
    print(f"Borrando contrato id={CONTRATO_ID}: {row}", flush=True)

    conn.execute(text("""
        DELETE FROM lineas_nota_remision
        WHERE nota_id IN (SELECT id FROM notas_remision WHERE contrato_id = :id)
    """), {"id": CONTRATO_ID})
    conn.execute(text("DELETE FROM notas_remision WHERE contrato_id = :id"), {"id": CONTRATO_ID})
    conn.execute(text("UPDATE eventos_agenda SET contrato_id = NULL WHERE contrato_id = :id"), {"id": CONTRATO_ID})
    conn.execute(text("DELETE FROM cargos_extra WHERE contrato_id = :id"), {"id": CONTRATO_ID})
    conn.execute(text("DELETE FROM pagos WHERE contrato_id = :id"), {"id": CONTRATO_ID})
    conn.execute(text("DELETE FROM lineas_contrato WHERE contrato_id = :id"), {"id": CONTRATO_ID})
    conn.execute(text("DELETE FROM contratos WHERE id = :id"), {"id": CONTRATO_ID})

print("LISTO.", flush=True)
