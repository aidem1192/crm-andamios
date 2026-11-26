"""
Cálculo de saldo pendiente de un contrato.

Regla de negocio: mientras el material NO haya sido devuelto por completo, la
deuda sigue acumulándose día con día a la tarifa diaria del contrato (no se
queda fija en el cobro de un solo día). Si ya se devolvió todo, el conteo se
detiene en la fecha real de devolución, no sigue sumando después.

monto_devengado = (días transcurridos desde el inicio hasta el corte) * tarifa_diaria
                   + suma de cargos extra (daños, reposiciones, etc.)
saldo_pendiente = monto_devengado - total pagado (hasta el corte)
"""
from datetime import date


def calcular_saldo(contrato, hasta: date | None = None, excluir_pago_id: int | None = None) -> dict:
    fecha_corte = hasta or (contrato.fecha_devolucion.date() if contrato.fecha_devolucion else date.today())
    dias = max(1, (fecha_corte - contrato.fecha_inicio).days + 1)
    tarifa = contrato.total_con_iva or 0
    cargos = sum(ce.monto for ce in contrato.cargos_extra)
    monto_devengado = round(dias * tarifa + cargos, 2)

    total_pagado = round(
        sum(p.monto for p in contrato.pagos if p.id != excluir_pago_id and p.fecha <= fecha_corte), 2
    )
    saldo = round(monto_devengado - total_pagado, 2)

    return {
        "dias_devengados": dias,
        "monto_devengado": monto_devengado,
        "total_pagado": total_pagado,
        "saldo_pendiente": saldo,
    }


def estado_pago_de(saldo_pendiente: float, total_pagado: float) -> str:
    if saldo_pendiente <= 0:
        return "pagado"
    if total_pagado > 0:
        return "parcial"
    return "pendiente"
