"""Genera recibo de pago en PDF usando reportlab."""
from pathlib import Path
from datetime import date
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT

from app.services.numero_a_letra import numero_a_letra

OUTPUT_DIR = Path(__file__).parent.parent.parent / "data" / "recibos_pago"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

NARANJA = colors.HexColor("#C2410C")
GRIS = colors.HexColor("#6B7280")
GRIS_CLARO = colors.HexColor("#F3F4F6")
VERDE = colors.HexColor("#15803D")

MESES_ES = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
            "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]


def fecha_larga(d: date) -> str:
    return f"{d.day} DE {MESES_ES[d.month - 1]} DEL {d.year}"


def generar_recibo_pago(data: dict) -> Path:
    """
    data keys:
      folio, fecha (date), monto, metodo_pago, referencia (opt), notas (opt),
      contrato_folio, cliente_nombre, lugar_obra,
      total_contrato, total_pagado_previo, saldo_anterior, saldo_nuevo
    """
    folio = data["folio"]
    output_path = OUTPUT_DIR / f"recibo_{folio}.pdf"

    doc = SimpleDocTemplate(str(output_path), pagesize=letter,
                            topMargin=15*mm, bottomMargin=15*mm,
                            leftMargin=18*mm, rightMargin=18*mm)

    styles = getSampleStyleSheet()
    s_emp = ParagraphStyle("E", alignment=TA_CENTER, fontSize=15,
                            fontName="Helvetica-Bold", textColor=NARANJA)
    s_sub = ParagraphStyle("S", alignment=TA_CENTER, fontSize=9, textColor=GRIS)
    s_lbl = ParagraphStyle("L", fontSize=8, textColor=GRIS)
    s_val = ParagraphStyle("V", fontSize=10, fontName="Helvetica-Bold")
    s_sec = ParagraphStyle("Sc", fontSize=9, fontName="Helvetica-Bold",
                            textColor=NARANJA, spaceBefore=5)
    s_letra = ParagraphStyle("Lt", fontSize=9, textColor=GRIS, alignment=TA_CENTER)

    story = []
    story.append(Paragraph("ANDAMIOS Y DERIVADOS DEL NORTE", s_emp))
    story.append(Paragraph("RECIBO DE PAGO", s_sub))
    story.append(Spacer(1, 4*mm))
    story.append(HRFlowable(width="100%", thickness=1.5, color=NARANJA))
    story.append(Spacer(1, 5*mm))

    # Encabezado: folio / fecha
    enc = Table([
        [Paragraph("FOLIO", s_lbl), Paragraph("FECHA", s_lbl), Paragraph("CONTRATO", s_lbl)],
        [Paragraph(f"<b>{folio}</b>", s_val),
         Paragraph(fecha_larga(data["fecha"]), s_val),
         Paragraph(data["contrato_folio"], s_val)],
    ], colWidths=[40*mm, 90*mm, 45*mm])
    enc.setStyle(TableStyle([("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    story.append(enc)
    story.append(Spacer(1, 4*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=GRIS_CLARO))
    story.append(Spacer(1, 4*mm))

    # Cliente
    story.append(Paragraph("CLIENTE", s_lbl))
    story.append(Paragraph(data["cliente_nombre"].upper(), s_val))
    if data.get("lugar_obra"):
        story.append(Spacer(1, 2*mm))
        story.append(Paragraph("LUGAR DE OBRA", s_lbl))
        story.append(Paragraph(data["lugar_obra"], ParagraphStyle("LO", fontSize=9)))
    story.append(Spacer(1, 6*mm))

    # Monto del pago — caja destacada
    monto_tabla = Table([
        [Paragraph("MONTO RECIBIDO", ParagraphStyle("MRL", fontSize=10, fontName="Helvetica-Bold",
                                                      textColor=colors.white)),
         Paragraph(f"${data['monto']:,.2f}", ParagraphStyle("MRV", fontSize=16,
                                                               fontName="Helvetica-Bold",
                                                               textColor=colors.white,
                                                               alignment=TA_RIGHT))],
    ], colWidths=[110*mm, 65*mm])
    monto_tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NARANJA),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (0, 0), 10),
        ("RIGHTPADDING", (-1, 0), (-1, 0), 10),
    ]))
    story.append(monto_tabla)
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph(f"SON: {numero_a_letra(data['monto'])}", s_letra))
    story.append(Spacer(1, 5*mm))

    # Forma de pago
    story.append(Paragraph("FORMA DE PAGO", s_sec))
    pago_filas = [
        [Paragraph("Método", s_lbl), Paragraph(data["metodo_pago"].upper(), s_val)],
    ]
    if data.get("referencia"):
        pago_filas.append([Paragraph("Referencia / Folio", s_lbl),
                           Paragraph(data["referencia"], s_val)])
    if data.get("notas"):
        pago_filas.append([Paragraph("Notas", s_lbl),
                           Paragraph(data["notas"], ParagraphStyle("N", fontSize=9))])
    pago_t = Table(pago_filas, colWidths=[45*mm, 130*mm])
    pago_t.setStyle(TableStyle([("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story.append(pago_t)
    story.append(Spacer(1, 5*mm))

    # Estado de cuenta
    story.append(Paragraph("ESTADO DE CUENTA DEL CONTRATO", s_sec))
    saldo_filas = [
        ["CONCEPTO", "IMPORTE"],
        ["Total del contrato", f"${data['total_contrato']:,.2f}"],
        ["Pagos anteriores", f"${data['total_pagado_previo']:,.2f}"],
        ["Este pago", f"${data['monto']:,.2f}"],
        ["SALDO PENDIENTE", f"${data['saldo_nuevo']:,.2f}"],
    ]
    saldo_t = Table(saldo_filas, colWidths=[130*mm, 45*mm])
    saldo_t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NARANJA),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, -1), (-1, -1),
         VERDE if data["saldo_nuevo"] <= 0 else GRIS_CLARO),
        ("TEXTCOLOR", (0, -1), (-1, -1),
         colors.white if data["saldo_nuevo"] <= 0 else colors.HexColor("#1F2937")),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E5E7EB")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, GRIS_CLARO]),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(saldo_t)
    story.append(Spacer(1, 15*mm))

    # Firma
    firma = Table([
        ["_______________________________", "_______________________________"],
        [Paragraph("RECIBÍ DE CONFORMIDAD", ParagraphStyle("F", alignment=TA_CENTER, fontSize=8, textColor=GRIS)),
         Paragraph("AUTORIZADO — ANDAMIOS Y DERIVADOS DEL NORTE",
                   ParagraphStyle("F2", alignment=TA_CENTER, fontSize=8, textColor=GRIS))],
        [Paragraph(data["cliente_nombre"].upper(),
                   ParagraphStyle("FC", alignment=TA_CENTER, fontSize=8, fontName="Helvetica-Bold")),
         Paragraph("", styles["Normal"])],
    ], colWidths=[87*mm, 87*mm])
    firma.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 1), (-1, 1), 4),
        ("TOPPADDING", (0, 2), (-1, 2), 2),
    ]))
    story.append(firma)

    doc.build(story)
    return output_path
