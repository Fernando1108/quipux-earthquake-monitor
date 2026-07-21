from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Quipux Earthquake Monitor"
    app_env: str = "development"
    log_level: str = "INFO"
    mongo_uri: str = "mongodb://mongodb:27017"
    mongo_database: str = "earthquake_monitor"
    usgs_url: str = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson"
    usgs_timeout_seconds: int = 15
    ingestion_interval_seconds: int = 180
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    default_page_size: int = 20
    max_page_size: int = 100

    model_config = {"env_file": ".env"}
