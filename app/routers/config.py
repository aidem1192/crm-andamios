import shutil
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from app.database import get_db, ConfigEmpresa, Usuario, AuditLog
from app.auth import hash_password, verify_password, log_audit, get_session_user

router = APIRouter()


def _require_admin(request: Request):
    user = get_session_user(request)
    if not user or user.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo el administrador puede realizar esta acción")

# Vive dentro de data/ (donde está el volumen persistente en producción) en vez de
# static/, para que un logo subido por el usuario no se pierda en el próximo despliegue.
UPLOAD_DIR = Path(__file__).parent.parent.parent / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Bootstrap: si el volumen está vacío (primer arranque), copia el logo por defecto
# que sí viaja con el código, para que la empresa no aparezca sin logo tras un deploy limpio.
_LOGO_BOOTSTRAP = Path(__file__).parent.parent.parent / "static" / "uploads" / "logo.png"
if _LOGO_BOOTSTRAP.exists() and not (UPLOAD_DIR / "logo.png").exists():
    shutil.copy(_LOGO_BOOTSTRAP, UPLOAD_DIR / "logo.png")


# ─────────────────────────────────────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────────────────────────────────────

class LoginBody(BaseModel):
    username: str
    password: str


@router.post("/api/auth/login")
def login(data: LoginBody, request: Request, db: Session = Depends(get_db)):
    user = db.query(Usuario).filter(
        Usuario.username == data.username,
        Usuario.activo == True,
    ).first()

    if not user or not verify_password(data.password, user.password_hash):
        # Intentar loggear el fallo (sin usuario_id)
        entry = AuditLog(
            usuario_nombre=data.username,
            accion="login_fallido",
            descripcion=f"Intento fallido para '{data.username}'",
            ip=request.client.host if request.client else "—",
        )
        db.add(entry)
        db.commit()
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")

    user.last_login = datetime.utcnow()
    request.session["user"] = {
        "id": user.id, "nombre": user.nombre,
        "username": user.username, "rol": user.rol,
    }

    entry = AuditLog(
        usuario_id=user.id, usuario_nombre=user.nombre,
        accion="login", entidad="usuario", entidad_id=user.id,
        descripcion=f"Inicio de sesión: {user.nombre}",
        ip=request.client.host if request.client else "—",
    )
    db.add(entry)
    db.commit()
    return {"ok": True, "nombre": user.nombre, "rol": user.rol}


@router.post("/api/auth/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    user = get_session_user(request)
    if user:
        log_audit(db, request, "logout", "usuario", user["id"],
                  f"Cierre de sesión: {user['nombre']}")
        db.commit()
    request.session.clear()
    return {"ok": True}


@router.get("/api/auth/me")
def me(request: Request):
    user = get_session_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="No autenticado")
    return user


# ─────────────────────────────────────────────────────────────────────────────
# Configuración de empresa
# ─────────────────────────────────────────────────────────────────────────────

class EmpresaUpdate(BaseModel):
    nombre: str
    rfc: Optional[str] = None
    domicilio: Optional[str] = None
    telefono: Optional[str] = None
    email: Optional[str] = None
    sitio_web: Optional[str] = None
    representante_legal: Optional[str] = None
    slogan: Optional[str] = None


@router.get("/api/config/empresa")
def get_empresa(db: Session = Depends(get_db)):
    emp = db.query(ConfigEmpresa).filter(ConfigEmpresa.id == 1).first()
    if not emp:
        return {}
    return {
        "id": emp.id, "nombre": emp.nombre, "rfc": emp.rfc,
        "domicilio": emp.domicilio, "telefono": emp.telefono,
        "email": emp.email, "sitio_web": emp.sitio_web,
        "representante_legal": emp.representante_legal,
        "slogan": emp.slogan,
        "logo_path": emp.logo_path,
    }


@router.put("/api/config/empresa")
def update_empresa(data: EmpresaUpdate, request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    emp = db.query(ConfigEmpresa).filter(ConfigEmpresa.id == 1).first()
    if not emp:
        emp = ConfigEmpresa(id=1)
        db.add(emp)
    for k, v in data.model_dump().items():
        setattr(emp, k, v)
    log_audit(db, request, "editar_empresa", "config", 1, "Datos de empresa actualizados")
    db.commit()
    db.refresh(emp)
    return {"ok": True}


@router.post("/api/config/empresa/logo")
async def upload_logo(request: Request, file: UploadFile = File(...),
                       db: Session = Depends(get_db)):
    _require_admin(request)
    ext = Path(file.filename).suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".svg", ".webp"):
        raise HTTPException(status_code=400, detail="Formato de imagen no soportado")
    dest = UPLOAD_DIR / f"logo{ext}"
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    emp = db.query(ConfigEmpresa).filter(ConfigEmpresa.id == 1).first()
    if not emp:
        emp = ConfigEmpresa(id=1)
        db.add(emp)
    emp.logo_path = f"uploads/logo{ext}"
    log_audit(db, request, "subir_logo", "config", 1, f"Logo actualizado: logo{ext}")
    db.commit()
    return {"ok": True, "logo_path": emp.logo_path}


