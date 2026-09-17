from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from datetime import date, datetime
from app.database import get_db, NotaCargo, LineaNotaCargo, Cliente, Material

router = APIRouter(prefix="/api/notas-cargo", tags=["notas_cargo"])


class LineaNotaCargoIn(BaseModel):
    material_id: Optional[int] = None
    concepto: str
    cantidad: int = 1
    precio_unitario: float


class NotaCargoIn(BaseModel):
    cliente_id: int
    fecha: date
    notas: Optional[str] = None
    lineas: List[LineaNotaCargoIn]


def _siguiente_folio(db: Session) -> str:
    count = db.query(NotaCargo).count() + 1
    return f"NC-{count:05d}"


def _nota_dict(n: NotaCargo) -> dict:
    return {
        "id": n.id,
        "folio": n.folio,
        "cliente_id": n.cliente_id,
        "cliente_nombre": n.cliente.nombre if n.cliente else "",
        "fecha": str(n.fecha),
        "notas": n.notas,
        "total": n.total,
        "created_at": str(n.created_at),
        "lineas": [
            {
                "id": l.id,
                "material_id": l.material_id,
                "material_nombre": l.material.nombre if l.material else None,
                "concepto": l.concepto,
                "cantidad": l.cantidad,
                "precio_unitario": l.precio_unitario,
                "total_linea": l.total_linea,
            }
            for l in n.lineas
        ],
    }


@router.get("")
def listar_notas(db: Session = Depends(get_db)):
    notas = db.query(NotaCargo).order_by(NotaCargo.created_at.desc()).all()
    return [_nota_dict(n) for n in notas]


@router.post("")
def crear_nota(data: NotaCargoIn, db: Session = Depends(get_db)):
    cliente = db.query(Cliente).filter(Cliente.id == data.cliente_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    if not data.lineas:
        raise HTTPException(status_code=400, detail="Agrega al menos un material o concepto")

    total = sum(l.cantidad * l.precio_unitario for l in data.lineas)
    nota = NotaCargo(
        folio=_siguiente_folio(db),
        cliente_id=data.cliente_id,
        fecha=data.fecha,
        notas=data.notas,
        total=total,
    )
    db.add(nota)
    db.flush()

    for l in data.lineas:
        linea = LineaNotaCargo(
            nota_id=nota.id,
            material_id=l.material_id,
            concepto=l.concepto,
            cantidad=l.cantidad,
            precio_unitario=l.precio_unitario,
            total_linea=l.cantidad * l.precio_unitario,
        )
        db.add(linea)

    db.commit()
    db.refresh(nota)
    return {"id": nota.id, "folio": nota.folio}


@router.get("/{nota_id}")
def obtener_nota(nota_id: int, db: Session = Depends(get_db)):
    nota = db.query(NotaCargo).filter(NotaCargo.id == nota_id).first()
    if not nota:
        raise HTTPException(status_code=404, detail="Nota de cargo no encontrada")
    return _nota_dict(nota)


@router.delete("/{nota_id}")
def eliminar_nota(nota_id: int, db: Session = Depends(get_db)):
    nota = db.query(NotaCargo).filter(NotaCargo.id == nota_id).first()
    if not nota:
        raise HTTPException(status_code=404, detail="Nota de cargo no encontrada")
    db.delete(nota)
    db.commit()
    return {"ok": True}
