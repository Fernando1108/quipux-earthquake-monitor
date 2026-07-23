"""Unit tests for Report and TopLocation domain models — no DB or network."""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.models.report import Report, TopLocation

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

UTC = timezone.utc
OFFSET_PLUS_5 = timezone(timedelta(hours=5))

PERIOD_START = datetime(2024, 6, 1, 12, 0, tzinfo=UTC)
PERIOD_END = PERIOD_START + timedelta(hours=1)
REPORT_DATE = PERIOD_END
GENERATED_AT = PERIOD_END + timedelta(seconds=10)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_top_location_data(**overrides) -> dict:
    defaults = dict(location="California", count=3)
    defaults.update(overrides)
    return defaults


def make_top_location(**overrides) -> TopLocation:
    return TopLocation(**make_top_location_data(**overrides))


def make_report_data(**overrides) -> dict:
    defaults = dict(
        report_date=REPORT_DATE,
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        total_events=10,
        events_with_magnitude=8,
        average_magnitude=3.5,
        max_magnitude=5.0,
        top_locations=[],
        generated_at=GENERATED_AT,
    )
    defaults.update(overrides)
    return defaults


def make_report(**overrides) -> Report:
    return Report(**make_report_data(**overrides))


# ---------------------------------------------------------------------------
# A. Public exports
# ---------------------------------------------------------------------------


def test_report_importable_from_app_models():
    from app.models import Report as R

    assert R is not None


def test_toplocation_importable_from_app_models():
    from app.models import TopLocation as TL

    assert TL is not None


def test_package_exports_are_same_class_objects():
    from app.models import Report as PkgReport
    from app.models import TopLocation as PkgTopLocation

    assert PkgReport is Report
    assert PkgTopLocation is TopLocation


def test_earthquake_export_remains_available():
    from app.models import Earthquake

    assert Earthquake is not None


def test_metric_export_remains_available():
    from app.models import Metric

    assert Metric is not None


def test_magnitude_distribution_export_remains_available():
    from app.models import MagnitudeDistribution

    assert MagnitudeDistribution is not None


def test_all_contains_exactly_five_names():
    import app.models as mod

    assert set(mod.__all__) == {
        "Earthquake",
        "MagnitudeDistribution",
        "Metric",
        "Report",
        "TopLocation",
    }
    assert len(mod.__all__) == 5


# ---------------------------------------------------------------------------
# B. TopLocation valid cases
# ---------------------------------------------------------------------------


def test_toplocation_valid_creation():
    tl = make_top_location()
    assert tl.location == "California"
    assert tl.count == 3


def test_toplocation_strips_leading_trailing_whitespace():
    tl = make_top_location(location="  Nevada  ")
    assert tl.location == "Nevada"


def test_toplocation_preserves_internal_whitespace():
    tl = make_top_location(location="New Mexico")
    assert tl.location == "New Mexico"


def test_toplocation_preserves_original_case():
    tl = make_top_location(location="CALIFORNIA")
    assert tl.location == "CALIFORNIA"


def test_toplocation_count_one_accepted():
    tl = make_top_location(count=1)
    assert tl.count == 1


def test_toplocation_large_count_accepted():
    tl = make_top_location(count=9999)
    assert tl.count == 9999


def test_toplocation_model_dump_has_exactly_location_and_count():
    tl = make_top_location()
    assert set(tl.model_dump().keys()) == {"location", "count"}


# ---------------------------------------------------------------------------
# C. TopLocation invalid location
# ---------------------------------------------------------------------------


def test_toplocation_empty_string_rejected():
    with pytest.raises(ValidationError):
        make_top_location(location="")


def test_toplocation_whitespace_only_rejected():
    with pytest.raises(ValidationError):
        make_top_location(location="   ")


def test_toplocation_none_location_rejected():
    with pytest.raises(ValidationError):
        make_top_location(location=None)


def test_toplocation_integer_location_rejected():
    with pytest.raises(ValidationError):
        make_top_location(location=42)


def test_toplocation_float_location_rejected():
    with pytest.raises(ValidationError):
        make_top_location(location=3.14)


def test_toplocation_boolean_location_rejected():
    with pytest.raises(ValidationError):
        make_top_location(location=True)


def test_toplocation_list_location_rejected():
    with pytest.raises(ValidationError):
        make_top_location(location=["California"])


