"""Genera cotización en PDF con membrete institucional, logo y diseño profesional."""
from pathlib import Path
from datetime import date, timedelta
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import mm, cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
    HRFlowable, Image, KeepTogether,
)

OUTPUT_DIR = Path(__file__).parent.parent.parent / "data" / "cotizaciones"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

ORANGE   = colors.HexColor("#E05A00")
DARK     = colors.HexColor("#1A1A1A")
GRAY     = colors.HexColor("#666666")
LGRAY    = colors.HexColor("#F5F5F5")
LORANGE  = colors.HexColor("#FFF0E6")
WHITE    = colors.white
BLACK    = colors.black

MESES = ["enero","febrero","marzo","abril","mayo","junio",
         "julio","agosto","septiembre","octubre","noviembre","diciembre"]


def fecha_larga(d: date) -> str:
    return f"{d.day} de {MESES[d.month-1]} de {d.year}"


def generar_cotizacion_pdf(cot, cfg=None) -> Path:
    folio = cot.folio
    output_path = OUTPUT_DIR / f"cotizacion_{folio}.pdf"

    # Datos empresa
    empresa_nombre = (cfg and cfg.nombre) or "Andamios y Derivados del Norte"
    empresa_rfc    = (cfg and cfg.rfc) or ""
    empresa_dir    = (cfg and cfg.domicilio) or ""
    empresa_tel    = (cfg and cfg.telefono) or ""
    empresa_email  = (cfg and cfg.email) or ""
    logo_path      = None
    if cfg and cfg.logo_path:
        lp = Path(__file__).parent.parent.parent / "data" / "uploads" / cfg.logo_path
        if lp.exists():
            logo_path = str(lp)

    doc = SimpleDocTemplate(
        str(output_path), pagesize=letter,
        topMargin=15*mm, bottomMargin=20*mm,
        leftMargin=18*mm, rightMargin=18*mm,
    )

    styles = getSampleStyleSheet()
    W = letter[0] - 36*mm  # ancho útil

    def s(name, **kw):
        base = styles.get(name, styles["Normal"])
        kw.setdefault("fontName", "Helvetica")
        return ParagraphStyle(name + str(id(kw)), parent=base, **kw)

    story = []

    # ── MEMBRETE ──────────────────────────────────────────────────────────────
    logo_cell = ""
    if logo_path:
        try:
            logo_cell = Image(logo_path, width=40*mm, height=18*mm, kind="proportional")
        except Exception:
            logo_cell = ""

    empresa_info = [
        Paragraph(f"<b>{empresa_nombre.upper()}</b>",
                  s("Normal", fontSize=13, textColor=ORANGE, leading=16)),
    ]
    if empresa_rfc:
        empresa_info.append(Paragraph(f"RFC: {empresa_rfc}",
                  s("Normal", fontSize=8, textColor=GRAY, leading=11)))
    if empresa_dir:
        empresa_info.append(Paragraph(empresa_dir,
                  s("Normal", fontSize=8, textColor=GRAY, leading=11)))
    contacto = "  |  ".join(filter(None, [empresa_tel, empresa_email]))
    if contacto:
        empresa_info.append(Paragraph(contacto,
                  s("Normal", fontSize=8, textColor=GRAY, leading=11)))

    folio_block = [
        Paragraph("COTIZACIÓN", s("Normal", fontSize=20, textColor=ORANGE,
                                   alignment=TA_RIGHT, leading=24, fontName="Helvetica-Bold")),
        Paragraph(folio, s("Normal", fontSize=13, textColor=DARK,
                            alignment=TA_RIGHT, leading=16, fontName="Helvetica-Bold")),
        Spacer(1, 3*mm),
        Paragraph(f"Fecha: {fecha_larga(cot.fecha)}",
                  s("Normal", fontSize=8, textColor=GRAY, alignment=TA_RIGHT)),
        Paragraph(f"Vigencia: {cot.vigencia_dias} días a partir de esta fecha",
                  s("Normal", fontSize=8, textColor=GRAY, alignment=TA_RIGHT)),
    ]

    header_table = Table(
        [[logo_cell or empresa_info[0],  folio_block]] if not logo_cell else
        [[[logo_cell, *empresa_info[1:]], folio_block]],
        colWidths=[W * 0.58, W * 0.42],
    )
    # Rebuild properly
    col1 = empresa_info
    col2 = folio_block
    header_table = Table([[col1, col2]], colWidths=[W * 0.58, W * 0.42])
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))

    if logo_path:
        try:
            img = Image(logo_path, width=40*mm, height=18*mm, kind="proportional")
            logo_and_name = Table([[img, empresa_info]], colWidths=[42*mm, W*0.58 - 42*mm])
            logo_and_name.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]))
            header_table = Table([[logo_and_name, col2]], colWidths=[W * 0.58, W * 0.42])
            header_table.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]))
        except Exception:
            pass

    story.append(header_table)
    story.append(Spacer(1, 3*mm))
    story.append(HRFlowable(width="100%", thickness=2, color=ORANGE, spaceAfter=4*mm))

    # ── DATOS DEL CLIENTE ────────────────────────────────────────────────────
    estado_color = {
        "borrador":  colors.HexColor("#888888"),
        "enviada":   colors.HexColor("#1565C0"),
        "aceptada":  colors.HexColor("#2E7D32"),
        "rechazada": colors.HexColor("#C62828"),
    }.get(cot.estado, GRAY)
    estado_label = {
        "borrador":  "BORRADOR",
        "enviada":   "ENVIADA",
        "aceptada":  "ACEPTADA ✓",
        "rechazada": "RECHAZADA",
    }.get(cot.estado, cot.estado.upper())

    cliente_lines = [
        Paragraph("<b>CLIENTE</b>",
                  s("Normal", fontSize=7, textColor=GRAY, fontName="Helvetica-Bold")),
        Paragraph(cot.cliente_nombre,
                  s("Normal", fontSize=12, textColor=DARK, leading=15, fontName="Helvetica-Bold")),
    ]
    if cot.cliente_telefono:
        cliente_lines.append(Paragraph(f"Tel: {cot.cliente_telefono}",
                  s("Normal", fontSize=8, textColor=GRAY)))
    if cot.cliente_domicilio:
        cliente_lines.append(Paragraph(cot.cliente_domicilio,
                  s("Normal", fontSize=8, textColor=GRAY)))
    if cot.cliente_rfc:
        cliente_lines.append(Paragraph(f"RFC: {cot.cliente_rfc}",
                  s("Normal", fontSize=8, textColor=GRAY)))
    if cot.lugar_obra:
        cliente_lines.append(Paragraph(f"Lugar de la obra: {cot.lugar_obra}",
                  s("Normal", fontSize=8, textColor=GRAY)))

    estado_block = [
        Paragraph("ESTADO",
                  s("Normal", fontSize=7, textColor=GRAY,
                    alignment=TA_RIGHT, fontName="Helvetica-Bold")),
        Paragraph(estado_label,
                  s("Normal", fontSize=11, textColor=estado_color,
                    alignment=TA_RIGHT, fontName="Helvetica-Bold")),
    ]

    cliente_table = Table([[cliente_lines, estado_block]], colWidths=[W * 0.7, W * 0.3])
    cliente_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LGRAY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, -1), 6),
        ("RIGHTPADDING", (-1, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ROUNDEDCORNERS", [3]),
    ]))
    story.append(cliente_table)
    story.append(Spacer(1, 5*mm))

    # ── TABLA DE CONCEPTOS ───────────────────────────────────────────────────
    story.append(Paragraph("CONCEPTOS Y PRECIOS",
                 s("Normal", fontSize=8, textColor=ORANGE,
                   fontName="Helvetica-Bold", spaceAfter=2)))

    col_w = [W * 0.10, W * 0.46, W * 0.10, W * 0.17, W * 0.17]
    tdata = [[
        Paragraph("TIPO", s("Normal", fontSize=8, textColor=WHITE,
                             fontName="Helvetica-Bold", alignment=TA_CENTER)),
        Paragraph("DESCRIPCIÓN", s("Normal", fontSize=8, textColor=WHITE, fontName="Helvetica-Bold")),
        Paragraph("CANT.", s("Normal", fontSize=8, textColor=WHITE,
                              fontName="Helvetica-Bold", alignment=TA_CENTER)),
        Paragraph("P. UNIT.", s("Normal", fontSize=8, textColor=WHITE,
                                 fontName="Helvetica-Bold", alignment=TA_RIGHT)),
        Paragraph("TOTAL", s("Normal", fontSize=8, textColor=WHITE,
                              fontName="Helvetica-Bold", alignment=TA_RIGHT)),
    ]]

    tipo_label = {"material": "Material", "servicio": "Servicio"}
    for i, l in enumerate(cot.lineas):
        bg = WHITE if i % 2 == 0 else LGRAY
        tdata.append([
            Paragraph(tipo_label.get(l.tipo, l.tipo),
                      s("Normal", fontSize=8, textColor=GRAY, alignment=TA_CENTER)),
            Paragraph(l.descripcion, s("Normal", fontSize=9, textColor=DARK)),
            Paragraph(f"{l.cantidad:g}", s("Normal", fontSize=9, textColor=DARK, alignment=TA_CENTER)),
            Paragraph(f"${l.precio_unitario:,.2f}", s("Normal", fontSize=9, textColor=DARK, alignment=TA_RIGHT)),
            Paragraph(f"${l.total_linea:,.2f}", s("Normal", fontSize=9, textColor=DARK, alignment=TA_RIGHT)),
        ])

    lineas_table = Table(tdata, colWidths=col_w, repeatRows=1)
    ts = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ORANGE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LGRAY]),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E0E0E0")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ])
    lineas_table.setStyle(ts)
    story.append(lineas_table)
    story.append(Spacer(1, 4*mm))

    # ── TOTALES ──────────────────────────────────────────────────────────────
    totales_data = []
    totales_data.append(["Subtotal", f"${cot.subtotal:,.2f}"])
    if cot.descuento_pct > 0:
        totales_data.append([f"Descuento ({cot.descuento_pct:.1f}%)", f"- ${cot.descuento_monto:,.2f}"])
    if cot.incluye_iva:
        totales_data.append(["IVA (16%)", f"${cot.iva:,.2f}"])
    totales_data.append(["TOTAL", f"${cot.total:,.2f}"])

    def tot_p(text, bold=False, right=False):
        return Paragraph(text, s("Normal", fontSize=9 if not bold else 11,
                                  textColor=ORANGE if bold else DARK,
                                  fontName="Helvetica-Bold" if bold else "Helvetica",
                                  alignment=TA_RIGHT if right else TA_LEFT))

    tot_rows = []
    for i, (label, val) in enumerate(totales_data):
        is_total = (label == "TOTAL")
        tot_rows.append([tot_p(label, bold=is_total), tot_p(val, bold=is_total, right=True)])

    tot_table = Table(tot_rows, colWidths=[W * 0.75, W * 0.25])
    tot_style = TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEABOVE", (0, -1), (-1, -1), 1.5, ORANGE),
        ("BACKGROUND", (0, -1), (-1, -1), LORANGE),
    ])
    tot_table.setStyle(tot_style)
    story.append(tot_table)
    story.append(Spacer(1, 5*mm))

    # ── NOTAS ────────────────────────────────────────────────────────────────
    if cot.notas:
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#DDDDDD"), spaceAfter=3*mm))
        story.append(Paragraph("<b>Notas y condiciones:</b>",
                     s("Normal", fontSize=8, textColor=GRAY, fontName="Helvetica-Bold")))
        story.append(Paragraph(cot.notas,
                     s("Normal", fontSize=8, textColor=DARK, leading=12)))
        story.append(Spacer(1, 3*mm))

    # ── CONDICIONES GENERALES ────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#DDDDDD"), spaceAfter=3*mm))
    condiciones = [
        f"• Esta cotización tiene una vigencia de <b>{cot.vigencia_dias} días</b> a partir de su fecha de emisión.",
        "• Los precios están expresados en pesos mexicanos (MXN).",
        "• El inicio del arrendamiento queda sujeto a la disponibilidad del material al momento de confirmar.",
        "• Para formalizar el servicio se requiere firma del contrato correspondiente.",
    ]
    for cond in condiciones:
        story.append(Paragraph(cond, s("Normal", fontSize=7.5, textColor=GRAY, leading=11, spaceAfter=1)))
    story.append(Spacer(1, 8*mm))

    # ── FIRMA ────────────────────────────────────────────────────────────────
    firma_table = Table([
        ["_" * 35, "_" * 35],
        [Paragraph("Autorizado por\n" + empresa_nombre,
                   s("Normal", fontSize=7.5, textColor=GRAY, alignment=TA_CENTER)),
         Paragraph("Aceptado por\n" + cot.cliente_nombre,
                   s("Normal", fontSize=7.5, textColor=GRAY, alignment=TA_CENTER))],
    ], colWidths=[W * 0.5, W * 0.5])
    firma_table.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 1), (-1, 1), 4),
    ]))
    story.append(firma_table)

    # ── PIE DE PÁGINA (via onFirstPage/onLaterPages) ─────────────────────────
    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(ORANGE)
        canvas.setLineWidth(1)
        canvas.line(18*mm, 14*mm, letter[0] - 18*mm, 14*mm)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(GRAY)
        pie = "  |  ".join(filter(None, [empresa_nombre, empresa_rfc, empresa_tel, empresa_email]))
        canvas.drawCentredString(letter[0] / 2, 9*mm, pie)
        canvas.drawRightString(letter[0] - 18*mm, 9*mm, f"Pág. {doc.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return output_path
