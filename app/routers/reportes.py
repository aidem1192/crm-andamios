from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import date, datetime, timedelta
from typing import Optional
from pydantic import BaseModel
from app.database import get_db, Contrato, Cliente, Material, LineaContrato, Pago, MetodoPago, Gasto
from app.services.devolucion import calcular_devolucion
import io

router = APIRouter(prefix="/api/reportes", tags=["reportes"])


# ─── utilidades de rango ────────────────────────────────────────────────────

def _rango(periodo: str, fecha_ini: Optional[str], fecha_fin: Optional[str]):
    """Devuelve (date_inicio, date_fin) según periodo o rango personalizado."""
    hoy = date.today()
    if fecha_ini and fecha_fin:
        return date.fromisoformat(fecha_ini), date.fromisoformat(fecha_fin)
    if periodo == "semana":
        lunes = hoy - timedelta(days=hoy.weekday())
        return lunes, hoy
    if periodo == "mes":
        return date(hoy.year, hoy.month, 1), hoy
    if periodo == "año":
        return date(hoy.year, 1, 1), hoy
    if periodo == "hoy":
        return hoy, hoy
    # default: mes actual
    return date(hoy.year, hoy.month, 1), hoy


# ─── resumen dashboard ──────────────────────────────────────────────────────

@router.get("/resumen")
def resumen(db: Session = Depends(get_db)):
    hoy = date.today()
    contratos_activos = db.query(Contrato).filter(Contrato.estado == "activo").all()
    todos_contratos = db.query(Contrato).all()
    contratos_no_cancelados = [c for c in todos_contratos if c.estado != "cancelado"]

    ingreso_diario_activo = sum(
        (c.total_diario_con_descuento or c.total_diario) *
        (1.16 if (c.incluye_iva if c.incluye_iva is not None else True) else 1.0)
        for c in contratos_activos
    )
    ingreso_total_historico = sum(c.total_con_iva or 0 for c in contratos_no_cancelados)
    ingreso_mes_actual = sum(
        c.total_con_iva or 0 for c in contratos_no_cancelados
        if c.created_at and c.created_at.year == hoy.year and c.created_at.month == hoy.month
    )

    total_clientes = db.query(Cliente).count()
    total_materiales_activos = db.query(Material).filter(Material.activo == True).count()

    piezas_en_obra = sum(l.cantidad for c in contratos_activos for l in c.lineas)

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


# ─── contratos por vencer ───────────────────────────────────────────────────

@router.get("/contratos-por-vencer")
def contratos_por_vencer(dias: int = 3, db: Session = Depends(get_db)):
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


# ─── alertas devolución ─────────────────────────────────────────────────────

@router.get("/alertas-devolucion")
def alertas_devolucion(db: Session = Depends(get_db)):
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


# ─── materiales en obra ─────────────────────────────────────────────────────

@router.get("/materiales-en-obra")
def materiales_en_obra(db: Session = Depends(get_db)):
    activos = db.query(Contrato).filter(Contrato.estado == "activo").all()
    conteo = {}
    for c in activos:
        for l in c.lineas:
            nombre = l.material.nombre if l.material else "?"
            conteo[nombre] = conteo.get(nombre, 0) + l.cantidad

    materiales = db.query(Material).filter(Material.activo == True).all()
    resultado = []
    for m in materiales:
        resultado.append({
            "material": m.nombre,
            "en_obra": conteo.get(m.nombre, 0),
            "ubicacion": m.ubicacion,
            "estado": m.estado,
        })
    resultado.sort(key=lambda x: -x["en_obra"])
    return resultado


# ─── ingresos por mes ───────────────────────────────────────────────────────

@router.get("/ingresos-por-mes")
def ingresos_por_mes(meses: int = 6, db: Session = Depends(get_db)):
    hoy = date.today()
    contratos = db.query(Contrato).all()

    buckets: dict[str, float] = {}
    cursor = date(hoy.year, hoy.month, 1)
    claves_ordenadas = []
    for i in range(meses):
        clave = f"{cursor.year}-{cursor.month:02d}"
        buckets[clave] = 0.0
        claves_ordenadas.append(clave)
        if cursor.month == 1:
            cursor = date(cursor.year - 1, 12, 1)
        else:
            cursor = date(cursor.year, cursor.month - 1, 1)

    for c in contratos:
        if not c.created_at or c.estado == "cancelado":
            continue
        clave = f"{c.created_at.year}-{c.created_at.month:02d}"
        if clave in buckets:
            buckets[clave] += c.total_con_iva or 0

    claves_ordenadas.reverse()
    return [{"mes": clave, "ingreso": round(buckets[clave], 2)} for clave in claves_ordenadas]


# ─── ingresos por periodo (con pagos) ──────────────────────────────────────

