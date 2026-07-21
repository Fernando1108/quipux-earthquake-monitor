"""Unit tests for the Earthquake domain model."""

from datetime import datetime, timezone, timedelta

import pytest
from pydantic import ValidationError

from app.models import Earthquake
from app.models.earthquake import Earthquake as EarthquakeFromModule


VALID_DATA = {
    "event_id": "us7000abc1",
    "magnitude": 4.5,
    "location": "10km NE of Springfield",
    "latitude": 35.0,
    "longitude": -118.0,
    "depth": 10.0,
    "event_time": datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
}


def valid(**overrides) -> dict:
    return {**VALID_DATA, **overrides}


# ---------------------------------------------------------------------------
# 1. Valid creation
# ---------------------------------------------------------------------------

def test_valid_creation():
    eq = Earthquake(**VALID_DATA)
    assert eq.event_id == "us7000abc1"
    assert eq.magnitude == 4.5
    assert eq.location == "10km NE of Springfield"
    assert eq.latitude == 35.0
    assert eq.longitude == -118.0
    assert eq.depth == 10.0
    assert eq.event_time == datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# 2. Magnitude None
# ---------------------------------------------------------------------------

def test_magnitude_none_is_valid():
    eq = Earthquake(**valid(magnitude=None))
    assert eq.magnitude is None


# ---------------------------------------------------------------------------
# 3. Location None
# ---------------------------------------------------------------------------

def test_location_none_is_valid():
    eq = Earthquake(**valid(location=None))
    assert eq.location is None


# ---------------------------------------------------------------------------
# 4. Empty location normalised to None
# ---------------------------------------------------------------------------

def test_location_empty_string_becomes_none():
    eq = Earthquake(**valid(location=""))
    assert eq.location is None


def test_location_whitespace_only_becomes_none():
    eq = Earthquake(**valid(location="   "))
    assert eq.location is None


# ---------------------------------------------------------------------------
# 5. event_id strip
# ---------------------------------------------------------------------------

def test_event_id_leading_trailing_spaces_stripped():
    eq = Earthquake(**valid(event_id="  us7000abc1  "))
    assert eq.event_id == "us7000abc1"


# ---------------------------------------------------------------------------
# 6. event_id empty rejected
# ---------------------------------------------------------------------------

def test_event_id_empty_string_rejected():
    with pytest.raises(ValidationError):
        Earthquake(**valid(event_id=""))


# ---------------------------------------------------------------------------
# 7. event_id whitespace only rejected
# ---------------------------------------------------------------------------

def test_event_id_whitespace_only_rejected():
    with pytest.raises(ValidationError):
        Earthquake(**valid(event_id="   "))


# ---------------------------------------------------------------------------
# 8-11. latitude
# ---------------------------------------------------------------------------

def test_latitude_minus_90_accepted():
    eq = Earthquake(**valid(latitude=-90.0))
    assert eq.latitude == -90.0


def test_latitude_90_accepted():
    eq = Earthquake(**valid(latitude=90.0))
    assert eq.latitude == 90.0


def test_latitude_below_minus_90_rejected():
    with pytest.raises(ValidationError):
        Earthquake(**valid(latitude=-90.1))


def test_latitude_above_90_rejected():
    with pytest.raises(ValidationError):
        Earthquake(**valid(latitude=90.1))


# ---------------------------------------------------------------------------
# 12-15. longitude
# ---------------------------------------------------------------------------

def test_longitude_minus_180_accepted():
    eq = Earthquake(**valid(longitude=-180.0))
    assert eq.longitude == -180.0


def test_longitude_180_accepted():
    eq = Earthquake(**valid(longitude=180.0))
    assert eq.longitude == 180.0


def test_longitude_below_minus_180_rejected():
    with pytest.raises(ValidationError):
        Earthquake(**valid(longitude=-180.1))


def test_longitude_above_180_rejected():
    with pytest.raises(ValidationError):
        Earthquake(**valid(longitude=180.1))


# ---------------------------------------------------------------------------
# 16-17. depth
# ---------------------------------------------------------------------------

def test_depth_zero_accepted():
    eq = Earthquake(**valid(depth=0.0))
    assert eq.depth == 0.0


def test_depth_negative_rejected():
    with pytest.raises(ValidationError):
        Earthquake(**valid(depth=-0.1))


# ---------------------------------------------------------------------------
# 18. event_time without timezone rejected
# ---------------------------------------------------------------------------

def test_event_time_naive_datetime_rejected():
    with pytest.raises(ValidationError):
        Earthquake(**valid(event_time=datetime(2024, 1, 15, 12, 0, 0)))


# ---------------------------------------------------------------------------
# 19. event_time with non-UTC timezone normalised to UTC
# ---------------------------------------------------------------------------

def test_event_time_non_utc_normalised_to_utc():
    eastern = timezone(timedelta(hours=-5))
    local_time = datetime(2024, 1, 15, 7, 0, 0, tzinfo=eastern)
    eq = Earthquake(**valid(event_time=local_time))
    assert eq.event_time == datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    assert eq.event_time.tzinfo == timezone.utc


# ---------------------------------------------------------------------------
# 20. Extra fields rejected
# ---------------------------------------------------------------------------

def test_extra_fields_rejected():
    with pytest.raises(ValidationError):
        Earthquake(**valid(tsunami=False))


def test_extra_field_status_rejected():
    with pytest.raises(ValidationError):
        Earthquake(**valid(status="reviewed"))


# ---------------------------------------------------------------------------
# 21. model_dump serialisation
# ---------------------------------------------------------------------------

def test_model_dump_returns_expected_keys():
    eq = Earthquake(**VALID_DATA)
    data = eq.model_dump()
    assert set(data.keys()) == {
        "event_id",
        "magnitude",
        "location",
        "latitude",
        "longitude",
        "depth",
        "event_time",
    }


def test_model_dump_values_match():
    eq = Earthquake(**VALID_DATA)
    data = eq.model_dump()
    assert data["event_id"] == "us7000abc1"
    assert data["magnitude"] == 4.5
    assert data["depth"] == 10.0


# ---------------------------------------------------------------------------
# 22. Import from app.models
# ---------------------------------------------------------------------------

def test_import_from_app_models():
    assert Earthquake is EarthquakeFromModule


# ---------------------------------------------------------------------------
# 23. Type rejection for event_id and location
# ---------------------------------------------------------------------------

def test_event_id_non_string_rejected():
    with pytest.raises(ValidationError, match="event_id must be a string"):
        Earthquake(**valid(event_id=123))


def test_location_non_string_rejected():
    with pytest.raises(ValidationError, match="location must be a string or None"):
        Earthquake(**valid(location=42))
