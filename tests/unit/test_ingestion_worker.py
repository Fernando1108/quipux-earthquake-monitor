"""Unit tests for IngestionWorker — all I/O is mocked."""

import asyncio
import inspect
import logging
import runpy
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.workers import IngestionWorker
from app.workers.ingestion_worker import main

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

INTERVAL = 60


def run(coro):
    return asyncio.run(coro)


def make_service(side_effect=None, return_value=None) -> MagicMock:
    """Return a mock IngestionService."""
    service = MagicMock()
    if side_effect is not None:
        service.run_once = AsyncMock(side_effect=side_effect)
    elif return_value is not None:
        service.run_once = AsyncMock(return_value=return_value)
    else:
        service.run_once = AsyncMock(return_value=MagicMock())
    return service


def cancelling_sleep(after_calls: int = 1):
    """Return an async sleep that raises CancelledError after `after_calls` invocations."""
    count = [0]

    async def _sleep(seconds: float) -> None:
        count[0] += 1
        if count[0] >= after_calls:
            raise asyncio.CancelledError

    return _sleep


@contextmanager
def main_patches(
    connect_effect=None,
    create_indexes_effect=None,
    run_forever_effect=None,
):
    """Patch all external dependencies of main() and yield a dict of mocks."""
    with (
        patch("app.workers.ingestion_worker.configure_logging") as mock_configure,
        patch("app.workers.ingestion_worker.Settings") as MockSettings,
        patch(
            "app.workers.ingestion_worker.connect_to_mongodb", new_callable=AsyncMock
        ) as mock_connect,
        patch("app.workers.ingestion_worker.get_database") as mock_get_db,
        patch(
            "app.workers.ingestion_worker.create_indexes", new_callable=AsyncMock
        ) as mock_indexes,
        patch("app.workers.ingestion_worker.IngestionService") as MockService,
        patch("app.workers.ingestion_worker.IngestionWorker") as MockWorker,
        patch("app.workers.ingestion_worker.close_mongodb_connection") as mock_close,
    ):
        mock_settings = MagicMock()
        mock_settings.ingestion_interval_seconds = 180
        MockSettings.return_value = mock_settings

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db

        mock_service_instance = MagicMock()
        MockService.return_value = mock_service_instance

        mock_worker_instance = MagicMock()
        mock_worker_instance.run_forever = AsyncMock(side_effect=run_forever_effect)
        MockWorker.return_value = mock_worker_instance

        if connect_effect is not None:
            mock_connect.side_effect = connect_effect
        if create_indexes_effect is not None:
            mock_indexes.side_effect = create_indexes_effect

        yield {
            "configure": mock_configure,
            "Settings": MockSettings,
            "settings": mock_settings,
            "connect": mock_connect,
            "get_database": mock_get_db,
            "database": mock_db,
            "create_indexes": mock_indexes,
            "Service": MockService,
            "service_instance": mock_service_instance,
            "Worker": MockWorker,
            "worker_instance": mock_worker_instance,
            "close": mock_close,
        }


# ---------------------------------------------------------------------------
# A. Imports and constructor
# ---------------------------------------------------------------------------


def test_ingestion_worker_importable_from_app_workers():
    from app.workers import IngestionWorker as IW

    assert IW is IngestionWorker


def test_dunder_all_contains_ingestion_worker():
    import app.workers as mod

    assert "IngestionWorker" in mod.__all__


def test_constructor_preserves_service():
    service = make_service()
    worker = IngestionWorker(service, INTERVAL, sleep_func=AsyncMock())
    assert worker._service is service


def test_constructor_preserves_sleep_func():
    sleep = AsyncMock()
    worker = IngestionWorker(make_service(), INTERVAL, sleep_func=sleep)
    assert worker._sleep_func is sleep


def test_constructor_stores_interval():
    worker = IngestionWorker(make_service(), INTERVAL, sleep_func=AsyncMock())
    assert worker._interval_seconds == INTERVAL


def test_sleep_func_none_uses_asyncio_sleep():
    worker = IngestionWorker(make_service(), INTERVAL)
    assert worker._sleep_func is asyncio.sleep


def test_positive_integer_interval_accepted():
    IngestionWorker(make_service(), 1, sleep_func=AsyncMock())


def test_zero_interval_rejected():
    with pytest.raises(ValueError):
        IngestionWorker(make_service(), 0)


def test_negative_interval_rejected():
    with pytest.raises(ValueError):
        IngestionWorker(make_service(), -1)


