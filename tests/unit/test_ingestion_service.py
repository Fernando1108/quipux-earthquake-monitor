"""Unit tests for IngestionService and IngestionResult — all I/O is mocked."""

import asyncio
import inspect
import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.earthquake import Earthquake
from app.services import IngestionResult, IngestionService, MetricsService
from app.services.ingestion_service import _feature_to_earthquake

# ---------------------------------------------------------------------------
# Constants / helpers
# ---------------------------------------------------------------------------

UTC = timezone.utc

EVENT_TIME = datetime(2024, 6, 1, 12, 15, 0, tzinfo=UTC)
# Derive EPOCH_MS from EVENT_TIME so the two stay in sync.
EPOCH_MS = int(EVENT_TIME.timestamp() * 1000)


def run(coro):
    return asyncio.run(coro)


def make_feature(
    event_id: object = "us7000test",
    mag: object = 3.5,
    place: object = "10km N of City",
    time: object = None,
    longitude: object = -100.0,
    latitude: object = 35.0,
    depth: object = 10.0,
    extra_props: dict | None = None,
    extra_coords: list | None = None,
) -> dict:
    """Build a minimal valid USGS-style feature dict."""
    t = time if time is not None else EPOCH_MS
    props: dict = {"mag": mag, "place": place, "time": t}
    if extra_props:
        props.update(extra_props)
    coords: list = [longitude, latitude, depth]
    if extra_coords:
        coords.extend(extra_coords)
    return {
        "id": event_id,
        "properties": props,
        "geometry": {"coordinates": coords},
    }


def make_earthquake(**overrides) -> Earthquake:
    defaults: dict = dict(
        event_id="us7000test",
        magnitude=3.5,
        location="10km N of City",
        latitude=35.0,
        longitude=-100.0,
        depth=10.0,
        event_time=EVENT_TIME,
    )
    defaults.update(overrides)
    return Earthquake(**defaults)


def make_service(
    features: list[dict] | None = None,
    insert_returns: list[bool] | None = None,
) -> tuple[IngestionService, MagicMock, MagicMock, MagicMock]:
    """Return (service, mock_client, mock_repo, mock_metrics) with defaults."""
    client = MagicMock()
    client.fetch_features = AsyncMock(return_value=features if features is not None else [])

    repo = MagicMock()
    if insert_returns is None:
        repo.insert_if_new = AsyncMock(return_value=True)
    else:
        repo.insert_if_new = AsyncMock(side_effect=insert_returns)

    metrics = MagicMock()
    metrics.update_for_earthquake = AsyncMock(return_value=MagicMock())

    svc = IngestionService(
        client=client,
        earthquake_repository=repo,
        metrics_service=metrics,
    )
    return svc, client, repo, metrics


# ---------------------------------------------------------------------------
# A. Imports and construction
# ---------------------------------------------------------------------------


def test_ingestion_result_importable_from_app_services():
    from app.services import IngestionResult as IR

    assert IR is IngestionResult


def test_ingestion_service_importable_from_app_services():
    from app.services import IngestionService as IS

    assert IS is IngestionService


def test_metrics_service_still_exported():
    from app.services import MetricsService as MS

    assert MS is MetricsService


def test_all_three_names_in_dunder_all():
    import app.services as mod

    assert set(mod.__all__) == {"IngestionResult", "IngestionService", "MetricsService", "ReportingService"}


def test_injected_client_preserved():
    client = MagicMock()
    with (
        patch("app.services.ingestion_service.EarthquakeRepository"),
        patch("app.services.ingestion_service.MetricsService"),
    ):
        svc = IngestionService(client=client)
    assert svc._client is client


def test_injected_repo_preserved():
    repo = MagicMock()
    with (
        patch("app.services.ingestion_service.USGSClient"),
        patch("app.services.ingestion_service.MetricsService"),
    ):
        svc = IngestionService(earthquake_repository=repo)
    assert svc._earthquake_repository is repo


def test_injected_metrics_service_preserved():
    metrics = MagicMock()
    with (
        patch("app.services.ingestion_service.USGSClient"),
        patch("app.services.ingestion_service.EarthquakeRepository"),
    ):
        svc = IngestionService(metrics_service=metrics)
    assert svc._metrics_service is metrics


