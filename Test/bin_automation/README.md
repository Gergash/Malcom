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