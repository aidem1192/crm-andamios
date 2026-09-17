from sqlalchemy import create_engine, Column, Integer, String, Float, Date, DateTime, Text, ForeignKey, Boolean, Enum, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
import enum
import os
from datetime import datetime

# En producción (Railway) se define DATABASE_URL apuntando a Supabase Postgres.
# En desarrollo local, si no está definida, cae en el SQLite de siempre.
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./data/andamios.db")

# Supabase (como Heroku) a veces entrega la URL con el esquema viejo "postgres://",
# que SQLAlchemy 2.x ya no acepta — hay que normalizarlo a "postgresql://".
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Forzar el driver psycopg (v3) en vez del psycopg2 por defecto — mejor soporte
# de wheels precompilados en plataformas de despliegue como Railway.
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

_es_sqlite = DATABASE_URL.startswith("sqlite")
if _es_sqlite:
    _connect_args = {"check_same_thread": False}
else:
    # El pooler de Supabase en modo "Transaction" no soporta prepared statements
    # (cada transacción puede caer en una conexión física distinta del servidor).
    # prepare_threshold=None le dice a psycopg que nunca las use.
    _connect_args = {"prepare_threshold": None}

engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class TipoMaterial(str, enum.Enum):
    pieza = "pieza"
    kit_fijo = "kit_fijo"
    kit_personalizable = "kit_personalizable"


class EstadoMaterial(str, enum.Enum):
    bueno = "bueno"
    danado = "danado"
    en_reparacion = "en_reparacion"


class UbicacionMaterial(str, enum.Enum):
    bodega = "bodega"
    en_obra = "en_obra"
    en_transito = "en_transito"


class EstadoContrato(str, enum.Enum):
    activo = "activo"
    terminado = "terminado"
    cancelado = "cancelado"


class Cliente(Base):
    __tablename__ = "clientes"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(200), nullable=False)
    telefono = Column(String(30))
    domicilio = Column(Text)
    rfc = Column(String(20))
    email = Column(String(100))
    lista_negra = Column(Boolean, default=False)
    motivo_lista_negra = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    referencias = relationship("ReferenciaCliente", back_populates="cliente", cascade="all, delete-orphan")
    contratos = relationship("Contrato", back_populates="cliente")


class ReferenciaCliente(Base):
    __tablename__ = "referencias_clientes"
    id = Column(Integer, primary_key=True, index=True)
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=False)
    nombre = Column(String(200), nullable=False)
    telefono = Column(String(30))
    direccion = Column(Text)

    cliente = relationship("Cliente", back_populates="referencias")


class Material(Base):
    __tablename__ = "materiales"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(200), nullable=False)
    tipo = Column(String(30), default="pieza")
    numero_serie = Column(String(100))
    estado = Column(String(30), default="bueno")
    ubicacion = Column(String(30), default="bodega")
    precio_renta_dia = Column(Float, nullable=False)
    precio_venta = Column(Float)
    descripcion = Column(Text)
    stock = Column(Integer, default=0)   # unidades totales en posesión (piezas)
    activo = Column(Boolean, default=True)

    componentes = relationship("LineaKit", foreign_keys="LineaKit.kit_id",
                               back_populates="kit", cascade="all, delete-orphan")


class LineaKit(Base):
    """Composición de un kit: qué piezas lo forman y en qué cantidad."""
    __tablename__ = "lineas_kit"
    id = Column(Integer, primary_key=True, index=True)
    kit_id = Column(Integer, ForeignKey("materiales.id"), nullable=False)
    pieza_id = Column(Integer, ForeignKey("materiales.id"), nullable=False)
    cantidad = Column(Integer, nullable=False, default=1)

    kit = relationship("Material", foreign_keys=[kit_id], back_populates="componentes")
    pieza = relationship("Material", foreign_keys=[pieza_id])


