"""Unit tests for hourly_report_dag.

Skipped entirely in the application image where Apache Airflow is intentionally
absent.  Runs in full inside the custom Airflow image built by Dockerfile.airflow.
"""

import asyncio
import inspect
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Skip the entire module when airflow.sdk is not installed (application image).
pytest.importorskip("airflow.sdk")

import pendulum  # noqa: E402

# PYTHONPATH=/opt/airflow in the Airflow container, so DAGs are importable as
# the "dags" package (not "airflow.dags").
from dags.hourly_report_dag import (  # noqa: E402
    DAG_ID,
    SCHEDULE,
    TASK_ID,
    UTC,
    _execute_hourly_report_task,
    _generate_report,
    _resolve_report_date,
    _to_plain_utc_datetime,
    _utc_now,
    hourly_report_dag,
)
import dags.hourly_report_dag as dag_mod  # noqa: E402

# Patch prefix matching the module path as seen by Python's import system.
_MOD = "dags.hourly_report_dag"

# ---------------------------------------------------------------------------
# Constants shared across sections
# ---------------------------------------------------------------------------

REPORT_DATE = datetime(2024, 6, 1, 13, 0, 0, tzinfo=UTC)
PERIOD_START = REPORT_DATE - timedelta(hours=1)
OFFSET_PLUS5 = timezone(timedelta(hours=5))
# Same instant as 13:00 UTC expressed in +05:00
REPORT_DATE_PLUS5 = datetime(2024, 6, 1, 18, 0, 0, tzinfo=OFFSET_PLUS5)


# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------


def run(coro):
    """Run a coroutine in a fresh event loop."""
    return asyncio.run(coro)


def _make_report_mock() -> MagicMock:
    """Return a mock resembling a Report domain object."""
    report = MagicMock()
    report.report_date = REPORT_DATE
    report.period_start = PERIOD_START
    report.period_end = REPORT_DATE
    report.total_events = 5
    report.events_with_magnitude = 3
    report.average_magnitude = 2.5
    report.max_magnitude = 4.0
    loc = MagicMock()
    loc.location = "California"
    loc.count = 3
    report.top_locations = [loc]
    return report


# ---------------------------------------------------------------------------
# Fixture for Section D
# ---------------------------------------------------------------------------


@pytest.fixture()
def gr_mocks():
    """Patch all _generate_report I/O dependencies and yield them as a dict."""
    report_mock = _make_report_mock()
    mock_service = MagicMock()
    mock_service.generate_hourly_report = AsyncMock(return_value=report_mock)
    mock_db = MagicMock(name="database")

    with (
        patch(f"{_MOD}.configure_logging") as m_log,
        patch(f"{_MOD}.connect_to_mongodb", new_callable=AsyncMock) as m_connect,
        patch(f"{_MOD}.get_database", return_value=mock_db) as m_get_db,
        patch(f"{_MOD}.create_indexes", new_callable=AsyncMock) as m_indexes,
        patch(f"{_MOD}.EarthquakeRepository") as m_eq_cls,
        patch(f"{_MOD}.ReportRepository") as m_rep_cls,
        patch(f"{_MOD}.ReportingService", return_value=mock_service) as m_svc_cls,
        patch(f"{_MOD}.close_mongodb_connection") as m_close,
    ):
        yield {
            "configure_logging": m_log,
            "connect_to_mongodb": m_connect,
            "get_database": m_get_db,
            "create_indexes": m_indexes,
            "EarthquakeRepository": m_eq_cls,
            "ReportRepository": m_rep_cls,
            "ReportingService": m_svc_cls,
            "close_mongodb_connection": m_close,
            "service": mock_service,
            "report": report_mock,
            "database": mock_db,
        }


# ===========================================================================
# A. DAG Import
# ===========================================================================


def test_module_imports_with_airflow_installed():
    """The module is importable when Airflow is installed."""
    assert dag_mod is not None


def test_hourly_report_dag_attribute_exists():
    """hourly_report_dag must be exposed as a module-level attribute."""
    assert hourly_report_dag is not None


def test_dag_id_equals_constant():
    """dag.dag_id must match DAG_ID and equal 'hourly_report_dag'."""
    assert hourly_report_dag.dag_id == DAG_ID
    assert DAG_ID == "hourly_report_dag"


