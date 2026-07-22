"""Unit tests for the Metric and MagnitudeDistribution domain models."""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.models import Earthquake, MagnitudeDistribution, Metric
from app.models.metric import MagnitudeDistribution as MDistDirect
from app.models.metric import Metric as MetricDirect


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

UTC = timezone.utc

WINDOW_START = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
WINDOW_END = WINDOW_START + timedelta(hours=1)
UPDATED_AT = WINDOW_START

EMPTY_DIST = dict(
    under_2=0,
    from_2_to_under_4=0,
    from_4_to_under_5=0,
    from_5_to_under_6=0,
    six_or_more=0,
    unknown=0,
)


def valid_metric(**overrides) -> dict:
    """Return a dict representing a valid empty metric (no events)."""
    base = dict(
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        earthquake_count=0,
        magnitude_count=0,
        magnitude_sum=0.0,
        average_magnitude=None,
        max_magnitude=None,
        magnitude_distribution=MagnitudeDistribution(**EMPTY_DIST),
        updated_at=UPDATED_AT,
    )
    base.update(overrides)
    return base


def valid_metric_with_events(
    n: int,
    magnitudes: list[float],
    unknown: int = 0,
) -> dict:
    """Build a valid Metric dict with n earthquakes and given magnitudes.

    `magnitudes` may be shorter than n when unknown > 0.
    """
    assert len(magnitudes) + unknown == n
    mag_sum = sum(magnitudes)
    mag_count = len(magnitudes)

    dist = dict(
        under_2=sum(1 for m in magnitudes if m < 2),
        from_2_to_under_4=sum(1 for m in magnitudes if 2 <= m < 4),
        from_4_to_under_5=sum(1 for m in magnitudes if 4 <= m < 5),
        from_5_to_under_6=sum(1 for m in magnitudes if 5 <= m < 6),
        six_or_more=sum(1 for m in magnitudes if m >= 6),
        unknown=unknown,
    )

    avg = mag_sum / mag_count if mag_count > 0 else None
    mx = max(magnitudes) if magnitudes else None

    return dict(
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        earthquake_count=n,
        magnitude_count=mag_count,
        magnitude_sum=mag_sum,
        average_magnitude=avg,
        max_magnitude=mx,
        magnitude_distribution=MagnitudeDistribution(**dist),
        updated_at=UPDATED_AT,
    )


# ---------------------------------------------------------------------------
# 1. Metric importable from app.models
# ---------------------------------------------------------------------------

def test_metric_importable_from_app_models():
    assert Metric is MetricDirect


# ---------------------------------------------------------------------------
# 2. MagnitudeDistribution importable from app.models
# ---------------------------------------------------------------------------

def test_magnitude_distribution_importable_from_app_models():
    assert MagnitudeDistribution is MDistDirect


# ---------------------------------------------------------------------------
# 3. A complete valid metric is accepted
# ---------------------------------------------------------------------------

def test_valid_empty_metric_accepted():
    m = Metric(**valid_metric())
    assert m.earthquake_count == 0
    assert m.average_magnitude is None


def test_valid_metric_with_events_accepted():
    data = valid_metric_with_events(3, [1.5, 3.0, 6.5])
    m = Metric(**data)
    assert m.earthquake_count == 3
    assert m.magnitude_count == 3
    assert m.average_magnitude is not None


# ---------------------------------------------------------------------------
# 4. Rejects unknown extra top-level fields
# ---------------------------------------------------------------------------

def test_metric_rejects_extra_fields():
    with pytest.raises(ValidationError):
        Metric(**valid_metric(tsunami=False))


# ---------------------------------------------------------------------------
# 5. MagnitudeDistribution rejects unknown range fields
# ---------------------------------------------------------------------------

def test_distribution_rejects_extra_fields():
    with pytest.raises(ValidationError):
        MagnitudeDistribution(**EMPTY_DIST, extra_range=0)


# ---------------------------------------------------------------------------
# 6. Every distribution field is required
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("missing_field", [
    "under_2", "from_2_to_under_4", "from_4_to_under_5",
    "from_5_to_under_6", "six_or_more", "unknown",
])
def test_distribution_all_fields_required(missing_field):
    data = {k: v for k, v in EMPTY_DIST.items() if k != missing_field}
    with pytest.raises(ValidationError):
        MagnitudeDistribution(**data)


# ---------------------------------------------------------------------------
# 7. Every distribution counter accepts zero
# ---------------------------------------------------------------------------

