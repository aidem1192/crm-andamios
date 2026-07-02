from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
from typing import Optional, List
from app.database import get_db, Material, LineaKit, LineaContrato, Contrato
from app.services import excel_io

router = APIRouter(prefix="/api/materiales", tags=["materiales"])

TIPOS_VALIDOS = {"pieza", "kit_fijo", "kit_personalizable"}
ESTADOS_VALIDOS = {"bueno", "danado", "en_reparacion"}
UBICACIONES_VALIDAS = {"bodega", "en_obra", "en_transito"}


class MaterialCreate(BaseModel):
    nombre: str
    tipo: str = "pieza"
    numero_serie: Optional[str] = None
    estado: str = "bueno"
    ubicacion: str = "bodega"
    precio_renta_dia: float
    precio_venta: Optional[float] = None
    descripcion: Optional[str] = None
    stock: int = 0


class MaterialUpdate(MaterialCreate):
    pass


class ComponenteIn(BaseModel):
    pieza_id: int
    cantidad: int


def _en_uso(db: Session, pieza_id: int) -> int:
    """
    Unidades de 'pieza_id' actualmente en contratos activos.
    Considera uso directo + uso a través de kits.
    """
    # Uso directo en contratos activos
    directo = db.query(func.sum(LineaContrato.cantidad)).join(Contrato).filter(
        LineaContrato.material_id == pieza_id,
        Contrato.estado == "activo",
    ).scalar() or 0

    # Uso vía kits: para cada kit que contiene esta pieza, suma qty_kit * qty_en_contrato
    kits_con_pieza = db.query(LineaKit).filter(LineaKit.pieza_id == pieza_id).all()
    via_kit = 0
    for lk in kits_con_pieza:
        uso_kit = db.query(func.sum(LineaContrato.cantidad)).join(Contrato).filter(
            LineaContrato.material_id == lk.kit_id,
            Contrato.estado == "activo",
        ).scalar() or 0
        via_kit += uso_kit * lk.cantidad

    return int(directo + via_kit)


def _material_dict(m: Material, db: Session) -> dict:
    d = {
        "id": m.id, "nombre": m.nombre, "tipo": m.tipo,
        "numero_serie": m.numero_serie, "estado": m.estado,
        "ubicacion": m.ubicacion, "precio_renta_dia": m.precio_renta_dia,
        "precio_venta": m.precio_venta, "descripcion": m.descripcion,
        "stock": m.stock or 0, "activo": m.activo,
    }
    if m.tipo == "pieza":
        en_uso = _en_uso(db, m.id)
        d["en_uso"] = en_uso
        d["disponible"] = max(0, (m.stock or 0) - en_uso)
    return d


@router.get("")
def listar_materiales(q: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(Material).filter(Material.activo == True)
    if q:
        query = query.filter(Material.nombre.ilike(f"%{q}%"))
    materiales = query.order_by(Material.nombre).all()
    return [_material_dict(m, db) for m in materiales]


@router.get("/piezas")
def listar_piezas(db: Session = Depends(get_db)):
    """Solo piezas individuales — para selector de componentes de kit."""
    piezas = db.query(Material).filter(
        Material.activo == True,
        Material.tipo == "pieza",
    ).order_by(Material.nombre).all()
    return [_material_dict(p, db) for p in piezas]


@router.get("/plantilla-excel")
def descargar_plantilla_materiales():
    buf = excel_io.plantilla_materiales()
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=plantilla_materiales.xlsx"},
    )