def test_toplocation_dict_location_rejected():
    with pytest.raises(ValidationError):
        make_top_location(location={"name": "California"})


def test_toplocation_extra_field_rejected():
    with pytest.raises(ValidationError):
        TopLocation(location="California", count=3, extra="bad")


# ---------------------------------------------------------------------------
# D. TopLocation invalid count
# ---------------------------------------------------------------------------


def test_toplocation_count_zero_rejected():
    with pytest.raises(ValidationError):
        make_top_location(count=0)


def test_toplocation_count_negative_rejected():
    with pytest.raises(ValidationError):
        make_top_location(count=-1)


def test_toplocation_count_boolean_rejected():
    with pytest.raises(ValidationError):
        make_top_location(count=True)


def test_toplocation_count_float_rejected():
    with pytest.raises(ValidationError):
        make_top_location(count=3.0)


def test_toplocation_count_numeric_string_rejected():
    with pytest.raises(ValidationError):
        make_top_location(count="3")


def test_toplocation_count_none_rejected():
    with pytest.raises(ValidationError):
        make_top_location(count=None)


def test_toplocation_missing_count_rejected():
    with pytest.raises(ValidationError):
        TopLocation(location="California")


# ---------------------------------------------------------------------------
# E. Report valid cases
# ---------------------------------------------------------------------------


def test_report_valid_creation():
    r = make_report()
    assert r.total_events == 10


def test_report_every_field_preserved():
    r = make_report()
    assert r.report_date == REPORT_DATE
    assert r.period_start == PERIOD_START
    assert r.period_end == PERIOD_END
    assert r.total_events == 10
    assert r.events_with_magnitude == 8
    assert r.average_magnitude == pytest.approx(3.5)
    assert r.max_magnitude == pytest.approx(5.0)
    assert r.top_locations == []
    assert r.generated_at == GENERATED_AT


def test_report_top_locations_becomes_list_of_toplocation():
    r = make_report(
        top_locations=[{"location": "California", "count": 3}],
        total_events=10,
    )
    assert len(r.top_locations) == 1
    assert isinstance(r.top_locations[0], TopLocation)


def test_report_empty_top_locations_accepted():
    r = make_report(top_locations=[])
    assert r.top_locations == []


def test_report_negative_magnitudes_accepted():
    r = make_report(
        events_with_magnitude=5,
        average_magnitude=-2.0,
        max_magnitude=-0.5,
    )
    assert r.average_magnitude == pytest.approx(-2.0)
    assert r.max_magnitude == pytest.approx(-0.5)


def test_report_generated_at_equal_period_end_accepted():
    r = make_report(generated_at=PERIOD_END)
    assert r.generated_at == PERIOD_END


def test_report_generated_at_later_than_period_end_accepted():
    r = make_report(generated_at=PERIOD_END + timedelta(hours=2))
    assert r.generated_at > PERIOD_END


def test_report_model_dump_has_exactly_nine_keys():
    r = make_report()
    expected = {
        "report_date",
        "period_start",
        "period_end",
        "total_events",
        "events_with_magnitude",
        "average_magnitude",
        "max_magnitude",
        "top_locations",
        "generated_at",
    }
    assert set(r.model_dump().keys()) == expected


def test_report_nested_model_dump_has_location_and_count():
    r = make_report(
        top_locations=[TopLocation(location="California", count=3)],
        total_events=10,
    )
    nested = r.model_dump()["top_locations"][0]
    assert set(nested.keys()) == {"location", "count"}


# ---------------------------------------------------------------------------
# F. Datetime validation
# ---------------------------------------------------------------------------


def test_naive_report_date_rejected():
    with pytest.raises(ValidationError):
        make_report(report_date=datetime(2024, 6, 1, 13, 0))


def test_naive_period_start_rejected():
    with pytest.raises(ValidationError):
        make_report(period_start=datetime(2024, 6, 1, 12, 0))


def test_naive_period_end_rejected():
    with pytest.raises(ValidationError):
        make_report(period_end=datetime(2024, 6, 1, 13, 0))


def test_naive_generated_at_rejected():
    with pytest.raises(ValidationError):
        make_report(generated_at=datetime(2024, 6, 1, 13, 0, 10))