def test_distribution_all_zeros_accepted():
    d = MagnitudeDistribution(**EMPTY_DIST)
    assert d.under_2 == 0
    assert d.unknown == 0


# ---------------------------------------------------------------------------
# 8. Each negative distribution counter is rejected
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("field", [
    "under_2", "from_2_to_under_4", "from_4_to_under_5",
    "from_5_to_under_6", "six_or_more", "unknown",
])
def test_distribution_negative_counter_rejected(field):
    data = {**EMPTY_DIST, field: -1}
    with pytest.raises(ValidationError):
        MagnitudeDistribution(**data)


# ---------------------------------------------------------------------------
# 9. earthquake_count zero accepted for consistent empty metric
# ---------------------------------------------------------------------------

def test_zero_earthquake_count_accepted():
    m = Metric(**valid_metric(earthquake_count=0))
    assert m.earthquake_count == 0


# ---------------------------------------------------------------------------
# 10. Negative earthquake_count rejected
# ---------------------------------------------------------------------------

def test_negative_earthquake_count_rejected():
    with pytest.raises(ValidationError):
        Metric(**valid_metric(earthquake_count=-1))


# ---------------------------------------------------------------------------
# 11. Negative magnitude_count rejected
# ---------------------------------------------------------------------------

def test_negative_magnitude_count_rejected():
    with pytest.raises(ValidationError):
        Metric(**valid_metric(magnitude_count=-1))


# ---------------------------------------------------------------------------
# 12. magnitude_count > earthquake_count rejected
# ---------------------------------------------------------------------------

def test_magnitude_count_exceeds_earthquake_count_rejected():
    # 2 earthquakes, 3 with magnitudes — impossible
    dist = MagnitudeDistribution(
        under_2=2, from_2_to_under_4=1, from_4_to_under_5=0,
        from_5_to_under_6=0, six_or_more=0, unknown=0,
    )
    with pytest.raises(ValidationError, match="magnitude_count must not exceed"):
        Metric(**valid_metric(
            earthquake_count=2,
            magnitude_count=3,
            magnitude_sum=9.0,
            average_magnitude=3.0,
            max_magnitude=4.0,
            magnitude_distribution=dist,
        ))


# ---------------------------------------------------------------------------
# 13. Negative magnitude_sum accepted when internally consistent
# ---------------------------------------------------------------------------

def test_negative_magnitude_sum_accepted():
    # 2 events: magnitudes -3.0 and -1.0  →  sum=-4, avg=-2, max=-1
    dist = MagnitudeDistribution(
        under_2=2, from_2_to_under_4=0, from_4_to_under_5=0,
        from_5_to_under_6=0, six_or_more=0, unknown=0,
    )
    m = Metric(
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        earthquake_count=2,
        magnitude_count=2,
        magnitude_sum=-4.0,
        average_magnitude=-2.0,
        max_magnitude=-1.0,
        magnitude_distribution=dist,
        updated_at=UPDATED_AT,
    )
    assert m.magnitude_sum == -4.0
    assert m.average_magnitude == -2.0


# ---------------------------------------------------------------------------
# 14-16. Naive datetimes rejected
# ---------------------------------------------------------------------------

def test_naive_window_start_rejected():
    with pytest.raises(ValidationError):
        Metric(**valid_metric(window_start=datetime(2024, 6, 1, 12, 0, 0)))


def test_naive_window_end_rejected():
    with pytest.raises(ValidationError):
        Metric(**valid_metric(window_end=datetime(2024, 6, 1, 13, 0, 0)))


def test_naive_updated_at_rejected():
    with pytest.raises(ValidationError):
        Metric(**valid_metric(updated_at=datetime(2024, 6, 1, 12, 0, 0)))


# ---------------------------------------------------------------------------
# 17-19. Aware datetimes normalised to UTC
# ---------------------------------------------------------------------------

def test_window_start_normalized_to_utc():
    eastern = timezone(timedelta(hours=-5))
    start = datetime(2024, 6, 1, 7, 0, 0, tzinfo=eastern)  # = 12:00 UTC
    end = start + timedelta(hours=1)
    m = Metric(**valid_metric(window_start=start, window_end=end))
    assert m.window_start.tzinfo == UTC
    assert m.window_start == WINDOW_START


