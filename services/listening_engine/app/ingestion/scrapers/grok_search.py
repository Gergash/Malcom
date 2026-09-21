"""
GrokSearchScraper — live web search via xAI Grok API.

Perfil COMES / Comando General FF.MM. (Anexo 6):
  Extrae menciones y publicaciones sobre cuentas oficiales, Plan Ayacucho,
  Sector Defensa y actores de interés — no monitoreo municipal.

How it works:
  1. Recibe URL de perfil/búsqueda o query libre (grok_topic / tiktok / youtube).
  2. Llama a grok-4 con tools web_search.
  3. Devuelve JSON de posts con texto, métricas y enlaces.
  4. Normaliza a ScrapedItem (metadata con engagement / reach / URLs).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import structlog

from app.ingestion.scrapers.base import BaseScraper

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Prompt templates — COMES / CGFM / Plan Ayacucho
# ---------------------------------------------------------------------------

_SYSTEM = """\
Eres un extractor de inteligencia de escucha digital para el Comando General \
de las Fuerzas Militares de Colombia (COMES / CGFM) y el monitoreo del Plan Ayacucho.

Tu tarea: busca publicaciones RECIENTES en la URL, perfil o consulta indicada \
y extrae el contenido textual de cada publicación, mención o conversación \
relevante para el Sector Defensa y las Fuerzas Militares.

Devuelve ÚNICAMENTE un JSON válido — sin explicaciones, sin markdown, sin texto adicional:

{
  "posts": [
    {
      "text": "<texto completo de la publicación o comentario>",
      "url": "<URL directa a la publicación>",
      "date": "<fecha ISO 8601 o null>",
      "platform": "<twitter|facebook|instagram|tiktok|youtube|news|web>",
      "author": "<handle o nombre público o null>",
      "likes": <número o null>,
      "comments": <número o null>,
      "shares": <número o null>,
      "views": <número o null>,
      "impressions": <número o null>,
      "reach": <número o null>,
      "followers": <número o null>,
      "linked_urls": ["<URLs compartidas en el post>"],
      "points_to_institutional": <true|false|null>,
      "csat_signal": <número 1-5 o null>,
      "nps_signal": <número -100..100 o null>
    }
  ],
  "source_name": "<nombre de la página, cuenta o medio>",
  "total_found": <número de publicaciones encontradas>
}

INCLUYE (prioridad COMES):
- Publicaciones de cuentas oficiales @FuerzasMilCol y @COMANDANTE_FFMM.
- Menciones directas e indirectas de "Plan Ayacucho" y hashtags asociados.
- Contenido sobre Comando General, Fuerzas Militares, Ejército, Armada, FAC, \
  Sector Defensa, seguridad nacional y operaciones institucionales de interés público.
- Publicaciones de líderes de opinión, periodistas, gremios y medios \
  (regionales, nacionales e internacionales) sobre esos temas.
- Comentarios y respuestas públicas relevantes cuando sean visibles.
- Enlaces compartidos; marca points_to_institutional=true si apuntan a sitios \
  oficiales (.mil.co, fuerzasmilitares, comando general, etc.).

EXCLUYE:
- Contenido puramente comercial o de entretenimiento sin vínculo con Defensa / FF.MM.
- Rumores sin texto usable; no inventes métricas ni citas.

REGLAS:
- Si no hay publicaciones relevantes, devuelve {"posts": [], "source_name": "", "total_found": 0}.
- Texto completo, no truncado. Máximo 20 publicaciones por llamada.
- Métricas (likes, comments, shares, views, impressions, reach, followers): \
  solo si son visibles/públicas; si no, null. No inventes cifras.
- csat_signal / nps_signal solo si el post es claramente una encuesta o reacción \
  tipificable de satisfacción; si no, null.