def test_no_dag_import_errors():
    """DAG parsed without errors — at least one task is registered."""
    assert len(hourly_report_dag.tasks) >= 1


def test_module_import_performs_no_mongodb_connection():
    """Importing the module must not open a MongoDB connection."""
    from app.database import mongodb as mongo_mod

    # If a connection were opened during parse, _database would be set.
    assert mongo_mod._database is None


def test_module_import_performs_no_report_generation():
    """Report generation must not occur at DAG parse time."""
    from app.database import mongodb as mongo_mod

    assert mongo_mod._client is None


# ===========================================================================
# B. DAG Configuration
# ===========================================================================


def test_schedule_constant_is_hourly_cron():
    assert SCHEDULE == "0 * * * *"


def test_start_date_is_fixed_and_timezone_aware():
    sd = hourly_report_dag.start_date
    assert sd is not None
    assert sd.tzinfo is not None


def test_start_date_timezone_is_utc():
    sd = hourly_report_dag.start_date
    assert sd.utcoffset().total_seconds() == 0


def test_catchup_is_false():
    assert hourly_report_dag.catchup is False


def test_max_active_runs_is_1():
    assert hourly_report_dag.max_active_runs == 1


def test_tags_are_correct():
    assert set(hourly_report_dag.tags) == {"quipux", "earthquakes", "reporting"}


def test_exactly_one_task_exists():
    assert len(hourly_report_dag.tasks) == 1


def test_task_id_equals_constant():
    assert hourly_report_dag.tasks[0].task_id == TASK_ID
    assert TASK_ID == "generate_hourly_report"


def test_task_retries_equals_2():
    task_obj = hourly_report_dag.get_task(TASK_ID)
    assert task_obj.retries == 2


def test_task_retry_delay_equals_five_minutes():
    task_obj = hourly_report_dag.get_task(TASK_ID)
    assert task_obj.retry_delay == timedelta(minutes=5)


# ===========================================================================
# C. Report Date Resolution
# ===========================================================================


def test_resolve_aware_utc_data_interval_end():
    """UTC-aligned data_interval_end is accepted and returned unchanged."""
    result = _resolve_report_date({"data_interval_end": REPORT_DATE})
    assert result == REPORT_DATE


def test_resolve_non_utc_data_interval_end_normalized_to_utc():
    """Non-UTC data_interval_end is normalized to UTC."""
    result = _resolve_report_date({"data_interval_end": REPORT_DATE_PLUS5})
    assert result.tzinfo == UTC
    assert result == REPORT_DATE


def test_resolve_non_datetime_data_interval_end_rejected():
    ctx = {"data_interval_end": "2024-06-01T13:00:00Z"}
    with pytest.raises(ValueError, match="data_interval_end must be a datetime"):
        _resolve_report_date(ctx)


def test_resolve_naive_data_interval_end_rejected():
    ctx = {"data_interval_end": datetime(2024, 6, 1, 13, 0, 0)}
    with pytest.raises(ValueError, match="data_interval_end must be timezone-aware"):
        _resolve_report_date(ctx)


def test_resolve_misaligned_data_interval_end_rejected():
    ctx = {"data_interval_end": datetime(2024, 6, 1, 13, 30, 0, tzinfo=UTC)}
    with pytest.raises(ValueError, match="aligned to an exact UTC hour"):
        _resolve_report_date(ctx)


def test_resolve_logical_date_used_when_interval_end_absent():
    """logical_date is consulted when data_interval_end is absent."""
    logical = datetime(2024, 6, 1, 13, 45, 0, tzinfo=UTC)
    result = _resolve_report_date({"logical_date": logical})
    assert result == REPORT_DATE  # floored to 13:00


def test_resolve_logical_date_floored_to_utc_hour():
    logical = datetime(2024, 6, 1, 13, 59, 59, 999999, tzinfo=UTC)
    result = _resolve_report_date({"logical_date": logical})
    assert result.minute == 0
    assert result.second == 0
    assert result.microsecond == 0
    assert result == REPORT_DATE