@router.post("/importar-excel")
async def importar_materiales_excel(archivo: UploadFile = File(...), db: Session = Depends(get_db)):
    if not archivo.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="El archivo debe ser un Excel (.xlsx)")

    contenido = await archivo.read()
    try:
        filas = excel_io.leer_filas(contenido)
    except Exception:
        raise HTTPException(status_code=400, detail="No se pudo leer el archivo. Verifica que sea un .xlsx válido.")

    importados = 0
    errores = []
    for idx, fila in enumerate(filas, start=2):
        nombre = excel_io.limpiar_texto(fila.get("nombre"))
        if not nombre:
            errores.append(f"Fila {idx}: falta el nombre, se omitió.")
            continue

        precio_renta_raw = fila.get("precio_renta_dia")
        try:
            precio_renta_dia = float(precio_renta_raw)
        except (TypeError, ValueError):
            errores.append(f"Fila {idx} ('{nombre}'): precio_renta_dia inválido, se omitió.")
            continue

        tipo = excel_io.limpiar_texto(fila.get("tipo")) or "pieza"
        if tipo not in TIPOS_VALIDOS:
            errores.append(f"Fila {idx} ('{nombre}'): tipo '{tipo}' inválido, se usó 'pieza'.")
            tipo = "pieza"

        estado = excel_io.limpiar_texto(fila.get("estado")) or "bueno"
        if estado not in ESTADOS_VALIDOS:
            errores.append(f"Fila {idx} ('{nombre}'): estado '{estado}' inválido, se usó 'bueno'.")
            estado = "bueno"

        ubicacion = excel_io.limpiar_texto(fila.get("ubicacion")) or "bodega"
        if ubicacion not in UBICACIONES_VALIDAS:
            errores.append(f"Fila {idx} ('{nombre}'): ubicación '{ubicacion}' inválida, se usó 'bodega'.")
            ubicacion = "bodega"

        precio_venta_raw = fila.get("precio_venta")
        try:
            precio_venta = float(precio_venta_raw) if excel_io.limpiar_texto(precio_venta_raw) is not None else None
        except (TypeError, ValueError):
            precio_venta = None

        stock_raw = fila.get("stock")
        try:
            stock = int(stock_raw) if excel_io.limpiar_texto(stock_raw) is not None else 0
        except (TypeError, ValueError):
            stock = 0

        m = Material(
            nombre=nombre,
            tipo=tipo,
            numero_serie=excel_io.limpiar_texto(fila.get("numero_serie")),
            estado=estado,
            ubicacion=ubicacion,
            precio_renta_dia=precio_renta_dia,
            precio_venta=precio_venta,
            descripcion=excel_io.limpiar_texto(fila.get("descripcion")),
            stock=stock if tipo == "pieza" else 0,
        )
        db.add(m)
        importados += 1

    db.commit()
    return {"importados": importados, "total_filas": len(filas), "errores": errores}


@router.get("/{material_id}")
def obtener_material(material_id: int, db: Session = Depends(get_db)):
    m = db.query(Material).filter(Material.id == material_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Material no encontrado")
    return _material_dict(m, db)


@router.get("/{material_id}/componentes")
def get_componentes(material_id: int, db: Session = Depends(get_db)):
    m = db.query(Material).filter(Material.id == material_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Material no encontrado")
    if m.tipo == "pieza":
        raise HTTPException(status_code=400, detail="Las piezas individuales no tienen componentes")
    return [{
        "id": lk.id,
        "pieza_id": lk.pieza_id,
        "nombre_pieza": lk.pieza.nombre if lk.pieza else "—",
        "cantidad": lk.cantidad,
        "stock_pieza": lk.pieza.stock or 0 if lk.pieza else 0,
        "en_uso_pieza": _en_uso(db, lk.pieza_id),
    } for lk in m.componentes]


@router.put("/{material_id}/componentes")
def set_componentes(material_id: int, componentes: List[ComponenteIn],
                    db: Session = Depends(get_db)):
    m = db.query(Material).filter(Material.id == material_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Material no encontrado")
    if m.tipo == "pieza":
        raise HTTPException(status_code=400, detail="No se pueden asignar componentes a una pieza")

    # Validar que todas las piezas existen y son tipo "pieza"
    for c in componentes:
        pieza = db.query(Material).filter(Material.id == c.pieza_id, Material.activo == True).first()
        if not pieza:
            raise HTTPException(status_code=400, detail=f"Pieza id={c.pieza_id} no encontrada")
        if pieza.tipo != "pieza":
            raise HTTPException(status_code=400, detail=f"'{pieza.nombre}' no es una pieza individual")
        if c.cantidad < 1:
            raise HTTPException(status_code=400, detail="La cantidad debe ser al menos 1")

    # Reemplazar componentes
    db.query(LineaKit).filter(LineaKit.kit_id == material_id).delete()
    for c in componentes:
        db.add(LineaKit(kit_id=material_id, pieza_id=c.pieza_id, cantidad=c.cantidad))
    db.commit()
    return {"ok": True, "total": len(componentes)}


@router.post("", status_code=201)
def crear_material(data: MaterialCreate, db: Session = Depends(get_db)):
    m = Material(**data.model_dump())
    db.add(m)
    db.commit()
    db.refresh(m)
    return _material_dict(m, db)


@router.put("/{material_id}")
def actualizar_material(material_id: int, data: MaterialUpdate, db: Session = Depends(get_db)):
    m = db.query(Material).filter(Material.id == material_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Material no encontrado")
    for field, val in data.model_dump().items():
        setattr(m, field, val)
    db.commit()
    db.refresh(m)
    return _material_dict(m, db)


@router.delete("/{material_id}")
def eliminar_material(material_id: int, db: Session = Depends(get_db)):
    m = db.query(Material).filter(Material.id == material_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Material no encontrado")
    m.activo = False
    db.commit()
    return {"ok": True}
