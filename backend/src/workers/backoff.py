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
    return uniform(ceiling / 2, ceiling)
