"""
report_generator.py: lectura de esquema, PDF (fpdf2) y Excel avanzado (pandas + xlsxwriter).
Separado de analyst_agent.py para mantener la responsabilidad de cada módulo acotada.
"""
from __future__ import annotations

import datetime
import os
from typing import TYPE_CHECKING, Optional, Tuple

import pandas as pd
from fpdf import FPDF

if TYPE_CHECKING:
    from app.api.schemas import ReportConfig

_DATA_EXTENSIONS = (".csv", ".xlsx", ".xls")


def _hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    h = (hex_color or "").strip().lstrip("#")
    if len(h) == 6 and all(c in "0123456789abcdefABCDEF" for c in h):
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return 40, 70, 140


def _load_report_config(config: Optional[ReportConfig]) -> Optional[ReportConfig]:
    if config is None:
        return None
    try:
        from app.api.schemas import ReportConfig as RC
    except ModuleNotFoundError:
        from api.schemas import ReportConfig as RC  # type: ignore
    if isinstance(config, RC):
        return config
    return RC.model_validate(config)


def _read_schema_sample(path: str) -> Tuple[pd.DataFrame, Optional[str]]:
    """Muestra de 2 filas para esquema. Soporta CSV (varios encodings y separadores) y Excel."""
    path_lower = path.lower()
    if path_lower.endswith((".xlsx", ".xls")):
        return pd.read_excel(path, nrows=2), None
    # Intentar auto-detectar separador + encoding para evitar que columnas queden fusionadas
    for encoding in ("utf-8", "latin-1", "cp1252", "iso-8859-1"):
        try:
            df = pd.read_csv(path, nrows=2, encoding=encoding, sep=None, engine="python")
            # Si todas las columnas quedaron en una sola, el separador no se detectó bien
            if len(df.columns) > 1:
                return df, encoding
        except (UnicodeDecodeError, Exception):
            continue
    # Fallback: dejar que pandas elija con latin-1
    return pd.read_csv(path, nrows=2, encoding="latin-1", sep=None, engine="python"), "latin-1"


def generar_reporte_pdf(
    texto_contenido: str,
    ruta_salida: str = "reporte_final.pdf",
    ruta_grafica: Optional[str] = None,
    report_config: Optional["ReportConfig"] = None,
) -> None:
    """
    Crea un PDF A4 con cabecera/pie de página usando fpdf2.
    Si existe ruta_grafica, inserta la imagen centrada debajo del texto.
    """
    cfg = _load_report_config(report_config)
    abs_out = os.path.abspath(ruta_salida)
    parent = os.path.dirname(abs_out)
    if parent:
        os.makedirs(parent, exist_ok=True)

    title_size = cfg.font_size_titles if cfg else 14
    body_size = cfg.font_size_body if cfg else 11
    primary = _hex_to_rgb(cfg.primary_color) if cfg else (40, 70, 140)

    class ReportePDF(FPDF):
        def header(self) -> None:
            self.set_text_color(*primary)
            self.set_font("Arial", "B", title_size)
            self.cell(0, 10, "InsightFlow - Análisis de Inteligencia", ln=1, align="C")
            self.set_text_color(0, 0, 0)
            self.ln(5)

        def footer(self) -> None:
            self.set_y(-15)
            self.set_font("Arial", "I", max(8, body_size - 3))
            self.set_text_color(80, 80, 80)
            self.cell(0, 10, f"Página {self.page_no()}", ln=0, align="C")
            self.set_text_color(0, 0, 0)

    pdf = ReportePDF()
    pdf.add_page()
    pdf.set_font("Arial", "", body_size)
    raw = texto_contenido or ""
    texto_limpio = raw.encode("latin-1", "replace").decode("latin-1")
    pdf.multi_cell(0, max(5, int(body_size * 0.65)), txt=f"Fecha: {datetime.date.today()}\n\n{texto_limpio}")

    if ruta_grafica and os.path.isfile(ruta_grafica):
        pdf.image(ruta_grafica, x=30, w=150)

    pdf.output(abs_out)


