"""
Módulo que interpreta instrucciones TUTO desde archivos sec-X.txt.
Convierte lenguaje natural en acciones estructuradas que el bot puede ejecutar.

Formato esperado:
- El archivo contiene HTML (opcional) seguido de un marcador "TUTO"
- Las líneas posteriores a "TUTO" describen acciones paso a paso
"""

def cargar_acciones_desde_archivo(ruta_txt):
    """
    Lee y transforma instrucciones TUTO en acciones automatizables para el bot.

    Args:
        ruta_txt (str): Ruta al archivo sec-X.txt

    Returns:
        list[dict]: Acciones estandarizadas con estructura:
            - type: 'click' | 'fill' | 'select' | 'goto' | 'wait'
            - selector: (CSS o texto Playwright)
            - value: (si aplica)
            - delay: segundos entre acciones
    """
    acciones = []
    with open(ruta_txt, "r", encoding="utf-8") as f:
        contenido = f.read()

    if "TUTO" not in contenido:
        raise ValueError("No se encontró la sección TUTO en el archivo.")

    instrucciones = contenido.split("TUTO")[1].strip().splitlines()

    for linea in instrucciones:
        linea = linea.strip().lower()
        if not linea:
            continue

        if "botón única" in linea:
            acciones.append({"type": "click", "selector": 'text=Única', "delay": 5})
        elif "moneda colombiana" in linea:
            acciones.append({"type": "select", "selector": "select", "value": "COL", "delay": 5})
        elif "50.000cop" in linea or "50.000" in linea:
            acciones.append({"type": "click", "selector": 'text=$50.000,00', "delay": 5})
        elif "click en donar" in linea:
            acciones.append({"type": "click", "selector": 'text=Donar', "delay": 5})
        elif "nombre" in linea:
            acciones.append({"type": "fill", "selector": 'input[name="first_name"]', "value": "$NOMBRE", "delay": 5})
        elif "apellido" in linea:
            acciones.append({"type": "fill", "selector": 'input[name="last_name"]', "value": "$APELLIDO", "delay": 5})
        elif "correo" in linea:
            acciones.append({"type": "fill", "selector": 'input[name="email"]', "value": "$EMAIL", "delay": 5})
        elif "documento" in linea:
            acciones.append({"type": "fill", "selector": 'input[name="document"]', "value": "$DOCUMENTO", "delay": 5})
        elif "número de la tarjeta" in linea:
            acciones.append({"type": "fill", "selector": 'input[name="cardnumber"]', "value": "$TARJETA", "delay": 5})
        elif "mes de expedición" in linea:
            acciones.append({"type": "fill", "selector": 'input[name="exp_month"]', "value": "09", "delay": 5})
        elif "año de vencimiento" in linea:
            acciones.append({"type": "fill", "selector": 'input[name="exp_year"]', "value": "2027", "delay": 5})
        elif "código de seguridad" in linea:
            acciones.append({"type": "fill", "selector": 'input[name="cvc"]', "value": "123", "delay": 5})
        elif "error de la tarjeta" in linea or "mensaje que te entregue" in linea:
            acciones.append({"type": "wait", "mensaje_selector": ".payment-error", "delay": 5})

    return acciones
