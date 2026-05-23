# BIN Automation System

Este sistema automatiza el proceso de clasificación y validación de BINs (Bank Identification Numbers).

## Estructura del Proyecto

```
bin_automation/
├── data/                        # Carpeta para los datos de entrada y salida
│   ├── input/                   # Archivos de entrada y temporales procesados
│   └── output/                  # Archivos generados como resultado final
├── src/                         # Código fuente del sistema
│   ├── ingest.py               # Script que normaliza y procesa los archivos de entrada
│   ├── validators/             # Módulo para validación de BINs
│   ├── classifiers/            # Módulo para clasificar BINs
│   └── exporters/              # Módulo para exportar los resultados
└── Makefile                    # Archivo para automatizar los pasos del flujo
```

## Requisitos

- Python 3.8+
- Make

## Uso

1. Coloque sus archivos de entrada en la carpeta `data/input/`
2. Ejecute el proceso de clasificación:
   ```
   make classify
   ```
3. Los resultados se encontrarán en `data/output/`

## Formatos de Salida

- CSV: `data/output/classified.csv`
- JSON: `data/output/classified.json`
- Resumen por tienda: `data/output/summary_by_store.csv` 

---

## Actualizaciones Recientes — InsightFlow / Malcom (Mayo 2026)

### Arquitectura de Embed Modular para WordPress / BeBuilder

- Refactorización del widget InsightFlow en archivos separados:
  - `widget-loader.js`
  - `powerups-edge-frame.html`
  - `powerups-edge-widget.js`
  - `powerups-edge-widget.css`
- Integración lista para producción en `wp-content/uploads/2026/05/`.
- Corrección de `pointer-events` y tamaño del iframe para que la burbuja sea clicable sin bloquear la página.
- Script inline en **Theme Options → Hooks → Bottom** con configuración pasada al iframe vía query string.

### Pipeline de Ingesta Avanzado (AnalystAgent)

- Nueva función `load_structured_dataframe()` para preparar DataFrames antes del análisis.
- Detección heurística de encabezado real cuando la fila 0 contiene metadatos y el encabezado está sepultado.
- Palabras clave transaccionales usadas como señales: `CIF`, `FOB`, `Cantidad`, `Arancel`, `Aduana`, `NIT`, `Factura`, `Saldo`, entre otras.
- Expansión automática de columnas concatenadas por delimitadores complejos (`|`, `;`).
- Limpieza silenciosa de valores nulos redundantes sin pedir aclaraciones al usuario.
- El agente ahora actúa como **Ingeniero de Datos Senior** experto en archivos corporativos y gubernamentales de Colombia, incluyendo DIAN, RIPS y extractos bancarios.

### ComplianceAgent — Cumplimiento Normativo y Aduanero

- Nuevo agente: `app/agents/compliance_agent.py`.
- Se integra con `app/agents/analyst_agent.py` y se ejecuta después del análisis cuantitativo.
- Agrega en cada reporte el bloque obligatorio:

```text
Diagnóstico de Cumplimiento e Impacto Operativo
```

- El diagnóstico incluye:
  1. **Cruce Arancelario**: identifica partidas arancelarias y advierte implicaciones de aranceles e IVA en Colombia.
  2. **Alertas de Tratados**: revisa países de origen/compra y advierte si se aprovechan o pierden preferencias comerciales.
  3. **Gestión de Riesgos**: alertas sobre INVIMA, consistencia FOB/CIF, posible subfacturación ante DIAN y uso de hubs logísticos como Zonas Francas.

### ModelManager Híbrido Gemini + Ollama

- Actualización de `app/agents/model_manager.py` para soportar modelo local vía Ollama.
- Modelo local por defecto: `llama3.1`.
- Endpoint local por defecto:

```text
http://localhost:11434/api/generate
```

- Nuevos parámetros de enrutamiento:
  - `force_local=True`
  - `sovereignty_mode=True`

- Enrutamiento inteligente:
  - **Ollama local** para estructuración de datos, formateo, generación de scripts locales de Pandas y planes con soberanía de datos estricta.
  - **Gemini** (`gemini-2.0-flash` / `gemini-2.5-flash`) para razonamiento conceptual complejo o prompts que superan la ventana eficiente del modelo local.

- Garantía de soberanía:
  - Cuando se usa Ollama, no se llama a APIs de terceros en esa generación.
  - El procesamiento local mantiene persistencia cero hacia Gemini u otros proveedores cloud.

### Estado Actual del Ecosistema InsightFlow / Malcom

- Widget web funcional en WordPress / BeBuilder.
- Pipeline de análisis reforzado para archivos corporativos y gubernamentales colombianos.
- Diagnóstico normativo y aduanero incorporado a los reportes.
- Soporte híbrido local/cloud para clientes con requerimientos de soberanía extrema de datos.