def test_bool_interval_rejected():
    with pytest.raises(ValueError):
        IngestionWorker(make_service(), True)


def test_float_interval_rejected():
    with pytest.raises(ValueError):
        IngestionWorker(make_service(), 60.0)  # type: ignore[arg-type]


def test_string_interval_rejected():
    with pytest.raises(ValueError):
        IngestionWorker(make_service(), "60")  # type: ignore[arg-type]


def test_constructor_does_not_call_run_once():
    service = make_service()
    IngestionWorker(service, INTERVAL, sleep_func=AsyncMock())
    service.run_once.assert_not_called()


def test_constructor_does_not_sleep():
    sleep = AsyncMock()
    IngestionWorker(make_service(), INTERVAL, sleep_func=sleep)
    sleep.assert_not_called()


# ---------------------------------------------------------------------------
# B. Immediate first iteration
# ---------------------------------------------------------------------------


def test_run_once_called_before_first_sleep():
    order: list[str] = []
    service = MagicMock()

    async def tracking_run_once() -> None:
        order.append("run_once")

    async def tracking_sleep(seconds: float) -> None:
        order.append("sleep")
        raise asyncio.CancelledError

    service.run_once = tracking_run_once
    worker = IngestionWorker(service, INTERVAL, sleep_func=tracking_sleep)
    with pytest.raises(asyncio.CancelledError):
        run(worker.run_forever())

    assert order[0] == "run_once"
    assert order[1] == "sleep"


def test_no_initial_sleep_before_first_run_once():
    order: list[str] = []
    service = MagicMock()

    async def run_once() -> None:
        order.append("run_once")

    async def sleep(seconds: float) -> None:
        order.append("sleep")
        raise asyncio.CancelledError

    service.run_once = run_once
    worker = IngestionWorker(service, INTERVAL, sleep_func=sleep)
    with pytest.raises(asyncio.CancelledError):
        run(worker.run_forever())

    assert order.index("run_once") < order.index("sleep")


def test_run_once_awaited_exactly_once_before_cancellation():
    service = make_service()
    worker = IngestionWorker(service, INTERVAL, sleep_func=cancelling_sleep(1))
    with pytest.raises(asyncio.CancelledError):
        run(worker.run_forever())
    assert service.run_once.await_count == 1


def test_sleep_receives_exact_interval_seconds():
    sleep_args: list[float] = []

    async def recording_sleep(seconds: float) -> None:
        sleep_args.append(seconds)
        raise asyncio.CancelledError

    worker = IngestionWorker(make_service(), INTERVAL, sleep_func=recording_sleep)
    with pytest.raises(asyncio.CancelledError):
        run(worker.run_forever())

    assert sleep_args == [INTERVAL]


def test_worker_does_not_inspect_ingestion_result_fields():
    from app.workers import ingestion_worker

    src = inspect.getsource(ingestion_worker.IngestionWorker.run_forever)
    # IngestionResult fields must not be accessed in the loop body
    for field in (".fetched", ".inserted", ".duplicates", ".invalid"):
        assert field not in src, f"run_forever should not access result{field}"


# ---------------------------------------------------------------------------
# C. Repetition
# ---------------------------------------------------------------------------


def test_run_once_executes_again_after_sleep():
    service = make_service()
    worker = IngestionWorker(service, INTERVAL, sleep_func=cancelling_sleep(2))
    with pytest.raises(asyncio.CancelledError):
        run(worker.run_forever())
    assert service.run_once.await_count == 2


def test_multiple_iterations_call_order():
    order: list[str] = []
    service = MagicMock()
    sleep_count = [0]

    async def run_once() -> None:
        order.append("run_once")

    async def sleep(seconds: float) -> None:
        order.append("sleep")
        sleep_count[0] += 1
        if sleep_count[0] >= 2:
            raise asyncio.CancelledError

    service.run_once = run_once
    worker = IngestionWorker(service, INTERVAL, sleep_func=sleep)
    with pytest.raises(asyncio.CancelledError):
        run(worker.run_forever())

    assert order == ["run_once", "sleep", "run_once", "sleep"]


def test_exactly_one_sleep_between_iterations():
    sleep_count = [0]

    async def counting_sleep(seconds: float) -> None:
        sleep_count[0] += 1
        if sleep_count[0] >= 2:
            raise asyncio.CancelledError

    service = make_service()
    worker = IngestionWorker(service, INTERVAL, sleep_func=counting_sleep)
    with pytest.raises(asyncio.CancelledError):
        run(worker.run_forever())

    assert sleep_count[0] == 2