def test_missing_client_created_exactly_once():
    with patch("app.services.ingestion_service.USGSClient") as MockClient:
        instance = MagicMock()
        MockClient.return_value = instance
        svc = IngestionService(
            earthquake_repository=MagicMock(), metrics_service=MagicMock()
        )
        MockClient.assert_called_once_with()
        assert svc._client is instance


def test_missing_repo_created_exactly_once():
    with patch("app.services.ingestion_service.EarthquakeRepository") as MockRepo:
        instance = MagicMock()
        MockRepo.return_value = instance
        svc = IngestionService(client=MagicMock(), metrics_service=MagicMock())
        MockRepo.assert_called_once_with()
        assert svc._earthquake_repository is instance


def test_missing_metrics_service_created_exactly_once():
    with patch("app.services.ingestion_service.MetricsService") as MockMetrics:
        instance = MagicMock()
        MockMetrics.return_value = instance
        svc = IngestionService(client=MagicMock(), earthquake_repository=MagicMock())
        MockMetrics.assert_called_once_with()
        assert svc._metrics_service is instance


def test_supplied_client_not_replaced():
    client = MagicMock()
    with patch("app.services.ingestion_service.USGSClient") as MockClient:
        IngestionService(
            client=client,
            earthquake_repository=MagicMock(),
            metrics_service=MagicMock(),
        )
        MockClient.assert_not_called()


def test_supplied_repo_not_replaced():
    repo = MagicMock()
    with patch("app.services.ingestion_service.EarthquakeRepository") as MockRepo:
        IngestionService(
            client=MagicMock(),
            earthquake_repository=repo,
            metrics_service=MagicMock(),
        )
        MockRepo.assert_not_called()


def test_supplied_metrics_service_not_replaced():
    metrics = MagicMock()
    with patch("app.services.ingestion_service.MetricsService") as MockMetrics:
        IngestionService(
            client=MagicMock(),
            earthquake_repository=MagicMock(),
            metrics_service=metrics,
        )
        MockMetrics.assert_not_called()


# ---------------------------------------------------------------------------
# B. Basic iteration
# ---------------------------------------------------------------------------


def test_fetch_features_awaited_exactly_once():
    svc, client, _, _ = make_service()
    run(svc.run_once())
    client.fetch_features.assert_awaited_once()


def test_empty_list_returns_all_zero_counters():
    svc, _, _, _ = make_service(features=[])
    result = run(svc.run_once())
    assert result == IngestionResult(fetched=0, inserted=0, duplicates=0, invalid=0)


def test_fetched_equals_feature_count():
    features = [make_feature(event_id=f"id{i}") for i in range(5)]
    svc, _, _, _ = make_service(features=features)
    result = run(svc.run_once())
    assert result.fetched == 5


def test_result_is_ingestion_result_instance():
    svc, _, _, _ = make_service()
    result = run(svc.run_once())
    assert isinstance(result, IngestionResult)


def test_result_is_frozen():
    svc, _, _, _ = make_service()
    result = run(svc.run_once())
    with pytest.raises((AttributeError, TypeError)):
        result.inserted = 99  # type: ignore[misc]


def test_consecutive_runs_return_distinct_objects():
    svc, _, _, _ = make_service()
    r1 = run(svc.run_once())
    r2 = run(svc.run_once())
    assert r1 is not r2


def test_one_info_summary_logged_after_successful_iteration(caplog):
    svc, _, _, _ = make_service(features=[make_feature()])
    with caplog.at_level(logging.INFO, logger="app.services.ingestion_service"):
        run(svc.run_once())
    info_records = [r for r in caplog.records if r.levelname == "INFO"]
    assert len(info_records) == 1
    msg = info_records[0].message
    assert "fetched" in msg
    assert "inserted" in msg
    assert "duplicates" in msg
    assert "invalid" in msg


def test_info_summary_contains_correct_values(caplog):
    features = [make_feature(event_id="f0"), make_feature(event_id="f1")]
    svc, _, _, _ = make_service(features=features, insert_returns=[True, False])
    with caplog.at_level(logging.INFO, logger="app.services.ingestion_service"):
        run(svc.run_once())
    info_records = [r for r in caplog.records if r.levelname == "INFO"]
    msg = info_records[0].message
    assert "fetched=2" in msg
    assert "inserted=1" in msg
    assert "duplicates=1" in msg
    assert "invalid=0" in msg


