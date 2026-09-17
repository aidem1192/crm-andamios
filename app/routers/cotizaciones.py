from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from datetime import date
from app.database import get_db, Cotizacion, LineaCotizacion, Cliente

router = APIRouter(prefix="/api/cotizaciones", tags=["cotizaciones"])

IVA_PCT = 0.16


class LineaCotizacionIn(BaseModel):
    tipo: str = "material"
    descripcion: str
    cantidad: float = 1
    precio_unitario: float


class CotizacionIn(BaseModel):
    cliente_id: Optional[int] = None
    cliente_nombre: str
    cliente_telefono: Optional[str] = None
    cliente_domicilio: Optional[str] = None
    cliente_rfc: Optional[str] = None
    fecha: date
    vigencia_dias: int = 15
    lugar_obra: Optional[str] = None
    incluye_iva: bool = True
    descuento_pct: float = 0.0
    notas: Optional[str] = None
    lineas: List[LineaCotizacionIn]


def _siguiente_folio(db: Session) -> str:
    count = db.query(Cotizacion).count() + 1
    return f"COT-{count:05d}"


def _calcular(lineas, descuento_pct, incluye_iva):
    subtotal = sum(l.cantidad * l.precio_unitario for l in lineas)
    descuento = round(subtotal * descuento_pct / 100, 2)
    base = subtotal - descuento
    iva = round(base * IVA_PCT, 2) if incluye_iva else 0.0
    total = round(base + iva, 2)
    return subtotal, descuento, iva, total


def _cot_dict(c: Cotizacion) -> dict:
    return {
        "id": c.id,
        "folio": c.folio,
        "cliente_id": c.cliente_id,
        "cliente_nombre": c.cliente_nombre,
        "cliente_telefono": c.cliente_telefono,
        "cliente_domicilio": c.cliente_domicilio,
        "cliente_rfc": c.cliente_rfc,
        "fecha": str(c.fecha),
        "vigencia_dias": c.vigencia_dias,
        "lugar_obra": c.lugar_obra,
        "incluye_iva": c.incluye_iva,
        "descuento_pct": c.descuento_pct,
        "subtotal": c.subtotal,
        "descuento_monto": c.descuento_monto,
        "iva": c.iva,
        "total": c.total,
        "notas": c.notas,
        "estado": c.estado,
        "created_at": str(c.created_at),
        "lineas": [
            {
                "id": l.id,
                "tipo": l.tipo,
                "descripcion": l.descripcion,
                "cantidad": l.cantidad,
                "precio_unitario": l.precio_unitario,
                "total_linea": l.total_linea,
            }
            for l in c.lineas
        ],
    }


@router.get("")
def listar(db: Session = Depends(get_db)):
    rows = db.query(Cotizacion).order_by(Cotizacion.created_at.desc()).all()
    return [_cot_dict(c) for c in rows]


@router.get("/{cot_id}")
def obtener(cot_id: int, db: Session = Depends(get_db)):
    c = db.query(Cotizacion).filter(Cotizacion.id == cot_id).first()
    if not c:
        raise HTTPException(404, "Cotización no encontrada")
    return _cot_dict(c)


@router.post("", status_code=201)
def crear(data: CotizacionIn, db: Session = Depends(get_db)):
    if not data.lineas:
        raise HTTPException(400, "Agrega al menos un concepto")

    subtotal, descuento, iva, total = _calcular(data.lineas, data.descuento_pct, data.incluye_iva)

    cot = Cotizacion(
        folio=_siguiente_folio(db),
        cliente_id=data.cliente_id,
        cliente_nombre=data.cliente_nombre,
        cliente_telefono=data.cliente_telefono,
        cliente_domicilio=data.cliente_domicilio,
        cliente_rfc=data.cliente_rfc,
        fecha=data.fecha,
        vigencia_dias=data.vigencia_dias,
        lugar_obra=data.lugar_obra,
        incluye_iva=data.incluye_iva,
        descuento_pct=data.descuento_pct,
        subtotal=subtotal,
        descuento_monto=descuento,
        iva=iva,
        total=total,
        notas=data.notas,
    )
    db.add(cot)
    db.flush()

    for l in data.lineas:
        db.add(LineaCotizacion(
            cotizacion_id=cot.id,
            tipo=l.tipo,
            descripcion=l.descripcion,
            cantidad=l.cantidad,
            precio_unitario=l.precio_unitario,
            total_linea=round(l.cantidad * l.precio_unitario, 2),
        ))

    db.commit()
    db.refresh(cot)
    return {"id": cot.id, "folio": cot.folio}


@router.patch("/{cot_id}/estado")
def cambiar_estado(cot_id: int, estado: str, db: Session = Depends(get_db)):
    c = db.query(Cotizacion).filter(Cotizacion.id == cot_id).first()
    if not c:
        raise HTTPException(404, "Cotización no encontrada")
    if estado not in ("borrador", "enviada", "aceptada", "rechazada"):
        raise HTTPException(400, "Estado inválido")
    c.estado = estado
    db.commit()
    return {"ok": True}


@router.delete("/{cot_id}")
def eliminar(cot_id: int, db: Session = Depends(get_db)):
    c = db.query(Cotizacion).filter(Cotizacion.id == cot_id).first()
    if not c:
        raise HTTPException(404, "Cotización no encontrada")
    db.delete(c)
    db.commit()
    return {"ok": True}


@router.get("/{cot_id}/pdf")
def descargar_pdf(cot_id: int, db: Session = Depends(get_db)):
    from app.services.generar_cotizacion import generar_cotizacion_pdf
    c = db.query(Cotizacion).filter(Cotizacion.id == cot_id).first()
    if not c:
        raise HTTPException(404, "Cotización no encontrada")

    cfg = None
    try:
        from app.database import ConfigEmpresa
        cfg = db.query(ConfigEmpresa).filter(ConfigEmpresa.id == 1).first()
    except Exception:
        pass

    path = generar_cotizacion_pdf(c, cfg)
    return FileResponse(path=str(path), filename=f"Cotizacion_{c.folio}.pdf", media_type="application/pdf")
