"""Genera recibo de nómina (PDF) por empleado usando reportlab."""
from pathlib import Path
from datetime import date
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT

OUTPUT_DIR = Path(__file__).parent.parent.parent / "data" / "recibos_nomina"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

NARANJA = colors.HexColor("#C2410C")
GRIS = colors.HexColor("#6B7280")
GRIS_CLARO = colors.HexColor("#F3F4F6")
VERDE = colors.HexColor("#15803D")
ROJO = colors.HexColor("#DC2626")

MESES_ES = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
            "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]


def fecha_corta(d: date) -> str:
    return f"{d.day} DE {MESES_ES[d.month - 1]} DEL {d.year}"


def generar_recibo_nomina(nomina_data: dict, linea_data: dict, empleado_data: dict) -> Path:
    """
    nomina_data: folio, fecha_inicio(date), fecha_fin(date), tipo_periodo
    linea_data:  todos los campos de LineaNomina
    empleado_data: nombre, puesto, rfc, nss, salario_diario
    """
    folio_nomina = nomina_data["folio"]
    nombre_emp = empleado_data["nombre"].upper()
    folio_archivo = f"{folio_nomina}_{empleado_data['id']}"
    output_path = OUTPUT_DIR / f"recibo_{folio_archivo}.pdf"

    doc = SimpleDocTemplate(str(output_path), pagesize=letter,
                            topMargin=12*mm, bottomMargin=12*mm,
                            leftMargin=15*mm, rightMargin=15*mm)
    styles = getSampleStyleSheet()
    s_empresa = ParagraphStyle("Empresa", alignment=TA_CENTER, fontSize=14,
                                fontName="Helvetica-Bold", textColor=NARANJA)
    s_sub = ParagraphStyle("Sub", alignment=TA_CENTER, fontSize=9, textColor=GRIS)
    s_label = ParagraphStyle("Lbl", fontSize=8, textColor=GRIS)
    s_val = ParagraphStyle("Val", fontSize=9, fontName="Helvetica-Bold")
    s_seccion = ParagraphStyle("Sec", fontSize=9, fontName="Helvetica-Bold",
                                textColor=NARANJA, spaceBefore=6)
    s_firma = ParagraphStyle("Firma", alignment=TA_CENTER, fontSize=8, textColor=GRIS)

    story = []
    story.append(Paragraph("ANDAMIOS Y DERIVADOS DEL NORTE", s_empresa))
    story.append(Paragraph("RECIBO DE NÓMINA", s_sub))
    story.append(Spacer(1, 4*mm))
    story.append(HRFlowable(width="100%", thickness=1, color=NARANJA))
    story.append(Spacer(1, 4*mm))

    # Encabezado nomina
    enc = Table([
        [Paragraph("FOLIO NÓMINA", s_label), Paragraph("PERÍODO", s_label),
         Paragraph("TIPO", s_label)],
        [Paragraph(f"<b>{folio_nomina}</b>", s_val),
         Paragraph(f"{fecha_corta(nomina_data['fecha_inicio'])} — {fecha_corta(nomina_data['fecha_fin'])}", s_val),
         Paragraph(nomina_data["tipo_periodo"].upper(), s_val)],
    ], colWidths=[35*mm, 105*mm, 35*mm])
    enc.setStyle(TableStyle([("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    story.append(enc)
    story.append(Spacer(1, 3*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=GRIS_CLARO))
    story.append(Spacer(1, 3*mm))

    # Datos del empleado
    story.append(Paragraph("DATOS DEL EMPLEADO", s_seccion))
    emp = Table([
        [Paragraph("NOMBRE", s_label), Paragraph("PUESTO", s_label),
         Paragraph("RFC", s_label), Paragraph("NSS", s_label)],
        [Paragraph(nombre_emp, s_val),
         Paragraph(empleado_data.get("puesto", "—") or "—", s_val),
         Paragraph(empleado_data.get("rfc", "—") or "—", s_val),
         Paragraph(empleado_data.get("nss", "—") or "—", s_val)],
    ], colWidths=[60*mm, 50*mm, 35*mm, 30*mm])
    emp.setStyle(TableStyle([("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    story.append(emp)
    story.append(Spacer(1, 4*mm))

    # Desglose de percepciones y deducciones
    story.append(Paragraph("PERCEPCIONES Y DEDUCCIONES", s_seccion))
    story.append(Spacer(1, 2*mm))

    l = linea_data
    pago_extra = round(l.get("horas_extra", 0) * (l["salario_diario"] / 8) * 2, 2)
    filas_perc = [
        ["CONCEPTO", "DÍAS / HORAS", "IMPORTE"],
        [f"Salario ordinario ({l['dias_trabajados']} días × ${l['salario_diario']:.2f})",
         str(l["dias_trabajados"]), f"${l['salario_diario'] * l['dias_trabajados']:.2f}"],
    ]
    if l.get("horas_extra", 0) > 0:
        filas_perc.append([f"Horas extra ({l['horas_extra']} hrs al doble)",
                           str(l["horas_extra"]), f"${pago_extra:.2f}"])
    if l.get("otros_ingresos", 0) > 0:
        filas_perc.append(["Otros ingresos (bonos)", "", f"${l['otros_ingresos']:.2f}"])
    filas_perc.append(["TOTAL PERCEPCIONES", "", f"${l['salario_bruto']:.2f}"])

    filas_ded = [
        ["DEDUCCIÓN", "", "IMPORTE"],
        ["IMSS (cuota obrera 2.15%)", "", f"${l['imss_obrero']:.2f}"],
        ["ISR (Art. 96 LISR)", "", f"${l['isr']:.2f}"],
    ]
    if l.get("otras_deducciones", 0) > 0:
        filas_ded.append(["Otras deducciones", "", f"${l['otras_deducciones']:.2f}"])
    filas_ded.append(["TOTAL DEDUCCIONES", "", f"${l['imss_obrero'] + l['isr'] + l.get('otras_deducciones', 0):.2f}"])

    def _tabla_concepto(filas, color_total):
        t = Table(filas, colWidths=[115*mm, 25*mm, 35*mm])
        estilo = [
            ("BACKGROUND", (0, 0), (-1, 0), NARANJA),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("BACKGROUND", (0, -1), (-1, -1), color_total),
            ("TEXTCOLOR", (0, -1), (-1, -1), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E5E7EB")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, GRIS_CLARO]),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]
        t.setStyle(TableStyle(estilo))
        return t

    story.append(_tabla_concepto(filas_perc, VERDE))
    story.append(Spacer(1, 3*mm))
    story.append(_tabla_concepto(filas_ded, ROJO))
    story.append(Spacer(1, 5*mm))

    # Neto a pagar
    neto_tabla = Table([
        [Paragraph("NETO A PAGAR", ParagraphStyle("N", fontName="Helvetica-Bold",
                                                    fontSize=12, textColor=colors.white)),
         Paragraph(f"${l['salario_neto']:.2f}", ParagraphStyle("NV", fontName="Helvetica-Bold",
                                                                  fontSize=14, textColor=colors.white,
                                                                  alignment=TA_RIGHT))],
    ], colWidths=[120*mm, 55*mm])
    neto_tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NARANJA),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (0, 0), 8),
        ("RIGHTPADDING", (-1, 0), (-1, 0), 8),
    ]))
    story.append(neto_tabla)
    story.append(Spacer(1, 15*mm))

    # Firma
    firma = Table([
        ["_______________________________", "_______________________________"],
        [Paragraph("FIRMA DEL EMPLEADO", s_firma),
         Paragraph("AUTORIZADO POR ADN", s_firma)],
    ], colWidths=[87*mm, 87*mm])
    firma.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 1), (-1, 1), 4),
    ]))
    story.append(firma)

    doc.build(story)
    return output_path
