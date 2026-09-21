# Listening Engine (Termómetro Cultural)

Motor de escucha social embebido en InsightFlow Malcom.

- Documentación de fusión e instrucciones Anexo 6: [`docs/FUSION-LISTENING.md`](../../docs/FUSION-LISTENING.md)
- Compose de producción unificado: raíz del repo `docker-compose.yml` (servicios `listening-*`)
- Compose histórico standalone (referencia): `docker-compose.standalone.example.yml`
- Fuentes CGFM (Anexo 6): [`config/sources_cgfm.yaml`](config/sources_cgfm.yaml) + brief [`docs/ANEXO6-SOURCES-CGFM.md`](docs/ANEXO6-SOURCES-CGFM.md)
- Activar: `LISTENING_SOURCES_FILE=config/sources_cgfm.yaml` en `.env`
- Producto: InsightFlow consume este API vía `GET /api/v1/listening/*` (proxy Go) y el chat del Brain.

```bash
# Desde la raíz de Malcom
docker compose up -d --build listening-api listening-worker listening-beat redis brain api
curl -sS http://127.0.0.1:8080/api/v1/listening/overview | head
```
