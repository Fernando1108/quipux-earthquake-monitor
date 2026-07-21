from fastapi import FastAPI

from app.config.logging import configure_logging
from app.config.settings import Settings

configure_logging()

settings = Settings()

app = FastAPI(title=settings.app_name)


@app.get("/")
async def root() -> dict:
    return {"message": "Quipux Earthquake Monitor"}
