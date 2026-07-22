"""Unit tests for USGSClient — no live HTTP calls."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.clients import USGSClient
from app.clients.usgs_client import USGSClient as USGSClientDirect


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(coro):
    return asyncio.run(coro)


def make_settings(
    url: str = "https://usgs.example.com/feed.geojson",
    timeout: int = 10,
) -> MagicMock:
    s = MagicMock()
    s.usgs_url = url
    s.usgs_timeout_seconds = timeout
    return s


def make_response(payload: object, status_code: int = 200) -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.json = MagicMock(return_value=payload)
    r.raise_for_status = MagicMock()
    return r


def make_http_client(response: MagicMock) -> MagicMock:
    client = MagicMock(spec=httpx.AsyncClient)
    client.get = AsyncMock(return_value=response)
    return client


VALID_FEATURES = [
    {"type": "Feature", "properties": {"mag": 3.5, "place": "10km N of X"}},
    {"type": "Feature", "properties": {"mag": None, "place": "5km S of Y"}},
]

VALID_PAYLOAD = {"type": "FeatureCollection", "features": VALID_FEATURES}


# ---------------------------------------------------------------------------
# 1. Import from app.clients
# ---------------------------------------------------------------------------

def test_import_from_app_clients():
    assert USGSClient is USGSClientDirect


# ---------------------------------------------------------------------------
# 2. Constructor uses provided Settings values
# ---------------------------------------------------------------------------

def test_constructor_stores_url_and_timeout():
    settings = make_settings(url="https://custom.url/feed", timeout=42)
    client = USGSClient(settings=settings)
    assert client._url == "https://custom.url/feed"
    assert client._timeout == 42


def test_constructor_instantiates_settings_when_none():
    with patch("app.clients.usgs_client.Settings") as MockSettings:
        MockSettings.return_value.usgs_url = "https://default.url"
        MockSettings.return_value.usgs_timeout_seconds = 15
        client = USGSClient()
    MockSettings.assert_called_once()
    assert client._url == "https://default.url"
    assert client._timeout == 15


# ---------------------------------------------------------------------------
# 3. GET receives the configured URL
# ---------------------------------------------------------------------------

def test_get_uses_configured_url():
    settings = make_settings(url="https://usgs.example.com/feed.geojson")
    response = make_response(VALID_PAYLOAD)
    http_client = make_http_client(response)

    run(USGSClient(settings=settings, http_client=http_client).fetch_features())

    http_client.get.assert_awaited_once()
    call_url = http_client.get.call_args.args[0]
    assert call_url == "https://usgs.example.com/feed.geojson"


# ---------------------------------------------------------------------------
# 4. GET receives the configured timeout
# ---------------------------------------------------------------------------

def test_get_uses_configured_timeout():
    settings = make_settings(timeout=7)
    response = make_response(VALID_PAYLOAD)
    http_client = make_http_client(response)

    run(USGSClient(settings=settings, http_client=http_client).fetch_features())

    call_kwargs = http_client.get.call_args.kwargs
    assert call_kwargs.get("timeout") == 7


# ---------------------------------------------------------------------------
# 5. raise_for_status is called
# ---------------------------------------------------------------------------

def test_raise_for_status_is_called():
    settings = make_settings()
    response = make_response(VALID_PAYLOAD)
    http_client = make_http_client(response)

    run(USGSClient(settings=settings, http_client=http_client).fetch_features())

    response.raise_for_status.assert_called_once()


# ---------------------------------------------------------------------------
# 6. Valid payload returns the exact features
# ---------------------------------------------------------------------------

def test_valid_payload_returns_features():
    settings = make_settings()
    response = make_response(VALID_PAYLOAD)
    http_client = make_http_client(response)

    result = run(USGSClient(settings=settings, http_client=http_client).fetch_features())

    assert result is VALID_FEATURES


# ---------------------------------------------------------------------------
# 7. Empty features list is accepted
# ---------------------------------------------------------------------------

def test_empty_features_list_is_accepted():
    settings = make_settings()
    response = make_response({"type": "FeatureCollection", "features": []})
    http_client = make_http_client(response)

    result = run(USGSClient(settings=settings, http_client=http_client).fetch_features())

    assert result == []


# ---------------------------------------------------------------------------
# 8. magnitude null inside a feature is preserved untouched
# ---------------------------------------------------------------------------

def test_null_magnitude_preserved():
    feature = {"type": "Feature", "properties": {"mag": None}}
    settings = make_settings()
    response = make_response({"features": [feature]})
    http_client = make_http_client(response)

    result = run(USGSClient(settings=settings, http_client=http_client).fetch_features())

    assert result[0]["properties"]["mag"] is None


# ---------------------------------------------------------------------------
# 9. Unknown extra USGS fields are preserved untouched
# ---------------------------------------------------------------------------

def test_extra_fields_preserved():
    feature = {"type": "Feature", "bbox": [1, 2, 3], "custom_field": "xyz"}
    settings = make_settings()
    response = make_response({"features": [feature]})
    http_client = make_http_client(response)

    result = run(USGSClient(settings=settings, http_client=http_client).fetch_features())

    assert result[0]["custom_field"] == "xyz"
    assert result[0]["bbox"] == [1, 2, 3]


# ---------------------------------------------------------------------------
# 10. Top-level non-dict raises ValueError
# ---------------------------------------------------------------------------

def test_non_dict_payload_raises_value_error():
    settings = make_settings()
    response = make_response([{"features": []}])
    http_client = make_http_client(response)

    with pytest.raises(ValueError, match="must be a JSON object"):
        run(USGSClient(settings=settings, http_client=http_client).fetch_features())


# ---------------------------------------------------------------------------
# 11. Missing "features" raises ValueError
# ---------------------------------------------------------------------------

def test_missing_features_key_raises_value_error():
    settings = make_settings()
    response = make_response({"type": "FeatureCollection"})
    http_client = make_http_client(response)

    with pytest.raises(ValueError, match="missing required key 'features'"):
        run(USGSClient(settings=settings, http_client=http_client).fetch_features())


# ---------------------------------------------------------------------------
# 12. "features" set to None raises ValueError
# ---------------------------------------------------------------------------

def test_features_none_raises_value_error():
    settings = make_settings()
    response = make_response({"features": None})
    http_client = make_http_client(response)

    with pytest.raises(ValueError, match="must be a list"):
        run(USGSClient(settings=settings, http_client=http_client).fetch_features())


# ---------------------------------------------------------------------------
# 13. "features" as a dict raises ValueError
# ---------------------------------------------------------------------------

def test_features_dict_raises_value_error():
    settings = make_settings()
    response = make_response({"features": {"0": {}}})
    http_client = make_http_client(response)

    with pytest.raises(ValueError, match="must be a list"):
        run(USGSClient(settings=settings, http_client=http_client).fetch_features())


# ---------------------------------------------------------------------------
# 14. A non-dict item inside features raises ValueError
# ---------------------------------------------------------------------------

def test_non_dict_item_in_features_raises_value_error():
    settings = make_settings()
    response = make_response({"features": [{"ok": True}, "not-a-dict"]})
    http_client = make_http_client(response)

    with pytest.raises(ValueError, match="index 1"):
        run(USGSClient(settings=settings, http_client=http_client).fetch_features())


# ---------------------------------------------------------------------------
# 15. HTTP status errors propagate
# ---------------------------------------------------------------------------

def test_http_status_error_propagates():
    settings = make_settings()
    response = MagicMock()
    response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            "404", request=MagicMock(), response=MagicMock()
        )
    )
    http_client = make_http_client(response)

    with pytest.raises(httpx.HTTPStatusError):
        run(USGSClient(settings=settings, http_client=http_client).fetch_features())


# ---------------------------------------------------------------------------
# 16. Timeout/network errors propagate
# ---------------------------------------------------------------------------

def test_timeout_error_propagates():
    settings = make_settings()
    http_client = MagicMock(spec=httpx.AsyncClient)
    http_client.get = AsyncMock(side_effect=httpx.TimeoutException("timed out"))

    with pytest.raises(httpx.TimeoutException):
        run(USGSClient(settings=settings, http_client=http_client).fetch_features())


def test_connect_error_propagates():
    settings = make_settings()
    http_client = MagicMock(spec=httpx.AsyncClient)
    http_client.get = AsyncMock(side_effect=httpx.ConnectError("conn refused"))

    with pytest.raises(httpx.ConnectError):
        run(USGSClient(settings=settings, http_client=http_client).fetch_features())


# ---------------------------------------------------------------------------
# 17. JSON decoding errors propagate
# ---------------------------------------------------------------------------

def test_json_decode_error_propagates():
    settings = make_settings()
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(side_effect=json.JSONDecodeError("bad json", "", 0))
    http_client = make_http_client(response)

    with pytest.raises(json.JSONDecodeError):
        run(USGSClient(settings=settings, http_client=http_client).fetch_features())


# ---------------------------------------------------------------------------
# 18. Injected AsyncClient is NOT closed
# ---------------------------------------------------------------------------

def test_injected_client_not_closed_on_success():
    settings = make_settings()
    response = make_response(VALID_PAYLOAD)
    http_client = make_http_client(response)
    http_client.aclose = AsyncMock()

    run(USGSClient(settings=settings, http_client=http_client).fetch_features())

    http_client.aclose.assert_not_awaited()


def test_injected_client_not_closed_on_failure():
    settings = make_settings()
    http_client = MagicMock(spec=httpx.AsyncClient)
    http_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
    http_client.aclose = AsyncMock()

    with pytest.raises(httpx.TimeoutException):
        run(USGSClient(settings=settings, http_client=http_client).fetch_features())

    http_client.aclose.assert_not_awaited()


# ---------------------------------------------------------------------------
# 19. Internally created AsyncClient is closed after success
# ---------------------------------------------------------------------------

def test_internal_client_closed_after_success():
    settings = make_settings()
    mock_internal = make_http_client(make_response(VALID_PAYLOAD))
    mock_internal.__aenter__ = AsyncMock(return_value=mock_internal)
    mock_internal.__aexit__ = AsyncMock(return_value=False)

    with patch("app.clients.usgs_client.httpx.AsyncClient", return_value=mock_internal):
        run(USGSClient(settings=settings).fetch_features())

    mock_internal.__aexit__.assert_awaited_once()


# ---------------------------------------------------------------------------
# 20. Internally created AsyncClient is closed after HTTP failure
# ---------------------------------------------------------------------------

def test_internal_client_closed_after_http_failure():
    settings = make_settings()
    response = MagicMock()
    response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError("500", request=MagicMock(), response=MagicMock())
    )
    mock_internal = MagicMock(spec=httpx.AsyncClient)
    mock_internal.get = AsyncMock(return_value=response)
    mock_internal.__aenter__ = AsyncMock(return_value=mock_internal)
    mock_internal.__aexit__ = AsyncMock(return_value=False)

    with patch("app.clients.usgs_client.httpx.AsyncClient", return_value=mock_internal):
        with pytest.raises(httpx.HTTPStatusError):
            run(USGSClient(settings=settings).fetch_features())

    mock_internal.__aexit__.assert_awaited_once()


# ---------------------------------------------------------------------------
# 21. Internally created AsyncClient is closed after payload validation failure
# ---------------------------------------------------------------------------

def test_internal_client_closed_after_validation_failure():
    settings = make_settings()
    mock_internal = make_http_client(make_response({"no_features": True}))
    mock_internal.__aenter__ = AsyncMock(return_value=mock_internal)
    mock_internal.__aexit__ = AsyncMock(return_value=False)

    with patch("app.clients.usgs_client.httpx.AsyncClient", return_value=mock_internal):
        with pytest.raises(ValueError):
            run(USGSClient(settings=settings).fetch_features())

    mock_internal.__aexit__.assert_awaited_once()


# ---------------------------------------------------------------------------
# 22. Returned feature dicts are not copied or mutated
# ---------------------------------------------------------------------------

def test_returned_features_are_original_objects():
    feature = {"type": "Feature", "properties": {"mag": 5.0}}
    features_list = [feature]
    settings = make_settings()
    response = make_response({"features": features_list})
    http_client = make_http_client(response)

    result = run(USGSClient(settings=settings, http_client=http_client).fetch_features())

    assert result is features_list
    assert result[0] is feature