def test_configured_interval_used_for_every_sleep():
    sleep_args: list[float] = []

    async def recording_sleep(seconds: float) -> None:
        sleep_args.append(seconds)
        if len(sleep_args) >= 2:
            raise asyncio.CancelledError

    service = make_service()
    worker = IngestionWorker(service, INTERVAL, sleep_func=recording_sleep)
    with pytest.raises(asyncio.CancelledError):
        run(worker.run_forever())

    assert sleep_args == [INTERVAL, INTERVAL]


def test_second_run_once_does_not_begin_before_sleep_completes():
    """Verify sequential: run_once does not start until sleep returns."""
    order: list[str] = []
    run_count = [0]
    sleep_count = [0]
    service = MagicMock()

    async def run_once() -> None:
        run_count[0] += 1
        order.append(f"run_once_{run_count[0]}")

    async def sleep(seconds: float) -> None:
        sleep_count[0] += 1
        order.append(f"sleep_{sleep_count[0]}")
        if sleep_count[0] >= 2:
            raise asyncio.CancelledError

    service.run_once = run_once
    worker = IngestionWorker(service, INTERVAL, sleep_func=sleep)
    with pytest.raises(asyncio.CancelledError):
        run(worker.run_forever())

    assert order == ["run_once_1", "sleep_1", "run_once_2", "sleep_2"]


# ---------------------------------------------------------------------------
# D. Iteration errors
# ---------------------------------------------------------------------------


def test_exception_from_run_once_is_caught(caplog):
    """RuntimeError from run_once must be caught, not propagate."""
    service = make_service(side_effect=RuntimeError("db fail"))
    worker = IngestionWorker(service, INTERVAL, sleep_func=cancelling_sleep(1))
    with caplog.at_level(logging.ERROR):
        with pytest.raises(asyncio.CancelledError):
            run(worker.run_forever())
    # RuntimeError was caught — only CancelledError propagated


def test_error_logged_at_error_level(caplog):
    service = make_service(side_effect=RuntimeError("db fail"))
    worker = IngestionWorker(service, INTERVAL, sleep_func=cancelling_sleep(1))
    with caplog.at_level(logging.ERROR, logger="app.workers.ingestion_worker"):
        with pytest.raises(asyncio.CancelledError):
            run(worker.run_forever())
    error_records = [r for r in caplog.records if r.levelname == "ERROR"]
    assert error_records


def test_error_log_contains_iteration_failed(caplog):
    service = make_service(side_effect=RuntimeError("db fail"))
    worker = IngestionWorker(service, INTERVAL, sleep_func=cancelling_sleep(1))
    with caplog.at_level(logging.ERROR, logger="app.workers.ingestion_worker"):
        with pytest.raises(asyncio.CancelledError):
            run(worker.run_forever())
    error_records = [r for r in caplog.records if r.levelname == "ERROR"]
    assert any("failed" in r.message.lower() for r in error_records)


def test_error_log_includes_retry_interval(caplog):
    service = make_service(side_effect=RuntimeError("db fail"))
    worker = IngestionWorker(service, INTERVAL, sleep_func=cancelling_sleep(1))
    with caplog.at_level(logging.ERROR, logger="app.workers.ingestion_worker"):
        with pytest.raises(asyncio.CancelledError):
            run(worker.run_forever())
    error_records = [r for r in caplog.records if r.levelname == "ERROR"]
    assert any(str(INTERVAL) in r.message for r in error_records)


def test_logger_exception_includes_exc_info(caplog):
    """logger.exception must attach exc_info to the log record."""
    service = make_service(side_effect=RuntimeError("db fail"))
    worker = IngestionWorker(service, INTERVAL, sleep_func=cancelling_sleep(1))
    with caplog.at_level(logging.ERROR, logger="app.workers.ingestion_worker"):
        with pytest.raises(asyncio.CancelledError):
            run(worker.run_forever())
    error_records = [r for r in caplog.records if r.levelname == "ERROR"]
    assert error_records
    assert error_records[0].exc_info is not None


def test_worker_sleeps_after_failed_iteration():
    """Sleep must be called even when run_once fails."""
    sleep_calls = [0]

    async def counting_sleep(seconds: float) -> None:
        sleep_calls[0] += 1
        raise asyncio.CancelledError

    service = make_service(side_effect=RuntimeError("db fail"))
    worker = IngestionWorker(service, INTERVAL, sleep_func=counting_sleep)
    with pytest.raises(asyncio.CancelledError):
        run(worker.run_forever())

    assert sleep_calls[0] == 1