# ---------------------------------------------------------------------------
# C. Transformation
# ---------------------------------------------------------------------------


def test_transform_event_id():
    eq = _feature_to_earthquake(make_feature(event_id="usp000abc"))
    assert eq.event_id == "usp000abc"


def test_transform_magnitude():
    eq = _feature_to_earthquake(make_feature(mag=5.2))
    assert eq.magnitude == pytest.approx(5.2)


def test_transform_location():
    eq = _feature_to_earthquake(make_feature(place="15km SE of Reno"))
    assert eq.location == "15km SE of Reno"


def test_transform_longitude():
    eq = _feature_to_earthquake(make_feature(longitude=-122.4))
    assert eq.longitude == pytest.approx(-122.4)


def test_transform_latitude():
    eq = _feature_to_earthquake(make_feature(latitude=37.8))
    assert eq.latitude == pytest.approx(37.8)


def test_transform_depth():
    eq = _feature_to_earthquake(make_feature(depth=25.3))
    assert eq.depth == pytest.approx(25.3)


def test_transform_epoch_ms_to_utc_datetime():
    eq = _feature_to_earthquake(make_feature(time=EPOCH_MS))
    expected = datetime.fromtimestamp(EPOCH_MS / 1000, tz=UTC)
    assert eq.event_time == expected
    assert eq.event_time.tzinfo is not None


def test_transform_fractional_milliseconds():
    ms = EPOCH_MS + 500  # +0.5 s
    eq = _feature_to_earthquake(make_feature(time=ms))
    expected = datetime.fromtimestamp(ms / 1000, tz=UTC)
    assert eq.event_time == expected


def test_transform_missing_mag_gives_none():
    feature = make_feature()
    del feature["properties"]["mag"]
    eq = _feature_to_earthquake(feature)
    assert eq.magnitude is None


def test_transform_explicit_null_mag_gives_none():
    eq = _feature_to_earthquake(make_feature(mag=None))
    assert eq.magnitude is None


def test_transform_missing_place_gives_none():
    feature = make_feature()
    del feature["properties"]["place"]
    eq = _feature_to_earthquake(feature)
    assert eq.location is None


def test_transform_explicit_null_place_gives_none():
    eq = _feature_to_earthquake(make_feature(place=None))
    assert eq.location is None


def test_transform_ignored_extra_properties_fields():
    feature = make_feature(extra_props={"felt": 12, "alert": "green", "unknown_key": True})
    eq = _feature_to_earthquake(feature)
    assert eq.event_id == feature["id"]


def test_transform_ignored_extra_coordinates():
    feature = make_feature(extra_coords=[999.0, 888.0])
    eq = _feature_to_earthquake(feature)
    assert eq.longitude == pytest.approx(-100.0)
    assert eq.latitude == pytest.approx(35.0)
    assert eq.depth == pytest.approx(10.0)


def test_transform_does_not_mutate_feature():
    feature = make_feature()
    props_before = dict(feature["properties"])
    geometry_before = dict(feature["geometry"])
    coords_before = list(feature["geometry"]["coordinates"])
    _feature_to_earthquake(feature)
    assert feature["properties"] == props_before
    assert feature["geometry"] == geometry_before
    assert feature["geometry"]["coordinates"] == coords_before


def test_transform_negative_magnitude_valid():
    eq = _feature_to_earthquake(make_feature(mag=-0.5))
    assert eq.magnitude == pytest.approx(-0.5)


def test_transform_integer_coords_accepted():
    eq = _feature_to_earthquake(make_feature(longitude=-100, latitude=35, depth=10))
    assert eq.longitude == pytest.approx(-100.0)
    assert eq.latitude == pytest.approx(35.0)
    assert eq.depth == pytest.approx(10.0)


def test_transform_returns_earthquake_instance():
    eq = _feature_to_earthquake(make_feature())
    assert isinstance(eq, Earthquake)


