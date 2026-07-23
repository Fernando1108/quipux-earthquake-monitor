# Arquitectura — Quipux Earthquake Monitor

---

## 1. Objetivo de la arquitectura

Proporcionar un sistema de monitoreo sísmico que:

- Ingeste eventos del feed público de USGS de manera continua y confiable.
- Calcule métricas horarias de forma incremental sin reprocesar datos históricos.
- Genere reportes horarios consolidados de manera orquestada y reproducible.
- Exponga los datos a través de una API REST de solo lectura, paginada y filtrable.
- Garantice idempotencia en todas las operaciones de escritura.

---

## 2. Principios

| Principio                     | Aplicación concreta                                                  |
|-------------------------------|----------------------------------------------------------------------|
| Separación de responsabilidades | Rutas, servicios y repositorios en capas independientes            |
| Idempotencia                  | Índices únicos en MongoDB; `insert_if_new` para eventos (captura `DuplicateKeyError`); `replace_one` con `upsert=True` para métricas y reportes |
| Desacoplamiento de procesos   | API, worker e Airflow son procesos separados con ciclos de vida propios |
| API de solo lectura           | FastAPI no escribe ni calcula; solo consulta datos ya persistidos   |
| Sin lógica de negocio en el DAG | Airflow orquesta; `ReportingService` calcula                      |
| Acceso a datos centralizado   | Los repositorios concentran las consultas y escrituras de dominio; `app/database/mongodb.py` gestiona la conexión y `app/database/indexes.py` los índices; las rutas no consultan colecciones directamente |

---

## 3. Componentes

### API REST (`api`)

- Implementada con FastAPI y Uvicorn.
- Expone cinco rutas: `GET /`, `GET /health`, `GET /earthquakes`, `GET /metrics`, `GET /reports`.
- Valida parámetros con Pydantic (`BaseListQueryParams` y subclases).
- Delega todas las consultas a los repositorios a través de dependencias inyectadas.
- No escribe en MongoDB ni invoca servicios de cálculo.

### Worker de ingesta (`ingestion-worker`)

- Proceso asyncio independiente basado en `IngestionWorker`.
- Llama a `IngestionService.run_once()` en un bucle con intervalo configurable (predeterminado: 180 s).
- `IngestionService` orquesta: cliente USGS → transformación → repositorio → métricas.

### DAG de reportes (`airflow-scheduler` / `hourly_report_dag`)

- DAG con schedule `0 * * * *` (UTC), `catchup=False`, `max_active_runs=1`.
- La tarea `generate_hourly_report` resuelve la hora objetivo desde `data_interval_end` del contexto de Airflow.
- Delega el cálculo a `ReportingService` y la persistencia a `ReportRepository`.

### MongoDB (`mongodb`)

- Almacén principal de datos de dominio.
- Tres colecciones: `earthquakes`, `metrics`, `hourly_reports`.
- Índices únicos en `event_id`, `window_start` y `report_date`.

### PostgreSQL (`airflow-postgres`)

- Base de datos exclusiva para los metadatos de Airflow (DAG runs, task instances, conexiones).
- No almacena datos de dominio del sistema.

---

## 4. Capas

Las capas no forman una pila rígida que todos los flujos atraviesan completa.
Su función es agrupar responsabilidades y definir qué puede llamar a qué:

```
Rutas FastAPI
  |-- Endpoints de lectura --> Repositorios --> MongoDB
  |-- (no pasan por servicios de negocio)

Servicios de negocio (usados por worker y Airflow, no por rutas)
  IngestionService --> USGSClient (externo) + EarthquakeRepository + MetricsService
  MetricsService   --> MetricRepository
  ReportingService --> EarthquakeRepository + ReportRepository

Repositorios (concentran consultas y escrituras de dominio)
  EarthquakeRepository  MetricRepository  ReportRepository

Infraestructura de base de datos
  app/database/mongodb.py   -- gestiona conexion Motor/AsyncIOMotorClient
  app/database/indexes.py   -- crea indices en arranque

MongoDB 7 (Motor asyncio)
```

**Reglas de visibilidad:**
- Las rutas no realizan consultas directas a colecciones; invocan repositorios a través de dependencias inyectadas.
- `IngestionService` puede utilizar clientes externos (`USGSClient`), servicios (`MetricsService`) y repositorios (`EarthquakeRepository`).
- `MetricsService` utiliza `MetricRepository`.
- `ReportingService` utiliza `EarthquakeRepository` y `ReportRepository`.
- Los repositorios acceden a MongoDB a través de `app/database/mongodb.py`; no invocan clientes externos.
- Las rutas API no invocan clientes externos.

---

## 5. Flujo de ingesta