def test_worker_retries_after_sleep_following_failure():
    """After a failed iteration + sleep, run_once is called again."""
    service = make_service(
        side_effect=[RuntimeError("fail"), MagicMock()]
    )
    worker = IngestionWorker(service, INTERVAL, sleep_func=cancelling_sleep(2))
    with pytest.raises(asyncio.CancelledError):
        run(worker.run_forever())
    assert service.run_once.await_count == 2


def test_failed_iteration_does_not_terminate_loop():
    """Exception from run_once must not stop the loop permanently."""
    service = make_service(
        side_effect=[RuntimeError("fail"), RuntimeError("fail2")]
    )
    worker = IngestionWorker(service, INTERVAL, sleep_func=cancelling_sleep(2))
    with pytest.raises(asyncio.CancelledError):
        run(worker.run_forever())
    # Both failures were handled, loop continued until sleep cancelled it
    assert service.run_once.await_count == 2


def test_failed_iteration_does_not_retry_before_sleep():
    """After failure, sleep must occur before the next run_once."""
    order: list[str] = []
    service = MagicMock()
    call_count = [0]

    async def run_once() -> None:
        call_count[0] += 1
        order.append(f"run_once_{call_count[0]}")
        if call_count[0] == 1:
            raise RuntimeError("fail")

    sleep_count = [0]

    async def sleep(seconds: float) -> None:
        sleep_count[0] += 1
        order.append(f"sleep_{sleep_count[0]}")
        if sleep_count[0] >= 2:
            raise asyncio.CancelledError

    service.run_once = run_once
    worker = IngestionWorker(service, INTERVAL, sleep_func=sleep)
    with pytest.raises(asyncio.CancelledError):
        run(worker.run_forever())

    assert order == ["run_once_1", "sleep_1", "run_once_2", "sleep_2"]


def test_errors_from_sleep_func_propagate():
    """Exceptions raised by sleep_func must propagate unconditionally."""
    service = make_service()

    async def failing_sleep(seconds: float) -> None:
        raise OSError("sleep failed")

    worker = IngestionWorker(service, INTERVAL, sleep_func=failing_sleep)
    with pytest.raises(OSError, match="sleep failed"):
        run(worker.run_forever())


def test_cancelled_error_from_run_once_propagates():
    """CancelledError from run_once is not caught by except Exception."""
    service = make_service(side_effect=asyncio.CancelledError())
    worker = IngestionWorker(service, INTERVAL, sleep_func=AsyncMock())
    with pytest.raises(asyncio.CancelledError):
        run(worker.run_forever())


def test_cancelled_error_from_sleep_func_propagates():
    """CancelledError from sleep propagates (it is outside the try block)."""
    service = make_service()

    async def cancelling(seconds: float) -> None:
        raise asyncio.CancelledError

    worker = IngestionWorker(service, INTERVAL, sleep_func=cancelling)
    with pytest.raises(asyncio.CancelledError):
        run(worker.run_forever())


def test_keyboard_interrupt_not_suppressed():
    """KeyboardInterrupt (BaseException) must not be caught by except Exception."""
    service = make_service(side_effect=KeyboardInterrupt())
    worker = IngestionWorker(service, INTERVAL, sleep_func=AsyncMock())
    raised = False
    try:
        run(worker.run_forever())
    except KeyboardInterrupt:
        raised = True
    assert raised, "KeyboardInterrupt must propagate from run_forever"


def test_system_exit_not_suppressed():
    """SystemExit (BaseException) must not be caught by except Exception."""
    service = make_service(side_effect=SystemExit(1))
    worker = IngestionWorker(service, INTERVAL, sleep_func=AsyncMock())
    with pytest.raises(SystemExit):
        run(worker.run_forever())


# ---------------------------------------------------------------------------
# E. main lifecycle
# ---------------------------------------------------------------------------


def test_main_calls_configure_logging_exactly_once():
    with main_patches() as mocks:
        run(main())
    mocks["configure"].assert_called_once_with()


def test_main_creates_settings():
    with main_patches() as mocks:
        run(main())
    mocks["Settings"].assert_called_once_with()


def test_main_awaits_connect_to_mongodb():
    with main_patches() as mocks:
        run(main())
    mocks["connect"].assert_awaited_once_with()