def test_resolve_non_utc_logical_date_normalized():
    """Non-UTC logical_date is normalized to UTC before flooring."""
    logical_plus5 = datetime(2024, 6, 1, 18, 30, 0, tzinfo=OFFSET_PLUS5)
    result = _resolve_report_date({"logical_date": logical_plus5})
    assert result.tzinfo == UTC
    assert result == REPORT_DATE


def test_resolve_naive_logical_date_rejected():
    ctx = {"logical_date": datetime(2024, 6, 1, 13, 0, 0)}
    with pytest.raises(ValueError, match="logical_date must be timezone-aware"):
        _resolve_report_date(ctx)


def test_resolve_now_provider_used_when_both_absent():
    """now_provider is called when neither context key is present."""
    provider = MagicMock(return_value=datetime(2024, 6, 1, 13, 45, 0, tzinfo=UTC))
    _resolve_report_date({}, now_provider=provider)
    provider.assert_called_once()


def test_resolve_now_provider_called_exactly_once():
    """now_provider is never invoked more than once."""
    provider = MagicMock(return_value=datetime(2024, 6, 1, 13, 0, 0, tzinfo=UTC))
    _resolve_report_date({}, now_provider=provider)
    assert provider.call_count == 1


def test_resolve_current_time_floored_to_utc_hour():
    provider = MagicMock(
        return_value=datetime(2024, 6, 1, 13, 59, 59, 500000, tzinfo=UTC)
    )
    result = _resolve_report_date({}, now_provider=provider)
    assert result == REPORT_DATE


def test_resolve_provider_errors_propagate():
    def broken():
        raise RuntimeError("clock broken")

    with pytest.raises(RuntimeError, match="clock broken"):
        _resolve_report_date({}, now_provider=broken)


# ===========================================================================
# C2. Pendulum boundary regression
#
# Reproduces and prevents the production failure:
#   pendulum.DateTime arithmetic can strip tzinfo from the result, causing
#   Report(period_start=...) to fail Pydantic validation with
#   "datetime must include timezone information".
# ===========================================================================


def test_to_plain_utc_datetime_converts_pendulum_utc_to_builtin():
    """_to_plain_utc_datetime returns an exact built-in datetime for a Pendulum UTC value."""
    pdt = pendulum.datetime(2026, 7, 23, 7, 0, 0, tz="UTC")
    result = _to_plain_utc_datetime(pdt, "test_field")
    assert type(result) is datetime
    assert result.tzinfo is UTC
    assert result == datetime(2026, 7, 23, 7, 0, 0, tzinfo=UTC)


def test_to_plain_utc_datetime_normalizes_non_utc_pendulum():
    """Non-UTC Pendulum DateTime is normalized to UTC and returned as built-in datetime."""
    # 12:00 +05:00 == 07:00 UTC
    pdt = pendulum.datetime(2026, 7, 23, 12, 0, 0, tz="Asia/Tashkent")
    result = _to_plain_utc_datetime(pdt, "test_field")
    assert type(result) is datetime
    assert result.tzinfo is UTC
    assert result == datetime(2026, 7, 23, 7, 0, 0, tzinfo=UTC)


def test_to_plain_utc_datetime_rejects_non_datetime():
    with pytest.raises(ValueError, match="test_field must be a datetime"):
        _to_plain_utc_datetime("2026-07-23T07:00:00Z", "test_field")


def test_to_plain_utc_datetime_rejects_naive():
    with pytest.raises(ValueError, match="test_field must be timezone-aware"):
        _to_plain_utc_datetime(datetime(2026, 7, 23, 7, 0, 0), "test_field")


def test_resolve_pendulum_data_interval_end_returns_builtin_datetime():
    """Core regression: Pendulum data_interval_end resolves to exact built-in datetime."""
    pdt = pendulum.datetime(2026, 7, 23, 7, 0, 0, tz="UTC")
    result = _resolve_report_date({"data_interval_end": pdt})
    assert type(result) is datetime
    assert result.tzinfo is UTC