def test_non_utc_report_date_normalized_to_utc():
    # 2024-06-01T18:00:00+05:00 == 13:00 UTC == PERIOD_END
    non_utc = datetime(2024, 6, 1, 18, 0, tzinfo=OFFSET_PLUS_5)
    r = make_report(report_date=non_utc)
    assert r.report_date == PERIOD_END
    assert r.report_date.tzinfo == UTC


def test_non_utc_period_start_normalized_to_utc():
    # 2024-06-01T17:00:00+05:00 == 12:00 UTC == PERIOD_START
    non_utc = datetime(2024, 6, 1, 17, 0, tzinfo=OFFSET_PLUS_5)
    r = make_report(period_start=non_utc)
    assert r.period_start == PERIOD_START
    assert r.period_start.tzinfo == UTC


def test_non_utc_period_end_normalized_to_utc():
    # 2024-06-01T18:00:00+05:00 == 13:00 UTC == PERIOD_END
    non_utc = datetime(2024, 6, 1, 18, 0, tzinfo=OFFSET_PLUS_5)
    r = make_report(period_end=non_utc, report_date=non_utc)
    assert r.period_end == PERIOD_END
    assert r.period_end.tzinfo == UTC


def test_non_utc_generated_at_normalized_to_utc():
    # 2024-06-01T18:00:10+05:00 == 13:00:10 UTC == GENERATED_AT
    non_utc = datetime(2024, 6, 1, 18, 0, 10, tzinfo=OFFSET_PLUS_5)
    r = make_report(generated_at=non_utc)
    assert r.generated_at == GENERATED_AT
    assert r.generated_at.tzinfo == UTC


def test_period_start_non_zero_minute_rejected():
    with pytest.raises(ValidationError):
        make_report(period_start=datetime(2024, 6, 1, 12, 30, tzinfo=UTC))


def test_period_start_non_zero_second_rejected():
    with pytest.raises(ValidationError):
        make_report(period_start=datetime(2024, 6, 1, 12, 0, 1, tzinfo=UTC))


def test_period_start_non_zero_microsecond_rejected():
    with pytest.raises(ValidationError):
        make_report(period_start=datetime(2024, 6, 1, 12, 0, 0, 1, tzinfo=UTC))


# ---------------------------------------------------------------------------
# G. Window consistency
# ---------------------------------------------------------------------------


def test_period_end_less_than_one_hour_after_start_rejected():
    wrong_end = PERIOD_START + timedelta(minutes=30)
    with pytest.raises(ValidationError):
        make_report(
            period_end=wrong_end,
            report_date=wrong_end,
            generated_at=wrong_end + timedelta(seconds=10),
        )


def test_period_end_more_than_one_hour_after_start_rejected():
    wrong_end = PERIOD_START + timedelta(hours=2)
    with pytest.raises(ValidationError):
        make_report(
            period_end=wrong_end,
            report_date=wrong_end,
            generated_at=wrong_end + timedelta(seconds=10),
        )


def test_report_date_before_period_end_rejected():
    with pytest.raises(ValidationError):
        make_report(report_date=PERIOD_START)


def test_report_date_after_period_end_rejected():
    with pytest.raises(ValidationError):
        make_report(report_date=PERIOD_END + timedelta(hours=1))


def test_generated_at_before_period_end_rejected():
    with pytest.raises(ValidationError):
        make_report(generated_at=PERIOD_END - timedelta(seconds=1))


def test_period_end_exactly_one_hour_after_start_accepted():
    r = make_report(period_end=PERIOD_END, report_date=PERIOD_END)
    assert r.period_end == PERIOD_START + timedelta(hours=1)


def test_report_date_exactly_equals_period_end_accepted():
    r = make_report(report_date=PERIOD_END)
    assert r.report_date == r.period_end


# ---------------------------------------------------------------------------
# H. Count validation
# ---------------------------------------------------------------------------


def test_total_events_negative_rejected():
    with pytest.raises(ValidationError):
        make_report(total_events=-1)


def test_total_events_boolean_rejected():
    with pytest.raises(ValidationError):
        make_report(total_events=True)


def test_total_events_float_rejected():
    with pytest.raises(ValidationError):
        make_report(total_events=5.0)


def test_total_events_numeric_string_rejected():
    with pytest.raises(ValidationError):
        make_report(total_events="5")