def test_get_database_called_after_connection_succeeds():
    with main_patches() as mocks:
        run(main())
    mocks["connect"].assert_awaited()
    mocks["get_database"].assert_called_once()


def test_create_indexes_receives_active_database():
    with main_patches() as mocks:
        run(main())
    mocks["create_indexes"].assert_awaited_once_with(mocks["database"])


def test_ingestion_service_created_after_indexes_complete():
    call_order: list[str] = []

    async def fake_indexes(db):
        call_order.append("indexes")

    async def fake_connect():
        call_order.append("connect")

    class FakeService:
        def __init__(self):
            call_order.append("service")

    with main_patches() as mocks:
        mocks["connect"].side_effect = fake_connect
        mocks["create_indexes"].side_effect = fake_indexes
        mocks["Service"].side_effect = FakeService
        run(main())

    assert call_order.index("indexes") < call_order.index("service")


def test_ingestion_worker_receives_created_service():
    with main_patches() as mocks:
        run(main())
    worker_call_args = mocks["Worker"].call_args
    assert worker_call_args[0][0] is mocks["service_instance"]


def test_ingestion_worker_receives_interval_from_settings():
    with main_patches() as mocks:
        run(main())
    worker_call_args = mocks["Worker"].call_args
    assert worker_call_args[0][1] == mocks["settings"].ingestion_interval_seconds


def test_main_awaits_run_forever():
    with main_patches() as mocks:
        run(main())
    mocks["worker_instance"].run_forever.assert_awaited_once_with()


def test_close_called_after_normal_return():
    with main_patches() as mocks:
        run(main())
    mocks["close"].assert_called_once_with()


def test_close_called_when_run_forever_raises():
    with main_patches(run_forever_effect=RuntimeError("worker crash")) as mocks:
        with pytest.raises(RuntimeError):
            run(main())
    mocks["close"].assert_called_once_with()


def test_close_called_when_run_forever_cancelled():
    with main_patches(run_forever_effect=asyncio.CancelledError()) as mocks:
        with pytest.raises(asyncio.CancelledError):
            run(main())
    mocks["close"].assert_called_once_with()


def test_close_called_when_connect_fails():
    with main_patches(connect_effect=RuntimeError("connection failed")) as mocks:
        with pytest.raises(RuntimeError):
            run(main())
    mocks["close"].assert_called_once_with()


def test_close_called_when_create_indexes_fails():
    with main_patches(create_indexes_effect=RuntimeError("index failed")) as mocks:
        with pytest.raises(RuntimeError):
            run(main())
    mocks["close"].assert_called_once_with()


def test_get_database_not_called_when_connect_fails():
    with main_patches(connect_effect=RuntimeError("connection failed")) as mocks:
        with pytest.raises(RuntimeError):
            run(main())
    mocks["get_database"].assert_not_called()


def test_create_indexes_not_called_when_connect_fails():
    with main_patches(connect_effect=RuntimeError("connection failed")) as mocks:
        with pytest.raises(RuntimeError):
            run(main())
    mocks["create_indexes"].assert_not_awaited()


def test_ingestion_service_not_created_when_connect_fails():
    with main_patches(connect_effect=RuntimeError("connection failed")) as mocks:
        with pytest.raises(RuntimeError):
            run(main())
    mocks["Service"].assert_not_called()


def test_ingestion_worker_not_created_when_connect_fails():
    with main_patches(connect_effect=RuntimeError("connection failed")) as mocks:
        with pytest.raises(RuntimeError):
            run(main())
    mocks["Worker"].assert_not_called()


def test_ingestion_service_not_created_when_indexes_fail():
    with main_patches(create_indexes_effect=RuntimeError("index failed")) as mocks:
        with pytest.raises(RuntimeError):
            run(main())
    mocks["Service"].assert_not_called()


def test_ingestion_worker_not_created_when_indexes_fail():
    with main_patches(create_indexes_effect=RuntimeError("index failed")) as mocks:
        with pytest.raises(RuntimeError):
            run(main())
    mocks["Worker"].assert_not_called()


def test_startup_exceptions_propagate():
    with main_patches(connect_effect=RuntimeError("startup failed")) as mocks:
        with pytest.raises(RuntimeError, match="startup failed"):
            run(main())


