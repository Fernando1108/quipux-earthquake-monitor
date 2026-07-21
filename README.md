# Quipux Earthquake Monitor

**Estado:** Fase 3 â€” Modelo de dominio

## Requisitos

- Docker
- Docker Compose

## Inicio rÃ¡pido

```bash
cp .env.example .env
docker compose up --build
```

## URLs

| Servicio | URL |
|----------|-----|
| API | http://localhost:8000 |
| Swagger | http://localhost:8000/docs |

## Pruebas

```bash
docker compose build
docker compose run --rm api pytest
docker compose run --rm api pytest --cov=app --cov-report=term-missing
```

> La lógica de negocio (ingesta USGS, métricas, reportes) aún no está implementada.

