# Database Schema – Termómetro Cultural

PostgreSQL schema for the social sentiment monitoring system. Each record type stores **source**, **platform**, **text**, **date**, **topic**, **sentiment**, **urgency**, and **confidence** where applicable.

> **Operación jul-2026:** Docker expone Postgres en puerto host **5433**. Columna `language VARCHAR(8)` en `posts` requerida por el ORM (aplicar manualmente si migración `001` no la incluye). Ver [OPERACION_JULIO_2026.md](OPERACION_JULIO_2026.md).

## Tables

### sources
Registered scraping targets (Facebook page, Instagram profile, news site).

| Column      | Type         | Description                    |
|------------|--------------|--------------------------------|
| id         | SERIAL PK    |                                |
| name       | VARCHAR(255) | Display name                   |
| platform   | VARCHAR(32)  | facebook, instagram, twitter, news |
| url        | VARCHAR(2048)| Base URL                       |
| is_active  | BOOLEAN      | Default true                   |
| created_at | TIMESTAMPTZ  |                                |
| updated_at | TIMESTAMPTZ  |                                |

**Indexes:** `(platform)`, `(platform, is_active)`, `(name)`.

---

### posts
Scraped posts/tweets/articles. Optional denormalized cache from latest analysis for fast dashboards.

| Column                  | Type         | Description                    |
|-------------------------|--------------|--------------------------------|
| id                      | SERIAL PK    |                                |
| source_id               | INT FK       | → sources.id (SET NULL)       |
| platform                | VARCHAR(32)  |                                |
| text                    | TEXT         | Post content                   |
| posted_at               | TIMESTAMPTZ  | Publication date              |
| url                     | VARCHAR(2048)|                                |
| scraped_at              | TIMESTAMPTZ  |                                |
| metadata                | JSONB        | Raw scraper payload            |
| cached_sentiment_label  | VARCHAR(64)  | From latest analysis           |
| cached_sentiment_score  | NUMERIC(5,4) |                                |
| cached_urgency          | VARCHAR(32)  | low, medium, high, critical    |
| cached_confidence       | NUMERIC(5,4) | 0–1                            |
| language                | VARCHAR(8)   | Código idioma detectado (ej. es) |

**Indexes:** `(source_id)`, `(platform)`, `(posted_at)`, `(scraped_at)`, `(cached_sentiment_label)`, `(cached_urgency)`, `(platform, posted_at)`, `(cached_sentiment_label, platform)`, `(posted_at DESC)`.

---

### comments
Comments on posts.

| Column             | Type         | Description        |
|--------------------|--------------|--------------------|
| id                 | SERIAL PK    |                    |
| post_id            | INT FK       | → posts.id CASCADE|
| text               | TEXT         |                    |
| posted_at          | TIMESTAMPTZ  |                    |
| author_identifier  | VARCHAR(255)  |                    |
| scraped_at         | TIMESTAMPTZ  |                    |
| metadata           | JSONB        |                    |

**Indexes:** `(post_id)`, `(post_id, posted_at)`, `(author_identifier)`.

---

### topics
Taxonomy for classification (e.g. cultura, educación, seguridad). Optional hierarchy via parent_id.

| Column    | Type          | Description   |
|-----------|---------------|---------------|
| id        | SERIAL PK     |               |
| name      | VARCHAR(128)  |               |
| slug      | VARCHAR(128)  | UNIQUE        |
| parent_id | INT FK        | → topics.id   |

**Indexes:** `(slug)`, `(parent_id)`.

---

### sentiment_scores
Dimension table: label and numeric score for sentiment.

| Column      | Type          | Description   |
|-------------|---------------|---------------|
| id          | SERIAL PK     |               |
| label       | VARCHAR(64)   | UNIQUE (e.g. positive, neutral, negative) |
| score_value | NUMERIC(5,4)  | e.g. -1, 0, 1 |
| description | TEXT          |               |

**Indexes:** `(label)`.  
**Seed data:** positive (1.0), neutral (0.0), negative (-1.0).

---

### analysis_results
One NLP analysis per post or comment. Stores sentiment (FK), urgency, confidence; topics via M2M.

| Column             | Type          | Description        |
|--------------------|---------------|--------------------|
| id                 | SERIAL PK     |                    |
| post_id            | INT FK        | → posts.id CASCADE |
| comment_id         | INT FK        | → comments.id CASCADE |
| sentiment_score_id | INT FK        | → sentiment_scores.id SET NULL |
| urgency            | VARCHAR(32)   | low, medium, high, critical |
| confidence         | NUMERIC(5,4)  | 0–1                |
| model_version      | VARCHAR(64)   |                    |
| created_at         | TIMESTAMPTZ   |                    |

**Indexes:** `(post_id)`, `(comment_id)`, `(sentiment_score_id)`, `(urgency)`, `(created_at)`, `(post_id, created_at)`, `(comment_id, created_at)`.

---

### analysis_result_topics
Many-to-many: analysis_result ↔ topics.

| Column             | Type   | Description |
|--------------------|--------|-------------|
| analysis_result_id | INT PK | FK → analysis_results.id CASCADE |
| topic_id           | INT PK | FK → topics.id CASCADE |

**Indexes:** `(topic_id)`, `(analysis_result_id)`.

---

## Performance (large datasets)

- **Time-series:** Use `(platform, posted_at)` and `(posted_at DESC)` for recent/filtered feeds.
- **Analytics:** Use `(cached_sentiment_label, platform)` and `(cached_urgency)` for aggregations without joining analysis_results.
- **Joins:** FKs and indexes on `post_id`, `comment_id`, `source_id`, `sentiment_score_id`, `topic_id` keep joins and filters fast.
- **JSONB:** `metadata` is JSONB for optional GIN index if you query inside JSON.

## Migrations

- **Alembic:** `alembic upgrade head` (uses `DATABASE_URL_SYNC` from `.env`).
- **Initial migration:** `alembic/versions/001_initial_schema_...` creates all tables and indexes.