@router.get("/ingresos-periodo")
def ingresos_periodo(
    periodo: str = "mes",
    fecha_ini: Optional[str] = None,
    fecha_fin: Optional[str] = None,
    db: Session = Depends(get_db),
):
    ini, fin = _rango(periodo, fecha_ini, fecha_fin)

    # Pagos recibidos en el periodo
    pagos = (
        db.query(Pago)
        .filter(Pago.fecha >= ini, Pago.fecha <= fin)
        .all()
    )
    total_cobrado = sum(p.monto for p in pagos)

    # Contratos creados en el periodo
    contratos = (
        db.query(Contrato)
        .filter(
            Contrato.estado != "cancelado",
            func.date(Contrato.created_at) >= ini,
            func.date(Contrato.created_at) <= fin,
        )
        .all()
    )
    total_facturado = sum(c.total_con_iva or 0 for c in contratos)

    # Gastos del periodo
    gastos = (
        db.query(Gasto)
        .filter(Gasto.fecha >= ini, Gasto.fecha <= fin)
        .all()
    )
    total_gastos = sum(g.monto for g in gastos)

    # Métodos de pago
    metodos: dict[str, float] = {}
    for p in pagos:
        nombre = p.metodo_pago.nombre if p.metodo_pago else "Sin método"
        metodos[nombre] = metodos.get(nombre, 0) + p.monto

    # Semanas del periodo para tendencia
    semanas: dict[str, float] = {}
    cursor = ini
    while cursor <= fin:
        lunes = cursor - timedelta(days=cursor.weekday())
        clave = lunes.isoformat()
        semanas.setdefault(clave, 0.0)
        cursor += timedelta(days=1)

    for p in pagos:
        lunes = p.fecha - timedelta(days=p.fecha.weekday())
        clave = lunes.isoformat()
        if clave in semanas:
            semanas[clave] += p.monto

    tendencia_semanas = [
        {"semana": k, "cobrado": round(v, 2)}
        for k, v in sorted(semanas.items())
    ]

    return {
        "periodo": {"ini": ini.isoformat(), "fin": fin.isoformat()},
        "total_cobrado": round(total_cobrado, 2),
        "total_facturado": round(total_facturado, 2),
        "total_gastos": round(total_gastos, 2),
        "utilidad": round(total_cobrado - total_gastos, 2),
        "num_contratos": len(contratos),
        "num_pagos": len(pagos),
        "metodos_pago": [
            {"metodo": k, "monto": round(v, 2)}
            for k, v in sorted(metodos.items(), key=lambda x: -x[1])
        ],
        "tendencia_semanas": tendencia_semanas,
        "pagos": [
            {
                "folio": p.folio,
                "fecha": p.fecha.isoformat(),
                "contrato": p.contrato.folio if p.contrato else "",
                "cliente": p.contrato.cliente.nombre if p.contrato and p.contrato.cliente else "",
                "metodo": p.metodo_pago.nombre if p.metodo_pago else "",
                "monto": p.monto,
                "referencia": p.referencia or "",
            }
            for p in sorted(pagos, key=lambda x: x.fecha, reverse=True)
        ],
        "gastos": [
            {
                "id": g.id,
                "fecha": g.fecha.isoformat(),
                "concepto": g.concepto,
                "categoria": g.categoria,
                "monto": g.monto,
                "notas": g.notas or "",
            }
            for g in sorted(gastos, key=lambda x: x.fecha, reverse=True)
        ],
    }


# ─── CRUD gastos ────────────────────────────────────────────────────────────

class GastoCreate(BaseModel):
    fecha: date
    concepto: str
    monto: float
    categoria: str = "otros"
    notas: Optional[str] = None