# ─────────────────────────────────────────────────────────────────────────────
# Usuarios
# ─────────────────────────────────────────────────────────────────────────────

class UsuarioCreate(BaseModel):
    nombre: str
    username: str
    password: str
    rol: str = "operador"


class UsuarioUpdate(BaseModel):
    nombre: str
    rol: str
    activo: bool


class PasswordChange(BaseModel):
    password_actual: Optional[str] = None   # requerido si no es admin quien cambia
    password_nuevo: str


@router.get("/api/config/usuarios")
def listar_usuarios(db: Session = Depends(get_db)):
    users = db.query(Usuario).order_by(Usuario.nombre).all()
    return [{
        "id": u.id, "nombre": u.nombre, "username": u.username,
        "rol": u.rol, "activo": u.activo,
        "created_at": str(u.created_at)[:10] if u.created_at else None,
        "last_login": str(u.last_login)[:16].replace("T", " ") if u.last_login else None,
    } for u in users]


@router.post("/api/config/usuarios", status_code=201)
def crear_usuario(data: UsuarioCreate, request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    if db.query(Usuario).filter(Usuario.username == data.username).first():
        raise HTTPException(status_code=400, detail="El nombre de usuario ya existe")
    if data.rol not in ("admin", "operador"):
        raise HTTPException(status_code=400, detail="Rol inválido")

    u = Usuario(
        nombre=data.nombre,
        username=data.username,
        password_hash=hash_password(data.password),
        rol=data.rol,
    )
    db.add(u)
    db.flush()
    log_audit(db, request, "crear_usuario", "usuario", u.id,
              f"Usuario creado: {u.username} ({u.rol})")
    db.commit()
    return {"id": u.id, "username": u.username}


@router.put("/api/config/usuarios/{user_id}")
def actualizar_usuario(user_id: int, data: UsuarioUpdate,
                        request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    u = db.query(Usuario).filter(Usuario.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    u.nombre = data.nombre
    u.rol = data.rol
    u.activo = data.activo
    log_audit(db, request, "editar_usuario", "usuario", user_id,
              f"Usuario editado: {u.username} — rol={u.rol} activo={u.activo}")
    db.commit()
    return {"ok": True}


@router.post("/api/config/usuarios/{user_id}/cambiar-password")
def cambiar_password(user_id: int, data: PasswordChange,
                     request: Request, db: Session = Depends(get_db)):
    u = db.query(Usuario).filter(Usuario.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    session_user = get_session_user(request)
    if not session_user:
        raise HTTPException(status_code=403, detail="No autenticado")
    es_admin = session_user.get("rol") == "admin"
    # Operador solo puede cambiar su propia contraseña
    if not es_admin and session_user["id"] != user_id:
        raise HTTPException(status_code=403, detail="Solo puedes cambiar tu propia contraseña")
    # Si no es admin, verificar contraseña actual
    if not es_admin:
        if not data.password_actual or not verify_password(data.password_actual, u.password_hash):
            raise HTTPException(status_code=403, detail="Contraseña actual incorrecta")

    if len(data.password_nuevo) < 6:
        raise HTTPException(status_code=400, detail="La contraseña debe tener al menos 6 caracteres")

    u.password_hash = hash_password(data.password_nuevo)
    log_audit(db, request, "cambiar_password", "usuario", user_id,
              f"Contraseña cambiada para: {u.username}")
    db.commit()
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────────────
# Bitácora / Audit Log
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/config/auditlog")
def get_auditlog(
    limite: int = 100,
    usuario_id: Optional[int] = None,
    entidad: Optional[str] = None,
    accion: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = db.query(AuditLog).order_by(AuditLog.fecha.desc())
    if usuario_id:
        query = query.filter(AuditLog.usuario_id == usuario_id)
    if entidad:
        query = query.filter(AuditLog.entidad == entidad)
    if accion:
        query = query.filter(AuditLog.accion.ilike(f"%{accion}%"))
    logs = query.limit(limite).all()
    return [{
        "id": l.id,
        "usuario": l.usuario_nombre or "Sistema",
        "accion": l.accion,
        "entidad": l.entidad,
        "entidad_id": l.entidad_id,
        "descripcion": l.descripcion,
        "ip": l.ip,
        "fecha": str(l.fecha)[:19].replace("T", " ") if l.fecha else None,
    } for l in logs]