class Contrato(Base):
    __tablename__ = "contratos"
    id = Column(Integer, primary_key=True, index=True)
    folio = Column(String(20), unique=True)
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=False)
    fecha_inicio = Column(Date, nullable=False)
    fecha_fin = Column(Date, nullable=False)
    dias = Column(Integer, nullable=False)
    lugar_obra = Column(Text)
    personas_autorizadas = Column(Text)
    lugar_celebracion = Column(String(200))
    total_diario = Column(Float, nullable=False)
    descuento_pct = Column(Float, default=0)
    descuento_autorizado = Column(Boolean, default=False)
    total_diario_con_descuento = Column(Float)
    iva = Column(Float)
    total_con_iva = Column(Float)
    estado = Column(String(20), default="activo")
    notas = Column(Text)
    motivo_cancelacion = Column(Text, nullable=True)
    incluye_iva = Column(Boolean, default=True)
    # Devolución real
    fecha_devolucion = Column(DateTime, nullable=True)
    dia_extra_cobrado = Column(Boolean, default=False)
    # Estado de pago
    total_pagado = Column(Float, default=0.0)
    estado_pago = Column(String(20), default="pendiente")  # pendiente | parcial | pagado
    created_at = Column(DateTime, default=datetime.utcnow)

    cliente = relationship("Cliente", back_populates="contratos")
    lineas = relationship("LineaContrato", back_populates="contrato", cascade="all, delete-orphan")
    pagos = relationship("Pago", back_populates="contrato", cascade="all, delete-orphan")
    cargos_extra = relationship("CargoExtra", back_populates="contrato", cascade="all, delete-orphan")


class LineaContrato(Base):
    __tablename__ = "lineas_contrato"
    id = Column(Integer, primary_key=True, index=True)
    contrato_id = Column(Integer, ForeignKey("contratos.id"), nullable=False)
    material_id = Column(Integer, ForeignKey("materiales.id"), nullable=False)
    cantidad = Column(Integer, nullable=False)
    precio_unitario = Column(Float, nullable=False)
    total_linea = Column(Float, nullable=False)
    cantidad_devuelta = Column(Integer, default=0)

    contrato = relationship("Contrato", back_populates="lineas")
    material = relationship("Material")


class CargoExtra(Base):
    __tablename__ = "cargos_extra"
    id = Column(Integer, primary_key=True, index=True)
    contrato_id = Column(Integer, ForeignKey("contratos.id"), nullable=False)
    concepto = Column(String(300), nullable=False)
    monto = Column(Float, nullable=False)
    tipo = Column(String(30), default="otro")  # danio | reposicion | otro
    created_at = Column(DateTime, default=datetime.utcnow)

    contrato = relationship("Contrato", back_populates="cargos_extra")


class NotaRemision(Base):
    __tablename__ = "notas_remision"
    id = Column(Integer, primary_key=True, index=True)
    folio = Column(String(20), unique=True)
    contrato_id = Column(Integer, ForeignKey("contratos.id"), nullable=False)
    tipo = Column(String(20), nullable=False)  # entrega | devolucion
    fecha = Column(Date, nullable=False)
    lugar_obra = Column(Text)
    entregado_por = Column(String(200))
    recibido_por = Column(String(200))
    observaciones = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    contrato = relationship("Contrato")
    lineas = relationship("LineaNotaRemision", back_populates="nota", cascade="all, delete-orphan")


class LineaNotaRemision(Base):
    __tablename__ = "lineas_nota_remision"
    id = Column(Integer, primary_key=True, index=True)
    nota_id = Column(Integer, ForeignKey("notas_remision.id"), nullable=False)
    material_id = Column(Integer, ForeignKey("materiales.id"), nullable=False)
    cantidad = Column(Integer, nullable=False)
    estado_material = Column(String(30), default="bueno")

    nota = relationship("NotaRemision", back_populates="lineas")
    material = relationship("Material")


class ConfigEmpresa(Base):
    """Singleton — siempre id=1."""
    __tablename__ = "config_empresa"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(200), default="Andamios y Derivados del Norte")
    rfc = Column(String(20))
    domicilio = Column(Text)
    telefono = Column(String(50))
    email = Column(String(100))
    sitio_web = Column(String(200))
    representante_legal = Column(String(200))
    slogan = Column(String(300))
    logo_path = Column(String(300))   # ruta relativa a /static/uploads/
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Usuario(Base):
    __tablename__ = "usuarios"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(200), nullable=False)
    username = Column(String(100), nullable=False, unique=True)
    password_hash = Column(String(300), nullable=False)
    rol = Column(String(20), default="operador")   # admin | operador
    activo = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)

    audit_logs = relationship("AuditLog", back_populates="usuario")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    usuario_nombre = Column(String(200))   # snapshot para no perder historial si se elimina
    accion = Column(String(100), nullable=False)   # crear_contrato, login, etc.
    entidad = Column(String(100))                  # contrato, pago, empleado, etc.
    entidad_id = Column(Integer, nullable=True)
    descripcion = Column(Text)                     # resumen legible
    ip = Column(String(50))
    fecha = Column(DateTime, default=datetime.utcnow)

    usuario = relationship("Usuario", back_populates="audit_logs")