@router.get("/gastos")
def listar_gastos(
    fecha_ini: Optional[str] = None,
    fecha_fin: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(Gasto).order_by(Gasto.fecha.desc())
    if fecha_ini:
        q = q.filter(Gasto.fecha >= date.fromisoformat(fecha_ini))
    if fecha_fin:
        q = q.filter(Gasto.fecha <= date.fromisoformat(fecha_fin))
    return [
        {"id": g.id, "fecha": g.fecha.isoformat(), "concepto": g.concepto,
         "categoria": g.categoria, "monto": g.monto, "notas": g.notas or ""}
        for g in q.all()
    ]


@router.post("/gastos", status_code=201)
def crear_gasto(data: GastoCreate, db: Session = Depends(get_db)):
    g = Gasto(**data.model_dump())
    db.add(g)
    db.commit()
    db.refresh(g)
    return {"id": g.id, "fecha": g.fecha.isoformat(), "concepto": g.concepto,
            "categoria": g.categoria, "monto": g.monto, "notas": g.notas or ""}


@router.put("/gastos/{gasto_id}")
def actualizar_gasto(gasto_id: int, data: GastoCreate, db: Session = Depends(get_db)):
    g = db.query(Gasto).filter(Gasto.id == gasto_id).first()
    if not g:
        raise HTTPException(status_code=404, detail="Gasto no encontrado")
    for k, v in data.model_dump().items():
        setattr(g, k, v)
    db.commit()
    db.refresh(g)
    return {"id": g.id, "fecha": g.fecha.isoformat(), "concepto": g.concepto,
            "categoria": g.categoria, "monto": g.monto, "notas": g.notas or ""}


@router.delete("/gastos/{gasto_id}")
def eliminar_gasto(gasto_id: int, db: Session = Depends(get_db)):
    g = db.query(Gasto).filter(Gasto.id == gasto_id).first()
    if not g:
        raise HTTPException(status_code=404, detail="Gasto no encontrado")
    db.delete(g)
    db.commit()
    return {"ok": True}


# ─── exportar Excel ─────────────────────────────────────────────────────────

@router.get("/exportar")
def exportar_excel(
    periodo: str = "mes",
    fecha_ini: Optional[str] = None,
    fecha_fin: Optional[str] = None,
    db: Session = Depends(get_db),
):
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
    except ImportError:
        raise HTTPException(status_code=500, detail="openpyxl no disponible")

    ini, fin = _rango(periodo, fecha_ini, fecha_fin)

    # ── datos ──
    pagos = db.query(Pago).filter(Pago.fecha >= ini, Pago.fecha <= fin).all()
    contratos = (
        db.query(Contrato)
        .filter(
            Contrato.estado != "cancelado",
            func.date(Contrato.created_at) >= ini,
            func.date(Contrato.created_at) <= fin,
        )
        .all()
    )
    gastos = db.query(Gasto).filter(Gasto.fecha >= ini, Gasto.fecha <= fin).all()

    wb = openpyxl.Workbook()

    naranja = "FF6B00"
    gris = "F2F2F2"
    hdr_font = Font(bold=True, color="FFFFFF")
    hdr_fill = PatternFill("solid", fgColor=naranja)
    sub_fill = PatternFill("solid", fgColor=gris)
    thin = Side(style="thin", color="CCCCCC")
    borde = Border(left=thin, right=thin, top=thin, bottom=thin)
    center = Alignment(horizontal="center")
    right_a = Alignment(horizontal="right")

    def _hdr(ws, row, cols):
        for ci, text in enumerate(cols, 1):
            c = ws.cell(row=row, column=ci, value=text)
            c.font = hdr_font
            c.fill = hdr_fill
            c.border = borde
            c.alignment = center

    def _autowidth(ws):
        for col in ws.columns:
            max_len = max((len(str(cell.value or "")) for cell in col), default=10)
            ws.column_dimensions[get_column_letter(col[0].column)].width = min(max_len + 4, 50)

    def _titulo(ws, texto, ncols):
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncols)
        c = ws.cell(row=1, column=1, value=texto)
        c.font = Font(bold=True, size=13, color=naranja)
        c.alignment = center
        ws.cell(row=2, column=1, value=f"Periodo: {ini} al {fin}").font = Font(italic=True, color="888888")
        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=ncols)

    # ── Hoja 1: Resumen ──
    ws = wb.active
    ws.title = "Resumen"
    total_cobrado = sum(p.monto for p in pagos)
    total_facturado = sum(c.total_con_iva or 0 for c in contratos)
    total_gastos_sum = sum(g.monto for g in gastos)
    _titulo(ws, "Resumen del periodo", 2)
    datos_resumen = [
        ("Contratos creados", len(contratos)),
        ("Pagos recibidos", len(pagos)),
        ("Total facturado (contratos)", round(total_facturado, 2)),
        ("Total cobrado (pagos)", round(total_cobrado, 2)),
        ("Total gastos", round(total_gastos_sum, 2)),
        ("Utilidad estimada", round(total_cobrado - total_gastos_sum, 2)),
    ]
    for ri, (k, v) in enumerate(datos_resumen, 3):
        ws.cell(row=ri, column=1, value=k).font = Font(bold=True)
        cell = ws.cell(row=ri, column=2, value=v)
        cell.alignment = right_a
        if isinstance(v, float):
            cell.number_format = '"$"#,##0.00'
        ws.cell(row=ri, column=1).fill = sub_fill if ri % 2 == 0 else PatternFill()
        ws.cell(row=ri, column=2).fill = sub_fill if ri % 2 == 0 else PatternFill()
    _autowidth(ws)

    # ── Hoja 2: Pagos ──
    ws2 = wb.create_sheet("Pagos")
    cols_p = ["Folio", "Fecha", "Contrato", "Cliente", "Método", "Referencia", "Monto"]
    _titulo(ws2, "Detalle de pagos recibidos", len(cols_p))
    _hdr(ws2, 3, cols_p)
    for ri, p in enumerate(sorted(pagos, key=lambda x: x.fecha), 4):
        row_data = [
            p.folio, str(p.fecha),
            p.contrato.folio if p.contrato else "",
            p.contrato.cliente.nombre if p.contrato and p.contrato.cliente else "",
            p.metodo_pago.nombre if p.metodo_pago else "",
            p.referencia or "",
            p.monto,
        ]
        for ci, val in enumerate(row_data, 1):
            cell = ws2.cell(row=ri, column=ci, value=val)
            cell.border = borde
            if ci == 7:
                cell.number_format = '"$"#,##0.00'
                cell.alignment = right_a
    # totales por método
    ws2.cell(row=len(pagos) + 5, column=1, value="Totales por método de pago").font = Font(bold=True)
    metodos: dict[str, float] = {}
    for p in pagos:
        nombre = p.metodo_pago.nombre if p.metodo_pago else "Sin método"
        metodos[nombre] = metodos.get(nombre, 0) + p.monto
    for ri, (nombre, monto) in enumerate(sorted(metodos.items(), key=lambda x: -x[1]), len(pagos) + 6):
        ws2.cell(row=ri, column=1, value=nombre).font = Font(bold=True)
        c = ws2.cell(row=ri, column=2, value=round(monto, 2))
        c.number_format = '"$"#,##0.00'
        c.alignment = right_a
    _autowidth(ws2)

    # ── Hoja 3: Contratos ──
    ws3 = wb.create_sheet("Contratos")
    cols_c = ["Folio", "Fecha", "Cliente", "Lugar obra", "Días", "Total s/IVA", "IVA", "Total c/IVA", "Estado"]
    _titulo(ws3, "Contratos del periodo", len(cols_c))
    _hdr(ws3, 3, cols_c)
    for ri, c in enumerate(sorted(contratos, key=lambda x: x.created_at or datetime.min), 4):
        row_data = [
            c.folio,
            str(c.created_at.date()) if c.created_at else "",
            c.cliente.nombre if c.cliente else "",
            c.lugar_obra or "",
            c.dias,
            c.total_diario_con_descuento or c.total_diario,
            c.iva or 0,
            c.total_con_iva or 0,
            c.estado,
        ]
        for ci, val in enumerate(row_data, 1):
            cell = ws3.cell(row=ri, column=ci, value=val)
            cell.border = borde
            if ci in (6, 7, 8):
                cell.number_format = '"$"#,##0.00'
                cell.alignment = right_a
    _autowidth(ws3)

    # ── Hoja 4: Gastos ──
    ws4 = wb.create_sheet("Gastos")
    cols_g = ["Fecha", "Concepto", "Categoría", "Monto", "Notas"]
    _titulo(ws4, "Gastos del periodo", len(cols_g))
    _hdr(ws4, 3, cols_g)
    for ri, g in enumerate(sorted(gastos, key=lambda x: x.fecha), 4):
        row_data = [str(g.fecha), g.concepto, g.categoria, g.monto, g.notas or ""]
        for ci, val in enumerate(row_data, 1):
            cell = ws4.cell(row=ri, column=ci, value=val)
            cell.border = borde
            if ci == 4:
                cell.number_format = '"$"#,##0.00'
                cell.alignment = right_a
    # total gastos
    total_row = len(gastos) + 4
    ws4.cell(row=total_row, column=3, value="TOTAL").font = Font(bold=True)
    tc = ws4.cell(row=total_row, column=4, value=round(total_gastos_sum, 2))
    tc.font = Font(bold=True)
    tc.number_format = '"$"#,##0.00'
    tc.alignment = right_a
    _autowidth(ws4)

    # ── Hoja 5: Tendencia semanal ──
    ws5 = wb.create_sheet("Tendencia semanal")
    semanas: dict[str, float] = {}
    cursor_d = ini
    while cursor_d <= fin:
        lunes = cursor_d - timedelta(days=cursor_d.weekday())
        semanas.setdefault(lunes.isoformat(), 0.0)
        cursor_d += timedelta(days=1)
    for p in pagos:
        lunes = p.fecha - timedelta(days=p.fecha.weekday())
        clave = lunes.isoformat()
        if clave in semanas:
            semanas[clave] += p.monto
    _titulo(ws5, "Cobros por semana", 2)
    _hdr(ws5, 3, ["Semana (lunes)", "Cobrado"])
    for ri, (sem, monto) in enumerate(sorted(semanas.items()), 4):
        ws5.cell(row=ri, column=1, value=sem).border = borde
        cell = ws5.cell(row=ri, column=2, value=round(monto, 2))
        cell.number_format = '"$"#,##0.00'
        cell.alignment = right_a
        cell.border = borde
    _autowidth(ws5)

    # ── stream ──
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    nombre_archivo = f"Reporte_ADN_{ini}_{fin}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{nombre_archivo}"'},
    )