def generar_reporte_premium_pdf(
    texto_contenido: str,
    ruta_salida: str = "reporte_final.pdf",
    rutas_graficas: Optional[list] = None,
    report_config: Optional["ReportConfig"] = None,
) -> None:
    """
    Genera un PDF multi-página de calidad corporativa (plan premium).
    Estructura: portada → análisis ejecutivo → gráficas (una por página).
    Solo debe llamarse desde código generado por el LLM vía la función inyectada;
    nunca importar fpdf directamente.
    """
    cfg = _load_report_config(report_config)
    abs_out = os.path.abspath(ruta_salida)
    parent = os.path.dirname(abs_out)
    if parent:
        os.makedirs(parent, exist_ok=True)

    title_size = cfg.font_size_titles if cfg else 16
    body_size = cfg.font_size_body if cfg else 11
    primary = _hex_to_rgb(cfg.primary_color) if cfg else (40, 70, 140)
    charts = [r for r in (rutas_graficas or []) if r and os.path.isfile(r)]

    class PremiumPDF(FPDF):
        def header(self) -> None:
            self.set_fill_color(*primary)
            self.rect(0, 0, 210, 10, "F")
            self.set_text_color(255, 255, 255)
            self.set_font("Arial", "B", 9)
            self.set_xy(0, 1)
            self.cell(0, 8, "InsightFlow — Dashboard Corporativo Premium", align="C")
            self.set_text_color(0, 0, 0)
            self.ln(8)

        def footer(self) -> None:
            self.set_y(-15)
            self.set_font("Arial", "I", max(7, body_size - 4))
            self.set_text_color(120, 120, 120)
            self.cell(0, 10, f"Pág. {self.page_no()}  |  PowerUps InsightFlow  |  {datetime.date.today()}", align="C")
            self.set_text_color(0, 0, 0)

    pdf = PremiumPDF()

    # ── Portada ──────────────────────────────────────────────────────────────
    pdf.add_page()
    pdf.ln(30)
    pdf.set_text_color(*primary)
    pdf.set_font("Arial", "B", title_size + 6)
    pdf.multi_cell(0, 12, "Dashboard Corporativo\nInsightFlow Analytics", align="C")
    pdf.ln(8)
    pdf.set_text_color(80, 80, 80)
    pdf.set_font("Arial", "", body_size)
    pdf.cell(0, 8, f"Generado el {datetime.date.today()}", align="C", ln=1)
    pdf.ln(6)
    pdf.set_draw_color(*primary)
    pdf.set_line_width(0.8)
    pdf.line(30, pdf.get_y(), 180, pdf.get_y())

    # ── Análisis ejecutivo ────────────────────────────────────────────────────
    pdf.add_page()
    pdf.set_text_color(*primary)
    pdf.set_font("Arial", "B", title_size)
    pdf.cell(0, 10, "Análisis Ejecutivo", ln=1)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Arial", "", body_size)
    raw = (texto_contenido or "").encode("latin-1", "replace").decode("latin-1")
    pdf.multi_cell(0, max(5, int(body_size * 0.65)), txt=raw)

    # ── Gráficas (una por página) ─────────────────────────────────────────────
    for i, ruta in enumerate(charts, start=1):
        pdf.add_page()
        pdf.set_text_color(*primary)
        pdf.set_font("Arial", "B", body_size + 1)
        pdf.cell(0, 10, f"Gráfica {i}", ln=1)
        pdf.set_text_color(0, 0, 0)
        pdf.image(ruta, x=15, w=180)

    pdf.output(abs_out)


def generar_reporte_excel_avanzado(
    df_datos: pd.DataFrame,
    texto_analisis: str,
    ruta_salida: str = "reporte_final.xlsx",
    ruta_grafica: Optional[str] = None,
    report_config: Optional["ReportConfig"] = None,
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

        cfg = _load_report_config(report_config)
        title_pt = cfg.font_size_titles if cfg else 14
        body_pt = cfg.font_size_body if cfg else 11
        primary_hex = cfg.primary_color if cfg else "#28468C"

        with pd.ExcelWriter(abs_out, engine="xlsxwriter") as writer:
            workbook = writer.book
            formato_titulo = workbook.add_format(
                {"bold": True, "font_size": title_pt, "font_color": primary_hex}
            )
            formato_texto = workbook.add_format(
                {"text_wrap": True, "valign": "top", "font_size": body_pt}
            )
            formato_fecha = workbook.add_format(
                {"italic": True, "font_color": "gray", "font_size": max(9, body_pt - 1)}
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