# ---------------------------------------------------------------------------
# D. New events and duplicates
# ---------------------------------------------------------------------------


def test_valid_feature_calls_insert_if_new_once():
    svc, _, repo, _ = make_service(features=[make_feature()])
    run(svc.run_once())
    repo.insert_if_new.assert_awaited_once()


def test_new_event_calls_metrics_once():
    svc, _, _, metrics = make_service(
        features=[make_feature()], insert_returns=[True]
    )
    run(svc.run_once())
    metrics.update_for_earthquake.assert_awaited_once()


def test_same_earthquake_instance_sent_to_repo_and_metrics():
    svc, _, repo, metrics = make_service(
        features=[make_feature()], insert_returns=[True]
    )
    run(svc.run_once())
    eq_to_repo = repo.insert_if_new.call_args[0][0]
    eq_to_metrics = metrics.update_for_earthquake.call_args[0][0]
    assert eq_to_repo is eq_to_metrics


def test_inserted_increments_for_new_event():
    svc, _, _, _ = make_service(features=[make_feature()], insert_returns=[True])
    result = run(svc.run_once())
    assert result.inserted == 1


def test_duplicate_increments_duplicates_counter():
    svc, _, _, _ = make_service(features=[make_feature()], insert_returns=[False])
    result = run(svc.run_once())
    assert result.duplicates == 1


def test_duplicate_does_not_call_metrics():
    svc, _, _, metrics = make_service(features=[make_feature()], insert_returns=[False])
    run(svc.run_once())
    metrics.update_for_earthquake.assert_not_awaited()


def test_mixed_new_and_duplicate_correct_counters():
    features = [make_feature(event_id=f"id{i}") for i in range(4)]
    svc, _, _, _ = make_service(
        features=features, insert_returns=[True, False, True, False]
    )
    result = run(svc.run_once())
    assert result.inserted == 2
    assert result.duplicates == 2
    assert result.fetched == 4
    assert result.invalid == 0


def test_later_features_continue_after_duplicate():
    features = [make_feature(event_id="dup"), make_feature(event_id="new")]
    svc, _, repo, _ = make_service(features=features, insert_returns=[False, True])
    result = run(svc.run_once())
    assert repo.insert_if_new.await_count == 2
    assert result.duplicates == 1
    assert result.inserted == 1


def test_source_order_preserved_in_repo_calls():
    features = [make_feature(event_id=f"id{i}") for i in range(3)]
    svc, _, repo, _ = make_service(
        features=features, insert_returns=[True, True, True]
    )
    run(svc.run_once())
    calls = [c[0][0].event_id for c in repo.insert_if_new.call_args_list]
    assert calls == ["id0", "id1", "id2"]


def test_processing_is_sequential():
    """insert_if_new is awaited in feature-list order with no concurrency."""
    order: list[str] = []

    async def tracked_insert(eq: Earthquake) -> bool:
        order.append(eq.event_id)
        return True

    features = [make_feature(event_id=f"id{i}") for i in range(3)]
    svc, _, repo, _ = make_service(features=features)
    repo.insert_if_new = tracked_insert
    run(svc.run_once())
    assert order == ["id0", "id1", "id2"]


# ---------------------------------------------------------------------------
# E. Invalid individual features
# ---------------------------------------------------------------------------

# Build a feature that is missing its "id" key.
_FEATURE_MISSING_ID = {
    "properties": {"mag": 1.0, "place": "X", "time": EPOCH_MS},
    "geometry": {"coordinates": [-100.0, 35.0, 10.0]},
}

