"""Convierte un importe numérico a su representación en letra (pesos mexicanos)."""

UNIDADES = ["", "UN", "DOS", "TRES", "CUATRO", "CINCO", "SEIS", "SIETE", "OCHO", "NUEVE",
             "DIEZ", "ONCE", "DOCE", "TRECE", "CATORCE", "QUINCE", "DIECISÉIS", "DIECISIETE",
             "DIECIOCHO", "DIECINUEVE"]
DECENAS = ["", "DIEZ", "VEINTE", "TREINTA", "CUARENTA", "CINCUENTA", "SESENTA", "SETENTA", "OCHENTA", "NOVENTA"]
CENTENAS = ["", "CIENTO", "DOSCIENTOS", "TRESCIENTOS", "CUATROCIENTOS", "QUINIENTOS",
             "SEISCIENTOS", "SETECIENTOS", "OCHOCIENTOS", "NOVECIENTOS"]


def _tres_digitos(n: int) -> str:
    if n == 0:
        return ""
    if n == 100:
        return "CIEN"
    centena = n // 100
    resto = n % 100
    partes = []
    if centena:
        partes.append(CENTENAS[centena])
    if resto < 20:
        if resto > 0:
            partes.append(UNIDADES[resto])
    else:
        decena = resto // 10
        unidad = resto % 10
        if unidad == 0:
            partes.append(DECENAS[decena])
        else:
            partes.append(f"{DECENAS[decena]} Y {UNIDADES[unidad]}")
    return " ".join(partes)


def numero_a_letra(monto: float) -> str:
    """Retorna ej: 'NOVENTA Y SEIS PESOS 00/100 M.N.'"""
    entero = int(monto)
    centavos = round((monto - entero) * 100)

    if entero == 0:
        letra = "CERO"
    elif entero < 1000:
        letra = _tres_digitos(entero)
    elif entero < 2000:
        resto = _tres_digitos(entero % 1000)
        letra = f"MIL {resto}".strip() if resto else "MIL"
    elif entero < 1_000_000:
        miles = entero // 1000
        resto = entero % 1000
        s_miles = _tres_digitos(miles)
        s_resto = _tres_digitos(resto)
        letra = f"{s_miles} MIL {s_resto}".strip() if s_resto else f"{s_miles} MIL"
    else:
        millones = entero // 1_000_000
        resto = entero % 1_000_000
        s_mill = _tres_digitos(millones)
        s_resto_miles = ""
        if resto >= 1000:
            miles = resto // 1000
            s_miles = _tres_digitos(miles)
            s_resto2 = _tres_digitos(resto % 1000)
            s_resto_miles = f"{s_miles} MIL {s_resto2}".strip() if s_resto2 else f"{s_miles} MIL"
        elif resto > 0:
            s_resto_miles = _tres_digitos(resto)
        sufijo = "MILLONES" if millones > 1 else "MILLÓN"
        letra = f"{s_mill} {sufijo} {s_resto_miles}".strip()

    return f"{letra} PESOS {centavos:02d}/100 M.N."
