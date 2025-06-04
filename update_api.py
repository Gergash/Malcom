"""
Microservidor Flask que permite actualizar archivos críticos del proyecto
(Malcom/core/bot.py, form_parser.py) mediante una solicitud POST HTTP local.

Usado para integración con Make + GPT que genera código automáticamente.
"""

from flask import Flask, request, jsonify
import os

app = Flask(__name__)

# Directorio base donde están los archivos a actualizar
CORE_PATH = os.path.join(os.getcwd(), "core")

@app.route("/update", methods=["POST"])
def actualizar_codigo():
    data = request.get_json()

    nombre_archivo = data.get("archivo")
    contenido = data.get("contenido")

    if not nombre_archivo or not contenido:
        return jsonify({"status": "error", "mensaje": "Faltan campos 'archivo' o 'contenido'"}), 400

    if nombre_archivo not in ["bot.py", "form_parser.py"]:
        return jsonify({"status": "error", "mensaje": "Archivo no permitido"}), 403

    ruta = os.path.join(CORE_PATH, nombre_archivo)

    try:
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(contenido)
        return jsonify({"status": "ok", "mensaje": f"{nombre_archivo} actualizado correctamente."})
    except Exception as e:
        return jsonify({"status": "error", "mensaje": str(e)}), 500

@app.route("/status", methods=["GET"])
def verificar_estado():
    return jsonify({"status": "ok", "mensaje": "Flask está activo"}), 200

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000)
