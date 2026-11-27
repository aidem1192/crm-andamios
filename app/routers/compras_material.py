from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from datetime import date
from app.database import get_db, CompraMaterial, LineaCompraMaterial, Material, Gasto

router = APIRouter(prefix="/api/compras-material", tags=["compras_material"])

METODOS = ["efectivo", "transferencia", "tarjeta", "cheque"]


class LineaCompraIn(BaseModel):
    material_id: int
    cantidad_comprada: int
    precio_unitario: float


class CompraMaterialIn(BaseModel):
    fecha: date
    proveedor: Optional[str] = None
    proveedor_telefono: Optional[str] = None
    metodo_pago: str = "efectivo"
    notas: Optional[str] = None
    lineas: List[LineaCompraIn]


class RecepcionIn(BaseModel):
    cantidad_recibida: int


def _siguiente_folio(db: Session) -> str:
    count = db.query(CompraMaterial).count() + 1
    return f"CM-{count:05d}"


def _recalcular_estado(compra: CompraMaterial):
    if all(l.cantidad_recibida >= l.cantidad_comprada for l in compra.lineas):
        compra.estado_recepcion = "completo"
    elif any(l.cantidad_recibida > 0 for l in compra.lineas):
        compra.estado_recepcion = "parcial"
    else:
        compra.estado_recepcion = "pendiente"


def _compra_dict(c: CompraMaterial) -> dict:
    return {
        "id": c.id,
        "folio": c.folio,
        "proveedor": c.proveedor,
        "proveedor_telefono": c.proveedor_telefono,
        "fecha": str(c.fecha),
        "notas": c.notas,
        "total": c.total,
        "estado_recepcion": c.estado_recepcion,
        "gasto_id": c.gasto_id,
        "lineas": [
            {
                "id": l.id,
                "material_id": l.material_id,
                "material_nombre": l.material.nombre if l.material else None,
                "cantidad_comprada": l.cantidad_comprada,
                "precio_unitario": l.precio_unitario,
                "total_linea": l.total_linea,
                "cantidad_recibida": l.cantidad_recibida,
            }
            for l in c.lineas
        ],
    }


@router.get("")
def listar(db: Session = Depends(get_db)):
    rows = db.query(CompraMaterial).order_by(CompraMaterial.fecha.desc(), CompraMaterial.id.desc()).all()
    return [_compra_dict(c) for c in rows]


@router.get("/{compra_id}")
def obtener(compra_id: int, db: Session = Depends(get_db)):
    c = db.query(CompraMaterial).filter(CompraMaterial.id == compra_id).first()
    if not c:
        raise HTTPException(404, "Compra no encontrada")
    return _compra_dict(c)


@router.post("", status_code=201)
def crear(data: CompraMaterialIn, db: Session = Depends(get_db)):
    if not data.lineas:
        raise HTTPException(400, "Agrega al menos un material")
    if data.metodo_pago not in METODOS:
        raise HTTPException(400, "Método de pago inválido")

    for l in data.lineas:
        if l.cantidad_comprada <= 0:
            raise HTTPException(400, "La cantidad comprada debe ser mayor a cero")
        material = db.query(Material).filter(Material.id == l.material_id).first()
        if not material:
            raise HTTPException(404, f"Material {l.material_id} no encontrado")

    total = round(sum(l.cantidad_comprada * l.precio_unitario for l in data.lineas), 2)
    folio = _siguiente_folio(db)

    gasto = Gasto(
        fecha=data.fecha,
        concepto=f"Compra de material {folio}" + (f" - {data.proveedor}" if data.proveedor else ""),
        monto=total,
        categoria="materiales",
        metodo_pago=data.metodo_pago,
        referencia=folio,
    )
    db.add(gasto)
    db.flush()

    compra = CompraMaterial(
        folio=folio,
        proveedor=data.proveedor,
        proveedor_telefono=data.proveedor_telefono,
        fecha=data.fecha,
        notas=data.notas,
        total=total,
        gasto_id=gasto.id,
    )
    db.add(compra)
    db.flush()

    for l in data.lineas:
        db.add(LineaCompraMaterial(
            compra_id=compra.id,
            material_id=l.material_id,
            cantidad_comprada=l.cantidad_comprada,
            precio_unitario=l.precio_unitario,
            total_linea=round(l.cantidad_comprada * l.precio_unitario, 2),
        ))

    db.commit()
    db.refresh(compra)
    return _compra_dict(compra)


@router.put("/{compra_id}/lineas/{linea_id}")
def actualizar_recepcion(compra_id: int, linea_id: int, data: RecepcionIn, db: Session = Depends(get_db)):
    compra = db.query(CompraMaterial).filter(CompraMaterial.id == compra_id).first()
    if not compra:
        raise HTTPException(404, "Compra no encontrada")
    linea = db.query(LineaCompraMaterial).filter(
        LineaCompraMaterial.id == linea_id, LineaCompraMaterial.compra_id == compra_id
    ).first()
    if not linea:
        raise HTTPException(404, "Línea no encontrada")
    if data.cantidad_recibida < 0 or data.cantidad_recibida > linea.cantidad_comprada:
        raise HTTPException(400, f"La cantidad recibida debe estar entre 0 y {linea.cantidad_comprada}")

    delta = data.cantidad_recibida - linea.cantidad_recibida
    if delta != 0:
        material = db.query(Material).filter(Material.id == linea.material_id).first()
        material.stock = (material.stock or 0) + delta
        linea.cantidad_recibida = data.cantidad_recibida

    _recalcular_estado(compra)
    db.commit()
    db.refresh(compra)
    return _compra_dict(compra)


@router.delete("/{compra_id}")
def eliminar(compra_id: int, db: Session = Depends(get_db)):
    compra = db.query(CompraMaterial).filter(CompraMaterial.id == compra_id).first()
    if not compra:
        raise HTTPException(404, "Compra no encontrada")
    if any(l.cantidad_recibida > 0 for l in compra.lineas):
        raise HTTPException(400, "No se puede eliminar una compra con material ya recibido")
    if compra.gasto_id:
        gasto = db.query(Gasto).filter(Gasto.id == compra.gasto_id).first()
        if gasto:
            db.delete(gasto)
    db.delete(compra)
    db.commit()
    return {"ok": True}