def test_window_end_normalized_to_utc():
    eastern = timezone(timedelta(hours=-5))
    start = datetime(2024, 6, 1, 7, 0, 0, tzinfo=eastern)
    end = datetime(2024, 6, 1, 8, 0, 0, tzinfo=eastern)  # = 13:00 UTC
    m = Metric(**valid_metric(window_start=start, window_end=end))
    assert m.window_end.tzinfo == UTC


def test_updated_at_normalized_to_utc():
    eastern = timezone(timedelta(hours=-5))
    updated = datetime(2024, 6, 1, 7, 0, 0, tzinfo=eastern)
    m = Metric(**valid_metric(updated_at=updated))
    assert m.updated_at.tzinfo == UTC
    assert m.updated_at == WINDOW_START


# ---------------------------------------------------------------------------
# 20-22. window_start alignment
# ---------------------------------------------------------------------------

def test_window_start_non_zero_minute_rejected():
    bad = datetime(2024, 6, 1, 12, 1, 0, tzinfo=UTC)
    with pytest.raises(ValidationError, match="aligned to the beginning of an hour"):
        Metric(**valid_metric(window_start=bad, window_end=bad + timedelta(hours=1)))


def test_window_start_non_zero_second_rejected():
    bad = datetime(2024, 6, 1, 12, 0, 1, tzinfo=UTC)
    with pytest.raises(ValidationError, match="aligned to the beginning of an hour"):
        Metric(**valid_metric(window_start=bad, window_end=bad + timedelta(hours=1)))


def test_window_start_non_zero_microsecond_rejected():
    bad = datetime(2024, 6, 1, 12, 0, 0, 1, tzinfo=UTC)
    with pytest.raises(ValidationError, match="aligned to the beginning of an hour"):
        Metric(**valid_metric(window_start=bad, window_end=bad + timedelta(hours=1)))


# ---------------------------------------------------------------------------
# 23-25. window_end constraints
# ---------------------------------------------------------------------------

def test_window_end_less_than_one_hour_rejected():
    with pytest.raises(ValidationError, match="window_end must be exactly"):
        Metric(**valid_metric(window_end=WINDOW_START + timedelta(minutes=59)))


def test_window_end_more_than_one_hour_rejected():
    with pytest.raises(ValidationError, match="window_end must be exactly"):
        Metric(**valid_metric(window_end=WINDOW_START + timedelta(hours=2)))


def test_exactly_one_hour_window_accepted():
    m = Metric(**valid_metric())
    assert m.window_end == m.window_start + timedelta(hours=1)


# ---------------------------------------------------------------------------
# 26-28. updated_at constraints
# ---------------------------------------------------------------------------

def test_updated_at_before_window_start_rejected():
    with pytest.raises(ValidationError, match="updated_at must be greater than or equal"):
        Metric(**valid_metric(updated_at=WINDOW_START - timedelta(seconds=1)))


def test_updated_at_equal_to_window_start_accepted():
    m = Metric(**valid_metric(updated_at=WINDOW_START))
    assert m.updated_at == WINDOW_START


def test_updated_at_after_window_end_accepted():
    late = WINDOW_END + timedelta(hours=2)
    m = Metric(**valid_metric(updated_at=late))
    assert m.updated_at > m.window_end


# ---------------------------------------------------------------------------
# 29. Distribution total must equal earthquake_count
# ---------------------------------------------------------------------------

def test_distribution_total_mismatch_rejected():
    dist = MagnitudeDistribution(
        under_2=1, from_2_to_under_4=0, from_4_to_under_5=0,
        from_5_to_under_6=0, six_or_more=0, unknown=0,
    )
    # earthquake_count=2 but dist total=1
    with pytest.raises(ValidationError, match="sum of all magnitude_distribution counters"):
        Metric(**valid_metric(
            earthquake_count=2,
            magnitude_count=1,
            magnitude_sum=1.5,
            average_magnitude=1.5,
            max_magnitude=1.5,
            magnitude_distribution=dist,
        ))


# ---------------------------------------------------------------------------
# 30. Known distribution total must equal magnitude_count
# ---------------------------------------------------------------------------

def test_known_distribution_total_mismatch_rejected():
    # earthquake_count=2, magnitude_count=2, but known counters sum to 1
    dist = MagnitudeDistribution(
        under_2=1, from_2_to_under_4=0, from_4_to_under_5=0,
        from_5_to_under_6=0, six_or_more=0, unknown=1,
    )
    with pytest.raises(ValidationError, match="sum of known magnitude_distribution counters"):
        Metric(**valid_metric(
            earthquake_count=2,
            magnitude_count=2,
            magnitude_sum=3.0,
            average_magnitude=1.5,
            max_magnitude=2.0,
            magnitude_distribution=dist,
        ))


