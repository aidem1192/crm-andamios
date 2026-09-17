from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from pathlib import Path
import shutil
import uuid
import os

from app.database import get_db, DocumentoCliente, Cliente

router = APIRouter(prefix="/api/clientes", tags=["documentos"])

TIPOS_VALIDOS = ["ine_frente", "ine_reverso", "comprobante_domicilio", "otro"]
EXTENSIONES_VALIDAS = {".jpg", ".jpeg", ".png", ".pdf", ".webp", ".heic"}
MAX_MB = 10

BASE_DIR = Path(__file__).parent.parent.parent
DOCS_DIR = BASE_DIR / "data" / "uploads" / "docs"


def _asegurar_dir(cliente_id: int) -> Path:
    d = DOCS_DIR / str(cliente_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.post("/{cliente_id}/documentos", status_code=201)
async def subir_documento(
    cliente_id: int,
    tipo: str = Form(...),
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not cliente:
        raise HTTPException(404, "Cliente no encontrado")
    if tipo not in TIPOS_VALIDOS:
        raise HTTPException(400, f"Tipo inválido. Usa: {', '.join(TIPOS_VALIDOS)}")

    ext = Path(archivo.filename).suffix.lower()
    if ext not in EXTENSIONES_VALIDAS:
        raise HTTPException(400, "Solo se aceptan imágenes (JPG, PNG, WEBP, HEIC) o PDF")

    contenido = await archivo.read()
    if len(contenido) > MAX_MB * 1024 * 1024:
        raise HTTPException(400, f"El archivo no puede superar {MAX_MB} MB")

    directorio = _asegurar_dir(cliente_id)
    nombre_unico = f"{tipo}_{uuid.uuid4().hex[:8]}{ext}"
    ruta_fisica = directorio / nombre_unico
    ruta_fisica.write_bytes(contenido)

    ruta_relativa = f"docs/{cliente_id}/{nombre_unico}"
    doc = DocumentoCliente(
        cliente_id=cliente_id,
        tipo=tipo,
        nombre_archivo=archivo.filename,
        ruta=ruta_relativa,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return _dict(doc)


@router.get("/{cliente_id}/documentos")
def listar_documentos(cliente_id: int, db: Session = Depends(get_db)):
    docs = (
        db.query(DocumentoCliente)
        .filter(DocumentoCliente.cliente_id == cliente_id)
        .order_by(DocumentoCliente.created_at.desc())
        .all()
    )
    return [_dict(d) for d in docs]


@router.delete("/{cliente_id}/documentos/{doc_id}")
def eliminar_documento(cliente_id: int, doc_id: int, db: Session = Depends(get_db)):
    doc = db.query(DocumentoCliente).filter(
        DocumentoCliente.id == doc_id,
        DocumentoCliente.cliente_id == cliente_id,
    ).first()
    if not doc:
        raise HTTPException(404, "Documento no encontrado")
    # Borrar el archivo físico
    ruta_fisica = BASE_DIR / "data" / "uploads" / doc.ruta
    if ruta_fisica.exists():
        ruta_fisica.unlink()
    db.delete(doc)
    db.commit()
    return {"ok": True}


def _dict(d: DocumentoCliente) -> dict:
    return {
        "id": d.id,
        "cliente_id": d.cliente_id,
        "tipo": d.tipo,
        "nombre_archivo": d.nombre_archivo,
        "url": f"/static/uploads/{d.ruta}",
        "es_imagen": not d.nombre_archivo.lower().endswith(".pdf"),
        "created_at": str(d.created_at),
    }
