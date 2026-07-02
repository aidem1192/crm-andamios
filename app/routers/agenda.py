from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from datetime import date, timedelta
import calendar

from app.database import get_db, EventoAgenda, Contrato, NotaRemision, Pago, Cliente
from app.auth import log_audit

router = APIRouter()


# ─── Tipos y colores ──────────────────────────────────────────────────────────
TIPO_COLOR = {
    "entrega":      "#f97316",   # naranja
    "recoleccion":  "#8b5cf6",   # morado
    "vencimiento":  "#ef4444",   # rojo
    "pago":         "#10b981",   # verde
    "recordatorio": "#3b82f6",   # azul
    "otro":         "#6b7280",   # gris
}


def _color(tipo: str) -> str:
    return TIPO_COLOR.get(tipo, "#6b7280")


# ─── GET eventos de un mes ────────────────────────────────────────────────────

@router.get("/api/agenda/eventos")
def get_eventos(mes: str, db: Session = Depends(get_db)):
    """
    mes = "YYYY-MM"
    Devuelve eventos manuales + automáticos (contratos, notas, pagos pendientes).
    """
    try:
        year, month = int(mes[:4]), int(mes[5:7])
    except Exception:
        raise HTTPException(status_code=400, detail="Formato de mes inválido. Usa YYYY-MM")

    _, last_day = calendar.monthrange(year, month)
    fecha_ini = date(year, month, 1)
    fecha_fin = date(year, month, last_day)

    eventos = []

    # 1. Eventos manuales del mes
    manuales = db.query(EventoAgenda).filter(
        EventoAgenda.fecha >= fecha_ini,
        EventoAgenda.fecha <= fecha_fin,
    ).order_by(EventoAgenda.fecha, EventoAgenda.hora).all()

    for e in manuales:
        eventos.append({
            "id": e.id, "manual": True,
            "titulo": e.titulo, "fecha": str(e.fecha),
            "hora": e.hora or "",
            "tipo": e.tipo, "color": _color(e.tipo),
            "descripcion": e.descripcion or "",
            "contrato_id": e.contrato_id,
            "completado": e.completado,
        })

    # 2. Vencimientos de contrato (fecha_fin de contratos activos)
    contratos = db.query(Contrato).filter(
        Contrato.fecha_fin >= fecha_ini,
        Contrato.fecha_fin <= fecha_fin,
        Contrato.estado == "activo",
    ).all()
    for c in contratos:
        nombre_cliente = c.cliente.nombre if c.cliente else "—"
        saldo = round((c.total_con_iva or 0) - (c.total_pagado or 0), 2)
        desc = f"Folio {c.folio} — {nombre_cliente}"
        if saldo > 0:
            desc += f" · Saldo pendiente: ${saldo:,.2f}"
        eventos.append({
            "id": f"c_{c.id}", "manual": False,
            "titulo": f"Vence contrato {c.folio}",
            "fecha": str(c.fecha_fin), "hora": "",
            "tipo": "vencimiento", "color": _color("vencimiento"),
            "descripcion": desc,
            "contrato_id": c.id, "completado": False,
        })

    # 3. Notas de remisión del mes (entregas y devoluciones)
    notas = db.query(NotaRemision).filter(
        NotaRemision.fecha >= fecha_ini,
        NotaRemision.fecha <= fecha_fin,
    ).all()
    for n in notas:
        tipo_ev = "entrega" if n.tipo == "entrega" else "recoleccion"
        label = "Entrega" if n.tipo == "entrega" else "Recolección"
        cliente_nombre = n.contrato.cliente.nombre if (n.contrato and n.contrato.cliente) else "—"
        eventos.append({
            "id": f"n_{n.id}", "manual": False,
            "titulo": f"{label} — {n.folio}",
            "fecha": str(n.fecha), "hora": "",
            "tipo": tipo_ev, "color": _color(tipo_ev),
            "descripcion": f"Contrato {n.contrato.folio if n.contrato else '—'} · {cliente_nombre}",
            "contrato_id": n.contrato_id, "completado": False,
        })

    # Ordenar por fecha y hora
    eventos.sort(key=lambda e: (e["fecha"], e["hora"] or ""))
    return eventos


# ─── CRUD eventos manuales ────────────────────────────────────────────────────

class EventoIn(BaseModel):
    titulo: str
    fecha: date
    hora: Optional[str] = None
    tipo: str = "recordatorio"
    descripcion: Optional[str] = None
    contrato_id: Optional[int] = None


@router.post("/api/agenda/eventos", status_code=201)
def crear_evento(data: EventoIn, request: Request, db: Session = Depends(get_db)):
    if not data.titulo.strip():
        raise HTTPException(status_code=400, detail="El título es requerido")
    e = EventoAgenda(
        titulo=data.titulo.strip(),
        fecha=data.fecha,
        hora=data.hora or None,
        tipo=data.tipo,
        descripcion=data.descripcion,
        contrato_id=data.contrato_id,
    )
    db.add(e)
    db.flush()
    log_audit(db, request, "crear_evento", "agenda", e.id,
              f"Evento creado: {e.titulo} ({e.fecha})")
    db.commit()
    return {"id": e.id}


@router.put("/api/agenda/eventos/{evento_id}")
def editar_evento(evento_id: int, data: EventoIn, request: Request,
                  db: Session = Depends(get_db)):
    e = db.query(EventoAgenda).filter(EventoAgenda.id == evento_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    e.titulo = data.titulo.strip()
    e.fecha = data.fecha
    e.hora = data.hora or None
    e.tipo = data.tipo
    e.descripcion = data.descripcion
    e.contrato_id = data.contrato_id
    log_audit(db, request, "editar_evento", "agenda", evento_id,
              f"Evento editado: {e.titulo}")
    db.commit()
    return {"ok": True}


@router.patch("/api/agenda/eventos/{evento_id}/completar")
def completar_evento(evento_id: int, request: Request, db: Session = Depends(get_db)):
    e = db.query(EventoAgenda).filter(EventoAgenda.id == evento_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    e.completado = not e.completado
    db.commit()
    return {"completado": e.completado}


@router.delete("/api/agenda/eventos/{evento_id}")
def eliminar_evento(evento_id: int, request: Request, db: Session = Depends(get_db)):
    e = db.query(EventoAgenda).filter(EventoAgenda.id == evento_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    log_audit(db, request, "eliminar_evento", "agenda", evento_id,
              f"Evento eliminado: {e.titulo}")
    db.delete(e)
    db.commit()
    return {"ok": True}
