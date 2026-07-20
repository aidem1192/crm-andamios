from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from pathlib import Path
import os

from app.database import init_db
from app.auth import get_session_user
from app.routers import clientes, materiales, contratos, reportes, notas_remision, rh, pagos
from app.routers import config as config_router
from app.routers import agenda as agenda_router

BASE_DIR = Path(__file__).parent.parent

app = FastAPI(title="CRM Andamios y Derivados del Norte")

@app.get("/debug-db")
def debug_db():
    import os
    from app.database import DATABASE_URL
    url = DATABASE_URL
    # Ocultar contraseña
    import re
    safe = re.sub(r":([^@]+)@", ":***@", url)
    return {"database_url": safe, "env_var": re.sub(r":([^@]+)@", ":***@", os.environ.get("DATABASE_URL", "NO_SET"))}

app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SECRET_KEY", "3a12c49ce7759a7bf1d3e0a18fb14a5881f5d7eda9a76836a8b925cd8867e31e"),
    session_cookie="adn_session",
    max_age=60 * 60 * 12,   # 12 horas
    https_only=os.environ.get("HTTPS_ONLY", "false").lower() == "true",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Más específico primero: /static/uploads vive en data/ (volumen persistente en Railway),
# separado del resto de /static que sí viaja con el código.
app.mount("/static/uploads", StaticFiles(directory=str(BASE_DIR / "data" / "uploads")), name="uploads")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))

app.include_router(clientes.router)
app.include_router(materiales.router)
app.include_router(contratos.router)
app.include_router(reportes.router)
app.include_router(notas_remision.router)
app.include_router(rh.router)
app.include_router(pagos.router)
app.include_router(config_router.router)
app.include_router(agenda_router.router)


@app.on_event("startup")
def startup():
    init_db()
    _seed_demo_data()


def _seed_demo_data():
    from app.database import SessionLocal, Cliente, Material, ReferenciaCliente, MetodoPago, Usuario
    from app.auth import hash_password
    db = SessionLocal()
    try:
        if db.query(Cliente).count() == 0:
            c = Cliente(nombre="Gilberto Loya Castillo", telefono="614-192-96-47",
                        domicilio="C. 62 #2000, COL CERRO DE LA CRUZ C.P.31460")
            db.add(c)
            db.flush()
            db.add(ReferenciaCliente(cliente_id=c.id, nombre="Joel González",
                                      telefono="614-486-25-04",
                                      direccion="C. Mina de San Carlos #17548, Col. El Porvenir"))
            db.add(ReferenciaCliente(cliente_id=c.id, nombre="Luis Armando Bailón Talamantes",
                                      telefono="614-202-78-27",
                                      direccion="C. Bolsón de Mapimí #17732 Col. Sahuaros"))
        if db.query(MetodoPago).count() == 0:
            metodos = [
                MetodoPago(nombre="Efectivo", descripcion="Pago en efectivo", requiere_referencia=False, activo=True, orden=1),
                MetodoPago(nombre="Transferencia bancaria", descripcion="SPEI o transferencia", requiere_referencia=True, activo=True, orden=2),
                MetodoPago(nombre="Cheque", descripcion="Cheque nominativo", requiere_referencia=True, activo=True, orden=3),
                MetodoPago(nombre="Tarjeta de débito", descripcion="Terminal punto de venta", requiere_referencia=False, activo=True, orden=4),
                MetodoPago(nombre="Tarjeta de crédito", descripcion="Terminal punto de venta", requiere_referencia=False, activo=False, orden=5),
            ]
            for m in metodos:
                db.add(m)
        if db.query(Material).count() == 0:
            materiales_data = [
                Material(nombre="Ruedas 8\"", tipo="pieza", precio_renta_dia=12.0, precio_venta=6616.0, ubicacion="bodega"),
                Material(nombre="Marco de andamio 90x190", tipo="pieza", precio_renta_dia=8.0, precio_venta=1200.0, ubicacion="bodega"),
                Material(nombre="Diagonal de andamio", tipo="pieza", precio_renta_dia=3.0, precio_venta=450.0, ubicacion="bodega"),
                Material(nombre="Tablón de madera", tipo="pieza", precio_renta_dia=5.0, precio_venta=350.0, ubicacion="bodega"),
                Material(nombre="Plataforma metálica", tipo="pieza", precio_renta_dia=6.0, precio_venta=800.0, ubicacion="bodega"),
                Material(nombre="Puntal telescópico 3m", tipo="pieza", precio_renta_dia=10.0, precio_venta=1500.0, ubicacion="bodega"),
                Material(nombre="Escalera 6 peldaños", tipo="pieza", precio_renta_dia=15.0, precio_venta=2000.0, ubicacion="bodega"),
            ]
            for m in materiales_data:
                db.add(m)
        # Seed admin user
        if db.query(Usuario).count() == 0:
            admin = Usuario(
                nombre="Administrador",
                username="admin",
                password_hash=hash_password("admin123"),
                rol="admin",
            )
            db.add(admin)
        db.commit()
    finally:
        db.close()


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _require_login(request: Request):
    """Redirige a /login si no hay sesión activa. Retorna None si ok."""
    if not get_session_user(request):
        return RedirectResponse(url="/login", status_code=302)
    return None