# ---------------------------------------------------------------------------
# 31. unknown must equal earthquake_count - magnitude_count
# ---------------------------------------------------------------------------

def test_unknown_mismatch_rejected():
    # earthquake_count=3, magnitude_count=2 → unknown must be 1, but set to 2
    # dist total = known(2) + unknown(2) = 4 ≠ earthquake_count(3) → rejected
    dist = MagnitudeDistribution(
        under_2=1, from_2_to_under_4=1, from_4_to_under_5=0,
        from_5_to_under_6=0, six_or_more=0, unknown=2,
    )
    with pytest.raises(ValidationError):
        Metric(**valid_metric(
            earthquake_count=3,
            magnitude_count=2,
            magnitude_sum=3.0,
            average_magnitude=1.5,
            max_magnitude=2.0,
            magnitude_distribution=dist,
        ))


# ---------------------------------------------------------------------------
# 32. magnitude_count == 0 accepts sum=0, avg=None, max=None
# ---------------------------------------------------------------------------

def test_zero_magnitude_count_accepts_sum_zero_avg_none_max_none():
    m = Metric(**valid_metric(
        earthquake_count=0,
        magnitude_count=0,
        magnitude_sum=0.0,
        average_magnitude=None,
        max_magnitude=None,
        magnitude_distribution=MagnitudeDistribution(**EMPTY_DIST),
    ))
    assert m.average_magnitude is None
    assert m.max_magnitude is None
    assert m.magnitude_sum == 0.0


# ---------------------------------------------------------------------------
# 33. magnitude_count == 0 rejects non-zero magnitude_sum
# ---------------------------------------------------------------------------

def test_zero_magnitude_count_rejects_nonzero_sum():
    with pytest.raises(ValidationError, match="magnitude_sum must be 0"):
        Metric(**valid_metric(
            earthquake_count=0,
            magnitude_count=0,
            magnitude_sum=1.5,
            average_magnitude=None,
            max_magnitude=None,
            magnitude_distribution=MagnitudeDistribution(**EMPTY_DIST),
        ))


# ---------------------------------------------------------------------------
# 34. magnitude_count == 0 rejects non-None average
# ---------------------------------------------------------------------------

def test_zero_magnitude_count_rejects_non_none_average():
    with pytest.raises(ValidationError, match="average_magnitude must be None"):
        Metric(**valid_metric(
            earthquake_count=1,
            magnitude_count=0,
            magnitude_sum=0.0,
            average_magnitude=0.0,
            max_magnitude=None,
            magnitude_distribution=MagnitudeDistribution(
                **{**EMPTY_DIST, "unknown": 1}
            ),
        ))


# ---------------------------------------------------------------------------
# 35. magnitude_count == 0 rejects non-None maximum
# ---------------------------------------------------------------------------

def test_zero_magnitude_count_rejects_non_none_maximum():
    with pytest.raises(ValidationError, match="max_magnitude must be None"):
        Metric(**valid_metric(
            earthquake_count=1,
            magnitude_count=0,
            magnitude_sum=0.0,
            average_magnitude=None,
            max_magnitude=0.0,
            magnitude_distribution=MagnitudeDistribution(
                **{**EMPTY_DIST, "unknown": 1}
            ),
        ))


# ---------------------------------------------------------------------------
# 36. magnitude_count > 0 rejects average_magnitude None
# ---------------------------------------------------------------------------

def test_positive_magnitude_count_rejects_none_average():
    dist = MagnitudeDistribution(
        under_2=1, from_2_to_under_4=0, from_4_to_under_5=0,
        from_5_to_under_6=0, six_or_more=0, unknown=0,
    )
    with pytest.raises(ValidationError, match="average_magnitude must not be None"):
        Metric(**valid_metric(
            earthquake_count=1,
            magnitude_count=1,
            magnitude_sum=1.5,
            average_magnitude=None,
            max_magnitude=1.5,
            magnitude_distribution=dist,
        ))


# ---------------------------------------------------------------------------
# 37. magnitude_count > 0 rejects max_magnitude None
# ---------------------------------------------------------------------------

