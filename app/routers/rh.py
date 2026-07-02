from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from datetime import date, timedelta
from app.database import get_db, Empleado, Asistencia, Nomina, LineaNomina
from app.services.calcular_nomina import calcular_linea_nomina

router = APIRouter(prefix="/api/rh", tags=["rh"])


# ─────────────────────────────────────────────────────────────────────────────
# Esquemas Pydantic
# ─────────────────────────────────────────────────────────────────────────────

class EmpleadoCreate(BaseModel):
    nombre: str
    rfc: Optional[str] = None
    curp: Optional[str] = None
    nss: Optional[str] = None
    puesto: Optional[str] = None
    departamento: Optional[str] = None
    salario_diario: float
    fecha_ingreso: date
    telefono: Optional[str] = None
    email: Optional[str] = None
    banco: Optional[str] = None
    cuenta_bancaria: Optional[str] = None
    observaciones: Optional[str] = None


class AsistenciaCreate(BaseModel):
    empleado_id: int
    fecha: date
    tipo: str = "presente"   # presente | falta | media_jornada | vacaciones | incapacidad | festivo
    horas_extra: float = 0.0
    observaciones: Optional[str] = None


class AsistenciaBulkCreate(BaseModel):
    """Registra asistencia de múltiples empleados en un día."""
    fecha: date
    registros: List[AsistenciaCreate]


class NominaCreate(BaseModel):
    fecha_inicio: date
    fecha_fin: date
    tipo_periodo: str = "semanal"
    notas: Optional[str] = None


class AjusteLineaNomina(BaseModel):
    otros_ingresos: float = 0.0
    otras_deducciones: float = 0.0
    observaciones: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# Empleados
# ─────────────────────────────────────────────────────────────────────────────

def _empleado_dict(e: Empleado) -> dict:
    return {
        "id": e.id, "nombre": e.nombre, "rfc": e.rfc, "curp": e.curp,
        "nss": e.nss, "puesto": e.puesto, "departamento": e.departamento,
        "salario_diario": e.salario_diario, "fecha_ingreso": str(e.fecha_ingreso),
        "fecha_baja": str(e.fecha_baja) if e.fecha_baja else None,
        "telefono": e.telefono, "email": e.email,
        "banco": e.banco, "cuenta_bancaria": e.cuenta_bancaria,
        "activo": e.activo, "observaciones": e.observaciones,
    }


@router.get("/empleados")
def listar_empleados(q: Optional[str] = None, activos: bool = True, db: Session = Depends(get_db)):
    query = db.query(Empleado)
    if activos:
        query = query.filter(Empleado.activo == True)
    if q:
        query = query.filter(Empleado.nombre.ilike(f"%{q}%"))
    return [_empleado_dict(e) for e in query.order_by(Empleado.nombre).all()]


