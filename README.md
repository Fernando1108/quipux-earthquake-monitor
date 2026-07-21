# Quipux Earthquake Monitor

**Estado:** Bootstrap inicial

## Requisitos

- Docker
- Docker Compose

## Inicio rápido

```bash
cp .env.example .env
docker compose up --build
```

## URLs

| Servicio | URL |
|----------|-----|
| API | http://localhost:8000 |
| Swagger | http://localhost:8000/docs |

> La lógica de negocio (ingesta USGS, métricas, reportes) aún no está implementada.