```
USGSClient.fetch_features()
    |
    v
[lista de features GeoJSON]
    |
    v
_feature_to_earthquake(feature)
    -- ValueError / ValidationError --> invalid++, continuar con siguiente
    |
    v
EarthquakeRepository.insert_if_new(earthquake)
    -- event_id ya existe (DuplicateKeyError) --> duplicates++, continuar
    |
    v (nuevo evento)
inserted++
    |
    v
MetricsService.update_for_earthquake(earthquake)
    |
    v
MetricRepository.replace_one upsert=True (sobre window_start)
```

Solo los eventos **nuevos** actualizan las métricas. Los duplicados se descartan antes de llegar a `MetricsService`.

---

## 6. Flujo de métricas

Las métricas se calculan por ventana UTC de exactamente una hora (`window_start` / `window_end`).

Por cada evento nuevo:

1. `MetricsService` identifica la ventana horaria del `event_time`.
2. Lee la métrica existente para esa ventana (o crea una vacía).
3. Actualiza `earthquake_count`, `magnitude_count`, `magnitude_sum`, `max_magnitude` y `magnitude_distribution`.
4. Persiste mediante `MetricRepository` con `upsert` sobre `window_start` (índice único).

---

## 7. Flujo de reportes

```
Airflow trigger (0 * * * * UTC)
    |
    v
hourly_report_dag --> generate_hourly_report
    |
    v
_resolve_report_date(context)  <-- data_interval_end del contexto Airflow
    |
    v
ReportingService.generate_hourly_report(report_date)
    |-- EarthquakeRepository: consultar eventos del periodo
    |-- calcular total_events, events_with_magnitude,
    |   average_magnitude, max_magnitude, top_locations
    |
    v
ReportRepository.upsert_report(report)
    replace_one upsert=True sobre report_date
    |
    v
hourly_reports (MongoDB)
    |
    v
GET /reports (API, solo lectura)
```

`report_date` equivale a `period_end`. `period_start = report_date - 1h`. Reejecutar la misma hora llama a `replace_one` con `upsert=True`, actualizando el documento existente.

---

## 8. Flujo de consultas API

```
HTTP GET /earthquakes?page=2&sort=asc
    |
    v
FastAPI route (list_earthquakes)
    |
    v
EarthquakeQueryParams (validacion Pydantic)
  page, page_size, start_time, end_time, sort, min_magnitude, max_magnitude
    -- falla validacion --> HTTP 422
    |
    v
Depends(get_earthquake_repository)  [inyeccion de dependencia]
    |
    v
EarthquakeRepository.list_earthquakes(...)  [acceso a MongoDB]
    |
    v
build_paginated_response(items, page, page_size, total)
    |
    v
PaginatedResponse[Earthquake] --> JSON
```

El mismo patrón aplica para `/metrics` (con `MetricQueryParams`) y `/reports` (con `ReportQueryParams`).

---

## 9. Persistencia e índices

### Colección `earthquakes`

| Índice                                       | Campos                          | Propósito                        |
|----------------------------------------------|---------------------------------|----------------------------------|
| `earthquakes_event_id_unique`                | `event_id` ASC, único           | Deduplicación de eventos USGS    |
| `earthquakes_event_time_desc`                | `event_time` DESC               | Consultas ordenadas por tiempo   |
| `earthquakes_magnitude_asc_event_time_desc`  | `magnitude` ASC + `event_time` DESC | Filtros por magnitud y tiempo |

### Colección `metrics`

| Índice                        | Campos              | Propósito                         |
|-------------------------------|---------------------|-----------------------------------|
| `metrics_window_start_unique` | `window_start` ASC, único | Una sola métrica por ventana |

### Colección `hourly_reports`

| Índice                              | Campos                | Propósito                     |
|-------------------------------------|-----------------------|-------------------------------|
| `hourly_reports_report_date_unique` | `report_date` ASC, único | Un solo reporte por hora   |

`create_indexes()` se invoca desde tres puntos de entrada:

- Arranque de la API (`app/api/main.py` en el lifespan).
- Arranque del ingestion-worker (`app/workers/ingestion_worker.py` en `main()`).
- Tarea de Airflow (`hourly_report_dag.py` en `_generate_report()`), antes de operar con MongoDB.

La operación es idempotente: MongoDB omite silenciosamente los índices que ya existen con las mismas claves y opciones.

---

## 10. Idempotencia

| Operación                   | Mecanismo                                      |
|-----------------------------|------------------------------------------------|
| Insertar evento USGS        | `insert_if_new` → `try insert` / captura `DuplicateKeyError` en `event_id` |
| Actualizar métrica horaria  | `replace_one` con `upsert=True` sobre `window_start` |
| Persistir reporte horario   | `replace_one` con `upsert=True` sobre `report_date`  |

Los mecanismos son distintos por colección: para eventos, un duplicado produce `DuplicateKeyError` sin modificar el documento existente ni las métricas; para métricas y reportes, `replace_one` con `upsert=True` reemplaza el documento. La idempotencia del flujo completo resulta de la combinación de los tres mecanismos, no de los índices únicos solos.

