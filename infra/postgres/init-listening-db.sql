-- Creates the Termómetro / listening_engine database on first Postgres init
-- (scripts in /docker-entrypoint-initdb.d run only when pgdata is empty).
--
-- If the volume already exists, create the DB manually once:
--   docker compose exec postgres psql -U insightflow -c "CREATE DATABASE termometro_cultural;"

SELECT 'CREATE DATABASE termometro_cultural'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'termometro_cultural')\gexec