def test_positive_magnitude_count_rejects_none_max():
    dist = MagnitudeDistribution(
        under_2=1, from_2_to_under_4=0, from_4_to_under_5=0,
        from_5_to_under_6=0, six_or_more=0, unknown=0,
    )
    with pytest.raises(ValidationError, match="max_magnitude must not be None"):
        Metric(**valid_metric(
            earthquake_count=1,
            magnitude_count=1,
            magnitude_sum=1.5,
            average_magnitude=1.5,
            max_magnitude=None,
            magnitude_distribution=dist,
        ))


# ---------------------------------------------------------------------------
# 38. Incorrect average rejected
# ---------------------------------------------------------------------------

def test_incorrect_average_rejected():
    dist = MagnitudeDistribution(
        under_2=2, from_2_to_under_4=0, from_4_to_under_5=0,
        from_5_to_under_6=0, six_or_more=0, unknown=0,
    )
    # magnitude_sum=3.0, count=2 → avg should be 1.5, not 2.0
    with pytest.raises(ValidationError, match="average_magnitude"):
        Metric(**valid_metric(
            earthquake_count=2,
            magnitude_count=2,
            magnitude_sum=3.0,
            average_magnitude=2.0,
            max_magnitude=2.0,
            magnitude_distribution=dist,
        ))


# ---------------------------------------------------------------------------
# 39. Correct floating-point average accepted using tolerant comparison
# ---------------------------------------------------------------------------

def test_correct_floating_point_average_accepted():
    # 1/3 cannot be represented exactly; model should accept via math.isclose
    dist = MagnitudeDistribution(
        under_2=3, from_2_to_under_4=0, from_4_to_under_5=0,
        from_5_to_under_6=0, six_or_more=0, unknown=0,
    )
    avg = 1.0 / 3.0
    m = Metric(**valid_metric(
        earthquake_count=3,
        magnitude_count=3,
        magnitude_sum=1.0,
        average_magnitude=avg,
        max_magnitude=avg,
        magnitude_distribution=dist,
    ))
    import math
    assert math.isclose(m.average_magnitude, avg)


# ---------------------------------------------------------------------------
# 40. max_magnitude lower than average_magnitude rejected
# ---------------------------------------------------------------------------

def test_max_lower_than_average_rejected():
    dist = MagnitudeDistribution(
        under_2=2, from_2_to_under_4=0, from_4_to_under_5=0,
        from_5_to_under_6=0, six_or_more=0, unknown=0,
    )
    with pytest.raises(ValidationError, match="max_magnitude must be greater than or equal"):
        Metric(**valid_metric(
            earthquake_count=2,
            magnitude_count=2,
            magnitude_sum=3.0,
            average_magnitude=1.5,
            max_magnitude=1.0,   # less than average 1.5
            magnitude_distribution=dist,
        ))


# ---------------------------------------------------------------------------
# 41. Negative magnitudes produce valid negative average and maximum
# ---------------------------------------------------------------------------

def test_negative_magnitudes_valid():
    dist = MagnitudeDistribution(
        under_2=2, from_2_to_under_4=0, from_4_to_under_5=0,
        from_5_to_under_6=0, six_or_more=0, unknown=0,
    )
    m = Metric(**valid_metric(
        earthquake_count=2,
        magnitude_count=2,
        magnitude_sum=-4.0,
        average_magnitude=-2.0,
        max_magnitude=-1.0,
        magnitude_distribution=dist,
    ))
    assert m.average_magnitude == -2.0
    assert m.max_magnitude == -1.0


# ---------------------------------------------------------------------------
# 42. model_dump(mode="python") preserves datetime objects
# ---------------------------------------------------------------------------

def test_model_dump_preserves_datetimes():
    m = Metric(**valid_metric())
    data = m.model_dump(mode="python")
    assert isinstance(data["window_start"], datetime)
    assert isinstance(data["window_end"], datetime)
    assert isinstance(data["updated_at"], datetime)


# ---------------------------------------------------------------------------
# 43-45. Tz-aware ISO strings accepted and normalised to UTC
#         (Pydantic coerces str→datetime before after-validator runs)
# ---------------------------------------------------------------------------

def test_iso_string_window_start_accepted_and_normalised():
    m = Metric(**valid_metric(window_start="2024-06-01T12:00:00+00:00"))
    assert m.window_start == WINDOW_START
    assert m.window_start.tzinfo == UTC


