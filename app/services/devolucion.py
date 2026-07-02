"""
Regla de gracia de devolución:
  El cliente puede regresar el material el siguiente día HÁBIL antes de las 10:00 AM
  sin que se le cobre un día extra.

  "Día hábil" = lunes a viernes (sin festivos, por ahora).

  Lógica:
    - fecha_limite = siguiente_dia_habil(fecha_fin_contrato) a las 10:00
    - Si fecha_devolucion <= fecha_limite → sin cargo extra
    - Si fecha_devolucion >  fecha_limite → cobrar 1 día extra
"""
from datetime import date, datetime, timedelta


def siguiente_dia_habil(d: date) -> date:
    """Retorna el siguiente día de lunes a viernes después de 'd'."""
    siguiente = d + timedelta(days=1)
    while siguiente.weekday() >= 5:  # 5=sábado, 6=domingo
        siguiente += timedelta(days=1)
    return siguiente


def calcular_devolucion(fecha_fin: date, fecha_devolucion: datetime) -> dict:
    """
    Evalúa si la devolución fue a tiempo o genera un día extra.

    Retorna:
      {
        "a_tiempo": bool,
        "dia_extra": bool,
        "fecha_limite": datetime,   # siguiente día hábil a las 10:00
        "mensaje": str
      }
    """
    sig_habil = siguiente_dia_habil(fecha_fin)
    fecha_limite = datetime(sig_habil.year, sig_habil.month, sig_habil.day, 10, 0, 0)

    a_tiempo = fecha_devolucion <= fecha_limite

    dia_semana = {0: "lunes", 1: "martes", 2: "miércoles", 3: "jueves",
                  4: "viernes", 5: "sábado", 6: "domingo"}

    nombre_dia = dia_semana[sig_habil.weekday()]
    limite_str = f"{nombre_dia} {sig_habil.day}/{sig_habil.month}/{sig_habil.year} a las 10:00 AM"

    if a_tiempo:
        mensaje = f"Devolución a tiempo. El límite era el {limite_str}."
    else:
        mensaje = f"Devolución tardía. El límite era el {limite_str}. Se cobra 1 día extra."

    return {
        "a_tiempo": a_tiempo,
        "dia_extra": not a_tiempo,
        "fecha_limite": fecha_limite.isoformat(),
        "siguiente_dia_habil": sig_habil.isoformat(),
        "mensaje": mensaje,
    }
