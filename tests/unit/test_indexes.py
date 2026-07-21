"""Unit tests for app.database.indexes — verifies index creation calls."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from pymongo import ASCENDING, DESCENDING

from app.database.indexes import create_indexes


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_database():
    earthquakes = MagicMock()
    earthquakes.create_index = AsyncMock()

    metrics = MagicMock()
    metrics.create_index = AsyncMock()

    hourly_reports = MagicMock()
    hourly_reports.create_index = AsyncMock()

    db = MagicMock()
    collections = {
        "earthquakes": earthquakes,
        "metrics": metrics,
        "hourly_reports": hourly_reports,
    }
    db.__getitem__ = MagicMock(side_effect=lambda name: collections[name])
    db._earthquakes = earthquakes
    db._metrics = metrics
    db._hourly_reports = hourly_reports

    return db


# ---------------------------------------------------------------------------
# Number of calls per collection
# ---------------------------------------------------------------------------

def test_create_indexes_calls_earthquakes_three_times(mock_database):
    run(create_indexes(mock_database))
    assert mock_database._earthquakes.create_index.await_count == 3


def test_create_indexes_calls_metrics_once(mock_database):
    run(create_indexes(mock_database))
    assert mock_database._metrics.create_index.await_count == 1


def test_create_indexes_calls_hourly_reports_once(mock_database):
    run(create_indexes(mock_database))
    assert mock_database._hourly_reports.create_index.await_count == 1


# ---------------------------------------------------------------------------
# earthquakes — event_id unique index
# ---------------------------------------------------------------------------

def test_earthquakes_event_id_index_keys(mock_database):
    run(create_indexes(mock_database))
    calls = mock_database._earthquakes.create_index.call_args_list
    keys = [c.args[0] for c in calls]
    assert [("event_id", ASCENDING)] in keys


def test_earthquakes_event_id_index_unique(mock_database):
    run(create_indexes(mock_database))
    calls = mock_database._earthquakes.create_index.call_args_list
    event_id_call = next(c for c in calls if c.args[0] == [("event_id", ASCENDING)])
    assert event_id_call.kwargs.get("unique") is True


def test_earthquakes_event_id_index_name(mock_database):
    run(create_indexes(mock_database))
    calls = mock_database._earthquakes.create_index.call_args_list
    event_id_call = next(c for c in calls if c.args[0] == [("event_id", ASCENDING)])
    assert event_id_call.kwargs.get("name") == "earthquakes_event_id_unique"


# ---------------------------------------------------------------------------
# earthquakes — event_time descending index
# ---------------------------------------------------------------------------

def test_earthquakes_event_time_index_keys(mock_database):
    run(create_indexes(mock_database))
    calls = mock_database._earthquakes.create_index.call_args_list
    keys = [c.args[0] for c in calls]
    assert [("event_time", DESCENDING)] in keys


def test_earthquakes_event_time_index_name(mock_database):
    run(create_indexes(mock_database))
    calls = mock_database._earthquakes.create_index.call_args_list
    event_time_call = next(c for c in calls if c.args[0] == [("event_time", DESCENDING)])
    assert event_time_call.kwargs.get("name") == "earthquakes_event_time_desc"


# ---------------------------------------------------------------------------
# earthquakes — compound magnitude + event_time index
# ---------------------------------------------------------------------------

def test_earthquakes_compound_index_keys(mock_database):
    run(create_indexes(mock_database))
    calls = mock_database._earthquakes.create_index.call_args_list
    keys = [c.args[0] for c in calls]
    assert [("magnitude", ASCENDING), ("event_time", DESCENDING)] in keys


def test_earthquakes_compound_index_name(mock_database):
    run(create_indexes(mock_database))
    calls = mock_database._earthquakes.create_index.call_args_list
    compound_call = next(
        c for c in calls
        if c.args[0] == [("magnitude", ASCENDING), ("event_time", DESCENDING)]
    )
    assert compound_call.kwargs.get("name") == "earthquakes_magnitude_asc_event_time_desc"


# ---------------------------------------------------------------------------
# metrics — window_start unique index
# ---------------------------------------------------------------------------

def test_metrics_window_start_index_keys(mock_database):
    run(create_indexes(mock_database))
    calls = mock_database._metrics.create_index.call_args_list
    keys = [c.args[0] for c in calls]
    assert [("window_start", ASCENDING)] in keys


def test_metrics_window_start_index_unique(mock_database):
    run(create_indexes(mock_database))
    calls = mock_database._metrics.create_index.call_args_list
    ws_call = next(c for c in calls if c.args[0] == [("window_start", ASCENDING)])
    assert ws_call.kwargs.get("unique") is True


def test_metrics_window_start_index_name(mock_database):
    run(create_indexes(mock_database))
    calls = mock_database._metrics.create_index.call_args_list
    ws_call = next(c for c in calls if c.args[0] == [("window_start", ASCENDING)])
    assert ws_call.kwargs.get("name") == "metrics_window_start_unique"


# ---------------------------------------------------------------------------
# hourly_reports — report_date unique index
# ---------------------------------------------------------------------------

def test_hourly_reports_report_date_index_keys(mock_database):
    run(create_indexes(mock_database))
    calls = mock_database._hourly_reports.create_index.call_args_list
    keys = [c.args[0] for c in calls]
    assert [("report_date", ASCENDING)] in keys


def test_hourly_reports_report_date_index_unique(mock_database):
    run(create_indexes(mock_database))
    calls = mock_database._hourly_reports.create_index.call_args_list
    rd_call = next(c for c in calls if c.args[0] == [("report_date", ASCENDING)])
    assert rd_call.kwargs.get("unique") is True


def test_hourly_reports_report_date_index_name(mock_database):
    run(create_indexes(mock_database))
    calls = mock_database._hourly_reports.create_index.call_args_list
    rd_call = next(c for c in calls if c.args[0] == [("report_date", ASCENDING)])
    assert rd_call.kwargs.get("name") == "hourly_reports_report_date_unique"
