import pytest

from workers.backoff import backoff_seconds


def upper(low: float, high: float) -> float:
    return high


def lower(low: float, high: float) -> float:
    return low


@pytest.mark.parametrize(("attempt", "ceiling"), [(1, 5), (2, 10), (3, 20), (4, 40)])
def test_the_ceiling_doubles_with_each_attempt(attempt: int, ceiling: float) -> None:
    assert backoff_seconds(attempt, base=5, cap=300, uniform=upper) == ceiling


def test_the_ceiling_stops_at_the_cap() -> None:
    assert backoff_seconds(20, base=5, cap=300, uniform=upper) == 300


def test_jitter_keeps_at_least_half_of_the_ceiling() -> None:
    assert backoff_seconds(3, base=5, cap=300, uniform=lower) == 10


def test_the_real_jitter_stays_within_bounds() -> None:
    delays = [backoff_seconds(2, base=5, cap=300) for _ in range(200)]

    assert all(5 <= delay <= 10 for delay in delays)
    assert len(set(delays)) > 1
