"""Guards del análisis CSV: coerce numérico + validación de columnas del código generado."""

import pandas as pd
import pytest

try:
    from app.agents.csv_code_guards import extract_df_column_refs, validate_code_columns
    from app.agents.data_cleaner import _NUMERIC_CRITICAL_HINTS, _coerce_numeric_quarantine, _series_to_numeric
except ModuleNotFoundError:
    from agents.csv_code_guards import extract_df_column_refs, validate_code_columns
    from agents.data_cleaner import _NUMERIC_CRITICAL_HINTS, _coerce_numeric_quarantine, _series_to_numeric


def test_numeric_hints_include_export_import_usd() -> None:
    joined = " ".join(_NUMERIC_CRITICAL_HINTS)
    assert "export" in joined
    assert "import" in joined
    assert "usd" in joined
    assert "$" in joined


def test_series_to_numeric_strips_currency() -> None:
    s = pd.Series(["$1,234.50", "  $99 ", "(100)", "n/a", "abc"])
    out = _series_to_numeric(s)
    assert float(out.iloc[0]) == pytest.approx(1234.50)
    assert float(out.iloc[1]) == pytest.approx(99.0)
    assert float(out.iloc[2]) == pytest.approx(-100.0)
    assert pd.isna(out.iloc[3])
    assert pd.isna(out.iloc[4])


def test_coerce_export_dollar_column() -> None:
    df = pd.DataFrame(
        {
            "Industry": ["Tech", "Agro", "Tech"],
            "Export($)": ["$1,000", "$2,500.5", "$500"],
        }
    )
    cleaned = _coerce_numeric_quarantine(df)
    assert pd.api.types.is_numeric_dtype(cleaned["Export($)"])
    assert float(cleaned["Export($)"].iloc[0]) == pytest.approx(1000.0)
    top = cleaned["Export($)"].nlargest(1)
    assert float(top.iloc[0]) == pytest.approx(2500.5)


def test_extract_df_column_refs() -> None:
    code = """
df = cargar_dataframe_limpio()
df['Export($)'] = pd.to_numeric(df['Export($)'], errors='coerce')
top = df.nlargest(5, 'Export($)')
g = df.groupby('Industry')['Export($)'].sum()
sub = df[['Industry', 'Export($)']]
"""
    refs = extract_df_column_refs(code)
    assert "Export($)" in refs
    assert "Industry" in refs


def test_validate_rejects_invented_columns() -> None:
    code = "df['Sector'] = 1\nx = df['Categoria_Producto'].value_counts()"
    with pytest.raises(ValueError, match="Columnas inexistentes"):
        validate_code_columns(code, ["Industry", "Export($)"])


def test_validate_accepts_real_columns() -> None:
    code = "df['Export($)'] = pd.to_numeric(df['Export($)'], errors='coerce')\nprint(df['Industry'].nunique())"
    validate_code_columns(code, ["Industry", "Export($)"])