def test_resolve_pendulum_period_start_preserves_tzinfo():
    """Subtracting one hour from the resolved value must not lose timezone — exact production failure path."""
    pdt = pendulum.datetime(2026, 7, 23, 7, 0, 0, tz="UTC")
    result = _resolve_report_date({"data_interval_end": pdt})
    period_start = result - timedelta(hours=1)
    assert type(period_start) is datetime
    assert period_start.tzinfo is UTC
    assert period_start.utcoffset() == timedelta(0)


def test_resolve_pendulum_period_start_correct_value():
    """Resolved period_start equals one hour before the scheduled data_interval_end."""
    pdt = pendulum.datetime(2026, 7, 23, 7, 0, 0, tz="UTC")
    result = _resolve_report_date({"data_interval_end": pdt})
    period_start = result - timedelta(hours=1)
    assert period_start == datetime(2026, 7, 23, 6, 0, 0, tzinfo=UTC)


def test_resolve_pendulum_logical_date_returns_builtin_datetime():
    """Pendulum logical_date is converted to built-in UTC datetime and floored."""
    pdt = pendulum.datetime(2026, 7, 23, 7, 45, 30, tz="UTC")
    result = _resolve_report_date({"logical_date": pdt})
    assert type(result) is datetime
    assert result.tzinfo is UTC
    assert result == datetime(2026, 7, 23, 7, 0, 0, tzinfo=UTC)


def test_resolve_pendulum_now_provider_returns_builtin_datetime():
    """Pendulum value from now_provider is converted to built-in UTC datetime and floored."""
    pdt = pendulum.datetime(2026, 7, 23, 7, 30, 0, tz="UTC")
    provider = MagicMock(return_value=pdt)
    result = _resolve_report_date({}, now_provider=provider)
    assert type(result) is datetime
    assert result.tzinfo is UTC
    assert result == datetime(2026, 7, 23, 7, 0, 0, tzinfo=UTC)
    provider.assert_called_once()


def test_resolve_pendulum_report_construction_succeeds():
    """End-to-end: Pendulum data_interval_end → resolved dates → Report construction passes Pydantic."""
    from app.models.report import Report

    pdt = pendulum.datetime(2026, 7, 23, 7, 0, 0, tz="UTC")
    report_date = _resolve_report_date({"data_interval_end": pdt})
    period_start = report_date - timedelta(hours=1)
    generated_at = report_date + timedelta(seconds=1)

    report = Report(
        report_date=report_date,
        period_start=period_start,
        period_end=report_date,
        total_events=0,
        events_with_magnitude=0,
        average_magnitude=None,
        max_magnitude=None,
        top_locations=[],
        generated_at=generated_at,
    )
    assert report.total_events == 0
    assert type(report.report_date) is datetime
    assert type(report.period_start) is datetime


# ===========================================================================
# D. Async Orchestration
# ===========================================================================


def test_generate_report_configures_logging(gr_mocks):
    run(_generate_report(REPORT_DATE))
    gr_mocks["configure_logging"].assert_called_once()


def test_generate_report_connects_to_mongodb(gr_mocks):
    run(_generate_report(REPORT_DATE))
    gr_mocks["connect_to_mongodb"].assert_awaited_once()


def test_generate_report_gets_database(gr_mocks):
    run(_generate_report(REPORT_DATE))
    gr_mocks["get_database"].assert_called_once()


def test_generate_report_creates_indexes_with_database(gr_mocks):
    run(_generate_report(REPORT_DATE))
    gr_mocks["create_indexes"].assert_awaited_once_with(gr_mocks["database"])


def test_generate_report_repositories_receive_same_database(gr_mocks):
    run(_generate_report(REPORT_DATE))
    db = gr_mocks["database"]
    gr_mocks["EarthquakeRepository"].assert_called_once_with(database=db)
    gr_mocks["ReportRepository"].assert_called_once_with(database=db)


def test_generate_report_service_receives_both_repos(gr_mocks):
    run(_generate_report(REPORT_DATE))
    eq_repo = gr_mocks["EarthquakeRepository"].return_value
    rep_repo = gr_mocks["ReportRepository"].return_value
    gr_mocks["ReportingService"].assert_called_once_with(
        earthquake_repository=eq_repo,
        report_repository=rep_repo,
    )


def test_generate_report_calls_generate_hourly_report_with_exact_date(gr_mocks):
    run(_generate_report(REPORT_DATE))
    gr_mocks["service"].generate_hourly_report.assert_awaited_once_with(REPORT_DATE)


