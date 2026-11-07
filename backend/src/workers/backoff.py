import random
from collections.abc import Callable


def backoff_seconds(
    attempt: int,
    *,
    base: float,
    cap: float,
    uniform: Callable[[float, float], float] = random.uniform,
) -> float:
    ceiling = min(cap, base * 2 ** max(attempt - 1, 0))
    # Half fixed, half random: retries of tickets that failed together spread
    # out instead of hitting the provider again in the same second.
    return uniform(ceiling / 2, ceiling)
