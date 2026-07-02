"""
Genera el contrato de renta rellenando el machote DOCX.
Usa python-docx para acceder a tablas/filas/celdas/runs con formato preservado.
"""
import shutil
from pathlib import Path
from datetime import date
from docx import Document

from app.services.numero_a_letra import numero_a_letra

TEMPLATE_PATH = Path(__file__).parent.parent.parent / "contrato_template.docx"
OUTPUT_DIR = Path(__file__).parent.parent.parent / "data" / "contratos"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

DIAS_ES = ["LUNES", "MARTES", "MIÉRCOLES", "JUEVES", "VIERNES", "SÁBADO", "DOMINGO"]
MESES_ES = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
             "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]


def fecha_larga(d: date) -> str:
    return f"{DIAS_ES[d.weekday()]} {d.day} DE {MESES_ES[d.month - 1]} DEL {d.year}"


def _run_valor(celda, idx_run: int, texto: str):
    """Actualiza el run en idx_run de la primera párrafo de la celda.
    Vacía todos los runs posteriores para limpiar valores divididos."""
    for para in celda.paragraphs:
        runs = para.runs
        if idx_run < len(runs):
            runs[idx_run].text = texto
            for r in runs[idx_run + 1:]:
                r.text = ""
            return
        idx_run -= len(runs)


def _consolidar_runs(celda, texto: str):
    """Pone todo el texto en el primer run y vacía los demás."""
    primer = True
    for para in celda.paragraphs:
        for run in para.runs:
            if primer:
                run.text = texto
                primer = False
            else:
                run.text = ""


def _set_celda(celda, texto: str):
    """Establece el texto completo de una celda (primer párrafo, primer run; limpia el resto)."""
    _consolidar_runs(celda, texto)


def _formatear_referencias(refs: list) -> str:
    partes = []
    for ref in refs[:2]:
        n = ref.get("nombre", "").upper()
        tel = ref.get("telefono", "")
        dire = ref.get("direccion", "")
        parte = n
        if tel:
            parte += f" TEL: {tel}"
        if dire:
            parte += f" DIR: {dire}"
        partes.append(parte)
    return ", ".join(partes)