class MetodoPago(Base):
    __tablename__ = "metodos_pago"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), nullable=False, unique=True)
    descripcion = Column(String(200))
    requiere_referencia = Column(Boolean, default=False)  # para transferencias/cheques
    activo = Column(Boolean, default=True)
    orden = Column(Integer, default=0)


class Pago(Base):
    __tablename__ = "pagos"
    id = Column(Integer, primary_key=True, index=True)
    folio = Column(String(20), unique=True)
    contrato_id = Column(Integer, ForeignKey("contratos.id"), nullable=False)
    fecha = Column(Date, nullable=False)
    monto = Column(Float, nullable=False)
    metodo_pago_id = Column(Integer, ForeignKey("metodos_pago.id"), nullable=False)
    referencia = Column(String(200))   # número de transferencia, cheque, etc.
    notas = Column(Text)
    tipo_gasto = Column(String(50), default="renta")   # renta | deposito | flete | cargo_extra | reposicion | otro
    created_at = Column(DateTime, default=datetime.utcnow)

    contrato = relationship("Contrato", back_populates="pagos")
    metodo_pago = relationship("MetodoPago")


class Empleado(Base):
    __tablename__ = "empleados"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(200), nullable=False)
    rfc = Column(String(20))
    curp = Column(String(20))
    nss = Column(String(20))            # Número de Seguro Social
    puesto = Column(String(100))
    departamento = Column(String(100))
    salario_diario = Column(Float, nullable=False)  # salario base por día
    fecha_ingreso = Column(Date, nullable=False)
    fecha_baja = Column(Date, nullable=True)
    telefono = Column(String(30))
    email = Column(String(100))
    banco = Column(String(100))
    cuenta_bancaria = Column(String(30))
    activo = Column(Boolean, default=True)
    observaciones = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    asistencias = relationship("Asistencia", back_populates="empleado", cascade="all, delete-orphan")
    lineas_nomina = relationship("LineaNomina", back_populates="empleado")


class Asistencia(Base):
    __tablename__ = "asistencias"
    id = Column(Integer, primary_key=True, index=True)
    empleado_id = Column(Integer, ForeignKey("empleados.id"), nullable=False)
    fecha = Column(Date, nullable=False)
    # presente | falta | media_jornada | vacaciones | incapacidad | festivo
    tipo = Column(String(30), default="presente")
    horas_extra = Column(Float, default=0.0)
    observaciones = Column(Text)

    empleado = relationship("Empleado", back_populates="asistencias")


class Nomina(Base):
    __tablename__ = "nominas"
    id = Column(Integer, primary_key=True, index=True)
    folio = Column(String(20), unique=True)
    fecha_inicio = Column(Date, nullable=False)
    fecha_fin = Column(Date, nullable=False)
    # semanal | quincenal | mensual
    tipo_periodo = Column(String(20), default="semanal")
    # borrador | autorizada | pagada
    estado = Column(String(20), default="borrador")
    total_bruto = Column(Float, default=0)
    total_deducciones = Column(Float, default=0)
    total_neto = Column(Float, default=0)
    notas = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    lineas = relationship("LineaNomina", back_populates="nomina", cascade="all, delete-orphan")


class LineaNomina(Base):
    __tablename__ = "lineas_nomina"
    id = Column(Integer, primary_key=True, index=True)
    nomina_id = Column(Integer, ForeignKey("nominas.id"), nullable=False)
    empleado_id = Column(Integer, ForeignKey("empleados.id"), nullable=False)
    dias_trabajados = Column(Float, default=0)
    dias_falta = Column(Float, default=0)
    horas_extra = Column(Float, default=0)
    salario_diario = Column(Float, default=0)
    salario_bruto = Column(Float, default=0)
    imss_obrero = Column(Float, default=0)
    isr = Column(Float, default=0)
    otras_deducciones = Column(Float, default=0)
    otros_ingresos = Column(Float, default=0)   # bonos, etc.
    salario_neto = Column(Float, default=0)
    observaciones = Column(Text)

    nomina = relationship("Nomina", back_populates="lineas")
    empleado = relationship("Empleado", back_populates="lineas_nomina")


