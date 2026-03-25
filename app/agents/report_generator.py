"""
report_generator.py: lectura de esquema, PDF (fpdf2) y Excel avanzado (pandas + xlsxwriter).
Separado de analyst_agent.py para mantener la responsabilidad de cada módulo acotada.
"""
import datetime
import os
from typing import Optional, Tuple

import pandas as pd
from fpdf import FPDF


_DATA_EXTENSIONS = (".csv", ".xlsx", ".xls")


def _read_schema_sample(path: str) -> Tuple[pd.DataFrame, Optional[str]]:
    """Muestra de 2 filas para esquema. Soporta CSV (varios encodings) y Excel."""
    path_lower = path.lower()
    if path_lower.endswith((".xlsx", ".xls")):
        return pd.read_excel(path, nrows=2), None
    for encoding in ("utf-8", "latin-1", "cp1252", "iso-8859-1"):
        try:
            return pd.read_csv(path, nrows=2, encoding=encoding), encoding
        except (UnicodeDecodeError, Exception):
            continue
    return pd.read_csv(path, nrows=2, encoding="latin-1"), "latin-1"


def generar_reporte_pdf(
    texto_contenido: str,
    ruta_salida: str = "reporte_final.pdf",
    ruta_grafica: Optional[str] = None,
) -> None:
    """
    Crea un PDF A4 con cabecera/pie de página usando fpdf2.
    Si existe ruta_grafica, inserta la imagen centrada debajo del texto.
    """
    abs_out = os.path.abspath(ruta_salida)
    parent = os.path.dirname(abs_out)
    if parent:
        os.makedirs(parent, exist_ok=True)

    class ReportePDF(FPDF):
        def header(self) -> None:
            self.set_font("Arial", "B", 14)
            self.cell(0, 10, "InsightFlow - Análisis de Inteligencia", ln=1, align="C")
            self.ln(5)

        def footer(self) -> None:
            self.set_y(-15)
            self.set_font("Arial", "I", 8)
            self.cell(0, 10, f"Página {self.page_no()}", ln=0, align="C")

    pdf = ReportePDF()
    pdf.add_page()
    pdf.set_font("Arial", "", 11)
    raw = texto_contenido or ""
    texto_limpio = raw.encode("latin-1", "replace").decode("latin-1")
    pdf.multi_cell(0, 7, txt=f"Fecha: {datetime.date.today()}\n\n{texto_limpio}")

    if ruta_grafica and os.path.isfile(ruta_grafica):
        pdf.image(ruta_grafica, x=30, w=150)

    pdf.output(abs_out)


def generar_reporte_excel_avanzado(
    df_datos: pd.DataFrame,
    texto_analisis: str,
    ruta_salida: str = "reporte_final.xlsx",
    ruta_grafica: Optional[str] = None,
) -> str:
    """
    Crea un .xlsx con resumen en texto, gráfica opcional y hoja de datos con tabla nativa.
    La IA solo debe llamar a esta función; no debe importar xlsxwriter ni diseñar hojas a mano.
    """
    try:
        abs_out = os.path.abspath(ruta_salida)
        parent = os.path.dirname(abs_out)
        if parent:
            os.makedirs(parent, exist_ok=True)

        with pd.ExcelWriter(abs_out, engine="xlsxwriter") as writer:
            workbook = writer.book
            formato_titulo = workbook.add_format(
                {"bold": True, "font_size": 14, "font_color": "#28468C"}
            )
            formato_texto = workbook.add_format(
                {"text_wrap": True, "valign": "top", "font_size": 11}
            )
            formato_fecha = workbook.add_format(
                {"italic": True, "font_color": "gray", "font_size": 10}
            )

            hoja_resumen = workbook.add_worksheet("Resumen Ejecutivo")
            hoja_resumen.write("A1", "InsightFlow - Reporte Inteligente de Datos", formato_titulo)
            hoja_resumen.write(
                "A2",
                f'Generado el: {datetime.date.today().strftime("%d/%m/%Y")}',
                formato_fecha,
            )
            hoja_resumen.set_column("A:A", 80)
            hoja_resumen.write("A4", texto_analisis or "", formato_texto)
            hoja_resumen.set_row(3, 150)

            if ruta_grafica and os.path.isfile(ruta_grafica):
                hoja_visual = workbook.add_worksheet("Análisis Visual")
                hoja_visual.write("A1", "Visualización de Tendencias Clave", formato_titulo)
                hoja_visual.insert_image("A3", ruta_grafica, {"x_scale": 0.8, "y_scale": 0.8})

            df_datos.to_excel(writer, sheet_name="Datos Completos", index=False)
            hoja_datos = writer.sheets["Datos Completos"]

            nrows, ncols = df_datos.shape
            if nrows > 0 and ncols > 0:
                column_settings = [{"header": str(c)} for c in df_datos.columns]
                hoja_datos.add_table(
                    0,
                    0,
                    nrows,
                    ncols - 1,
                    {"columns": column_settings, "style": "Table Style Medium 9"},
                )

            for i, col in enumerate(df_datos.columns):
                try:
                    column_len = int(df_datos[col].astype(str).str.len().max() or 0)
                except (TypeError, ValueError):
                    column_len = 10
                column_len = min(max(column_len, len(str(col))) + 2, 60)
                hoja_datos.set_column(i, i, column_len)

        return f"LOG: {abs_out} generado exitosamente."
    except Exception as e:
        return f"ERROR generando Excel: {e}"
