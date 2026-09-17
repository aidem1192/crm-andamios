from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from datetime import date, datetime
from app.database import get_db, Contrato, LineaContrato, Cliente, Material, Usuario, CargoExtra
from app.services.numero_a_letra import numero_a_letra
from app.services.devolucion import calcular_devolucion
from app.auth import verify_password, log_audit
import os

router = APIRouter(prefix="/api/contratos", tags=["contratos"])

# PIN del dueño para autorizar descuentos (sobreescribible con la variable de entorno PIN_DESCUENTO)
PIN_DESCUENTO = os.environ.get("PIN_DESCUENTO", "1234")
IVA_PCT = 0.16


class LineaContratoSchema(BaseModel):
    material_id: int
    cantidad: int
    precio_unitario: float


class CargoExtraSchema(BaseModel):
    concepto: str
    monto: float
    tipo: str = "otro"


class ContratoCreate(BaseModel):
    cliente_id: int
    fecha_inicio: date
    fecha_fin: date
    lugar_obra: Optional[str] = None
    personas_autorizadas: Optional[str] = None
    lugar_celebracion: Optional[str] = "ANDAMIOS Y DERIVADOS"
    descuento_pct: float = 0.0
    pin_descuento: Optional[str] = None
    notas: Optional[str] = None
    incluye_iva: bool = True
    lineas: List[LineaContratoSchema]
    cargos_extra: List[CargoExtraSchema] = []


def _calcular_totales(lineas_data: list, descuento_pct: float, incluye_iva: bool = True):
    total_diario = sum(l["cantidad"] * l["precio_unitario"] for l in lineas_data)
    descuento_monto = total_diario * (descuento_pct / 100)
    total_con_descuento = total_diario - descuento_monto
    if incluye_iva:
        iva = round(total_con_descuento * IVA_PCT, 2)
        total_con_iva = round(total_con_descuento + iva, 2)
    else:
        iva = 0.0
        total_con_iva = round(total_con_descuento, 2)
    return total_diario, total_con_descuento, iva, total_con_iva


def _siguiente_folio(db: Session) -> str:
    count = db.query(Contrato).count() + 1
    return f"ADN-{count:05d}"


@router.get("")
def listar_contratos(db: Session = Depends(get_db)):
    contratos = db.query(Contrato).order_by(Contrato.created_at.desc()).all()
    result = []
    for c in contratos:
        result.append({
            "id": c.id,
            "folio": c.folio,
            "cliente": c.cliente.nombre if c.cliente else "",
            "fecha_inicio": str(c.fecha_inicio),
            "fecha_fin": str(c.fecha_fin),
            "dias": c.dias,
            "total_con_iva": c.total_con_iva,
            "estado": c.estado,
        })
    return result


