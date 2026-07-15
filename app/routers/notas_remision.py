from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from datetime import date, datetime
from app.database import get_db, NotaRemision, LineaNotaRemision, Contrato, LineaContrato, Material

router = APIRouter(prefix="/api/notas-remision", tags=["notas-remision"])


class LineaNotaSchema(BaseModel):
    material_id: int
    cantidad: int
    estado_material: str = "bueno"


class NotaRemisionCreate(BaseModel):
    contrato_id: int
    tipo: str  # entrega | devolucion
    fecha: date
    entregado_por: Optional[str] = None
    recibido_por: Optional[str] = None
    observaciones: Optional[str] = None
    lineas: List[LineaNotaSchema]


def _siguiente_folio(db: Session) -> str:
    count = db.query(NotaRemision).count() + 1
    return f"NR-{count:05d}"


@router.get("")
def listar_notas(contrato_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = db.query(NotaRemision).order_by(NotaRemision.created_at.desc())
    if contrato_id:
        query = query.filter(NotaRemision.contrato_id == contrato_id)
    notas = query.all()
    return [{
        "id": n.id,
        "folio": n.folio,
        "contrato_id": n.contrato_id,
        "contrato_folio": n.contrato.folio if n.contrato else "",
        "tipo": n.tipo,
        "fecha": str(n.fecha),
        "entregado_por": n.entregado_por,
        "recibido_por": n.recibido_por,
        "lineas": [{
            "material_id": l.material_id,
            "material_nombre": l.material.nombre if l.material else "",
            "cantidad": l.cantidad,
            "estado_material": l.estado_material,
        } for l in n.lineas],
    } for n in notas]


@router.get("/{nota_id}")
def obtener_nota(nota_id: int, db: Session = Depends(get_db)):
    n = db.query(NotaRemision).filter(NotaRemision.id == nota_id).first()
    if not n:
        raise HTTPException(status_code=404, detail="Nota de remisión no encontrada")
    return {
        "id": n.id,
        "folio": n.folio,
        "contrato_id": n.contrato_id,
        "contrato_folio": n.contrato.folio if n.contrato else "",
        "tipo": n.tipo,
        "fecha": str(n.fecha),
        "lugar_obra": n.lugar_obra,
        "entregado_por": n.entregado_por,
        "recibido_por": n.recibido_por,
        "observaciones": n.observaciones,
        "lineas": [{
            "material_id": l.material_id,
            "material_nombre": l.material.nombre if l.material else "",
            "cantidad": l.cantidad,
            "estado_material": l.estado_material,
        } for l in n.lineas],
    }


@router.post("", status_code=201)
def crear_nota(data: NotaRemisionCreate, db: Session = Depends(get_db)):
    if data.tipo not in ("entrega", "devolucion"):
        raise HTTPException(status_code=400, detail="Tipo debe ser 'entrega' o 'devolucion'")

    contrato = db.query(Contrato).filter(Contrato.id == data.contrato_id).first()
    if not contrato:
        raise HTTPException(status_code=404, detail="Contrato no encontrado")

    if not data.lineas:
        raise HTTPException(status_code=400, detail="La nota debe tener al menos una línea de material")

    for l in data.lineas:
        if not db.query(Material).filter(Material.id == l.material_id).first():
            raise HTTPException(status_code=404, detail=f"Material {l.material_id} no encontrado")

    folio = _siguiente_folio(db)
    nota = NotaRemision(
        folio=folio,
        contrato_id=data.contrato_id,
        tipo=data.tipo,
        fecha=data.fecha,
        lugar_obra=contrato.lugar_obra,
        entregado_por=data.entregado_por,
        recibido_por=data.recibido_por,
        observaciones=data.observaciones,
    )
    db.add(nota)
    db.flush()

    for l in data.lineas:
        db.add(LineaNotaRemision(
            nota_id=nota.id,
            material_id=l.material_id,
            cantidad=l.cantidad,
            estado_material=l.estado_material,
        ))

    # Si es devolución, actualizar cantidad_devuelta por línea de contrato
    if data.tipo == "devolucion":
        for l in data.lineas:
            lc = db.query(LineaContrato).filter(
                LineaContrato.contrato_id == data.contrato_id,
                LineaContrato.material_id == l.material_id,
            ).first()
            if lc:
                lc.cantidad_devuelta = min((lc.cantidad_devuelta or 0) + l.cantidad, lc.cantidad)

        # Verificar si todo fue devuelto
        lineas_contrato = db.query(LineaContrato).filter(
            LineaContrato.contrato_id == data.contrato_id
        ).all()
        todo_devuelto = all((lc.cantidad_devuelta or 0) >= lc.cantidad for lc in lineas_contrato)

        if todo_devuelto and contrato.estado == "activo":
            contrato.estado = "terminado"
            contrato.fecha_devolucion = datetime.utcnow()

    db.commit()
    db.refresh(nota)
    return {"id": nota.id, "folio": nota.folio}


@router.get("/{nota_id}/pdf")
def descargar_nota_pdf(nota_id: int, db: Session = Depends(get_db)):
    from app.services.generar_nota_remision import generar_nota_remision

    n = db.query(NotaRemision).filter(NotaRemision.id == nota_id).first()
    if not n:
        raise HTTPException(status_code=404, detail="Nota de remisión no encontrada")

    lineas_data = [{
        "material": l.material.nombre if l.material else "",
        "cantidad": l.cantidad,
        "estado_material": l.estado_material,
    } for l in n.lineas]

    data = {
        "folio": n.folio,
        "tipo": n.tipo,
        "fecha": n.fecha,
        "contrato_folio": n.contrato.folio if n.contrato else "",
        "cliente_nombre": n.contrato.cliente.nombre if n.contrato and n.contrato.cliente else "",
        "lugar_obra": n.lugar_obra,
        "entregado_por": n.entregado_por or "",
        "recibido_por": n.recibido_por or "",
        "observaciones": n.observaciones,
        "lineas": lineas_data,
    }

    output_path = generar_nota_remision(data)
    return FileResponse(
        path=str(output_path),
        filename=f"NotaRemision_{n.folio}.pdf",
        media_type="application/pdf",
    )
