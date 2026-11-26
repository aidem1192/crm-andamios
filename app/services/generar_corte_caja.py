"""Genera el corte de caja semanal en PDF: total cobrado por metodo de pago,
detalle de cada pago de la semana, y espacio de firma para cuadrar y archivar."""
from pathlib import Path
from datetime import date
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable,
)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT

OUTPUT_DIR = Path(__file__).parent.parent.parent / "data" / "cortes_caja"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

NARANJA = colors.HexColor("#C2410C")
GRIS = colors.HexColor("#6B7280")
GRIS_CLARO = colors.HexColor("#F3F4F6")
VERDE = colors.HexColor("#15803D")
BLANCO = colors.white

MESES_ES = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
            "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]


def _fecha_corta(d: date) -> str:
    return f"{d.day:02d}/{d.month:02d}/{d.year}"


def generar_corte_caja(data: dict) -> Path:
    """
    data keys:
      empresa_nombre, lunes (date), domingo (date),
      metodos: [{metodo, monto}],
      pagos: [{folio, fecha, cliente, contrato, metodo, monto}],
      total_cobrado, total_gastos, elaboro (str, opcional), recibio (str, opcional)
    """
    lunes: date = data["lunes"]
    domingo: date = data["domingo"]
    folio_doc = f"CORTE-{lunes.isoformat()}"
    output_path = OUTPUT_DIR / f"{folio_doc}.pdf"

    doc = SimpleDocTemplate(str(output_path), pagesize=letter,
                            topMargin=15*mm, bottomMargin=15*mm,
                            leftMargin=18*mm, rightMargin=18*mm)

    s_emp = ParagraphStyle("E", alignment=TA_CENTER, fontSize=15,
                            fontName="Helvetica-Bold", textColor=NARANJA)
    s_sub = ParagraphStyle("S", alignment=TA_CENTER, fontSize=10,
                            fontName="Helvetica-Bold", textColor=GRIS)
    s_periodo = ParagraphStyle("P", alignment=TA_CENTER, fontSize=9, textColor=GRIS)
    s_sec = ParagraphStyle("Sc", fontSize=10, fontName="Helvetica-Bold", textColor=NARANJA, spaceBefore=4)
    s_firma = ParagraphStyle("F", fontSize=8.5, textColor=GRIS, alignment=TA_CENTER)

    story = []
    story.append(Paragraph(data.get("empresa_nombre", "ANDAMIOS Y DERIVADOS DEL NORTE").upper(), s_emp))
    story.append(Paragraph("CORTE DE CAJA SEMANAL", s_sub))
    story.append(Paragraph(f"Semana del {_fecha_corta(lunes)} al {_fecha_corta(domingo)}", s_periodo))
    story.append(Spacer(1, 4*mm))
    story.append(HRFlowable(width="100%", thickness=1.5, color=NARANJA))
    story.append(Spacer(1, 6*mm))

    # ── Resumen por método de pago ──────────────────────────────────────────
    story.append(Paragraph("TOTAL COBRADO POR MÉTODO DE PAGO", s_sec))
    story.append(Spacer(1, 2*mm))
    total_cobrado = data.get("total_cobrado", 0)
    filas_metodo = [[Paragraph("MÉTODO", ParagraphStyle("h", fontSize=8, textColor=BLANCO, fontName="Helvetica-Bold")),
                      Paragraph("MONTO", ParagraphStyle("h2", fontSize=8, textColor=BLANCO, fontName="Helvetica-Bold", alignment=TA_RIGHT)),
                      Paragraph("%", ParagraphStyle("h3", fontSize=8, textColor=BLANCO, fontName="Helvetica-Bold", alignment=TA_RIGHT))]]
    for m in data.get("metodos", []):
        pct = (m["monto"] / total_cobrado * 100) if total_cobrado else 0
        filas_metodo.append([
            Paragraph(m["metodo"], ParagraphStyle("c", fontSize=9)),
            Paragraph(f"${m['monto']:,.2f}", ParagraphStyle("c2", fontSize=9, alignment=TA_RIGHT)),
            Paragraph(f"{pct:.1f}%", ParagraphStyle("c3", fontSize=9, alignment=TA_RIGHT, textColor=GRIS)),
        ])
    tbl_metodo = Table(filas_metodo, colWidths=[90*mm, 45*mm, 25*mm])
    tbl_metodo.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NARANJA),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [BLANCO, GRIS_CLARO]),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E0E0E0")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(tbl_metodo)
    story.append(Spacer(1, 6*mm))

    # ── Detalle de pagos ─────────────────────────────────────────────────────
    story.append(Paragraph("DETALLE DE PAGOS DE LA SEMANA", s_sec))
    story.append(Spacer(1, 2*mm))
    pagos = data.get("pagos", [])
    if pagos:
        col_h = ["FOLIO", "FECHA", "CLIENTE", "CONTRATO", "MÉTODO", "MONTO"]
        filas_pagos = [[Paragraph(h, ParagraphStyle("ph", fontSize=7.5, textColor=BLANCO, fontName="Helvetica-Bold",
                                                       alignment=TA_RIGHT if h == "MONTO" else TA_LEFT)) for h in col_h]]
        for p in pagos:
            filas_pagos.append([
                Paragraph(p["folio"], ParagraphStyle("p1", fontSize=8)),
                Paragraph(_fecha_corta(p["fecha"]), ParagraphStyle("p2", fontSize=8)),
                Paragraph(p["cliente"], ParagraphStyle("p3", fontSize=8)),
                Paragraph(p["contrato"], ParagraphStyle("p4", fontSize=8, textColor=NARANJA)),
                Paragraph(p["metodo"], ParagraphStyle("p5", fontSize=8)),
                Paragraph(f"${p['monto']:,.2f}", ParagraphStyle("p6", fontSize=8, alignment=TA_RIGHT)),
            ])
        tbl_pagos = Table(filas_pagos, colWidths=[22*mm, 20*mm, 45*mm, 25*mm, 28*mm, 20*mm], repeatRows=1)
        tbl_pagos.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), GRIS),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [BLANCO, GRIS_CLARO]),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E0E0E0")),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(tbl_pagos)
    else:
        story.append(Paragraph("No se registraron pagos esta semana.", ParagraphStyle("np", fontSize=9, textColor=GRIS)))
    story.append(Spacer(1, 6*mm))

    # ── Totales ───────────────────────────────────────────────────────────────
    total_gastos = data.get("total_gastos", 0)
    neto = total_cobrado - total_gastos
    filas_tot = [
        ["Total cobrado", f"${total_cobrado:,.2f}"],
        ["Total gastos de la semana", f"- ${total_gastos:,.2f}"],
        ["NETO DE LA SEMANA", f"${neto:,.2f}"],
    ]
    tot_rows = []
    for label, val in filas_tot:
        es_total = label.startswith("NETO")
        tot_rows.append([
            Paragraph(label, ParagraphStyle("tl", fontSize=10 if es_total else 9,
                                              fontName="Helvetica-Bold" if es_total else "Helvetica",
                                              textColor=NARANJA if es_total else colors.black)),
            Paragraph(val, ParagraphStyle("tv", fontSize=10 if es_total else 9,
                                            fontName="Helvetica-Bold" if es_total else "Helvetica",
                                            alignment=TA_RIGHT,
                                            textColor=NARANJA if es_total else colors.black)),
        ])
    tbl_tot = Table(tot_rows, colWidths=[140*mm, 40*mm])
    tbl_tot.setStyle(TableStyle([
        ("LINEABOVE", (0, -1), (-1, -1), 1.2, NARANJA),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(tbl_tot)
    story.append(Spacer(1, 14*mm))

    # ── Firmas ────────────────────────────────────────────────────────────────
    firma_tbl = Table([
        ["_" * 32, "_" * 32],
        [Paragraph("Elaboró<br/>" + data.get("elaboro", ""), s_firma),
         Paragraph("Recibió conforme<br/>" + data.get("recibio", ""), s_firma)],
    ], colWidths=[85*mm, 85*mm])
    firma_tbl.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 1), (-1, 1), 4),
    ]))
    story.append(firma_tbl)

    doc.build(story)
    return output_path
