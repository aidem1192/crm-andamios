from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from app.database import get_db, Cliente, ReferenciaCliente
from app.services import excel_io

router = APIRouter(prefix="/api/clientes", tags=["clientes"])


class ReferenciaSchema(BaseModel):
    nombre: str
    telefono: Optional[str] = None
    direccion: Optional[str] = None


class ClienteCreate(BaseModel):
    nombre: str
    telefono: Optional[str] = None
    domicilio: Optional[str] = None
    rfc: Optional[str] = None
    email: Optional[str] = None
    referencias: List[ReferenciaSchema] = []


class ClienteUpdate(ClienteCreate):
    pass


def _cliente_dict(c: Cliente) -> dict:
    return {
        "id": c.id,
        "nombre": c.nombre,
        "telefono": c.telefono,
        "domicilio": c.domicilio,
        "rfc": c.rfc,
        "email": c.email,
        "lista_negra": bool(c.lista_negra),
        "motivo_lista_negra": c.motivo_lista_negra,
        "created_at": str(c.created_at)[:10] if c.created_at else None,
        "referencias": [
            {"id": r.id, "nombre": r.nombre, "telefono": r.telefono, "direccion": r.direccion}
            for r in c.referencias
        ],
    }


@router.get("")
def listar_clientes(q: Optional[str] = None, lista_negra: Optional[bool] = None,
                    page: int = 1, limit: int = 100, db: Session = Depends(get_db)):
    query = db.query(Cliente)
    if q:
        query = query.filter(Cliente.nombre.ilike(f"%{q}%"))
    if lista_negra is True:
        query = query.filter(Cliente.lista_negra == True)
    elif lista_negra is False:
        query = query.filter((Cliente.lista_negra == False) | (Cliente.lista_negra == None))
    total = query.count()
    offset = (page - 1) * limit
    clientes = query.order_by(Cliente.nombre).offset(offset).limit(limit).all()
    return {"total": total, "page": page, "limit": limit, "clientes": [_cliente_dict(c) for c in clientes]}


@router.get("/plantilla-excel")
def descargar_plantilla_clientes():
    buf = excel_io.plantilla_clientes()
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=plantilla_clientes.xlsx"},
    )


@router.post("/importar-excel")
async def importar_clientes_excel(archivo: UploadFile = File(...), db: Session = Depends(get_db)):
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

        referencias = []
        for pref in ("ref1_", "ref2_"):
            rnombre = excel_io.limpiar_texto(fila.get(pref + "nombre"))
            if rnombre:
                referencias.append(ReferenciaCliente(
                    nombre=rnombre,
                    telefono=excel_io.limpiar_texto(fila.get(pref + "telefono")),
                    direccion=excel_io.limpiar_texto(fila.get(pref + "direccion")),
                ))

        cliente = Cliente(
            nombre=nombre,
            telefono=excel_io.limpiar_texto(fila.get("telefono")),
            domicilio=excel_io.limpiar_texto(fila.get("domicilio")),
            rfc=excel_io.limpiar_texto(fila.get("rfc")),
            email=excel_io.limpiar_texto(fila.get("email")),
        )
        db.add(cliente)
        db.flush()
        for ref in referencias:
            ref.cliente_id = cliente.id
            db.add(ref)
        importados += 1

    db.commit()
    return {"importados": importados, "total_filas": len(filas), "errores": errores}


@router.get("/{cliente_id}")
def obtener_cliente(cliente_id: int, db: Session = Depends(get_db)):
    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return _cliente_dict(cliente)


@router.post("", status_code=201)
def crear_cliente(data: ClienteCreate, db: Session = Depends(get_db)):
    cliente = Cliente(
        nombre=data.nombre,
        telefono=data.telefono,
        domicilio=data.domicilio,
        rfc=data.rfc,
        email=data.email,
    )
    db.add(cliente)
    db.flush()
    for ref in data.referencias:
        r = ReferenciaCliente(cliente_id=cliente.id, **ref.model_dump())
        db.add(r)
    db.commit()
    db.refresh(cliente)
    return _cliente_dict(cliente)


@router.put("/{cliente_id}")
def actualizar_cliente(cliente_id: int, data: ClienteUpdate, db: Session = Depends(get_db)):
    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    for field in ["nombre", "telefono", "domicilio", "rfc", "email"]:
        setattr(cliente, field, getattr(data, field))
    db.query(ReferenciaCliente).filter(ReferenciaCliente.cliente_id == cliente_id).delete()
    for ref in data.referencias:
        r = ReferenciaCliente(cliente_id=cliente_id, **ref.model_dump())
        db.add(r)
    db.commit()
    db.refresh(cliente)
    return _cliente_dict(cliente)


@router.delete("/{cliente_id}")
def eliminar_cliente(cliente_id: int, db: Session = Depends(get_db)):
    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    db.delete(cliente)
    db.commit()
    return {"ok": True}


class ListaNegraBody(BaseModel):
    motivo: Optional[str] = None


@router.post("/{cliente_id}/lista-negra")
def agregar_lista_negra(cliente_id: int, body: ListaNegraBody, db: Session = Depends(get_db)):
    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    cliente.lista_negra = True
    cliente.motivo_lista_negra = body.motivo
    db.commit()
    return _cliente_dict(cliente)


@router.delete("/{cliente_id}/lista-negra")
def quitar_lista_negra(cliente_id: int, db: Session = Depends(get_db)):
    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    cliente.lista_negra = False
    cliente.motivo_lista_negra = None
    db.commit()
    return _cliente_dict(cliente)
