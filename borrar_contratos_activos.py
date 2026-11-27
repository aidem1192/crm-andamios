"""Script temporal de un solo uso: borra los contratos activos (y sus registros ligados)."""
import os
from sqlalchemy import create_engine, text

url = os.environ["DATABASE_URL"]
if url.startswith("postgres://"):
    url = url.replace("postgres://", "postgresql+psycopg://", 1)
elif url.startswith("postgresql://"):
    url = url.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(url, connect_args={"prepare_threshold": None})

with engine.begin() as conn:
    ids = [r[0] for r in conn.execute(text("SELECT id FROM contratos WHERE estado = 'activo'")).fetchall()]
    print(f"Borrando {len(ids)} contrato(s) activo(s): {ids}", flush=True)

    if ids:
        conn.execute(text("""
            DELETE FROM lineas_nota_remision
            WHERE nota_id IN (SELECT id FROM notas_remision WHERE contrato_id = ANY(:ids))
        """), {"ids": ids})
        conn.execute(text("DELETE FROM notas_remision WHERE contrato_id = ANY(:ids)"), {"ids": ids})
        conn.execute(text("UPDATE eventos_agenda SET contrato_id = NULL WHERE contrato_id = ANY(:ids)"), {"ids": ids})
        conn.execute(text("DELETE FROM cargos_extra WHERE contrato_id = ANY(:ids)"), {"ids": ids})
        conn.execute(text("DELETE FROM pagos WHERE contrato_id = ANY(:ids)"), {"ids": ids})
        conn.execute(text("DELETE FROM lineas_contrato WHERE contrato_id = ANY(:ids)"), {"ids": ids})
        conn.execute(text("DELETE FROM contratos WHERE id = ANY(:ids)"), {"ids": ids})

print("LISTO.", flush=True)