def test_run_forever_exception_propagates_after_cleanup():
    error = RuntimeError("run_forever crashed")
    with main_patches(run_forever_effect=error) as mocks:
        with pytest.raises(RuntimeError, match="run_forever crashed"):
            run(main())
    mocks["close"].assert_called_once_with()


# ---------------------------------------------------------------------------
# F. Module and architecture
# ---------------------------------------------------------------------------


def _worker_src() -> str:
    from app.workers import ingestion_worker

    return inspect.getsource(ingestion_worker)


def test_importing_module_does_not_call_configure_logging():
    src = _worker_src()
    # configure_logging() must appear only inside function bodies (indented)
    for line in src.splitlines():
        if "configure_logging()" in line and not line.startswith((" ", "\t")):
            pytest.fail("configure_logging() found at module level")


def test_importing_module_does_not_connect_to_mongodb():
    src = _worker_src()
    for line in src.splitlines():
        if "connect_to_mongodb()" in line and not line.startswith((" ", "\t")):
            pytest.fail("connect_to_mongodb() found at module level")


def test_module_contains_main_guard():
    src = _worker_src()
    assert '__name__ == "__main__"' in src


def test_main_guard_calls_asyncio_run_main():
    import app.workers.ingestion_worker as worker_module

    module_path = Path(worker_module.__file__)
    received: list = []

    def fake_run(coroutine):
        received.append(coroutine)
        coroutine.close()

    with patch("asyncio.run", side_effect=fake_run) as mock_run:
        runpy.run_path(str(module_path), run_name="__main__")

    mock_run.assert_called_once()
    assert len(received) == 1
    assert inspect.iscoroutine(received[0])
    assert received[0].cr_code.co_name == "main"


def test_no_usgs_client_import():
    src = _worker_src()
    assert "USGSClient" not in src


def test_no_repository_imports():
    src = _worker_src()
    assert "EarthquakeRepository" not in src
    assert "MetricRepository" not in src


def test_no_model_imports():
    src = _worker_src()
    assert "from app.models" not in src


def test_no_direct_collection_access():
    src = _worker_src()
    assert "_collection" not in src


def test_no_time_sleep():
    src = _worker_src()
    assert "time.sleep" not in src


def test_no_gather():
    src = _worker_src()
    assert "asyncio.gather" not in src


def test_no_create_task():
    src = _worker_src()
    assert "create_task" not in src


def test_no_task_group():
    src = _worker_src()
    assert "TaskGroup" not in src


def test_startup_log_includes_interval(caplog):
    """run_forever must emit an INFO log mentioning the configured interval."""
    service = make_service()
    worker = IngestionWorker(service, INTERVAL, sleep_func=cancelling_sleep(1))
    with caplog.at_level(logging.INFO, logger="app.workers.ingestion_worker"):
        with pytest.raises(asyncio.CancelledError):
            run(worker.run_forever())
    info_records = [r for r in caplog.records if r.levelname == "INFO"]
    assert any(str(INTERVAL) in r.message for r in info_records)


# ---------------------------------------------------------------------------
# G. Package-level lazy import (PEP 562)
# ---------------------------------------------------------------------------


def test_package_import_is_lazy():
    """Importing app.workers must NOT load app.workers.ingestion_worker."""
    script = """
import sys
import app.workers
assert "app.workers.ingestion_worker" not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )


def test_public_export_still_works():
    """Accessing IngestionWorker via app.workers triggers lazy load."""
    script = """
import sys
import app.workers

assert "app.workers.ingestion_worker" not in sys.modules

from app.workers import IngestionWorker
from app.workers.ingestion_worker import IngestionWorker as DirectIngestionWorker

assert IngestionWorker is DirectIngestionWorker
assert "app.workers.ingestion_worker" in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )


def test_unknown_attribute_raises_attribute_error():
    """Accessing an undefined name on app.workers raises AttributeError."""
    import app.workers as mod

    with pytest.raises(AttributeError):
        _ = mod.NonExistentAttribute


def test_module_execution_has_no_runpy_runtimewarning():
    """Running app.workers.ingestion_worker as __main__ must not raise RuntimeWarning."""
    script = """
import runpy
from unittest.mock import patch

def fake_run(coroutine):
    coroutine.close()

with patch("asyncio.run", side_effect=fake_run) as mocked_run:
    runpy.run_module(
        "app.workers.ingestion_worker",
        run_name="__main__",
    )

assert mocked_run.call_count == 1
"""
    result = subprocess.run(
        [sys.executable, "-W", "error::RuntimeWarning", "-c", script],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