_INVALID_FEATURE_CASES: list[tuple[dict, str]] = [
    (_FEATURE_MISSING_ID, "missing_id"),
    (
        {"id": 123, "properties": {"mag": 1.0, "place": "X", "time": EPOCH_MS},
         "geometry": {"coordinates": [-100.0, 35.0, 10.0]}},
        "numeric_id",
    ),
    ({"id": "x", "geometry": {"coordinates": [-100.0, 35.0, 10.0]}}, "missing_properties"),
    (
        {"id": "x", "properties": "notadict",
         "geometry": {"coordinates": [-100.0, 35.0, 10.0]}},
        "properties_not_dict",
    ),
    (
        {"id": "x", "properties": {"mag": 1.0, "place": "X", "time": EPOCH_MS}},
        "missing_geometry",
    ),
    (
        {"id": "x", "properties": {"mag": 1.0, "place": "X", "time": EPOCH_MS},
         "geometry": "notadict"},
        "geometry_not_dict",
    ),
    (
        {"id": "x", "properties": {"mag": 1.0, "place": "X", "time": EPOCH_MS},
         "geometry": {}},
        "missing_coordinates",
    ),
    (
        {"id": "x", "properties": {"mag": 1.0, "place": "X", "time": EPOCH_MS},
         "geometry": {"coordinates": "notalist"}},
        "coordinates_not_list",
    ),
    (
        {"id": "x", "properties": {"mag": 1.0, "place": "X", "time": EPOCH_MS},
         "geometry": {"coordinates": [-100.0, 35.0]}},
        "fewer_than_3_coords",
    ),
    (
        {"id": "x", "properties": {"mag": 1.0, "place": "X"},
         "geometry": {"coordinates": [-100.0, 35.0, 10.0]}},
        "missing_time",
    ),
    (make_feature(time="2024-01-01T00:00:00Z"), "string_time"),
    (make_feature(time=True), "bool_time"),
    (make_feature(time=float("nan")), "nan_time"),
    (make_feature(time=float("inf")), "inf_time"),
    (make_feature(time=float("-inf")), "neginf_time"),
    (make_feature(latitude=91.0), "invalid_latitude"),
    (make_feature(longitude=181.0), "invalid_longitude"),
    (make_feature(depth=-1.0), "negative_depth"),
    (make_feature(mag="3.5"), "string_mag"),
    (make_feature(mag=True), "bool_mag"),
    (make_feature(mag=float("nan")), "nan_mag"),
    (make_feature(mag=float("inf")), "inf_mag"),
    (make_feature(place=42), "numeric_location"),
    (make_feature(longitude="bad"), "string_longitude"),
    (make_feature(latitude=True), "bool_latitude"),
    (make_feature(depth=float("nan")), "nan_depth"),
]


@pytest.mark.parametrize("bad_feature,description", _INVALID_FEATURE_CASES)
def test_invalid_feature_increments_invalid(bad_feature, description):
    svc, _, repo, metrics = make_service(features=[bad_feature])
    result = run(svc.run_once())
    assert result.invalid == 1, f"Expected invalid=1 for case '{description}'"
    assert result.inserted == 0
    assert result.duplicates == 0


@pytest.mark.parametrize("bad_feature,description", _INVALID_FEATURE_CASES)
def test_invalid_feature_logs_warning_with_index(bad_feature, description, caplog):
    svc, _, _, _ = make_service(features=[bad_feature])
    with caplog.at_level(logging.WARNING, logger="app.services.ingestion_service"):
        run(svc.run_once())
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert warnings, f"No WARNING logged for '{description}'"
    # Feature is at index 0.
    assert "0" in warnings[0].message, f"Index not in warning for '{description}'"


@pytest.mark.parametrize("bad_feature,description", _INVALID_FEATURE_CASES)
def test_invalid_feature_does_not_call_repo(bad_feature, description):
    svc, _, repo, _ = make_service(features=[bad_feature])
    run(svc.run_once())
    repo.insert_if_new.assert_not_awaited()


@pytest.mark.parametrize("bad_feature,description", _INVALID_FEATURE_CASES)
def test_invalid_feature_does_not_call_metrics(bad_feature, description):
    svc, _, _, metrics = make_service(features=[bad_feature])
    run(svc.run_once())
    metrics.update_for_earthquake.assert_not_awaited()


def test_invalid_feature_raw_content_not_logged(caplog):
    bad_feature = make_feature(latitude=91.0)
    svc, _, _, _ = make_service(features=[bad_feature])
    with caplog.at_level(logging.WARNING, logger="app.services.ingestion_service"):
        run(svc.run_once())
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert warnings
    msg = warnings[0].message
    # The full nested structures must not appear in the log.
    assert str(bad_feature["geometry"]) not in msg
    assert str(bad_feature["properties"]) not in msg