def test_generate_report_returns_json_serializable_summary(gr_mocks):
    result = run(_generate_report(REPORT_DATE))
    report = gr_mocks["report"]
    assert result["report_date"] == report.report_date.isoformat()
    assert result["period_start"] == report.period_start.isoformat()
    assert result["period_end"] == report.period_end.isoformat()
    assert result["total_events"] == report.total_events
    assert result["events_with_magnitude"] == report.events_with_magnitude
    assert result["average_magnitude"] == report.average_magnitude
    assert result["max_magnitude"] == report.max_magnitude
    assert result["top_locations"] == [
        {
            "location": report.top_locations[0].location,
            "count": report.top_locations[0].count,
        }
    ]


def test_generate_report_closes_mongodb_after_success(gr_mocks):
    run(_generate_report(REPORT_DATE))
    gr_mocks["close_mongodb_connection"].assert_called_once()


def test_generate_report_closes_mongodb_after_failure(gr_mocks):
    """close_mongodb_connection is called even when ReportingService raises."""
    gr_mocks["service"].generate_hourly_report = AsyncMock(
        side_effect=RuntimeError("service failure")
    )
    with pytest.raises(RuntimeError, match="service failure"):
        run(_generate_report(REPORT_DATE))
    gr_mocks["close_mongodb_connection"].assert_called_once()


def test_generate_report_errors_propagate(gr_mocks):
    gr_mocks["connect_to_mongodb"].side_effect = ConnectionError("mongo down")
    with pytest.raises(ConnectionError, match="mongo down"):
        run(_generate_report(REPORT_DATE))


def test_generate_report_no_direct_collection_access(gr_mocks):
    """_generate_report must not access MongoDB collections directly."""
    run(_generate_report(REPORT_DATE))
    # Direct collection access would call database["collection_name"].
    gr_mocks["database"].__getitem__.assert_not_called()


# ===========================================================================
# E. Task Callable
# ===========================================================================
#
# _generate_report is patched in every test here so that asyncio.run receives
# a plain MagicMock (the sentinel), not a real coroutine object.  Without this
# patch the production call `_generate_report(report_date)` would create a
# real coroutine that the mocked asyncio.run never awaits, producing a
# RuntimeWarning: coroutine was never awaited.


def _make_generate_mock(sentinel: MagicMock) -> MagicMock:
    """Return a plain MagicMock that wraps _generate_report.

    Using new= in patch forces a MagicMock instead of the AsyncMock that
    patch would auto-create for an async def, preventing unawaited-coroutine
    warnings from AsyncMockMixin._execute_mock_call.
    """
    return MagicMock(name="_generate_report", return_value=sentinel)


def test_task_callable_obtains_context_once():
    mock_context = {"data_interval_end": REPORT_DATE}
    mock_result = {"report_date": REPORT_DATE.isoformat()}
    awaitable_sentinel = MagicMock(name="generate_report_awaitable")
    generate_mock = _make_generate_mock(awaitable_sentinel)
    with (
        patch(f"{_MOD}.get_current_context", return_value=mock_context) as m_ctx,
        patch(f"{_MOD}._resolve_report_date", return_value=REPORT_DATE),
        patch(f"{_MOD}._generate_report", new=generate_mock),
        patch(f"{_MOD}.asyncio.run", return_value=mock_result),
    ):
        _execute_hourly_report_task()
        m_ctx.assert_called_once()


def test_task_callable_resolves_report_date_once():
    mock_context = {"data_interval_end": REPORT_DATE}
    mock_result = {"report_date": REPORT_DATE.isoformat()}
    awaitable_sentinel = MagicMock(name="generate_report_awaitable")
    generate_mock = _make_generate_mock(awaitable_sentinel)
    with (
        patch(f"{_MOD}.get_current_context", return_value=mock_context),
        patch(f"{_MOD}._resolve_report_date", return_value=REPORT_DATE) as m_resolve,
        patch(f"{_MOD}._generate_report", new=generate_mock),
        patch(f"{_MOD}.asyncio.run", return_value=mock_result),
    ):
        _execute_hourly_report_task()
        m_resolve.assert_called_once_with(mock_context)


