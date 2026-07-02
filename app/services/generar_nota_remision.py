"""Genera la Nota de Remisión en PDF (documento de entrega/recepción de material,
independiente del contrato legal). Usa reportlab."""
from pathlib import Path
from datetime import date
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT

OUTPUT_DIR = Path(__file__).parent.parent.parent / "data" / "notas_remision"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

DIAS_ES = ["LUNES", "MARTES", "MIÉRCOLES", "JUEVES", "VIERNES", "SÁBADO", "DOMINGO"]
MESES_ES = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
            "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]


def fecha_larga(d: date) -> str:
    return f"{DIAS_ES[d.weekday()]} {d.day} DE {MESES_ES[d.month - 1]} DEL {d.year}"


def generar_nota_remision(data: dict) -> Path:
    """
    data keys:
      folio, tipo ('entrega'|'devolucion'), fecha (date), contrato_folio,
      cliente_nombre, lugar_obra, entregado_por, recibido_por, observaciones,
      lineas: [{material, cantidad, estado_material}]
    """
    folio = data["folio"]
    output_path = OUTPUT_DIR / f"nota_{folio}.pdf"

    doc = SimpleDocTemplate(
        str(output_path), pagesize=letter,
        topMargin=18 * mm, bottomMargin=18 * mm, leftMargin=18 * mm, rightMargin=18 * mm,
    )
    styles = getSampleStyleSheet()
    titulo_style = ParagraphStyle("Titulo", parent=styles["Heading1"], alignment=TA_CENTER,
                                   textColor=colors.HexColor("#C2410C"), fontSize=16)
    sub_style = ParagraphStyle("Sub", parent=styles["Normal"], alignment=TA_CENTER, fontSize=10,
                                textColor=colors.HexColor("#666666"))
    label_style = ParagraphStyle("Label", parent=styles["Normal"], fontSize=9,
                                  textColor=colors.HexColor("#888888"))
    valor_style = ParagraphStyle("Valor", parent=styles["Normal"], fontSize=11)

    tipo_texto = "ENTREGA DE MATERIAL" if data["tipo"] == "entrega" else "DEVOLUCIÓN DE MATERIAL"

    story = []
    story.append(Paragraph("ANDAMIOS Y DERIVADOS DEL NORTE", titulo_style))
    story.append(Paragraph("NOTA DE REMISIÓN — " + tipo_texto, sub_style))
    story.append(Spacer(1, 10 * mm))

    # Encabezado: folio / fecha / contrato
    info_tabla = Table([
        [Paragraph("FOLIO", label_style), Paragraph("FECHA", label_style), Paragraph("CONTRATO RELACIONADO", label_style)],
        [Paragraph(f"<b>{folio}</b>", valor_style),
         Paragraph(fecha_larga(data["fecha"]), valor_style),
         Paragraph(data.get("contrato_folio", "—"), valor_style)],
    ], colWidths=[55 * mm, 75 * mm, 65 * mm])
    info_tabla.setStyle(TableStyle([
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 1), (-1, 1), 2),
    ]))
    story.append(info_tabla)
    story.append(Spacer(1, 6 * mm))

    # Cliente y lugar de obra
    datos_tabla = Table([
        [Paragraph("CLIENTE", label_style)],
        [Paragraph(f"<b>{data.get('cliente_nombre', '')}</b>", valor_style)],
        [Paragraph("LUGAR DE LA OBRA", label_style)],
        [Paragraph(data.get("lugar_obra", "—") or "—", valor_style)],
    ], colWidths=[195 * mm])
    datos_tabla.setStyle(TableStyle([("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    story.append(datos_tabla)
    story.append(Spacer(1, 8 * mm))

    # Tabla de materiales
    encabezados = ["Material", "Cantidad", "Estado"] if data["tipo"] == "devolucion" else ["Material", "Cantidad"]
    filas = [encabezados]
    for l in data.get("lineas", []):
        if data["tipo"] == "devolucion":
            filas.append([l["material"], str(l["cantidad"]), l.get("estado_material", "bueno").upper()])
        else:
            filas.append([l["material"], str(l["cantidad"])])

    col_widths = [120 * mm, 35 * mm, 40 * mm] if data["tipo"] == "devolucion" else [150 * mm, 45 * mm]
    mat_tabla = Table(filas, colWidths=col_widths, repeatRows=1)
    mat_tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#FB923C")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FFF7ED")]),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(mat_tabla)
    story.append(Spacer(1, 8 * mm))

    if data.get("observaciones"):
        story.append(Paragraph("OBSERVACIONES", label_style))
        story.append(Paragraph(data["observaciones"], valor_style))
        story.append(Spacer(1, 8 * mm))

    story.append(Spacer(1, 15 * mm))

    # Firmas
    firma_tabla = Table([
        ["_________________________________", "_________________________________"],
        [Paragraph(f"ENTREGA<br/>{data.get('entregado_por', '')}", label_style),
         Paragraph(f"RECIBE<br/>{data.get('recibido_por', '')}", label_style)],
    ], colWidths=[97 * mm, 97 * mm])
    firma_tabla.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 1), (-1, 1), 6),
    ]))
    story.append(firma_tabla)

    doc.build(story)
    return output_path