def test_invalid_feature_later_valid_features_still_processed():
    bad = make_feature(latitude=91.0)
    good = make_feature(event_id="good_id")
    svc, _, repo, _ = make_service(features=[bad, good], insert_returns=[True])
    result = run(svc.run_once())
    assert result.invalid == 1
    assert result.inserted == 1
    repo.insert_if_new.assert_awaited_once()


def test_multiple_invalid_features_counted_separately():
    bad1 = make_feature(event_id="b1", latitude=91.0)
    bad2 = make_feature(event_id="b2", longitude=181.0)
    svc, _, _, _ = make_service(features=[bad1, bad2])
    result = run(svc.run_once())
    assert result.invalid == 2


def test_warning_includes_feature_index_for_second_invalid_feature(caplog):
    good = make_feature(event_id="good")
    bad = make_feature(event_id="bad", latitude=91.0)
    svc, _, _, _ = make_service(features=[good, bad], insert_returns=[True])
    with caplog.at_level(logging.WARNING, logger="app.services.ingestion_service"):
        run(svc.run_once())
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert warnings
    # Bad feature is at index 1.
    assert "1" in warnings[0].message


def test_mixed_new_duplicate_invalid_correct_counters():
    features = [
        make_feature(event_id="new"),
        make_feature(event_id="bad", latitude=91.0),
        make_feature(event_id="dup"),
    ]
    svc, _, _, _ = make_service(
        features=features, insert_returns=[True, False]
    )
    result = run(svc.run_once())
    assert result.inserted == 1
    assert result.invalid == 1
    assert result.duplicates == 1
    assert result.fetched == 3


# ---------------------------------------------------------------------------
# F. Error propagation
# ---------------------------------------------------------------------------


def test_fetch_error_propagates():
    svc, client, _, _ = make_service()
    client.fetch_features.side_effect = RuntimeError("network down")
    with pytest.raises(RuntimeError, match="network down"):
        run(svc.run_once())


def test_no_downstream_calls_after_fetch_failure():
    svc, client, repo, metrics = make_service()
    client.fetch_features.side_effect = RuntimeError("network down")
    with pytest.raises(RuntimeError):
        run(svc.run_once())
    repo.insert_if_new.assert_not_awaited()
    metrics.update_for_earthquake.assert_not_awaited()


def test_repository_error_propagates():
    svc, _, repo, _ = make_service(features=[make_feature()])
    repo.insert_if_new.side_effect = RuntimeError("db error")
    with pytest.raises(RuntimeError, match="db error"):
        run(svc.run_once())


def test_metrics_error_propagates():
    svc, _, _, metrics = make_service(
        features=[make_feature()], insert_returns=[True]
    )
    metrics.update_for_earthquake.side_effect = RuntimeError("metrics error")
    with pytest.raises(RuntimeError, match="metrics error"):
        run(svc.run_once())


def test_metrics_not_called_when_insert_fails():
    svc, _, repo, metrics = make_service(features=[make_feature()])
    repo.insert_if_new.side_effect = RuntimeError("db error")
    with pytest.raises(RuntimeError):
        run(svc.run_once())
    metrics.update_for_earthquake.assert_not_awaited()


def test_later_features_not_processed_after_repo_failure():
    features = [make_feature(event_id="f0"), make_feature(event_id="f1")]
    svc, _, repo, _ = make_service(features=features)
    repo.insert_if_new.side_effect = RuntimeError("db error")
    with pytest.raises(RuntimeError):
        run(svc.run_once())
    assert repo.insert_if_new.await_count == 1


def test_later_features_not_processed_after_metrics_failure():
    features = [make_feature(event_id="f0"), make_feature(event_id="f1")]
    svc, _, repo, metrics = make_service(
        features=features, insert_returns=[True, True]
    )
    metrics.update_for_earthquake.side_effect = RuntimeError("metrics error")
    with pytest.raises(RuntimeError):
        run(svc.run_once())
    assert repo.insert_if_new.await_count == 1


def test_no_successful_result_after_iteration_level_failure():
    svc, client, _, _ = make_service()
    client.fetch_features.side_effect = RuntimeError("fail")
    result = None
    with pytest.raises(RuntimeError):
        result = run(svc.run_once())
    assert result is None


