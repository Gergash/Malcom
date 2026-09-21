"""Tests unitarios del puente Termómetro → ECharts (sin red)."""

from __future__ import annotations

from app.listening.charts import (
    build_listening_dashboard,
    narrative_summary,
    primary_echarts_option,
    sentiment_pie_option,
)
from app.listening.packs import parse_pack_choice
from app.listening.service import is_listening_query, is_scrape_intent


def test_is_listening_query_detects_termometro():
    assert is_listening_query("muéstrame el termómetro cultural")
    assert is_listening_query("Escucha social de Tuluá")
    assert not is_listening_query("analiza este CSV de ventas")


def test_is_scrape_intent_requires_context():
    assert is_scrape_intent("recolectar datos del termómetro")
    assert not is_scrape_intent("recolectar datos")  # sin contexto listening


def test_is_scrape_intent_monitoreo_y_handles():
    msg = (
        "Termómetro Cultural Monitoreo exhaustivo de las cuentas "
        "@FuerzasMilCol y @COMANDANTE_FFMM"
    )
    assert is_listening_query(msg)
    assert is_scrape_intent(msg)
    # Solo handles sin contexto listening no dispara scrape
    assert not is_scrape_intent("mira @FuerzasMilCol")


def test_collection_progress_option():
    from app.listening.charts import collection_progress_option

    opt = collection_progress_option(
        percent=42, phase="scraping", sources_done=10, sources_total=31
    )
    assert opt["series"][0]["type"] == "gauge"
    assert opt["series"][0]["data"][0]["value"] == 42


def test_parse_pack_exhaustivo_es_profunda():
    assert parse_pack_choice("monitoreo exhaustivo") == "profunda"
    assert parse_pack_choice("cobertura completa") == "profunda"

def test_sentiment_pie_and_dashboard():
    sentiment = {
        "summary": {
            "positive": 10,
            "neutral": 5,
            "negative": 3,
            "total": 18,
            "score": 0.39,
        },
        "by_platform": {},
    }
    topics = {
        "topics": [
            {"slug": "security", "name": "Seguridad", "count": 7},
            {"slug": "taxes", "name": "Impuestos", "count": 4},
        ],
        "total_classified": 11,
    }
    timeline = {
        "timeline": [
            {"date": "2026-03-01", "positive": 2, "neutral": 1, "negative": 0, "score": 0.5},
            {"date": "2026-03-02", "positive": 1, "neutral": 2, "negative": 1, "score": 0.0},
        ]
    }
    pie = sentiment_pie_option(sentiment)
    assert pie["series"][0]["type"] == "pie"
    opt = primary_echarts_option(sentiment, topics, timeline)
    assert "series" in opt
    dash = build_listening_dashboard(
        sentiment=sentiment, topics=topics, timeline=timeline, alerts={"data": []}
    )
    assert dash["live"] is True
    assert len(dash["widgets"]) >= 3
    text = narrative_summary(sentiment, topics)
    assert "18" in text
    assert "Seguridad" in text
    collecting = narrative_summary(
        sentiment,
        topics,
        collection_phase="collecting",
        scrape_meta={"task_id": "abc", "sources_count": 31, "eta_minutes": 15},
    )
    assert "recolección en proceso" in collecting.lower() or "en proceso" in collecting.lower()
    assert "abc" in collecting