def test_iso_string_window_end_accepted_and_normalised():
    m = Metric(**valid_metric(window_end="2024-06-01T13:00:00+00:00"))
    assert m.window_end == WINDOW_END
    assert m.window_end.tzinfo == UTC


def test_iso_string_updated_at_accepted_and_normalised():
    m = Metric(**valid_metric(updated_at="2024-06-01T12:00:00+00:00"))
    assert m.updated_at == UPDATED_AT
    assert m.updated_at.tzinfo == UTC


# ---------------------------------------------------------------------------
# 46-48. Naive ISO strings rejected (no timezone info after coercion)
# ---------------------------------------------------------------------------

def test_naive_iso_string_window_start_rejected():
    with pytest.raises(ValidationError):
        Metric(**valid_metric(window_start="2024-06-01T12:00:00"))


def test_naive_iso_string_window_end_rejected():
    with pytest.raises(ValidationError):
        Metric(**valid_metric(window_end="2024-06-01T13:00:00"))


def test_naive_iso_string_updated_at_rejected():
    with pytest.raises(ValidationError):
        Metric(**valid_metric(updated_at="2024-06-01T12:00:00"))


# ---------------------------------------------------------------------------
# 47-52. Distribution counters reject str, float, and bool
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("field", [
    "under_2", "from_2_to_under_4", "from_4_to_under_5",
    "from_5_to_under_6", "six_or_more", "unknown",
])
def test_distribution_counter_rejects_string(field):
    data = {**EMPTY_DIST, field: "1"}
    with pytest.raises(ValidationError):
        MagnitudeDistribution(**data)


@pytest.mark.parametrize("field", [
    "under_2", "from_2_to_under_4", "from_4_to_under_5",
    "from_5_to_under_6", "six_or_more", "unknown",
])
def test_distribution_counter_rejects_float(field):
    data = {**EMPTY_DIST, field: 1.0}
    with pytest.raises(ValidationError):
        MagnitudeDistribution(**data)


@pytest.mark.parametrize("field", [
    "under_2", "from_2_to_under_4", "from_4_to_under_5",
    "from_5_to_under_6", "six_or_more", "unknown",
])
def test_distribution_counter_rejects_bool(field):
    data = {**EMPTY_DIST, field: True}
    with pytest.raises(ValidationError):
        MagnitudeDistribution(**data)


# ---------------------------------------------------------------------------
# 53-54. earthquake_count and magnitude_count reject str, float, bool
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("field", ["earthquake_count", "magnitude_count"])
def test_metric_count_rejects_string(field):
    with pytest.raises(ValidationError):
        Metric(**valid_metric(**{field: "1"}))


@pytest.mark.parametrize("field", ["earthquake_count", "magnitude_count"])
def test_metric_count_rejects_float(field):
    with pytest.raises(ValidationError):
        Metric(**valid_metric(**{field: 0.0}))


@pytest.mark.parametrize("field", ["earthquake_count", "magnitude_count"])
def test_metric_count_rejects_bool(field):
    with pytest.raises(ValidationError):
        Metric(**valid_metric(**{field: False}))


# ---------------------------------------------------------------------------
# 55. Real integers still accepted for all strict counter fields
# ---------------------------------------------------------------------------

def test_distribution_integer_counters_accepted():
    d = MagnitudeDistribution(
        under_2=1, from_2_to_under_4=2, from_4_to_under_5=3,
        from_5_to_under_6=0, six_or_more=0, unknown=0,
    )
    assert d.under_2 == 1
    assert d.from_2_to_under_4 == 2
    assert d.from_4_to_under_5 == 3


def test_metric_integer_counts_accepted():
    dist = MagnitudeDistribution(
        under_2=2, from_2_to_under_4=0, from_4_to_under_5=0,
        from_5_to_under_6=0, six_or_more=0, unknown=1,
    )
    m = Metric(**valid_metric(
        earthquake_count=3,
        magnitude_count=2,
        magnitude_sum=3.0,
        average_magnitude=1.5,
        max_magnitude=2.0,
        magnitude_distribution=dist,
    ))
    assert m.earthquake_count == 3
    assert m.magnitude_count == 2


# ---------------------------------------------------------------------------
# Existing Earthquake export unbroken
# ---------------------------------------------------------------------------

def test_earthquake_still_importable_from_app_models():
    from app.models import Earthquake as EQ
    from app.models.earthquake import Earthquake as EQDirect
    assert EQ is EQDirect