class EventoAgenda(Base):
    __tablename__ = "eventos_agenda"
    id = Column(Integer, primary_key=True, index=True)
    titulo = Column(String(200), nullable=False)
    fecha = Column(Date, nullable=False)
    hora = Column(String(10), nullable=True)          # "09:00" — opcional
    # entrega | recoleccion | pago | recordatorio | otro
    tipo = Column(String(30), default="recordatorio")
    descripcion = Column(Text, nullable=True)
    contrato_id = Column(Integer, ForeignKey("contratos.id"), nullable=True)
    completado = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    contrato = relationship("Contrato")


class CategoriaGasto(str, enum.Enum):
    renta = "renta"
    combustible = "combustible"
    salarios = "salarios"
    mantenimiento = "mantenimiento"
    transporte = "transporte"
    servicios = "servicios"
    otros = "otros"


class Gasto(Base):
    __tablename__ = "gastos"
    id = Column(Integer, primary_key=True, index=True)
    fecha = Column(Date, nullable=False)
    concepto = Column(String(300), nullable=False)
    monto = Column(Float, nullable=False)
    categoria = Column(String(50), default="otros")
    metodo_pago = Column(String(50), default="efectivo")
    referencia = Column(String(200))
    notas = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class Cotizacion(Base):
    __tablename__ = "cotizaciones"
    id = Column(Integer, primary_key=True, index=True)
    folio = Column(String(20), unique=True)
    # cliente puede ser registrado o solo nombre libre
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=True)
    cliente_nombre = Column(String(200), nullable=False)
    cliente_telefono = Column(String(30))
    cliente_domicilio = Column(Text)
    cliente_rfc = Column(String(20))
    fecha = Column(Date, nullable=False)
    vigencia_dias = Column(Integer, default=15)
    lugar_obra = Column(Text)
    incluye_iva = Column(Boolean, default=True)
    descuento_pct = Column(Float, default=0.0)
    subtotal = Column(Float, default=0.0)
    descuento_monto = Column(Float, default=0.0)
    iva = Column(Float, default=0.0)
    total = Column(Float, default=0.0)
    notas = Column(Text)
    estado = Column(String(20), default="borrador")  # borrador | enviada | aceptada | rechazada
    created_at = Column(DateTime, default=datetime.utcnow)

    cliente = relationship("Cliente")
    lineas = relationship("LineaCotizacion", back_populates="cotizacion", cascade="all, delete-orphan")


class LineaCotizacion(Base):
    __tablename__ = "lineas_cotizacion"
    id = Column(Integer, primary_key=True, index=True)
    cotizacion_id = Column(Integer, ForeignKey("cotizaciones.id"), nullable=False)
    tipo = Column(String(20), default="material")   # material | servicio
    descripcion = Column(String(300), nullable=False)
    cantidad = Column(Float, default=1)
    precio_unitario = Column(Float, nullable=False)
    total_linea = Column(Float, nullable=False)

    cotizacion = relationship("Cotizacion", back_populates="lineas")


class DocumentoCliente(Base):
    __tablename__ = "documentos_cliente"
    id = Column(Integer, primary_key=True, index=True)
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=False)
    tipo = Column(String(50), nullable=False)   # ine_frente | ine_reverso | comprobante_domicilio | otro
    nombre_archivo = Column(String(300), nullable=False)
    ruta = Column(String(500), nullable=False)  # ruta relativa a /data/uploads/docs/
    created_at = Column(DateTime, default=datetime.utcnow)

    cliente = relationship("Cliente")


class NotaCargo(Base):
    __tablename__ = "notas_cargo"
    id = Column(Integer, primary_key=True, index=True)
    folio = Column(String(20), unique=True)
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=False)
    fecha = Column(Date, nullable=False)
    notas = Column(Text)
    total = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)

    cliente = relationship("Cliente")
    lineas = relationship("LineaNotaCargo", back_populates="nota", cascade="all, delete-orphan")


