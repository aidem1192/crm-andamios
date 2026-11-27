from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from datetime import date
from app.database import get_db, Pago, Contrato, MetodoPago
from app.services.saldo import calcular_saldo, estado_pago_de
from app.auth import require_admin, log_audit

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
def actualizar_metodo(metodo_id: int, data: MetodoPagoCreate, request: Request,
                       db: Session = Depends(get_db), _=Depends(require_admin)):
    m = db.query(MetodoPago).filter(MetodoPago.id == metodo_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Método no encontrado")
    for k, v in data.model_dump().items():
        setattr(m, k, v)
    log_audit(db, request, "editar_metodo_pago", "metodo_pago", metodo_id, f"Método editado: {m.nombre}")
    db.commit()
    db.refresh(m)
    return m


@router.delete("/api/metodos-pago/{metodo_id}")
def desactivar_metodo(metodo_id: int, request: Request,
                       db: Session = Depends(get_db), _=Depends(require_admin)):
    m = db.query(MetodoPago).filter(MetodoPago.id == metodo_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Método no encontrado")
    # No eliminar si tiene pagos asociados; sólo desactivar
    if db.query(Pago).filter(Pago.metodo_pago_id == metodo_id).count() > 0:
        m.activo = False
        log_audit(db, request, "desactivar_metodo_pago", "metodo_pago", metodo_id, f"Método desactivado: {m.nombre}")
        db.commit()
        return {"ok": True, "accion": "desactivado"}
    log_audit(db, request, "eliminar_metodo_pago", "metodo_pago", metodo_id, f"Método eliminado: {m.nombre}")
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
    """Actualiza el total pagado (histórico completo) y el estado de pago
    según el saldo acumulado AL DÍA DE HOY (o a la fecha de devolución si ya cerró)."""
    contrato.total_pagado = round(sum(p.monto for p in contrato.pagos), 2)
    s = calcular_saldo(contrato)
    contrato.estado_pago = estado_pago_de(s["saldo_pendiente"], contrato.total_pagado)


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
    s = calcular_saldo(c)
    return {
        "total_contrato": c.total_con_iva,
        "dias_devengados": s["dias_devengados"],
        "monto_devengado": s["monto_devengado"],
        "total_pagado": s["total_pagado"],
        "saldo_pendiente": s["saldo_pendiente"],
        "estado_pago": estado_pago_de(s["saldo_pendiente"], s["total_pagado"]),
        "pagos": [{
            "id": p.id, "folio": p.folio, "fecha": str(p.fecha),
            "monto": p.monto, "metodo_pago": p.metodo_pago.nombre if p.metodo_pago else "",
            "referencia": p.referencia, "notas": p.notas,
        } for p in sorted(c.pagos, key=lambda x: x.fecha)],
    }


@router.post("/api/pagos", status_code=201)
def registrar_pago(data: PagoCreate, request: Request, db: Session = Depends(get_db)):
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

    saldo_actual = calcular_saldo(c)["saldo_pendiente"]
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
    log_audit(db, request, "registrar_pago", "pago", pago.id,
              f"Pago {folio} de ${data.monto:.2f} para contrato {c.folio}")
    db.commit()
    db.refresh(pago)
    return {
        "id": pago.id, "folio": pago.folio,
        "estado_pago": c.estado_pago,
        "saldo_nuevo": calcular_saldo(c)["saldo_pendiente"],
    }


@router.get("/api/pagos/{pago_id}/recibo")
def descargar_recibo_pago(pago_id: int, db: Session = Depends(get_db)):
    from app.services.generar_recibo_pago import generar_recibo_pago

    p = db.query(Pago).filter(Pago.id == pago_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Pago no encontrado")

    c = p.contrato
    # Saldo devengado a la fecha de ESTE pago: antes (sin contarlo) y después (con él)
    saldo_antes = calcular_saldo(c, hasta=p.fecha, excluir_pago_id=p.id)
    saldo_despues = calcular_saldo(c, hasta=p.fecha)

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
        "total_pagado_previo": saldo_antes["total_pagado"],
        "saldo_anterior": saldo_antes["saldo_pendiente"],
        "saldo_nuevo": saldo_despues["saldo_pendiente"],
    }
    output_path = generar_recibo_pago(data)
    return FileResponse(
        path=str(output_path),
        filename=f"ReciboPago_{p.folio}.pdf",
        media_type="application/pdf",
    )