def _ctx(request: Request, extra: dict = None) -> dict:
    """Contexto base para todas las plantillas: session_user + logo_url."""
    from app.database import SessionLocal, ConfigEmpresa
    db = SessionLocal()
    try:
        emp = db.query(ConfigEmpresa).filter(ConfigEmpresa.id == 1).first()
        logo_url = f"/static/{emp.logo_path}" if emp and emp.logo_path else None
    except Exception:
        logo_url = None
    finally:
        db.close()
    ctx = {"session_user": get_session_user(request), "logo_url": logo_url}
    if extra:
        ctx.update(extra)
    return ctx


# ─── Página de login ──────────────────────────────────────────────────────────

@app.get("/login")
def page_login(request: Request):
    if get_session_user(request):
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse(request=request, name="login.html")


# ─── Páginas protegidas ───────────────────────────────────────────────────────

@app.get("/")
def index(request: Request):
    redir = _require_login(request)
    if redir:
        return redir
    return templates.TemplateResponse(request=request, name="index.html", context=_ctx(request))


@app.get("/contratos/nuevo")
def nuevo_contrato(request: Request):
    redir = _require_login(request)
    if redir:
        return redir
    return templates.TemplateResponse(request=request, name="contrato_form.html", context=_ctx(request))


@app.get("/contratos/{contrato_id}")
def ver_contrato(request: Request, contrato_id: int):
    redir = _require_login(request)
    if redir:
        return redir
    return templates.TemplateResponse(request=request, name="contrato_detalle.html",
                                       context=_ctx(request, {"contrato_id": contrato_id}))


@app.get("/clientes")
def page_clientes(request: Request):
    redir = _require_login(request)
    if redir:
        return redir
    return templates.TemplateResponse(request=request, name="clientes.html", context=_ctx(request))


@app.get("/materiales")
def page_materiales(request: Request):
    redir = _require_login(request)
    if redir:
        return redir
    return templates.TemplateResponse(request=request, name="materiales.html", context=_ctx(request))


@app.get("/reportes")
def page_reportes(request: Request):
    redir = _require_login(request)
    if redir:
        return redir
    return templates.TemplateResponse(request=request, name="reportes.html", context=_ctx(request))


@app.get("/rh/empleados")
def page_empleados(request: Request):
    redir = _require_login(request)
    if redir:
        return redir
    return templates.TemplateResponse(request=request, name="rh_empleados.html", context=_ctx(request))


@app.get("/rh/nominas")
def page_nominas(request: Request):
    redir = _require_login(request)
    if redir:
        return redir
    return templates.TemplateResponse(request=request, name="rh_nominas.html", context=_ctx(request))


@app.get("/rh/nominas/{nomina_id}")
def page_nomina_detalle(request: Request, nomina_id: int):
    redir = _require_login(request)
    if redir:
        return redir
    return templates.TemplateResponse(request=request, name="rh_nomina_detalle.html",
                                       context=_ctx(request, {"nomina_id": nomina_id}))


@app.get("/agenda")
def page_agenda(request: Request):
    redir = _require_login(request)
    if redir:
        return redir
    return templates.TemplateResponse(request=request, name="agenda.html", context=_ctx(request))


@app.get("/configuracion")
def page_configuracion(request: Request):
    redir = _require_login(request)
    if redir:
        return redir
    return templates.TemplateResponse(request=request, name="configuracion.html", context=_ctx(request))