class LineaNotaCargo(Base):
    __tablename__ = "lineas_nota_cargo"
    id = Column(Integer, primary_key=True, index=True)
    nota_id = Column(Integer, ForeignKey("notas_cargo.id"), nullable=False)
    material_id = Column(Integer, ForeignKey("materiales.id"), nullable=True)
    concepto = Column(String(300), nullable=False)
    cantidad = Column(Integer, default=1)
    precio_unitario = Column(Float, nullable=False)
    total_linea = Column(Float, nullable=False)

    nota = relationship("NotaCargo", back_populates="lineas")
    material = relationship("Material")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)
    _migrar_columnas_nuevas()
    _seed_metodos_pago()


def _seed_metodos_pago():
    """Crea los métodos de pago por defecto si la tabla está vacía."""
    db = SessionLocal()
    try:
        if db.query(MetodoPago).count() == 0:
            defaults = [
                MetodoPago(nombre="Efectivo",       descripcion="Pago en efectivo",                    requiere_referencia=False, activo=True, orden=1),
                MetodoPago(nombre="Transferencia",  descripcion="Transferencia bancaria / SPEI",       requiere_referencia=True,  activo=True, orden=2),
                MetodoPago(nombre="Tarjeta",        descripcion="Pago con tarjeta de débito o crédito",requiere_referencia=False, activo=True, orden=3),
                MetodoPago(nombre="Cheque",         descripcion="Pago con cheque",                     requiere_referencia=True,  activo=True, orden=4),
            ]
            for m in defaults:
                db.add(m)
            db.commit()
    finally:
        db.close()


def _migrar_columnas_nuevas():
    """Agrega columnas nuevas a tablas ya existentes (create_all no altera tablas existentes).
    Usa el inspector de SQLAlchemy en vez de SQL crudo para funcionar tanto en SQLite como en Postgres."""
    from sqlalchemy import inspect
    inspector = inspect(engine)
    if "contratos" not in inspector.get_table_names():
        return
    columnas = [c["name"] for c in inspector.get_columns("contratos")]
    if "motivo_cancelacion" not in columnas:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE contratos ADD COLUMN motivo_cancelacion TEXT"))
            conn.commit()

    if "lineas_contrato" in inspector.get_table_names():
        cols_lc = [c["name"] for c in inspector.get_columns("lineas_contrato")]
        if "cantidad_devuelta" not in cols_lc:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE lineas_contrato ADD COLUMN cantidad_devuelta INTEGER DEFAULT 0"))
                conn.commit()

    if "contratos" in inspector.get_table_names():
        cols_c = [c["name"] for c in inspector.get_columns("contratos")]
        if "incluye_iva" not in cols_c:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE contratos ADD COLUMN incluye_iva BOOLEAN DEFAULT TRUE"))
                conn.commit()

    if "clientes" in inspector.get_table_names():
        cols_cli = [c["name"] for c in inspector.get_columns("clientes")]
        with engine.connect() as conn:
            if "lista_negra" not in cols_cli:
                conn.execute(text("ALTER TABLE clientes ADD COLUMN lista_negra BOOLEAN DEFAULT FALSE"))
            if "motivo_lista_negra" not in cols_cli:
                conn.execute(text("ALTER TABLE clientes ADD COLUMN motivo_lista_negra TEXT"))
            conn.commit()

    if "gastos" in inspector.get_table_names():
        cols_g = [c["name"] for c in inspector.get_columns("gastos")]
        with engine.connect() as conn:
            if "metodo_pago" not in cols_g:
                conn.execute(text("ALTER TABLE gastos ADD COLUMN metodo_pago VARCHAR(50) DEFAULT 'efectivo'"))
            if "referencia" not in cols_g:
                conn.execute(text("ALTER TABLE gastos ADD COLUMN referencia VARCHAR(200)"))
            conn.commit()

    if "pagos" in inspector.get_table_names():
        cols_p = [c["name"] for c in inspector.get_columns("pagos")]
        if "tipo_gasto" not in cols_p:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE pagos ADD COLUMN tipo_gasto VARCHAR(50) DEFAULT 'renta'"))
                conn.commit()

    # documentos_cliente se crea automáticamente vía create_all si no existe