---

## 11. Contenedores y comunicación

```
quipux_network
---------------------------------------------------------------------
  [mongodb :27017] <--- [ingestion-worker]
  [mongodb :27017] <--- [api :8000] <--- host :8000
  [mongodb :27017] <--- airflow-scheduler (hourly_report_dag)

  Airflow cluster:
    airflow-postgres  airflow-api-server (:8080) <--- host :8080
    airflow-scheduler  airflow-dag-processor
    airflow-init (one-shot, Exited 0 tras inicializar)
---------------------------------------------------------------------
Puertos expuestos al host: 8000 (api), 8080 (airflow-api-server), 27017 (mongodb)
```

Todos los servicios comparten la red interna `quipux_network`. Las comunicaciones entre contenedores usan nombres de servicio como hostnames (`mongodb`, `airflow-postgres`, `airflow-api-server`).

`airflow-init` es un servicio de una sola ejecución (`restart: "no"`). Completada la inicialización, aparece como `Exited (0)`, lo cual es el comportamiento esperado.

`airflow-cli` está disponible bajo el perfil `debug` para uso interactivo y ejecución de pruebas del DAG.

---

## 12. Manejo de fallos

### Worker de ingesta

- Si una iteración completa falla (error de red, MongoDB no disponible), `IngestionWorker` registra la excepción y espera el intervalo antes de reintentar.
- Los eventos inválidos (transformación fallida) se contabilizan como `invalid` y se omiten sin detener el proceso.
- `restart: unless-stopped` en Docker Compose garantiza el reinicio automático si el proceso termina inesperadamente.

### Tarea Airflow

- `retries=2` con `retry_delay=5min`: la tarea se reintenta automáticamente hasta dos veces ante fallos de MongoDB u otros errores transitorios.
- `max_active_runs=1` previene solapamiento de ejecuciones del mismo DAG.
- Los errores del repositorio y del servicio propagan hacia Airflow sin ser capturados en el DAG, lo que permite que Airflow registre el fallo y aplique la política de reintentos.

### API

- La API depende de MongoDB para completar su inicialización. Si MongoDB no está disponible durante el arranque, la API puede no completar el ciclo de vida y no responder solicitudes.
- Si una solicitud llega mientras la dependencia de base de datos no está disponible, `get_db()` responde `HTTP 503` con `{"detail": "Database unavailable"}`.
- Los errores inesperados del repositorio producen `HTTP 500`.

---

## 13. Escalabilidad

El diseño actual está orientado a un entorno de desarrollo local con un solo nodo. Las siguientes decisiones facilitan la evolución hacia producción:

- **Repositorios desacoplados**: los repositorios concentran el acceso a MongoDB, lo que reduce el impacto de un cambio de tecnología de persistencia. Sin embargo, dicho cambio también afectaría `app/database/mongodb.py`, `app/database/indexes.py`, la inyección de dependencias, la configuración y posiblemente pruebas y modelos de persistencia.
- **Servicios mayormente sin estado entre ejecuciones**: `ReportingService` es reproducible para una hora dada y el DAG limita `max_active_runs` a 1. Escalar horizontalmente la ingesta requeriría coordinación o particionado, actualizaciones atómicas de métricas y una cola o mecanismo de exclusión para evitar condiciones de carrera en el ciclo lectura-cálculo-reemplazo de métricas. Los índices únicos protegen la inserción de eventos duplicados, pero no resuelven por sí solos todas las condiciones de concurrencia.
- **LocalExecutor → CeleryExecutor**: si se añaden más DAGs concurrentes, el cambio de ejecutor en Airflow no requiere modificar el DAG.
- **Índices compuestos**: el índice `(magnitude, event_time)` en `earthquakes` permite consultas eficientes por magnitud y tiempo sin cambios en el esquema.

---

## 14. Límites actuales

| Límite                          | Descripción                                                          |
|---------------------------------|----------------------------------------------------------------------|
| Sin autenticación en la API     | Las rutas son públicas. No hay API key ni JWT.                       |
| Simple Auth Manager en Airflow  | Adecuado para desarrollo local; no recomendado para producción.      |
| LocalExecutor con paralelismo 1 | Un solo DAG activo a la vez. No escala a múltiples tareas concurrentes. |
| Sin TLS                         | Comunicaciones sin cifrado. Requiere reverse proxy en producción.    |
| Sin política de retención       | Las colecciones crecen indefinidamente. Sin TTL indexes configurados.|
| Worker de ingesta de proceso único | Un solo proceso de ingesta; no hay particionado ni distribución.  |
| PostgreSQL solo para Airflow    | Subutilización si se quisieran agregar más servicios con RDBMS.      |
| Diagrama de arquitectura visual | Pendiente como entregable futuro. El documento actual es textual.    |
