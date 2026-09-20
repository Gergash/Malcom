"""Unit tests for barrio → comuna geo matching."""
from pathlib import Path

import pytest

from app.analysis.geo import detectar_comuna, load_barrio_index, sentiment_to_score

EQ = Path(__file__).resolve().parent.parent / "config" / "equivalencia_barrio_comuna.csv"


@pytest.fixture(scope="module")
def indice():
    assert EQ.exists(), f"Missing equivalencia CSV at {EQ}"
    # Clear cache so path override is used
    load_barrio_index.cache_clear()
    idx = load_barrio_index(str(EQ))
    assert len(idx) > 50
    return idx


def test_comuna_literal(indice):
    g = detectar_comuna("Hay problemas en la Comuna 3 por el alumbrado", indice)
    assert g is not None
    assert g["comuna_id"] == 3
    assert g["match_tipo"] == "comuna_literal"
    assert g["confianza_geo"] == "alta"


def test_barrio_non_ambiguous(indice):
    g = detectar_comuna(
        "En panamericano llevan semanas sin agua potable",
        indice,
    )
    assert g is not None
    assert g["comuna_id"] == 1
    assert g["match_tipo"] == "barrio"
    assert g["match_texto"] == "panamericano"


def test_ambiguous_requires_prefix(indice):
    bare = detectar_comuna("Voy al centro a hacer un trámite municipal", indice)
    if bare and bare.get("match_texto") == "el centro":
        pytest.fail("ambiguous 'el centro' matched without barrio/sector prefix")

    with_prefix = detectar_comuna("En el barrio El Centro no hay luz", indice)
    assert with_prefix is not None
    assert with_prefix["match_texto"] == "el centro"
    assert with_prefix["confianza_geo"] == "alta"


def test_no_geo_returns_none(indice):
    assert detectar_comuna("La alcaldía anunció una reunión virtual mañana", indice) is None


def test_sentiment_to_score():
    assert sentiment_to_score("positive") == 1.0
    assert sentiment_to_score("negative") == -1.0
    assert sentiment_to_score("neutral") == 0.0
    assert sentiment_to_score(None) is None
    assert sentiment_to_score("weird") is None


def test_extract_comment_texts():
    from app.scheduler.repository import _extract_comment_texts

    texts = _extract_comment_texts(
        {
            "comments_sample": ["Hola barrio", "  ", "Hola barrio"],
            "comments": [{"text": "Otro comentario útil"}],
        }
    )
    assert texts == ["Hola barrio", "Otro comentario útil"]