"""


def _is_url(value: str) -> bool:
    """Return True if value looks like a URL rather than a search query."""
    return value.startswith("http://") or value.startswith("https://") or value.startswith("www.")


def _is_search_results_url(url: str) -> bool:
    """True for X/Facebook/TikTok/YouTube search pages that list many posts."""
    lower = url.lower()
    return (
        "x.com/search" in lower
        or "twitter.com/search" in lower
        or "facebook.com/search" in lower
        or "facebook.com/groups/search" in lower
        or "tiktok.com/search" in lower
        or "youtube.com/results" in lower
        or "youtube.com/search" in lower
    )


def _is_news_homepage(url: str) -> bool:
    """True for news site root or section pages (not a single article)."""
    try:
        parsed = urlparse(url)
        path = parsed.path.strip("/")
        return not path or path in {
            "noticias",
            "actualidad",
            "colombia",
            "mundo",
            "politica",
            "nacion",
            "defense",
            "defensa",
        }
    except Exception:
        return False


_FOCUS_BRIEF = (
    "Enfoque COMES: Comando General de las Fuerzas Militares, "
    "@FuerzasMilCol, @COMANDANTE_FFMM, Plan Ayacucho, Sector Defensa, "
    "seguridad nacional, líderes de opinión y medios que traten estos temas."
)


def _build_user_prompt(
    query: str,
    source_name: str,
    days_back: int = 7,
    target_platform: str = "facebook",
) -> str:
    """
    Build the user message for Grok (perfil COMES / CGFM).
    """
    since = (datetime.now(tz=timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")
    plat = (target_platform or "").lower()

    if _is_url(query):
        if plat == "news" or _is_news_homepage(query):
            return (
                f"Visita el medio digital: {query}\n"
                f"Nombre de la fuente: {source_name}\n"
                f"Periodo: desde {since} hasta hoy.\n\n"
                f"{_FOCUS_BRIEF}\n\n"
                f"Extrae artículos/editoriales/blogs recientes sobre Fuerzas Militares, "
                f"Comando General, Plan Ayacucho, Sector Defensa u operaciones "
                f"institucionales de interés público. Por cada pieza: texto usable "
                f"(titular + lead o cuerpo), URL directa, y métricas públicas si aparecen.\n"
                f"Máximo 20 artículos."
            )
        if _is_search_results_url(query):
            return (
                f"Visita esta página de resultados de búsqueda: {query}\n"
                f"Nombre de la fuente: {source_name}\n"
                f"Plataforma esperada: {plat or 'web'}\n"
                f"Periodo: desde {since} hasta hoy.\n\n"
                f"{_FOCUS_BRIEF}\n\n"
                f"Extrae cada publicación/mención visible con texto completo, URL directa, "
                f"autor si aparece, métricas de engagement (likes/comentarios/shares/"
                f"views/impresiones/alcance) y URLs enlazadas en el post."
            )
        # Perfil oficial u otra URL concreta (X/FB/IG/TikTok/YouTube)
        return (
            f"Monitorea de forma exhaustiva el perfil o página: {query}\n"
            f"Nombre de la fuente: {source_name}\n"
            f"Plataforma: {plat or 'web'}\n"
            f"Periodo: desde {since} hasta hoy.\n\n"
            f"{_FOCUS_BRIEF}\n\n"
            f"Extrae las publicaciones recientes de esa cuenta/página (texto completo, "
            f"URL de cada post, métricas públicas de rendimiento, seguidores del perfil "
            f"si son visibles, y cualquier enlace compartido). "
            f"Si es @FuerzasMilCol o @COMANDANTE_FFMM, prioriza cobertura completa del feed reciente."
        )

    # Query libre (grok_topic / keywords / hashtags)
    platform_hint = {
        "tiktok": "Prioriza resultados de TikTok.",
        "youtube": "Prioriza videos y comentarios públicos de YouTube.",
        "twitter": "Prioriza X (Twitter).",
        "facebook": "Prioriza Facebook.",
        "instagram": "Prioriza Instagram.",
        "grok_topic": "Busca en X, Facebook, Instagram, TikTok, YouTube y medios digitales.",
    }.get(plat, "Busca en redes sociales y medios digitales.")

    return (
        f"Busca en internet publicaciones recientes sobre:\n\n"
        f"\"{query}\"\n\n"
        f"Periodo: desde {since} hasta hoy.\n"
        f"{platform_hint}\n"
        f"{_FOCUS_BRIEF}\n\n"
        f"Incluye menciones de campañas (Plan Ayacucho), cuentas oficiales, "
        f"periodistas, gremios y keywords/hashtags del Sector Defensa. "
        f"Devuelve texto, URL, métricas y enlaces compartidos por cada hallazgo."
    )


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------

class GrokSearchScraper(BaseScraper):
    """
    Scraper COMES: Grok live search para redes y medios sin API de plataforma.
    """

    platform = "grok_search"

    def __init__(
        self,
        *,
        target_platform: str = "facebook",
        days_back: int = 7,
        max_results: int = 20,
        proxy_rotation: bool = False,
        proxy_list: Optional[List[str]] = None,
        headless: bool = True,
        timeout_ms: int = 60_000,
    ):
        super().__init__(
            proxy_rotation=proxy_rotation,
            proxy_list=proxy_list,
            headless=headless,
            timeout_ms=timeout_ms,
        )
        self.target_platform = target_platform
        self.days_back = days_back
        self.max_results = max_results

    def _grok_client(self):
        """
        Return (AsyncOpenAI, model_name) pointing at xAI.
        Web search via responses.create() requires the grok-4 model family.
        """
        from openai import AsyncOpenAI
        from app.config import get_settings

        s = get_settings()
        if not s.grok_api_key:
            raise RuntimeError(
                "GROK_API_KEY is not set. Cannot use GrokSearchScraper."
            )
        search_model = "grok-4-0709"
        return AsyncOpenAI(api_key=s.grok_api_key, base_url="https://api.x.ai/v1"), search_model

    async def _call_grok_search(self, url: str, source_name: str) -> Optional[Dict[str, Any]]:
        """Live-search request to Grok (responses API + web_search)."""
        client, model = self._grok_client()

        try:
            response = await client.responses.create(
                model=model,
                input=[
                    {"role": "system", "content": _SYSTEM},
                    {
                        "role": "user",
                        "content": _build_user_prompt(
                            url, source_name, self.days_back, self.target_platform
                        ),
                    },
                ],
                tools=[{"type": "web_search"}],
            )
        except Exception as exc:
            logger.error("grok_search_api_error", url=url, error=str(exc))
            return None

        raw = ""
        try:
            if hasattr(response, "output_text"):
                raw = response.output_text or ""
            else:
                for item in (response.output or []):
                    if hasattr(item, "content"):
                        for block in (item.content or []):
                            if hasattr(block, "text"):
                                raw += block.text
                        break
        except Exception as exc:
            logger.warning("grok_search_response_parse_error", url=url, error=str(exc))
            return None

        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(
                line for line in lines if not line.strip().startswith("```")
            ).strip()

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("grok_search_json_parse_failed", url=url, raw_preview=raw[:300])
            return None

    async def _scrape_impl(self, url: Optional[str] = None, **kwargs: Any) -> List[Dict[str, Any]]:
        if not url:
            return []

        source_name: str = kwargs.get("source_name") or _infer_source_name(url)
        log = logger.bind(url=url, source_name=source_name, platform=self.target_platform)
        log.info("grok_search_started")

        data = await self._call_grok_search(url, source_name)
        if not data:
            log.warning("grok_search_no_data")
            return []

        posts = data.get("posts") or []
        if not posts:
            log.info("grok_search_no_posts_found", total=data.get("total_found", 0))
            return []

        resolved_source = data.get("source_name") or source_name
        results: List[Dict[str, Any]] = []

        for post in posts[: self.max_results]:
            text = (post.get("text") or "").strip()
            if not text:
                continue

            post_url = (post.get("url") or url).strip()
            post_date: Optional[datetime] = None

            raw_date = post.get("date")
            if raw_date:
                try:
                    post_date = datetime.fromisoformat(
                        str(raw_date).replace("Z", "+00:00")
                    )
                except (ValueError, TypeError):
                    pass

            linked = post.get("linked_urls") or []
            if not isinstance(linked, list):
                linked = [linked] if linked else []

            likes = post.get("likes")
            comments = post.get("comments")
            shares = post.get("shares")
            views = post.get("views")
            impressions = post.get("impressions")
            reach = post.get("reach")
            engagement = None
            try:
                parts = [x for x in (likes, comments, shares) if isinstance(x, (int, float))]
                if parts:
                    engagement = int(sum(parts))
            except (TypeError, ValueError):
                engagement = None

            results.append(
                self._normalize(
                    source=resolved_source,
                    text=text,
                    url=post_url,
                    date=post_date or datetime.now(tz=timezone.utc),
                    metadata={
                        "platform_label": self.target_platform,
                        "author": post.get("author"),
                        "likes": likes,
                        "comments": comments,
                        "shares": shares,
                        "views": views,
                        "impressions": impressions,
                        "reach": reach,
                        "followers": post.get("followers"),
                        "engagement": engagement,
                        "linked_urls": [str(u) for u in linked if u],
                        "points_to_institutional": post.get("points_to_institutional"),
                        "csat_signal": post.get("csat_signal"),
                        "nps_signal": post.get("nps_signal"),
                        "via": "grok_live_search",
                        "mandate": "comes_cgfm",
                    },
                )
            )

        log.info("grok_search_complete", extracted=len(results), total_found=data.get("total_found", 0))
        return results


def _infer_source_name(url: str) -> str:
    """Derive a readable source name from a URL."""
    try:
        path = urlparse(url).path.strip("/")
        parts = [p for p in path.split("/") if p and p not in ("groups", "pages", "search", "results")]
        return parts[0] if parts else urlparse(url).netloc
    except Exception:
        return url[:50]
