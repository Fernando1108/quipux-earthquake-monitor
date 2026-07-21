# Arquitectura — Quipux Earthquake Monitor

**Estado:** Arquitectura V1

## Componentes previstos

| Componente | Descripción |
|------------|-------------|
| FastAPI | API REST principal |
| Ingestion Worker | Worker de ingesta periódica desde USGS |
| MongoDB | Almacenamiento de eventos sísmicos, métricas y reportes |
| Airflow | Orquestador de reportes horarios |

> En el bootstrap solo están activos **FastAPI** y **MongoDB**.