def test_events_with_magnitude_negative_rejected():
    with pytest.raises(ValidationError):
        make_report(events_with_magnitude=-1)


def test_events_with_magnitude_boolean_rejected():
    with pytest.raises(ValidationError):
        make_report(events_with_magnitude=True)


def test_events_with_magnitude_float_rejected():
    with pytest.raises(ValidationError):
        make_report(events_with_magnitude=5.0)


def test_events_with_magnitude_numeric_string_rejected():
    with pytest.raises(ValidationError):
        make_report(events_with_magnitude="5")


def test_events_with_magnitude_greater_than_total_rejected():
    with pytest.raises(ValidationError):
        make_report(total_events=5, events_with_magnitude=6)


def test_events_with_magnitude_equal_to_total_accepted():
    r = make_report(total_events=8, events_with_magnitude=8)
    assert r.events_with_magnitude == r.total_events


def test_zero_counts_with_consistent_stats_accepted():
    r = make_report(
        total_events=0,
        events_with_magnitude=0,
        average_magnitude=None,
        max_magnitude=None,
        top_locations=[],
    )
    assert r.total_events == 0
    assert r.events_with_magnitude == 0


# ---------------------------------------------------------------------------
# I. Magnitude statistics
# ---------------------------------------------------------------------------


def test_zero_events_with_magnitude_requires_average_none():
    with pytest.raises(ValidationError):
        make_report(
            events_with_magnitude=0,
            average_magnitude=3.5,
            max_magnitude=None,
        )


def test_zero_events_with_magnitude_requires_max_none():
    with pytest.raises(ValidationError):
        make_report(
            events_with_magnitude=0,
            average_magnitude=None,
            max_magnitude=5.0,
        )


def test_both_none_accepted_when_events_with_magnitude_zero():
    r = make_report(
        events_with_magnitude=0,
        average_magnitude=None,
        max_magnitude=None,
    )
    assert r.average_magnitude is None
    assert r.max_magnitude is None


def test_positive_total_events_with_zero_events_with_magnitude_accepted():
    r = make_report(
        total_events=5,
        events_with_magnitude=0,
        average_magnitude=None,
        max_magnitude=None,
        top_locations=[],
    )
    assert r.total_events == 5
    assert r.events_with_magnitude == 0


def test_positive_events_with_magnitude_requires_average():
    with pytest.raises(ValidationError):
        make_report(
            events_with_magnitude=5,
            average_magnitude=None,
            max_magnitude=5.0,
        )


def test_positive_events_with_magnitude_requires_max():
    with pytest.raises(ValidationError):
        make_report(
            events_with_magnitude=5,
            average_magnitude=3.5,
            max_magnitude=None,
        )


def test_max_below_average_rejected():
    with pytest.raises(ValidationError):
        make_report(
            events_with_magnitude=5,
            average_magnitude=5.0,
            max_magnitude=3.0,
        )


def test_max_equal_to_average_accepted():
    r = make_report(
        events_with_magnitude=5,
        average_magnitude=4.0,
        max_magnitude=4.0,
    )
    assert r.max_magnitude == pytest.approx(r.average_magnitude)


def test_max_above_average_accepted():
    r = make_report(
        events_with_magnitude=5,
        average_magnitude=3.0,
        max_magnitude=6.0,
    )
    assert r.max_magnitude > r.average_magnitude


def test_nan_average_rejected():
    with pytest.raises(ValidationError):
        make_report(
            events_with_magnitude=5,
            average_magnitude=float("nan"),
            max_magnitude=5.0,
        )


def test_nan_max_rejected():
    with pytest.raises(ValidationError):
        make_report(
            events_with_magnitude=5,
            average_magnitude=3.5,
            max_magnitude=float("nan"),
        )


def test_positive_infinity_average_rejected():
    with pytest.raises(ValidationError):
        make_report(
            events_with_magnitude=5,
            average_magnitude=float("inf"),
            max_magnitude=float("inf"),
        )


def test_negative_infinity_average_rejected():
    with pytest.raises(ValidationError):
        make_report(
            events_with_magnitude=5,
            average_magnitude=float("-inf"),
            max_magnitude=5.0,
        )


def test_positive_infinity_max_rejected():
    with pytest.raises(ValidationError):
        make_report(
            events_with_magnitude=5,
            average_magnitude=3.0,
            max_magnitude=float("inf"),
        )


