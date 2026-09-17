from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from datetime import date
from app.database import get_db, Pago, Contrato, MetodoPago

router = APIRouter(tags=["pagos"])


# ─────────────────────────────────────────────────────────────────────────────
# Métodos de pago (configuración)
# ─────────────────────────────────────────────────────────────────────────────

class MetodoPagoCreate(BaseModel):
    nombre: str
    descripcion: Optional[str] = None
    requiere_referencia: bool = False
    activo: bool = True
    orden: int = 0


@router.get("/api/metodos-pago")
def listar_metodos(solo_activos: bool = True, db: Session = Depends(get_db)):
    q = db.query(MetodoPago)
    if solo_activos:
        q = q.filter(MetodoPago.activo == True)
    return q.order_by(MetodoPago.orden, MetodoPago.nombre).all()


@router.post("/api/metodos-pago", status_code=201)
def crear_metodo(data: MetodoPagoCreate, db: Session = Depends(get_db)):
    existente = db.query(MetodoPago).filter(MetodoPago.nombre == data.nombre).first()
    if existente:
        raise HTTPException(status_code=400, detail="Ya existe un método con ese nombre")
    m = MetodoPago(**data.model_dump())
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


@router.put("/api/metodos-pago/{metodo_id}")
def actualizar_metodo(metodo_id: int, data: MetodoPagoCreate, db: Session = Depends(get_db)):
    m = db.query(MetodoPago).filter(MetodoPago.id == metodo_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Método no encontrado")
    for k, v in data.model_dump().items():
        setattr(m, k, v)
    db.commit()
    db.refresh(m)
    return m


@router.delete("/api/metodos-pago/{metodo_id}")
def desactivar_metodo(metodo_id: int, db: Session = Depends(get_db)):
    m = db.query(MetodoPago).filter(MetodoPago.id == metodo_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Método no encontrado")
    # No eliminar si tiene pagos asociados; sólo desactivar
    if db.query(Pago).filter(Pago.metodo_pago_id == metodo_id).count() > 0:
        m.activo = False
        db.commit()
        return {"ok": True, "accion": "desactivado"}
    db.delete(m)
    db.commit()
    return {"ok": True, "accion": "eliminado"}


# ─────────────────────────────────────────────────────────────────────────────
# Pagos de contratos
# ─────────────────────────────────────────────────────────────────────────────

class PagoCreate(BaseModel):
    contrato_id: int
    fecha: date
    monto: float
    metodo_pago_id: int
    referencia: Optional[str] = None
    notas: Optional[str] = None
    tipo_gasto: Optional[str] = "renta"


def _siguiente_folio_pago(db: Session) -> str:
    count = db.query(Pago).count() + 1
    return f"PAG-{count:05d}"


def _actualizar_estado_pago(contrato: Contrato, db: Session):
    total_pagado = sum(p.monto for p in contrato.pagos)
    contrato.total_pagado = round(total_pagado, 2)
    saldo = round(contrato.total_con_iva - total_pagado, 2)
    if saldo <= 0:
        contrato.estado_pago = "pagado"
    elif total_pagado > 0:
        contrato.estado_pago = "parcial"
    else:
        contrato.estado_pago = "pendiente"


@router.get("/api/pagos")
def listar_todos_pagos(db: Session = Depends(get_db)):
    pagos = db.query(Pago).order_by(Pago.fecha.desc(), Pago.id.desc()).limit(200).all()
    return [{
        "id": p.id, "folio": p.folio, "fecha": str(p.fecha),
        "monto": p.monto,
        "tipo_gasto": p.tipo_gasto or "renta",
        "metodo_pago": p.metodo_pago.nombre if p.metodo_pago else "",
        "referencia": p.referencia or "",
        "notas": p.notas or "",
        "contrato_folio": p.contrato.folio if p.contrato else "",
        "cliente_nombre": p.contrato.cliente.nombre if p.contrato and p.contrato.cliente else "",
    } for p in pagos]


@router.get("/api/contratos/{contrato_id}/pagos")
def listar_pagos_contrato(contrato_id: int, db: Session = Depends(get_db)):
    c = db.query(Contrato).filter(Contrato.id == contrato_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Contrato no encontrado")
    return {
        "total_contrato": c.total_con_iva,
        "total_pagado": c.total_pagado or 0,
        "saldo_pendiente": round((c.total_con_iva or 0) - (c.total_pagado or 0), 2),
        "estado_pago": c.estado_pago or "pendiente",
        "pagos": [{
            "id": p.id, "folio": p.folio, "fecha": str(p.fecha),
            "monto": p.monto, "metodo_pago": p.metodo_pago.nombre if p.metodo_pago else "",
            "referencia": p.referencia, "notas": p.notas,
        } for p in sorted(c.pagos, key=lambda x: x.fecha)],
    }


@router.post("/api/pagos", status_code=201)
def registrar_pago(data: PagoCreate, db: Session = Depends(get_db)):
    c = db.query(Contrato).filter(Contrato.id == data.contrato_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Contrato no encontrado")
    if data.monto <= 0:
        raise HTTPException(status_code=400, detail="El monto debe ser mayor a cero")

    metodo = db.query(MetodoPago).filter(MetodoPago.id == data.metodo_pago_id).first()
    if not metodo:
        raise HTTPException(status_code=404, detail="Método de pago no encontrado")
    if not metodo.activo:
        raise HTTPException(status_code=400, detail="El método de pago está desactivado")
    if metodo.requiere_referencia and not data.referencia:
        raise HTTPException(status_code=400,
                            detail=f"El método '{metodo.nombre}' requiere número de referencia")

    saldo_actual = round((c.total_con_iva or 0) - (c.total_pagado or 0), 2)
    if data.monto > saldo_actual + 0.01:
        raise HTTPException(status_code=400,
                            detail=f"El monto (${data.monto:.2f}) supera el saldo pendiente (${saldo_actual:.2f})")

    folio = _siguiente_folio_pago(db)
    pago = Pago(
        folio=folio,
        contrato_id=data.contrato_id,
        fecha=data.fecha,
        monto=data.monto,
        metodo_pago_id=data.metodo_pago_id,
        referencia=data.referencia,
        notas=data.notas,
        tipo_gasto=data.tipo_gasto or "renta",
    )
    db.add(pago)
    db.flush()

    _actualizar_estado_pago(c, db)
    db.commit()
    db.refresh(pago)
    return {
        "id": pago.id, "folio": pago.folio,
        "estado_pago": c.estado_pago,
        "saldo_nuevo": round((c.total_con_iva or 0) - (c.total_pagado or 0), 2),
    }


@router.get("/api/pagos/{pago_id}/recibo")
def descargar_recibo_pago(pago_id: int, db: Session = Depends(get_db)):
    from app.services.generar_recibo_pago import generar_recibo_pago

    p = db.query(Pago).filter(Pago.id == pago_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Pago no encontrado")

    c = p.contrato
    # Calcular cuánto se había pagado ANTES de este pago (excluyendo el actual)
    otros_pagos = sum(op.monto for op in c.pagos if op.id != p.id)

    data = {
        "folio": p.folio,
        "fecha": p.fecha,
        "monto": p.monto,
        "metodo_pago": p.metodo_pago.nombre if p.metodo_pago else "",
        "referencia": p.referencia,
        "notas": p.notas,
        "contrato_folio": c.folio,
        "cliente_nombre": c.cliente.nombre if c.cliente else "",
        "lugar_obra": c.lugar_obra or "",
        "total_contrato": c.total_con_iva or 0,
        "total_pagado_previo": round(otros_pagos, 2),
        "saldo_anterior": round((c.total_con_iva or 0) - otros_pagos, 2),
        "saldo_nuevo": round((c.total_con_iva or 0) - (c.total_pagado or 0), 2),
    }
    output_path = generar_recibo_pago(data)
    return FileResponse(
        path=str(output_path),
        filename=f"ReciboPago_{p.folio}.pdf",
        media_type="application/pdf",
    )