@router.get("/{contrato_id}")
def obtener_contrato(contrato_id: int, db: Session = Depends(get_db)):
    c = db.query(Contrato).filter(Contrato.id == contrato_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Contrato no encontrado")
    lineas = []
    for l in c.lineas:
        lineas.append({
            "id": l.id,
            "material_id": l.material_id,
            "material_nombre": l.material.nombre if l.material else "",
            "cantidad": l.cantidad,
            "cantidad_devuelta": l.cantidad_devuelta or 0,
            "precio_unitario": l.precio_unitario,
            "total_linea": l.total_linea,
            "precio_venta": l.material.precio_venta if l.material else 0,
        })
    return {
        "id": c.id,
        "folio": c.folio,
        "cliente_id": c.cliente_id,
        "cliente": {
            "id": c.cliente.id,
            "nombre": c.cliente.nombre,
            "telefono": c.cliente.telefono,
            "domicilio": c.cliente.domicilio,
            "rfc": c.cliente.rfc,
            "referencias": [{"nombre": r.nombre, "telefono": r.telefono, "direccion": r.direccion}
                            for r in c.cliente.referencias],
        } if c.cliente else None,
        "fecha_inicio": str(c.fecha_inicio),
        "fecha_fin": str(c.fecha_fin),
        "dias": c.dias,
        "lugar_obra": c.lugar_obra,
        "personas_autorizadas": c.personas_autorizadas,
        "lugar_celebracion": c.lugar_celebracion,
        "total_diario": c.total_diario,
        "descuento_pct": c.descuento_pct,
        "total_diario_con_descuento": c.total_diario_con_descuento,
        "iva": c.iva,
        "total_con_iva": c.total_con_iva,
        "importe_letra": numero_a_letra(c.total_con_iva or 0),
        "incluye_iva": c.incluye_iva if c.incluye_iva is not None else True,
        "estado": c.estado,
        "notas": c.notas,
        "motivo_cancelacion": c.motivo_cancelacion,
        "fecha_devolucion": c.fecha_devolucion.isoformat() if c.fecha_devolucion else None,
        "dia_extra_cobrado": c.dia_extra_cobrado,
        "lineas": lineas,
        "cargos_extra": [
            {"id": ce.id, "concepto": ce.concepto, "monto": ce.monto,
             "tipo": ce.tipo, "created_at": str(ce.created_at)[:10]}
            for ce in c.cargos_extra
        ],
        "total_cargos_extra": round(sum(ce.monto for ce in c.cargos_extra), 2),
    }


@router.get("/{contrato_id}/estado-material")
def estado_material(contrato_id: int, db: Session = Depends(get_db)):
    """Devuelve el estado de devolución por línea de contrato."""
    c = db.query(Contrato).filter(Contrato.id == contrato_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Contrato no encontrado")
    lineas = []
    for l in c.lineas:
        devuelta = l.cantidad_devuelta or 0
        lineas.append({
            "material_id": l.material_id,
            "material_nombre": l.material.nombre if l.material else "",
            "cantidad": l.cantidad,
            "cantidad_devuelta": devuelta,
            "pendiente": max(0, l.cantidad - devuelta),
        })
    todo_devuelto = all(row["pendiente"] == 0 for row in lineas) if lineas else False
    return {"lineas": lineas, "todo_devuelto": todo_devuelto}


@router.post("", status_code=201)
def crear_contrato(data: ContratoCreate, db: Session = Depends(get_db)):
    # Validar descuento
    if data.descuento_pct > 0:
        if data.pin_descuento != PIN_DESCUENTO:
            raise HTTPException(status_code=403, detail="PIN de descuento incorrecto. Se requiere autorización del gerente.")

    # Validar cliente
    cliente = db.query(Cliente).filter(Cliente.id == data.cliente_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    if cliente.lista_negra:
        motivo = f" Motivo: {cliente.motivo_lista_negra}" if cliente.motivo_lista_negra else ""
        raise HTTPException(status_code=403, detail=f"Este cliente está en la lista negra y no puede rentar material.{motivo}")

    # Validar fechas
    if data.fecha_fin < data.fecha_inicio:
        raise HTTPException(status_code=400, detail="La fecha de fin no puede ser anterior a la fecha de inicio")
    dias = (data.fecha_fin - data.fecha_inicio).days + 1

    # Validar líneas
    if not data.lineas:
        raise HTTPException(status_code=400, detail="El contrato debe tener al menos una línea de material")

    lineas_data = []
    for l in data.lineas:
        material = db.query(Material).filter(Material.id == l.material_id).first()
        if not material:
            raise HTTPException(status_code=404, detail=f"Material {l.material_id} no encontrado")
        lineas_data.append({
            "material_id": l.material_id,
            "cantidad": l.cantidad,
            "precio_unitario": l.precio_unitario,
        })

    total_diario, total_con_descuento, iva, total_con_iva = _calcular_totales(lineas_data, data.descuento_pct, data.incluye_iva)

    folio = _siguiente_folio(db)
    contrato = Contrato(
        folio=folio,
        cliente_id=data.cliente_id,
        fecha_inicio=data.fecha_inicio,
        fecha_fin=data.fecha_fin,
        dias=dias,
        lugar_obra=data.lugar_obra,
        personas_autorizadas=data.personas_autorizadas,
        lugar_celebracion=data.lugar_celebracion,
        total_diario=total_diario,
        descuento_pct=data.descuento_pct,
        descuento_autorizado=data.descuento_pct > 0,
        total_diario_con_descuento=total_con_descuento,
        iva=iva,
        total_con_iva=total_con_iva,
        incluye_iva=data.incluye_iva,
        notas=data.notas,
    )
    db.add(contrato)
    db.flush()

    for l in lineas_data:
        linea = LineaContrato(
            contrato_id=contrato.id,
            material_id=l["material_id"],
            cantidad=l["cantidad"],
            precio_unitario=l["precio_unitario"],
            total_linea=l["cantidad"] * l["precio_unitario"],
        )
        db.add(linea)

    for ce in data.cargos_extra:
        cargo = CargoExtra(
            contrato_id=contrato.id,
            concepto=ce.concepto,
            monto=ce.monto,
            tipo=ce.tipo,
        )
        db.add(cargo)

    db.commit()
    db.refresh(contrato)
    return {"id": contrato.id, "folio": contrato.folio}


@router.get("/{contrato_id}/pagare")
def descargar_pagare(contrato_id: int, db: Session = Depends(get_db)):
    from app.services.generar_pagare import generar_pagare

    c = db.query(Contrato).filter(Contrato.id == contrato_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Contrato no encontrado")

    lineas_data = []
    for l in c.lineas:
        lineas_data.append({
            "material": l.material.nombre if l.material else "",
            "cantidad": l.cantidad,
            "valor_convencional": l.material.precio_venta if l.material else 0,
        })

    contrato_data = {
        "folio": c.folio,
        "cliente_nombre": c.cliente.nombre if c.cliente else "",
        "cliente_telefono": c.cliente.telefono or "",
        "cliente_domicilio": c.cliente.domicilio or "",
        "cliente_rfc": c.cliente.rfc or "",
        "lineas": lineas_data,
        "fecha_inicio": c.fecha_inicio,
        "lugar_obra": c.lugar_obra or "",
        "lugar_celebracion": c.lugar_celebracion or "CHIHUAHUA, CHIHUAHUA",
    }

    output_path = generar_pagare(contrato_data)
    return FileResponse(
        path=str(output_path),
        filename=f"Pagare_{c.folio}.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@router.get("/{contrato_id}/pdf")
def descargar_contrato(contrato_id: int, db: Session = Depends(get_db)):
    from app.services.generar_contrato import generar_contrato, OUTPUT_DIR
    from pathlib import Path

    c = db.query(Contrato).filter(Contrato.id == contrato_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Contrato no encontrado")

    lineas_data = []
    for l in c.lineas:
        lineas_data.append({
            "material": l.material.nombre if l.material else "",
            "cantidad": l.cantidad,
            "precio_unitario": l.precio_unitario,
            "total_diario": l.total_linea,
            "valor_convencional": l.material.precio_venta if l.material else 0,
        })

    contrato_data = {
        "folio": c.folio,
        "cliente_nombre": c.cliente.nombre,
        "cliente_telefono": c.cliente.telefono or "",
        "cliente_domicilio": c.cliente.domicilio or "",
        "cliente_rfc": c.cliente.rfc or "",
        "referencias": [{"nombre": r.nombre, "telefono": r.telefono or "", "direccion": r.direccion or ""}
                        for r in c.cliente.referencias],
        "lineas": lineas_data,
        "total_diario": c.total_diario_con_descuento if c.total_diario_con_descuento else c.total_diario,
        "total_con_iva": c.total_con_iva,
        "fecha_inicio": c.fecha_inicio,
        "fecha_fin": c.fecha_fin,
        "dias": c.dias,
        "lugar_obra": c.lugar_obra or "",
        "personas_autorizadas": c.personas_autorizadas or "",
        "lugar_celebracion": c.lugar_celebracion or "ANDAMIOS Y DERIVADOS",
    }

    output_path = generar_contrato(contrato_data)
    return FileResponse(
        path=str(output_path),
        filename=f"Contrato_{c.folio}.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


class CancelarContratoBody(BaseModel):
    password_admin: str
    motivo: Optional[str] = None


@router.post("/{contrato_id}/cancelar")
def cancelar_contrato(contrato_id: int, body: CancelarContratoBody, request: Request,
                      db: Session = Depends(get_db)):
    """Cancela un contrato. Requiere la contraseña de un usuario con rol 'admin'."""
    c = db.query(Contrato).filter(Contrato.id == contrato_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Contrato no encontrado")
    if c.estado == "cancelado":
        raise HTTPException(status_code=400, detail="El contrato ya está cancelado.")
    if c.estado == "terminado":
        raise HTTPException(status_code=400, detail="No se puede cancelar un contrato ya terminado.")

    admins = db.query(Usuario).filter(Usuario.rol == "admin", Usuario.activo == True).all()
    if not admins or not any(verify_password(body.password_admin, a.password_hash) for a in admins):
        raise HTTPException(status_code=403, detail="Clave de administrador incorrecta.")

    c.estado = "cancelado"
    c.motivo_cancelacion = body.motivo
    log_audit(db, request, "cancelar_contrato", entidad="contrato", entidad_id=c.id,
              descripcion=f"Contrato {c.folio} cancelado. Motivo: {body.motivo or '(sin motivo)'}")
    db.commit()
    db.refresh(c)

    return {"id": c.id, "folio": c.folio, "estado": c.estado, "motivo_cancelacion": c.motivo_cancelacion}


@router.post("/calcular-totales")
def calcular_totales(data: dict):
    """Endpoint para calcular totales en tiempo real desde el frontend."""
    lineas = data.get("lineas", [])
    descuento_pct = float(data.get("descuento_pct", 0))
    incluye_iva = bool(data.get("incluye_iva", True))
    total_diario, total_con_descuento, iva, total_con_iva = _calcular_totales(lineas, descuento_pct, incluye_iva)
    return {
        "total_diario": round(total_diario, 2),
        "total_con_descuento": round(total_con_descuento, 2),
        "iva": round(iva, 2),
        "total_con_iva": round(total_con_iva, 2),
        "importe_letra": numero_a_letra(total_con_iva),
    }


# ---------------------------------------------------------------------------
# Devolución de material
# ---------------------------------------------------------------------------

class DevolucionBody(BaseModel):
    fecha_devolucion: datetime  # ISO 8601, ej. "2026-07-06T09:30:00"


@router.get("/{contrato_id}/verificar-devolucion")
def verificar_devolucion(contrato_id: int, fecha_devolucion: str, db: Session = Depends(get_db)):
    """
    Verifica si una fecha/hora de devolución está dentro de la gracia (antes de las 10 AM
    del siguiente día hábil) sin guardar nada. Útil para mostrar preview en el formulario.
    """
    c = db.query(Contrato).filter(Contrato.id == contrato_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Contrato no encontrado")
    try:
        dt_devolucion = datetime.fromisoformat(fecha_devolucion)
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de fecha inválido. Usa ISO 8601.")

    return calcular_devolucion(c.fecha_fin, dt_devolucion)


@router.post("/{contrato_id}/devolucion")
def registrar_devolucion(contrato_id: int, body: DevolucionBody, db: Session = Depends(get_db)):
    """
    Registra la devolución real del material y determina si se cobra día extra.
    Cambia el estado del contrato a 'terminado'.
    """
    c = db.query(Contrato).filter(Contrato.id == contrato_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Contrato no encontrado")
    if c.estado == "terminado":
        raise HTTPException(status_code=400, detail="El contrato ya fue cerrado.")

    resultado = calcular_devolucion(c.fecha_fin, body.fecha_devolucion)

    c.fecha_devolucion = body.fecha_devolucion
    c.dia_extra_cobrado = resultado["dia_extra"]
    c.estado = "terminado"

    # Si hubo día extra, actualizar totales
    if resultado["dia_extra"]:
        total_extra_dia = c.total_diario_con_descuento if c.total_diario_con_descuento else c.total_diario
        aplica_iva = c.incluye_iva if c.incluye_iva is not None else True
        nuevo_iva = round(total_extra_dia * IVA_PCT, 2) if aplica_iva else 0.0
        c.total_con_iva = round(c.total_con_iva + total_extra_dia + nuevo_iva, 2)
        c.iva = round(c.iva + nuevo_iva, 2)
        c.dias += 1

    db.commit()
    db.refresh(c)

    return {
        **resultado,
        "contrato_id": c.id,
        "folio": c.folio,
        "estado": c.estado,
        "total_con_iva_final": c.total_con_iva,
    }


# ─── Cargos extra ─────────────────────────────────────────────────────────────

class CargoExtraIn(BaseModel):
    concepto: str
    monto: float
    tipo: str = "otro"  # danio | reposicion | otro


@router.get("/{contrato_id}/cargos-extra")
def listar_cargos_extra(contrato_id: int, db: Session = Depends(get_db)):
    c = db.query(Contrato).filter(Contrato.id == contrato_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Contrato no encontrado")
    return [
        {"id": ce.id, "concepto": ce.concepto, "monto": ce.monto,
         "tipo": ce.tipo, "created_at": str(ce.created_at)[:10]}
        for ce in c.cargos_extra
    ]


@router.post("/{contrato_id}/cargos-extra", status_code=201)
def agregar_cargo_extra(contrato_id: int, body: CargoExtraIn, request: Request,
                        db: Session = Depends(get_db)):
    c = db.query(Contrato).filter(Contrato.id == contrato_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Contrato no encontrado")
    ce = CargoExtra(
        contrato_id=contrato_id,
        concepto=body.concepto.strip(),
        monto=round(body.monto, 2),
        tipo=body.tipo,
    )
    db.add(ce)
    log_audit(db, request, "cargo_extra", "contratos", contrato_id,
              f"Cargo extra: {body.concepto} ${body.monto:.2f}")
    db.commit()
    db.refresh(ce)
    return {"id": ce.id, "concepto": ce.concepto, "monto": ce.monto, "tipo": ce.tipo}


@router.delete("/{contrato_id}/cargos-extra/{cargo_id}")
def eliminar_cargo_extra(contrato_id: int, cargo_id: int, request: Request,
                         db: Session = Depends(get_db)):
    ce = db.query(CargoExtra).filter(
        CargoExtra.id == cargo_id,
        CargoExtra.contrato_id == contrato_id,
    ).first()
    if not ce:
        raise HTTPException(status_code=404, detail="Cargo no encontrado")
    log_audit(db, request, "eliminar_cargo_extra", "contratos", contrato_id,
              f"Eliminado cargo: {ce.concepto} ${ce.monto:.2f}")
    db.delete(ce)
    db.commit()
    return {"ok": True}
