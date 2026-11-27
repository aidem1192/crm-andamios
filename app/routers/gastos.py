from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from datetime import date
from app.database import get_db, Gasto
from app.auth import require_admin, log_audit

router = APIRouter(prefix="/api/gastos", tags=["gastos"])

CATEGORIAS = ["combustible", "mantenimiento", "nomina", "renta_local", "servicios",
              "materiales", "transporte", "administrativo", "otros"]

METODOS = ["efectivo", "transferencia", "tarjeta", "cheque"]


class GastoIn(BaseModel):
    fecha: date
    concepto: str
    monto: float
    categoria: str = "otros"
    metodo_pago: str = "efectivo"
    referencia: Optional[str] = None
    notas: Optional[str] = None


@router.get("")
def listar(db: Session = Depends(get_db)):
    rows = db.query(Gasto).order_by(Gasto.fecha.desc(), Gasto.id.desc()).all()
    return [_dict(g) for g in rows]


@router.post("", status_code=201)
def crear(data: GastoIn, request: Request, db: Session = Depends(get_db)):
    if data.monto <= 0:
        raise HTTPException(400, "El monto debe ser mayor a cero")
    g = Gasto(
        fecha=data.fecha,
        concepto=data.concepto,
        monto=data.monto,
        categoria=data.categoria,
        metodo_pago=data.metodo_pago,
        referencia=data.referencia,
        notas=data.notas,
    )
    db.add(g)
    db.flush()
    log_audit(db, request, "crear_gasto", "gasto", g.id, f"Gasto registrado: {g.concepto} ${g.monto:.2f}")
    db.commit()
    db.refresh(g)
    return _dict(g)


@router.delete("/{gasto_id}")
def eliminar(gasto_id: int, request: Request,
             db: Session = Depends(get_db), _=Depends(require_admin)):
    g = db.query(Gasto).filter(Gasto.id == gasto_id).first()
    if not g:
        raise HTTPException(404, "Gasto no encontrado")
    log_audit(db, request, "eliminar_gasto", "gasto", gasto_id, f"Gasto eliminado: {g.concepto} ${g.monto:.2f}")
    db.delete(g)
    db.commit()
    return {"ok": True}


def _dict(g: Gasto) -> dict:
    return {
        "id": g.id,
        "fecha": str(g.fecha),
        "concepto": g.concepto,
        "monto": g.monto,
        "categoria": g.categoria,
        "metodo_pago": g.metodo_pago,
        "referencia": g.referencia or "",
        "notas": g.notas or "",
        "created_at": str(g.created_at),
    }