def test_negative_infinity_max_rejected():
    with pytest.raises(ValidationError):
        make_report(
            events_with_magnitude=5,
            average_magnitude=3.0,
            max_magnitude=float("-inf"),
        )


# ---------------------------------------------------------------------------
# J. Top locations consistency
# ---------------------------------------------------------------------------


def test_empty_top_locations_accepted():
    r = make_report(top_locations=[])
    assert r.top_locations == []


def test_one_location_accepted():
    r = make_report(
        total_events=5,
        events_with_magnitude=5,
        top_locations=[TopLocation(location="California", count=3)],
    )
    assert len(r.top_locations) == 1


def test_multiple_different_locations_accepted():
    r = make_report(
        total_events=10,
        top_locations=[
            TopLocation(location="California", count=4),
            TopLocation(location="Nevada", count=3),
        ],
    )
    assert len(r.top_locations) == 2


def test_duplicate_exact_locations_rejected():
    with pytest.raises(ValidationError):
        make_report(
            total_events=10,
            top_locations=[
                TopLocation(location="California", count=3),
                TopLocation(location="California", count=2),
            ],
        )


def test_different_casing_not_treated_as_duplicate():
    r = make_report(
        total_events=10,
        top_locations=[
            TopLocation(location="California", count=4),
            TopLocation(location="california", count=3),
        ],
    )
    assert len(r.top_locations) == 2


def test_sum_of_counts_equal_to_total_events_accepted():
    r = make_report(
        total_events=5,
        events_with_magnitude=0,
        average_magnitude=None,
        max_magnitude=None,
        top_locations=[
            TopLocation(location="California", count=3),
            TopLocation(location="Nevada", count=2),
        ],
    )
    total = sum(item.count for item in r.top_locations)
    assert total == r.total_events


def test_sum_of_counts_below_total_events_accepted():
    r = make_report(
        total_events=10,
        top_locations=[TopLocation(location="California", count=3)],
    )
    assert sum(item.count for item in r.top_locations) < r.total_events


def test_sum_of_counts_above_total_events_rejected():
    with pytest.raises(ValidationError):
        make_report(
            total_events=5,
            top_locations=[
                TopLocation(location="California", count=3),
                TopLocation(location="Nevada", count=3),
            ],
        )


def test_nonempty_list_rejected_when_total_events_zero():
    with pytest.raises(ValidationError):
        make_report(
            total_events=0,
            events_with_magnitude=0,
            average_magnitude=None,
            max_magnitude=None,
            top_locations=[TopLocation(location="California", count=1)],
        )


def test_nested_extra_fields_rejected():
    with pytest.raises(ValidationError):
        make_report(
            total_events=5,
            top_locations=[{"location": "California", "count": 3, "extra": "bad"}],
        )


def test_invalid_nested_toplocation_propagates_validation_error():
    with pytest.raises(ValidationError):
        make_report(
            total_events=5,
            top_locations=[{"location": "", "count": 3}],
        )


def test_top_locations_order_preserved():
    locations_in = ["Zz", "Aa", "Mm"]
    r = make_report(
        total_events=6,
        events_with_magnitude=6,
        top_locations=[TopLocation(location=loc, count=2) for loc in locations_in],
    )
    assert [item.location for item in r.top_locations] == locations_in


def test_model_does_not_sort_top_locations():
    locations_in = ["Nevada", "California", "Alaska"]
    r = make_report(
        total_events=6,
        events_with_magnitude=6,
        top_locations=[TopLocation(location=loc, count=2) for loc in locations_in],
    )
    assert [item.location for item in r.top_locations] == locations_in


# ---------------------------------------------------------------------------
# K. Report structure
# ---------------------------------------------------------------------------


def test_extra_report_fields_rejected():
    with pytest.raises(ValidationError):
        Report(**make_report_data(), extra_field="bad")


def test_missing_required_field_rejected():
    data = make_report_data()
    del data["report_date"]
    with pytest.raises(ValidationError):
        Report(**data)


def test_top_locations_none_rejected():
    with pytest.raises(ValidationError):
        make_report(top_locations=None)


def test_top_locations_with_non_object_values_rejected():
    with pytest.raises(ValidationError):
        make_report(
            total_events=5,
            top_locations=[42],
        )
