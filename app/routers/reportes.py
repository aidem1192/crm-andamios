from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import date, datetime, timedelta
from app.database import get_db, Contrato, Cliente, Material, LineaContrato
from app.services.devolucion import calcular_devolucion

router = APIRouter(prefix="/api/reportes", tags=["reportes"])


@router.get("/resumen")
def resumen(db: Session = Depends(get_db)):
    """Indicadores generales para el dashboard."""
    hoy = date.today()

    contratos_activos = db.query(Contrato).filter(Contrato.estado == "activo").all()
    todos_contratos = db.query(Contrato).all()
    contratos_no_cancelados = [c for c in todos_contratos if c.estado != "cancelado"]

    ingreso_diario_activo = sum(
        (c.total_diario_con_descuento or c.total_diario) for c in contratos_activos
    )
    ingreso_total_historico = sum(c.total_con_iva or 0 for c in contratos_no_cancelados)
    ingreso_mes_actual = sum(
        c.total_con_iva or 0 for c in contratos_no_cancelados
        if c.created_at and c.created_at.year == hoy.year and c.created_at.month == hoy.month
    )

    total_clientes = db.query(Cliente).count()
    total_materiales_activos = db.query(Material).filter(Material.activo == True).count()

    # Material actualmente en obra (suma de cantidades en contratos activos)
    piezas_en_obra = 0
    for c in contratos_activos:
        for l in c.lineas:
            piezas_en_obra += l.cantidad

    return {
        "contratos_activos": len(contratos_activos),
        "contratos_terminados": len([c for c in todos_contratos if c.estado == "terminado"]),
        "contratos_cancelados": len([c for c in todos_contratos if c.estado == "cancelado"]),
        "ingreso_diario_activo": round(ingreso_diario_activo, 2),
        "ingreso_mes_actual": round(ingreso_mes_actual, 2),
        "ingreso_total_historico": round(ingreso_total_historico, 2),
        "total_clientes": total_clientes,
        "total_materiales_activos": total_materiales_activos,
        "piezas_en_obra": piezas_en_obra,
    }


@router.get("/contratos-por-vencer")
def contratos_por_vencer(dias: int = 3, db: Session = Depends(get_db)):
    """Contratos activos cuya fecha_fin está dentro de los próximos N días (o ya vencida)."""
    hoy = date.today()
    limite = hoy + timedelta(days=dias)

    activos = db.query(Contrato).filter(Contrato.estado == "activo").all()
    resultado = []
    for c in activos:
        if c.fecha_fin <= limite:
            dias_restantes = (c.fecha_fin - hoy).days
            resultado.append({
                "id": c.id,
                "folio": c.folio,
                "cliente": c.cliente.nombre if c.cliente else "",
                "fecha_fin": str(c.fecha_fin),
                "dias_restantes": dias_restantes,
                "vencido": dias_restantes < 0,
            })
    resultado.sort(key=lambda x: x["dias_restantes"])
    return resultado


@router.get("/alertas-devolucion")
def alertas_devolucion(db: Session = Depends(get_db)):
    """
    Contratos activos cuya fecha_fin ya pasó y que están corriendo el riesgo
    (o ya superaron) el plazo de gracia de devolución (siguiente día hábil 10 AM).
    """
    ahora = datetime.now()
    activos = db.query(Contrato).filter(Contrato.estado == "activo").all()
    alertas = []
    for c in activos:
        if c.fecha_fin < ahora.date():
            chk = calcular_devolucion(c.fecha_fin, ahora)
            alertas.append({
                "id": c.id,
                "folio": c.folio,
                "cliente": c.cliente.nombre if c.cliente else "",
                "fecha_fin": str(c.fecha_fin),
                "fecha_limite": chk["fecha_limite"],
                "dia_extra": chk["dia_extra"],
                "mensaje": chk["mensaje"],
            })
    return alertas


@router.get("/materiales-en-obra")
def materiales_en_obra(db: Session = Depends(get_db)):
    """Resumen de cuántas piezas de cada material están actualmente rentadas (contratos activos)."""
    activos = db.query(Contrato).filter(Contrato.estado == "activo").all()
    conteo = {}
    for c in activos:
        for l in c.lineas:
            nombre = l.material.nombre if l.material else "?"
            conteo[nombre] = conteo.get(nombre, 0) + l.cantidad

    materiales = db.query(Material).filter(Material.activo == True).all()
    resultado = []
    for m in materiales:
        en_obra = conteo.get(m.nombre, 0)
        resultado.append({
            "material": m.nombre,
            "en_obra": en_obra,
            "ubicacion": m.ubicacion,
            "estado": m.estado,
        })
    resultado.sort(key=lambda x: -x["en_obra"])
    return resultado


@router.get("/ingresos-por-mes")
def ingresos_por_mes(meses: int = 6, db: Session = Depends(get_db)):
    """Ingresos totales (con IVA) agrupados por mes, últimos N meses."""
    hoy = date.today()
    contratos = db.query(Contrato).all()

    buckets = {}
    cursor = date(hoy.year, hoy.month, 1)
    claves_ordenadas = []
    for i in range(meses):
        clave = f"{cursor.year}-{cursor.month:02d}"
        buckets[clave] = 0.0
        claves_ordenadas.append(clave)
        # retroceder un mes
        if cursor.month == 1:
            cursor = date(cursor.year - 1, 12, 1)
        else:
            cursor = date(cursor.year, cursor.month - 1, 1)

    for c in contratos:
        if not c.created_at:
            continue
        clave = f"{c.created_at.year}-{c.created_at.month:02d}"
        if clave in buckets:
            buckets[clave] += c.total_con_iva or 0

    claves_ordenadas.reverse()
    return [{"mes": clave, "ingreso": round(buckets[clave], 2)} for clave in claves_ordenadas]
