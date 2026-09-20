"""
Async aggregates for geo / comuna sentiment.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.geo import detectar_comuna, load_barrio_index, sentiment_to_score


async def get_comuna_sentiment(
    db: AsyncSession,
    *,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    n_min: int = 15,
    include_comments: bool = True,
) -> Dict[str, Any]:
    """
    Scan posts (+ optional comments) for barrio/comuna mentions and aggregate
    sentiment. Only texts with a geo match contribute.
    """
    indice = load_barrio_index()

    params: Dict[str, Any] = {}
    date_clause = ""
    if from_date is not None:
        date_clause += " AND p.posted_at >= :from_date "
        params["from_date"] = from_date
    if to_date is not None:
        date_clause += " AND p.posted_at <= :to_date "
        params["to_date"] = to_date

    post_sql = text(
        f"""
        SELECT p.id AS item_id, 'post' AS item_type, p.text,
               p.cached_sentiment_label AS sentiment_label,
               p.posted_at, p.url, p.platform
        FROM posts p
        WHERE length(coalesce(p.text, '')) > 10
        {date_clause}
        ORDER BY p.posted_at DESC NULLS LAST
        LIMIT 5000
        """
    )
    post_rows = (await db.execute(post_sql, params)).mappings().all()

    comment_rows: List[Any] = []
    if include_comments:
        # Prefer comment-level analysis; fall back to parent post cache
        comment_sql = text(
            f"""
            SELECT c.id AS item_id, 'comment' AS item_type, c.text,
                   COALESCE(ss.label, p.cached_sentiment_label) AS sentiment_label,
                   COALESCE(c.posted_at, p.posted_at) AS posted_at,
                   p.url, p.platform
            FROM comments c
            JOIN posts p ON p.id = c.post_id
            LEFT JOIN analysis_results ar ON ar.comment_id = c.id
            LEFT JOIN sentiment_scores ss ON ss.id = ar.sentiment_score_id
            WHERE length(coalesce(c.text, '')) > 5
            {date_clause}
            ORDER BY COALESCE(c.posted_at, p.posted_at) DESC NULLS LAST
            LIMIT 5000
            """
        )
        comment_rows = (await db.execute(comment_sql, params)).mappings().all()

    buckets: Dict[int, Dict[str, Any]] = {
        i: {
            "comuna_id": i,
            "comuna_label": f"Comuna {i}",
            "n": 0,
            "n_posts": 0,
            "n_comments": 0,
            "positive": 0,
            "neutral": 0,
            "negative": 0,
            "unknown": 0,
            "scores": [],
            "matches": [],
        }
        for i in range(1, 11)
    }

    signals: List[Dict[str, Any]] = []

    for row in list(post_rows) + list(comment_rows):
        geo = detectar_comuna(row["text"] or "", indice)
        if not geo:
            continue
        cid = int(geo["comuna_id"])
        b = buckets[cid]
        b["n"] += 1
        if row["item_type"] == "post":
            b["n_posts"] += 1
        else:
            b["n_comments"] += 1

        label = row["sentiment_label"]
        score = sentiment_to_score(label)
        if score is None:
            b["unknown"] += 1
        elif score > 0:
            b["positive"] += 1
            b["scores"].append(score)
        elif score < 0:
            b["negative"] += 1
            b["scores"].append(score)
        else:
            b["neutral"] += 1
            b["scores"].append(score)

        if len(b["matches"]) < 5:
            b["matches"].append(geo.get("match_texto"))

        signals.append(
            {
                "item_id": row["item_id"],
                "item_type": row["item_type"],
                "comuna_id": cid,
                "match_texto": geo.get("match_texto"),
                "match_tipo": geo.get("match_tipo"),
                "confianza_geo": geo.get("confianza_geo"),
                "sentiment_label": label,
                "posted_at": row["posted_at"].isoformat() if row["posted_at"] else None,
                "url": row["url"],
                "platform": row["platform"],
            }
        )

    comunas_out = []
    for i in range(1, 11):
        b = buckets[i]
        scores = b.pop("scores")
        n = b["n"]
        classified = b["positive"] + b["neutral"] + b["negative"]
        sentiment_score = (
            round(sum(scores) / len(scores), 4) if scores else None
        )
        if n == 0:
            banda = "sin_dato"
            muestra_suficiente = False
        elif n < n_min:
            banda = "muestra_baja"
            muestra_suficiente = False
        elif sentiment_score is None:
            banda = "sin_dato"
            muestra_suficiente = False
        elif sentiment_score >= 0.25:
            banda = "alta"
            muestra_suficiente = True
        elif sentiment_score >= -0.15:
            banda = "media"
            muestra_suficiente = True
        else:
            banda = "baja"
            muestra_suficiente = True

        comunas_out.append(
            {
                **{k: v for k, v in b.items() if k != "matches"},
                "match_ejemplos": b["matches"],
                "sentiment_score": sentiment_score,
                "classified": classified,
                "banda": banda,
                "muestra_suficiente": muestra_suficiente,
                "n_min": n_min,
            }
        )

    comunas_con_dato = sum(1 for c in comunas_out if c["n"] > 0)
    comunas_sobre_minimo = sum(1 for c in comunas_out if c["muestra_suficiente"])

    return {
        "comunas": comunas_out,
        "signals_total": len(signals),
        "signals_sample": signals[:50],
        "coverage": {
            "comunas_con_dato": comunas_con_dato,
            "comunas_sobre_minimo": comunas_sobre_minimo,
            "n_min_por_comuna": n_min,
            "choropleth_completo_recomendado": comunas_sobre_minimo >= 8,
        },
        "advertencia": (
            "Proxy geo: solo textos con mención barrio/comuna. "
            "No es encuesta ni geo del espectador de Meta Ads. "
            "No recolorear mapa a todo color si coverage.choropleth_completo_recomendado=false."
        ),
    }
