"""
Módulo para leer archivos de datos utilizados por el bot:
- TTCA.txt: contiene los números de tarjetas de crédito a probar
- dummies.txt: contiene datos personales simulados para llenar formularios

Formato esperado para `dummies.txt`:
    nombre|apellido|email|telefono|documento
    Ejemplo:
    Juan|Pérez|juan.perez@mail.com|3123456789|1020304050
"""

def cargar_tarjetas(ruta):
    """
    Carga una lista de tarjetas desde un archivo de texto plano.
    Cada línea debe contener una tarjeta.

    Args:
        ruta (str): Ruta al archivo TTCA.txt

    Returns:
        list[str]: Lista de tarjetas como strings
    """
    tarjetas = []
    with open(ruta, "r", encoding="utf-8") as f:
        for linea in f:
            tarjeta = linea.strip()
            if tarjeta:
                tarjetas.append(tarjeta)
    return tarjetas


def cargar_dummies(ruta):
    """
    Carga una lista de diccionarios con datos simulados desde dummies.txt

    Args:
        ruta (str): Ruta al archivo dummies.txt

    Returns:
        list[dict]: Lista de diccionarios con claves:
            - nombre
            - apellido
            - email
            - telefono
            - documento
    """
    dummies = []
    with open(ruta, "r", encoding="utf-8") as f:
        for linea in f:
            partes = linea.strip().split("|")
            if len(partes) != 5:
                continue  # Formato incorrecto
            nombre, apellido, email, telefono, documento = partes
            dummies.append({
                "nombre": nombre,
                "apellido": apellido,
                "email": email,
                "telefono": telefono,
                "documento": documento
            })
    return dummies
