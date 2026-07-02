"""
Cálculo de IMSS e ISR para nómina.

IMSS obrero (cuota del trabajador, 2024):
  - Enfermedad y Maternidad (cuota obrera)  : 0.40 % del SBC
  - Invalidez y Vida                        : 0.625%
  - Cesantía y Vejez                        : 1.125%
  - Guarderías y Prest. Sociales            : gratis al obrero
  ─────────────────────────────────────────
  TOTAL CUOTA OBRERA ≈                       2.150 % del SBC
  (Aportación adicional excedente IMSS no aplica en salarios bajos;
   se omite para simplificación. Actualizar con tabla completa si se necesita.)

ISR (Art. 96 LISR 2025 — tabla mensual, escalada al período):
  Se calcula salario mensual equivalente, se aplica la tabla mensual
  y se re-escala al número de días del período.
"""

# Cuota obrera IMSS total (aprox.)
IMSS_OBRERO_PCT = 0.0215   # 2.15 % del salario bruto del período

# Tabla mensual ISR 2025 (Art. 96 LISR)
# (limite_inferior, limite_superior, cuota_fija, tasa_excedente)
ISR_TABLA_MENSUAL = [
    (0.01,       746.04,      0.00,       0.0192),
    (746.05,     6_332.05,    14.32,      0.0640),
    (6_332.06,   11_128.01,   371.83,     0.1088),
    (11_128.02,  12_935.82,   893.63,     0.1600),
    (12_935.83,  15_487.71,   1_182.88,   0.1792),
    (15_487.72,  31_236.49,   1_640.18,   0.2136),
    (31_236.50,  49_233.00,   5_004.12,   0.2352),
    (49_233.01,  93_993.90,   9_236.89,   0.3000),
    (93_993.91,  125_325.20,  22_665.17,  0.3200),
    (125_325.21, 375_975.61,  32_691.18,  0.3400),
    (375_975.62, float("inf"), 117_912.32, 0.3500),
]


def calcular_isr_mensual(salario_mensual: float) -> float:
    """Retorna el ISR mensual dado el salario mensual gravable."""
    if salario_mensual <= 0:
        return 0.0
    for li, ls, cf, tasa in ISR_TABLA_MENSUAL:
        if li <= salario_mensual <= ls:
            return round(cf + (salario_mensual - li) * tasa, 2)
    return 0.0


def calcular_linea_nomina(salario_diario: float, dias_trabajados: float,
                          horas_extra: float = 0, otros_ingresos: float = 0,
                          otras_deducciones: float = 0,
                          dias_periodo: int = 7) -> dict:
    """
    Calcula todos los campos de una línea de nómina.

    Args:
        salario_diario: salario base por día del empleado
        dias_trabajados: días efectivos en el período (faltas ya descontadas)
        horas_extra: horas extra trabajadas en el período
        otros_ingresos: bonos u otros ingresos adicionales
        otras_deducciones: descuentos adicionales (préstamos, etc.)
        dias_periodo: total de días naturales del período (para escalar ISR)

    Returns:
        dict con salario_bruto, imss_obrero, isr, otras_deducciones,
             otros_ingresos, salario_neto
    """
    # Pago de horas extra: las primeras 9 horas/semana se pagan al doble,
    # el resto al triple. Simplificación: todas al doble.
    valor_hora = salario_diario / 8
    pago_extra = round(horas_extra * valor_hora * 2, 2)

    salario_bruto = round(salario_diario * dias_trabajados + pago_extra + otros_ingresos, 2)

    imss_obrero = round(salario_bruto * IMSS_OBRERO_PCT, 2)

    # ISR: escalar al mes (30 días) → tabla mensual → re-escalar al período
    salario_mensual_equiv = salario_diario * 30
    isr_mensual = calcular_isr_mensual(salario_mensual_equiv)
    isr_periodo = round(isr_mensual * (dias_periodo / 30), 2)

    total_deducciones = round(imss_obrero + isr_periodo + otras_deducciones, 2)
    salario_neto = round(salario_bruto - total_deducciones, 2)

    return {
        "salario_diario": salario_diario,
        "salario_bruto": salario_bruto,
        "imss_obrero": imss_obrero,
        "isr": isr_periodo,
        "otras_deducciones": otras_deducciones,
        "otros_ingresos": otros_ingresos,
        "salario_neto": max(salario_neto, 0),
    }