def generar_contrato(contrato_data: dict) -> Path:
    """
    contrato_data keys:
      folio, cliente_nombre, cliente_telefono, cliente_domicilio, cliente_rfc,
      referencias: [{nombre, telefono, direccion}]  (hasta 2)
      lineas: [{material, cantidad, precio_unitario, total_diario, valor_convencional}]  (hasta 9)
      total_diario, total_con_iva, fecha_inicio (date), fecha_fin (date), dias,
      lugar_obra, personas_autorizadas, lugar_celebracion
    """
    folio = contrato_data["folio"]
    output_path = OUTPUT_DIR / f"contrato_{folio}.docx"
    shutil.copy2(TEMPLATE_PATH, output_path)

    doc = Document(str(output_path))
    t = doc.tables  # alias

    lineas    = contrato_data.get("lineas", [])
    refs      = contrato_data.get("referencias", [])
    total_iva = contrato_data.get("total_con_iva", 0)
    letra     = numero_a_letra(total_iva)
    fecha_ini: date = contrato_data["fecha_inicio"]
    fecha_fin: date = contrato_data["fecha_fin"]
    dias      = contrato_data["dias"]
    lugar_cel = contrato_data.get("lugar_celebracion", "ANDAMIOS Y DERIVADOS")

    # -----------------------------------------------------------------------
    # TABLA 0 — Cliente (1 celda por fila, runs: [etiqueta][valor])
    # -----------------------------------------------------------------------
    # Fila 0: ['CLIENTE', '; ', 'GILBERTO LOYA CASTILLO']  → run[2] = nombre
    _run_valor(t[0].rows[0].cells[0], 2, contrato_data["cliente_nombre"].upper())
    # Fila 1: ['TELEFONO:  ', '614-192-96-47']             → run[1] = tel
    _run_valor(t[0].rows[1].cells[0], 1, contrato_data.get("cliente_telefono", ""))
    # Fila 2: ['REFERENCIA:', 'JOEL...', '‬', '‬'] → run[1] = refs, run[2,3] vacíos
    _run_valor(t[0].rows[2].cells[0], 1, " " + _formatear_referencias(refs))

    # -----------------------------------------------------------------------
    # TABLA 1 — Domicilio cliente (runs: ['DOMICILIO:', 'valor'])
    # -----------------------------------------------------------------------
    _run_valor(t[1].rows[0].cells[0], 1, " " + contrato_data.get("cliente_domicilio", ""))

    # -----------------------------------------------------------------------
    # TABLA 5 — Materiales rentados
    # Fila 0: headers (no tocar)
    # Fila 1: 4 celdas, cada una con runs  [vacíos..., valor, vacío]
    #   → el run con valor es el run index 3 (runs 0-2 son vacíos, 3 = valor, 4 = vacío)
    # Filas 2-9: 4 celdas. Celdas 0-2 vacías, celda 3: runs[..., '$-' o '$  0.00', ...]
    # Fila 10: celda 2 (TOTALFINAL) y celda 3 (subtotal)
    # -----------------------------------------------------------------------
    MAX_FILAS_MAT = 9  # filas de datos (índices 1 a 9)

    for i in range(1, MAX_FILAS_MAT + 1):
        fila = t[5].rows[i]
        c0, c1, c2, c3 = fila.cells[0], fila.cells[1], fila.cells[2], fila.cells[3]
        if i - 1 < len(lineas):
            l = lineas[i - 1]
            nombre   = str(l.get("material", "")).upper()
            cantidad = str(int(l.get("cantidad", 1)))
            precio   = f"${float(l.get('precio_unitario', 0)):.2f}"
            total    = f"${float(l.get('total_diario', 0)):.2f}"
            # En fila 1 el run de valor está en posición 3; en filas 2-9 no hay runs con valor en c0-c2
            if i == 1:
                _run_valor(c0, 3, nombre)
                _run_valor(c1, 3, cantidad)
                _run_valor(c2, 3, precio)
                _run_valor(c3, 3, total)
            else:
                # Filas 2-9: escribir en el primer run disponible de cada celda vacía
                _consolidar_runs(c0, nombre)
                _consolidar_runs(c1, cantidad)
                _consolidar_runs(c2, precio)
                # Celda 3: tiene runs[..., '$-' o '$  0.00', ...]
                # Encontrar el run que contiene '$'
                _set_ultimo_run_con_dato(c3, total)
        else:
            # Limpiar fila vacía
            _set_celda(c0, "")
            _set_celda(c1, "")
            _set_celda(c2, "")
            _set_celda(c3, "")

    # Fila 10: totales — celda 2 contiene "TOTALFINAL: $$96.00 $$48.00"
    # Runs: ['TOTALFINAL', ':', ' ', '$', '', '', '', '$96.00', '']
    # → run[3] = '$', run[7] = valor total sin IVA → actualizar run[7] y vaciar runs extras
    total_sin_iva = contrato_data.get("total_diario", 0)
    _run_valor(t[5].rows[10].cells[2], 7, f"${total_iva:.2f}")
    _run_valor(t[5].rows[10].cells[3], 4, f"${total_sin_iva:.2f}")

    # -----------------------------------------------------------------------
    # TABLA 6 — Importe total con IVA + importe en letra
    # 1 celda: runs=['$96.00','(','SON','NOVENTA ','PESOS','00','/100',')']
    # → run[0] = total, run[2]='SON', run[3]=palabra1, run[4]=palabra2, etc.
    # Más fácil: consolidar todo el contenido en un solo run
    # -----------------------------------------------------------------------
    _consolidar_runs(t[6].rows[0].cells[0], f"${total_iva:.2f} (SON {letra})")

    # -----------------------------------------------------------------------
    # TABLA 7 — Fechas (3 celdas)
    # Celda 0: runs=['FECHA DE INICIO: ', 'LUNES 20...']   → run[1] = fecha inicio
    # Celda 1: runs=['FECHA DE TERMINACIÓN: ', 'MARTES...'] → run[1] = fecha fin
    # Celda 2: runs=['PERIODO: (DÍAS) ', '2']               → run[1] = días
    # -----------------------------------------------------------------------
    _run_valor(t[7].rows[0].cells[0], 1, fecha_larga(fecha_ini))
    _run_valor(t[7].rows[0].cells[1], 1, fecha_larga(fecha_fin))
    _run_valor(t[7].rows[0].cells[2], 1, str(dias))

    # -----------------------------------------------------------------------
    # TABLA 8 — Penalización por no devolución
    # Fila 1: 2 celdas: celda 0 = nombre, celda 1 runs=['$',' 6,616.00'] → run[1] = valor
    # Filas 2-9: 2 celdas: celda 0 vacía, celda 1 runs=['$','    0.00'] → run[1] = valor
    # Fila 10: total
    # -----------------------------------------------------------------------
    total_pen = 0.0
    for i in range(1, 10):
        if i >= len(t[8].rows):
            break
        fila = t[8].rows[i]
        c0, c1 = fila.cells[0], fila.cells[1]
        if i - 1 < len(lineas):
            l = lineas[i - 1]
            nombre   = str(l.get("material", "")).upper()
            val_unit = float(l.get("valor_convencional", 0))
            cantidad = int(l.get("cantidad", 1))
            val_conv = val_unit * cantidad
            total_pen += val_conv
            _consolidar_runs(c0, nombre)
            # Celda 1: runs=['$',' valor'] → actualizar run[1]
            _run_valor(c1, 1, f" {val_conv:,.2f}")  # run[0]='$', run[1]=valor
        else:
            _set_celda(c0, "")
            _set_celda(c1, "")

    # Fila 10 de penalización (última) — 2 celdas: 'TOTAL' y valor
    fila_total_pen = t[8].rows[-1]
    _run_valor(fila_total_pen.cells[1], 1, f" {total_pen:,.2f}")  # run[0]='$', run[1]=valor

    # -----------------------------------------------------------------------
    # TABLA 9 — Lugar de la obra
    # 1 celda: runs=['SNTE, SALIDA A JUÁREZ']
    # -----------------------------------------------------------------------
    _consolidar_runs(t[9].rows[0].cells[0], contrato_data.get("lugar_obra", ""))

    # -----------------------------------------------------------------------
    # TABLA 10 — Personas autorizadas
    # -----------------------------------------------------------------------
    _consolidar_runs(t[10].rows[0].cells[0], contrato_data.get("personas_autorizadas", ""))

    # -----------------------------------------------------------------------
    # TABLA 11 — Lugar y fecha de celebración (2 celdas)
    # Celda 0: runs=['LUGAR DE CELEBRACIÓN: ', 'ANDAMIOS Y DERIVADOS'] → run[1]
    # Celda 1: runs=['FECHA DE CELEBRACIÓN: ', 'LUNES 20 DE...']        → run[1]
    # -----------------------------------------------------------------------
    _run_valor(t[11].rows[0].cells[0], 1, lugar_cel)
    _run_valor(t[11].rows[0].cells[1], 1, fecha_larga(fecha_ini))

    # -----------------------------------------------------------------------
    # TABLA 14 — Pagaré: importe en la celda 2
    # Celda 2: runs=['$96.00'] → consolidar con nuevo valor
    # -----------------------------------------------------------------------
    _consolidar_runs(t[14].rows[0].cells[2], f"${total_iva:.2f}")

    # -----------------------------------------------------------------------
    # TABLA 15 — Pagaré: nombre / teléfono / domicilio / referencia
    # Fila 0: celda 1: runs=['/', 'GILBERTO LOYA CASTILLO'] → run[1] = nombre
    # Fila 1: celda 1: runs=['614-192-96-47']               → consolidar = tel
    # Fila 2: celda 1: runs=['C. 62...', '.']               → run[0] = domicilio, vaciar run[1]
    # Fila 3: celda 1: referencia
    # -----------------------------------------------------------------------
    _run_valor(t[15].rows[0].cells[1], 1, contrato_data["cliente_nombre"].upper())
    _consolidar_runs(t[15].rows[1].cells[1], contrato_data.get("cliente_telefono", ""))
    _run_valor(t[15].rows[2].cells[1], 0, contrato_data.get("cliente_domicilio", ""))
    if len(t[15].rows) > 3:
        _consolidar_runs(t[15].rows[3].cells[1], _formatear_referencias(refs))

    # -----------------------------------------------------------------------
    # TABLA 16 — Pagaré: fecha de suscripción
    # -----------------------------------------------------------------------
    _consolidar_runs(t[16].rows[0].cells[0], fecha_larga(fecha_ini))

    # -----------------------------------------------------------------------
    # TABLA 17 — Pagaré: importe $$  (1 celda, runs=['$','','','','$96.00',''])
    # → El '$' inicial es el símbolo fijo, run[4] = valor
    # -----------------------------------------------------------------------
    _run_valor(t[17].rows[0].cells[0], 4, f"${total_iva:.2f}")

    # -----------------------------------------------------------------------
    # TABLA 18 — Pagaré: importe en letra (runs fragmentados)
    # -----------------------------------------------------------------------
    _consolidar_runs(t[18].rows[0].cells[0], letra)

    # -----------------------------------------------------------------------
    # TABLA 19 — Pagaré: lugar y fecha de suscripción
    # Celda 1: runs=['LUNES 20 DE ENERO DEL 2025', 'Lateral Perif...']
    # → run[0] = fecha, run[1] en adelante = dirección fija (no tocar)
    # -----------------------------------------------------------------------
    _run_valor(t[19].rows[0].cells[1], 0, fecha_larga(fecha_ini))

    doc.save(str(output_path))
    return output_path


def _set_ultimo_run_con_dato(celda, texto: str):
    """Para celda 3 de filas 2-9 de la tabla de materiales:
    encuentra el run con '$' y lo actualiza."""
    for para in celda.paragraphs:
        for run in para.runs:
            if run.text.strip().startswith("$") or run.text.strip() == "-":
                run.text = texto
                return
    # Si no encontró ninguno con '$', pone en el primero disponible
    _consolidar_runs(celda, texto)