def test_task_callable_uses_asyncio_run_once():
    mock_result = {"report_date": REPORT_DATE.isoformat(), "total_events": 0}
    awaitable_sentinel = MagicMock(name="generate_report_awaitable")
    generate_mock = _make_generate_mock(awaitable_sentinel)
    with (
        patch(f"{_MOD}.get_current_context", return_value={"data_interval_end": REPORT_DATE}),
        patch(f"{_MOD}._resolve_report_date", return_value=REPORT_DATE),
        patch(f"{_MOD}._generate_report", new=generate_mock),
        patch(f"{_MOD}.asyncio.run", return_value=mock_result) as m_run,
    ):
        _execute_hourly_report_task()
        generate_mock.assert_called_once_with(REPORT_DATE)
        m_run.assert_called_once_with(awaitable_sentinel)
        assert m_run.call_count == 1


def test_task_callable_returns_result_unchanged():
    mock_result = {"report_date": REPORT_DATE.isoformat(), "total_events": 7}
    awaitable_sentinel = MagicMock(name="generate_report_awaitable")
    generate_mock = _make_generate_mock(awaitable_sentinel)
    with (
        patch(f"{_MOD}.get_current_context", return_value={"data_interval_end": REPORT_DATE}),
        patch(f"{_MOD}._resolve_report_date", return_value=REPORT_DATE),
        patch(f"{_MOD}._generate_report", new=generate_mock),
        patch(f"{_MOD}.asyncio.run", return_value=mock_result),
    ):
        result = _execute_hourly_report_task()
        assert result is mock_result


def test_task_callable_errors_propagate():
    awaitable_sentinel = MagicMock(name="generate_report_awaitable")
    generate_mock = _make_generate_mock(awaitable_sentinel)
    with (
        patch(f"{_MOD}.get_current_context", return_value={"data_interval_end": REPORT_DATE}),
        patch(f"{_MOD}._resolve_report_date", return_value=REPORT_DATE),
        patch(f"{_MOD}._generate_report", new=generate_mock),
        patch(f"{_MOD}.asyncio.run", side_effect=RuntimeError("task failed")) as m_run,
    ):
        with pytest.raises(RuntimeError, match="task failed"):
            _execute_hourly_report_task()
        generate_mock.assert_called_once_with(REPORT_DATE)
        m_run.assert_called_once_with(awaitable_sentinel)


# ===========================================================================
# F. Architecture
# ===========================================================================


def _dag_source() -> str:
    return inspect.getsource(dag_mod)


def _dag_code_lines() -> str:
    """Return source with comment-only lines removed."""
    return "\n".join(
        line
        for line in _dag_source().splitlines()
        if not line.strip().startswith("#")
    )


def test_dag_imports_from_airflow_sdk():
    assert "from airflow.sdk import" in _dag_source()


def test_no_legacy_airflow_decorators_import():
    assert "airflow.decorators" not in _dag_source()


def test_no_airflow_models_dag_import():
    assert "from airflow.models" not in _dag_source()
    assert "airflow.models.DAG" not in _dag_source()


def test_no_fastapi_import():
    assert "fastapi" not in _dag_source().lower()


def test_no_direct_motor_import():
    assert "import motor" not in _dag_source()


def test_no_direct_pymongo_import():
    assert "import pymongo" not in _dag_source()


def test_no_counter_usage():
    assert "Counter" not in _dag_source()


def test_no_average_magnitude_calculation():
    """No direct average calculation in non-comment code."""
    code = _dag_code_lines()
    assert "/ count" not in code
    assert "/ len(" not in code


def test_no_max_magnitude_calculation():
    """No direct max() call in non-comment code."""
    assert "max(" not in _dag_code_lines()


def test_no_replace_one():
    assert "replace_one" not in _dag_source()


def test_no_direct_hourly_reports_collection_access():
    assert '"hourly_reports"' not in _dag_source()
    assert "'hourly_reports'" not in _dag_source()


def test_no_report_model_construction():
    """DAG must not import or construct Report domain model objects."""
    assert "from app.models.report import" not in _dag_source()
    assert "from app.models import" not in _dag_source()