# ---------------------------------------------------------------------------
# G. Architecture
# ---------------------------------------------------------------------------


def _source() -> str:
    import app.services.ingestion_service as mod

    return inspect.getsource(mod)


def test_no_motor_or_pymongo_import():
    src = _source()
    assert "motor" not in src
    assert "pymongo" not in src


def test_no_httpx_import():
    src = _source()
    assert "import httpx" not in src


def test_no_asyncio_sleep():
    src = _source()
    assert "asyncio.sleep" not in src


def test_no_asyncio_gather():
    src = _source()
    assert "asyncio.gather" not in src


def test_no_create_task():
    src = _source()
    assert "create_task" not in src


def test_no_task_group():
    src = _source()
    assert "TaskGroup" not in src


def test_no_while_true_loop():
    src = _source()
    assert "while True" not in src


def test_no_direct_collection_access():
    src = _source()
    assert "_collection" not in src


# ---------------------------------------------------------------------------
# H. _ms_to_utc exception translation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("exc_type", [OverflowError, OSError, ValueError])
def test_ms_to_utc_wraps_fromtimestamp_error_in_value_error(exc_type):
    from app.services.ingestion_service import _ms_to_utc

    with patch(
        "app.services.ingestion_service.datetime",
        wraps=datetime,
    ) as mock_dt:
        mock_dt.fromtimestamp.side_effect = exc_type("platform error")
        with pytest.raises(ValueError, match="USGS timestamp is invalid"):
            _ms_to_utc(EPOCH_MS)


@pytest.mark.parametrize("exc_type", [OverflowError, OSError, ValueError])
def test_ms_to_utc_original_exception_is_cause(exc_type):
    from app.services.ingestion_service import _ms_to_utc

    original = exc_type("platform error")
    with patch(
        "app.services.ingestion_service.datetime",
        wraps=datetime,
    ) as mock_dt:
        mock_dt.fromtimestamp.side_effect = original
        with pytest.raises(ValueError) as exc_info:
            _ms_to_utc(EPOCH_MS)
    assert exc_info.value.__cause__ is original


# ---------------------------------------------------------------------------
# I. Unexpected transformation errors propagate
# ---------------------------------------------------------------------------


def test_unexpected_transformation_error_propagates():
    svc, _, repo, metrics = make_service(features=[make_feature()])
    with patch(
        "app.services.ingestion_service._feature_to_earthquake",
        side_effect=RuntimeError("unexpected transformation bug"),
    ):
        with pytest.raises(RuntimeError, match="unexpected transformation bug"):
            run(svc.run_once())


def test_unexpected_transformation_error_repo_not_called():
    svc, _, repo, metrics = make_service(features=[make_feature()])
    with patch(
        "app.services.ingestion_service._feature_to_earthquake",
        side_effect=RuntimeError("unexpected transformation bug"),
    ):
        with pytest.raises(RuntimeError):
            run(svc.run_once())
    repo.insert_if_new.assert_not_awaited()


def test_unexpected_transformation_error_metrics_not_called():
    svc, _, repo, metrics = make_service(features=[make_feature()])
    with patch(
        "app.services.ingestion_service._feature_to_earthquake",
        side_effect=RuntimeError("unexpected transformation bug"),
    ):
        with pytest.raises(RuntimeError):
            run(svc.run_once())
    metrics.update_for_earthquake.assert_not_awaited()


def test_unexpected_transformation_error_no_result_returned():
    svc, _, _, _ = make_service(features=[make_feature()])
    result = None
    with patch(
        "app.services.ingestion_service._feature_to_earthquake",
        side_effect=RuntimeError("unexpected transformation bug"),
    ):
        with pytest.raises(RuntimeError):
            result = run(svc.run_once())
    assert result is None


def test_unexpected_transformation_error_not_counted_as_invalid(caplog):
    svc, _, _, _ = make_service(features=[make_feature()])
    with patch(
        "app.services.ingestion_service._feature_to_earthquake",
        side_effect=RuntimeError("unexpected transformation bug"),
    ):
        with caplog.at_level(logging.WARNING, logger="app.services.ingestion_service"):
            with pytest.raises(RuntimeError):
                run(svc.run_once())
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert not warnings
