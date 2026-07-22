"""HTTP client responsible for fetching earthquake data from the USGS GeoJSON feed."""

import httpx

from app.config.settings import Settings


class USGSClient:
    """Fetch the raw GeoJSON feature list from the USGS earthquake feed.

    The client performs no transformation: it validates the envelope shape and
    returns the feature dicts exactly as received from the API.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if settings is None:
            settings = Settings()

        self._url: str = settings.usgs_url
        self._timeout: int = settings.usgs_timeout_seconds
        self._injected_client: httpx.AsyncClient | None = http_client

    async def fetch_features(self) -> list[dict[str, object]]:
        """GET the USGS feed and return the validated features list.

        Raises:
            ValueError: if the top-level payload is not a dict, lacks
                "features", or "features" is not a list of dicts.
            httpx.HTTPStatusError: propagated from raise_for_status().
            httpx.TransportError: propagated on network/timeout failures.
            Exception: JSON decoding errors propagate unchanged.
        """
        if self._injected_client is not None:
            return await self._request(self._injected_client)

        async with httpx.AsyncClient() as client:
            return await self._request(client)

    async def _request(self, client: httpx.AsyncClient) -> list[dict[str, object]]:
        response = await client.get(self._url, timeout=self._timeout)
        response.raise_for_status()
        payload = response.json()
        return self._validate_payload(payload)

    @staticmethod
    def _validate_payload(payload: object) -> list[dict[str, object]]:
        if not isinstance(payload, dict):
            raise ValueError(
                f"USGS response must be a JSON object, got {type(payload).__name__}"
            )
        if "features" not in payload:
            raise ValueError("USGS response is missing required key 'features'")
        features = payload["features"]
        if not isinstance(features, list):
            raise ValueError(
                f"'features' must be a list, got {type(features).__name__}"
            )
        for i, item in enumerate(features):
            if not isinstance(item, dict):
                raise ValueError(
                    f"Item at index {i} in 'features' must be a dict, "
                    f"got {type(item).__name__}"
                )
        return features
