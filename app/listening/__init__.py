"""
Puente InsightFlow Brain ↔ Termómetro Cultural (listening-api).

Recoge agregados vía HTTP interno y los convierte en echarts_option / dashboard
consumibles por el widget y GET /api/v1/listening/overview.
"""

from app.listening.service import (
    build_listening_overview,
    handle_listening_message,
    is_listening_query,
    is_scrape_intent,
)

__all__ = [
    "build_listening_overview",
    "handle_listening_message",
    "is_listening_query",
    "is_scrape_intent",
]
