"""Helpers de autenticación, sesión y auditoría."""
from fastapi import Request
from sqlalchemy.orm import Session
from app.database import AuditLog
import bcrypt


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


def get_session_user(request: Request) -> dict | None:
    """Retorna el dict del usuario en sesión, o None si no hay sesión activa."""
    return request.session.get("user")


def require_auth(request: Request):
    """Lanza redirect a /login si no hay sesión. Usar en page handlers."""
    user = get_session_user(request)
    if not user:
        raise _AuthRedirect()
    return user


class _AuthRedirect(Exception):
    pass


def log_audit(db: Session, request: Request, accion: str,
              entidad: str = None, entidad_id: int = None, descripcion: str = None):
    """Registra una entrada en el audit log. No lanza excepciones."""
    try:
        user = get_session_user(request)
        ip = request.client.host if request.client else "—"
        entry = AuditLog(
            usuario_id=user["id"] if user else None,
            usuario_nombre=user["nombre"] if user else "Sistema",
            accion=accion,
            entidad=entidad,
            entidad_id=entidad_id,
            descripcion=descripcion,
            ip=ip,
        )
        db.add(entry)
        db.flush()   # no hace commit — el caller decide
    except Exception:
        pass   # el log nunca debe romper una operación