@router.get("/empleados/{emp_id}")
def obtener_empleado(emp_id: int, db: Session = Depends(get_db)):
    e = db.query(Empleado).filter(Empleado.id == emp_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Empleado no encontrado")
    return _empleado_dict(e)


@router.post("/empleados", status_code=201)
def crear_empleado(data: EmpleadoCreate, db: Session = Depends(get_db)):
    e = Empleado(**data.model_dump())
    db.add(e)
    db.commit()
    db.refresh(e)
    return _empleado_dict(e)


@router.put("/empleados/{emp_id}")
def actualizar_empleado(emp_id: int, data: EmpleadoCreate, db: Session = Depends(get_db)):
    e = db.query(Empleado).filter(Empleado.id == emp_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Empleado no encontrado")
    for k, v in data.model_dump().items():
        setattr(e, k, v)
    db.commit()
    db.refresh(e)
    return _empleado_dict(e)


@router.delete("/empleados/{emp_id}")
def dar_baja_empleado(emp_id: int, fecha_baja: Optional[date] = None, db: Session = Depends(get_db)):
    e = db.query(Empleado).filter(Empleado.id == emp_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Empleado no encontrado")
    e.activo = False
    e.fecha_baja = fecha_baja or date.today()
    db.commit()
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────────────
# Asistencia
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/asistencia")
def listar_asistencia(fecha_inicio: Optional[date] = None, fecha_fin: Optional[date] = None,
                      empleado_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = db.query(Asistencia)
    if fecha_inicio:
        query = query.filter(Asistencia.fecha >= fecha_inicio)
    if fecha_fin:
        query = query.filter(Asistencia.fecha <= fecha_fin)
    if empleado_id:
        query = query.filter(Asistencia.empleado_id == empleado_id)
    asistencias = query.order_by(Asistencia.fecha.desc()).all()
    return [{
        "id": a.id, "empleado_id": a.empleado_id,
        "empleado_nombre": a.empleado.nombre if a.empleado else "",
        "fecha": str(a.fecha), "tipo": a.tipo,
        "horas_extra": a.horas_extra, "observaciones": a.observaciones,
    } for a in asistencias]


@router.post("/asistencia", status_code=201)
def registrar_asistencia(data: AsistenciaCreate, db: Session = Depends(get_db)):
    existente = db.query(Asistencia).filter(
        Asistencia.empleado_id == data.empleado_id,
        Asistencia.fecha == data.fecha,
    ).first()
    if existente:
        # Actualizar en lugar de duplicar
        for k, v in data.model_dump().items():
            setattr(existente, k, v)
        db.commit()
        return {"id": existente.id, "updated": True}

    a = Asistencia(**data.model_dump())
    db.add(a)
    db.commit()
    db.refresh(a)
    return {"id": a.id, "updated": False}


@router.post("/asistencia/bulk", status_code=201)
def registrar_asistencia_bulk(data: AsistenciaBulkCreate, db: Session = Depends(get_db)):
    resultados = []
    for reg in data.registros:
        existente = db.query(Asistencia).filter(
            Asistencia.empleado_id == reg.empleado_id,
            Asistencia.fecha == data.fecha,
        ).first()
        if existente:
            for k, v in reg.model_dump().items():
                setattr(existente, k, v)
            resultados.append({"empleado_id": reg.empleado_id, "updated": True})
        else:
            a = Asistencia(**reg.model_dump(), fecha=data.fecha)
            db.add(a)
            resultados.append({"empleado_id": reg.empleado_id, "updated": False})
    db.commit()
    return {"registrados": len(resultados), "detalle": resultados}


# ─────────────────────────────────────────────────────────────────────────────
# Nómina
# ─────────────────────────────────────────────────────────────────────────────

def _siguiente_folio_nomina(db: Session) -> str:
    count = db.query(Nomina).count() + 1
    return f"NOM-{count:05d}"


def _calcular_dias_trabajados(empleado_id: int, fecha_inicio: date,
                               fecha_fin: date, db: Session):
    """Cuenta días y horas extra del empleado en el rango, según asistencias registradas."""
    asistencias = db.query(Asistencia).filter(
        Asistencia.empleado_id == empleado_id,
        Asistencia.fecha >= fecha_inicio,
        Asistencia.fecha <= fecha_fin,
    ).all()

    dias = 0.0
    horas_extra = 0.0
    for a in asistencias:
        if a.tipo == "presente":
            dias += 1.0
        elif a.tipo == "media_jornada":
            dias += 0.5
        elif a.tipo in ("falta", "incapacidad"):
            pass   # no se cuenta
        elif a.tipo in ("vacaciones", "festivo"):
            dias += 1.0   # se paga aunque no trabaje
        horas_extra += a.horas_extra or 0

    # Si no hay asistencias registradas: asumir todos los días del período presentes
    total_dias_periodo = (fecha_fin - fecha_inicio).days + 1
    if not asistencias:
        dias = float(total_dias_periodo)

    return dias, horas_extra, total_dias_periodo


@router.get("/nominas")
def listar_nominas(db: Session = Depends(get_db)):
    nominas = db.query(Nomina).order_by(Nomina.created_at.desc()).all()
    return [{
        "id": n.id, "folio": n.folio,
        "fecha_inicio": str(n.fecha_inicio), "fecha_fin": str(n.fecha_fin),
        "tipo_periodo": n.tipo_periodo, "estado": n.estado,
        "total_bruto": n.total_bruto, "total_deducciones": n.total_deducciones,
        "total_neto": n.total_neto,
        "num_empleados": len(n.lineas),
    } for n in nominas]


@router.get("/nominas/{nomina_id}")
def obtener_nomina(nomina_id: int, db: Session = Depends(get_db)):
    n = db.query(Nomina).filter(Nomina.id == nomina_id).first()
    if not n:
        raise HTTPException(status_code=404, detail="Nómina no encontrada")
    lineas = [{
        "id": l.id, "empleado_id": l.empleado_id,
        "empleado_nombre": l.empleado.nombre if l.empleado else "",
        "empleado_puesto": l.empleado.puesto if l.empleado else "",
        "dias_trabajados": l.dias_trabajados, "dias_falta": l.dias_falta,
        "horas_extra": l.horas_extra, "salario_diario": l.salario_diario,
        "salario_bruto": l.salario_bruto, "imss_obrero": l.imss_obrero,
        "isr": l.isr, "otras_deducciones": l.otras_deducciones,
        "otros_ingresos": l.otros_ingresos, "salario_neto": l.salario_neto,
        "observaciones": l.observaciones,
    } for l in n.lineas]
    return {
        "id": n.id, "folio": n.folio,
        "fecha_inicio": str(n.fecha_inicio), "fecha_fin": str(n.fecha_fin),
        "tipo_periodo": n.tipo_periodo, "estado": n.estado,
        "total_bruto": n.total_bruto, "total_deducciones": n.total_deducciones,
        "total_neto": n.total_neto, "notas": n.notas,
        "lineas": lineas,
    }


@router.post("/nominas", status_code=201)
def crear_nomina(data: NominaCreate, db: Session = Depends(get_db)):
    """Crea la nómina y pre-calcula líneas para todos los empleados activos."""
    if data.fecha_fin < data.fecha_inicio:
        raise HTTPException(status_code=400, detail="fecha_fin debe ser >= fecha_inicio")

    empleados = db.query(Empleado).filter(Empleado.activo == True).all()
    if not empleados:
        raise HTTPException(status_code=400, detail="No hay empleados activos")

    folio = _siguiente_folio_nomina(db)
    nomina = Nomina(
        folio=folio,
        fecha_inicio=data.fecha_inicio,
        fecha_fin=data.fecha_fin,
        tipo_periodo=data.tipo_periodo,
        notas=data.notas,
    )
    db.add(nomina)
    db.flush()

    total_bruto = total_ded = total_neto = 0.0

    for emp in empleados:
        dias_trabajados, horas_extra, dias_periodo = _calcular_dias_trabajados(
            emp.id, data.fecha_inicio, data.fecha_fin, db)

        calc = calcular_linea_nomina(
            salario_diario=emp.salario_diario,
            dias_trabajados=dias_trabajados,
            horas_extra=horas_extra,
            dias_periodo=dias_periodo,
        )
        dias_falta = dias_periodo - dias_trabajados

        linea = LineaNomina(
            nomina_id=nomina.id,
            empleado_id=emp.id,
            dias_trabajados=dias_trabajados,
            dias_falta=dias_falta,
            horas_extra=horas_extra,
            salario_diario=emp.salario_diario,
            salario_bruto=calc["salario_bruto"],
            imss_obrero=calc["imss_obrero"],
            isr=calc["isr"],
            otras_deducciones=0.0,
            otros_ingresos=0.0,
            salario_neto=calc["salario_neto"],
        )
        db.add(linea)
        total_bruto += calc["salario_bruto"]
        total_ded += calc["imss_obrero"] + calc["isr"]
        total_neto += calc["salario_neto"]

    nomina.total_bruto = round(total_bruto, 2)
    nomina.total_deducciones = round(total_ded, 2)
    nomina.total_neto = round(total_neto, 2)
    db.commit()
    db.refresh(nomina)
    return {"id": nomina.id, "folio": nomina.folio}


@router.put("/nominas/{nomina_id}/linea/{linea_id}")
def ajustar_linea(nomina_id: int, linea_id: int, data: AjusteLineaNomina, db: Session = Depends(get_db)):
    """Permite editar bonos u otras deducciones de una línea y recalcular el neto."""
    n = db.query(Nomina).filter(Nomina.id == nomina_id).first()
    if not n:
        raise HTTPException(status_code=404, detail="Nómina no encontrada")
    if n.estado == "pagada":
        raise HTTPException(status_code=400, detail="No se puede modificar una nómina pagada")

    l = db.query(LineaNomina).filter(LineaNomina.id == linea_id, LineaNomina.nomina_id == nomina_id).first()
    if not l:
        raise HTTPException(status_code=404, detail="Línea no encontrada")

    l.otros_ingresos = data.otros_ingresos
    l.otras_deducciones = data.otras_deducciones
    if data.observaciones is not None:
        l.observaciones = data.observaciones

    # Recalcular neto
    l.salario_neto = round(l.salario_bruto + data.otros_ingresos - l.imss_obrero - l.isr - data.otras_deducciones, 2)
    l.salario_neto = max(l.salario_neto, 0)

    # Recalcular totales de la nómina
    n.total_bruto = round(sum(ll.salario_bruto + ll.otros_ingresos for ll in n.lineas), 2)
    n.total_deducciones = round(sum(ll.imss_obrero + ll.isr + ll.otras_deducciones for ll in n.lineas), 2)
    n.total_neto = round(sum(ll.salario_neto for ll in n.lineas), 2)
    db.commit()
    return {"ok": True, "salario_neto": l.salario_neto}


@router.post("/nominas/{nomina_id}/autorizar")
def autorizar_nomina(nomina_id: int, db: Session = Depends(get_db)):
    n = db.query(Nomina).filter(Nomina.id == nomina_id).first()
    if not n:
        raise HTTPException(status_code=404, detail="Nómina no encontrada")
    if n.estado != "borrador":
        raise HTTPException(status_code=400, detail=f"La nómina ya está en estado '{n.estado}'")
    n.estado = "autorizada"
    db.commit()
    return {"ok": True, "estado": n.estado}


@router.post("/nominas/{nomina_id}/pagar")
def pagar_nomina(nomina_id: int, db: Session = Depends(get_db)):
    n = db.query(Nomina).filter(Nomina.id == nomina_id).first()
    if not n:
        raise HTTPException(status_code=404, detail="Nómina no encontrada")
    if n.estado != "autorizada":
        raise HTTPException(status_code=400, detail="La nómina debe estar autorizada antes de marcarla como pagada")
    n.estado = "pagada"
    db.commit()
    return {"ok": True, "estado": n.estado}


@router.get("/nominas/{nomina_id}/recibo/{empleado_id}")
def descargar_recibo(nomina_id: int, empleado_id: int, db: Session = Depends(get_db)):
    from app.services.generar_recibo_nomina import generar_recibo_nomina

    n = db.query(Nomina).filter(Nomina.id == nomina_id).first()
    if not n:
        raise HTTPException(status_code=404, detail="Nómina no encontrada")

    l = db.query(LineaNomina).filter(
        LineaNomina.nomina_id == nomina_id,
        LineaNomina.empleado_id == empleado_id,
    ).first()
    if not l:
        raise HTTPException(status_code=404, detail="Línea de nómina no encontrada")

    emp = l.empleado
    nomina_data = {
        "folio": n.folio,
        "fecha_inicio": n.fecha_inicio,
        "fecha_fin": n.fecha_fin,
        "tipo_periodo": n.tipo_periodo,
    }
    linea_data = {
        "salario_diario": l.salario_diario,
        "dias_trabajados": l.dias_trabajados,
        "horas_extra": l.horas_extra,
        "otros_ingresos": l.otros_ingresos,
        "otras_deducciones": l.otras_deducciones,
        "salario_bruto": l.salario_bruto,
        "imss_obrero": l.imss_obrero,
        "isr": l.isr,
        "salario_neto": l.salario_neto,
    }
    empleado_data = {
        "id": emp.id, "nombre": emp.nombre, "puesto": emp.puesto,
        "rfc": emp.rfc, "nss": emp.nss,
    }
    output_path = generar_recibo_nomina(nomina_data, linea_data, empleado_data)
    return FileResponse(
        path=str(output_path),
        filename=f"Recibo_{n.folio}_{emp.nombre.replace(' ', '_')}.pdf",
        media_type="application/pdf",
    )
