import math
from collections import Counter
from dataclasses import dataclass, field

ACTIVE_STATUSES = ("received", "generating", "approved", "sending")


def percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile; 0 for an empty list."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(fraction * len(ordered)))
    return ordered[rank - 1]


def is_drained(counts: dict[str, int], approving: bool) -> bool:
    active = ACTIVE_STATUSES + (("draft_ready",) if approving else ())
    return all(counts.get(status, 0) == 0 for status in active)


@dataclass
class RunReport:
    events: int = 0
    copied_events: int = 0
    requests: int = 0
    poll_errors: Counter[str] = field(default_factory=Counter)
    approve_errors: Counter[str] = field(default_factory=Counter)
    fatal: str | None = None
    drain_checked: bool = True
    latencies_ms: list[float] = field(default_factory=list)
    responses: Counter[str] = field(default_factory=Counter)
    accepted_per_event: Counter[str] = field(default_factory=Counter)
    approved: int = 0
    drain_seconds: float | None = None
    final_counts: dict[str, int] = field(default_factory=dict)
    deliveries: dict[str, object] = field(default_factory=dict)

    def record(self, event_id: str, outcome: str, latency_ms: float) -> None:
        self.requests += 1
        self.responses[outcome] += 1
        self.latencies_ms.append(latency_ms)
        if outcome == "accepted":
            self.accepted_per_event[event_id] += 1

    @property
    def accepted_twice(self) -> int:
        """Events the backend accepted more than once: an I2 violation."""
        return sum(1 for n in self.accepted_per_event.values() if n > 1)

    @property
    def never_accepted(self) -> int:
        """Events with no `accepted` answer, for example during an outage."""
        return self.events - len(self.accepted_per_event)

    def summary(self) -> dict[str, object]:
        return {
            "events": self.events,
            "copied_events": self.copied_events,
            "webhook_requests": self.requests,
            "latency_ms": {
                "p50": round(percentile(self.latencies_ms, 0.50), 1),
                "p95": round(percentile(self.latencies_ms, 0.95), 1),
                "max": round(max(self.latencies_ms, default=0.0), 1),
            },
            "responses": dict(sorted(self.responses.items())),
            "accepted_twice": self.accepted_twice,
            "never_accepted": self.never_accepted,
            "dedupe_errors": self.accepted_twice + self.never_accepted,
            "approved": self.approved,
            "approve_errors": dict(sorted(self.approve_errors.items())),
            "poll_errors": dict(sorted(self.poll_errors.items())),
            "fatal": self.fatal,
            "drain_checked": self.drain_checked,
            "drain_seconds": (
                None if self.drain_seconds is None else round(self.drain_seconds, 1)
            ),
            "final_counts": {k: v for k, v in self.final_counts.items() if v},
            "mock_deliveries": self.deliveries,
        }


def render(summary: dict[str, object]) -> str:
    latency = summary["latency_ms"]
    lines = [
        f"events sent:        {summary['events']} "
        f"({summary['copied_events']} sent as simultaneous copies, "
        f"{summary['webhook_requests']} webhook requests)",
        f"webhook latency ms: p50 {latency['p50']}, p95 {latency['p95']}, "
        f"max {latency['max']}",
        f"responses:          {summary['responses']}",
        f"dedupe errors:      {summary['dedupe_errors']} "
        f"(accepted twice {summary['accepted_twice']}, "
        f"never accepted {summary['never_accepted']})",
        f"approved by run:    {summary['approved']}",
        f"poll errors:        {summary['poll_errors']}",
        f"approve errors:     {summary['approve_errors']}",
        f"drained after:      {summary['drain_seconds']} s after the last webhook",
        f"final statuses:     {summary['final_counts']}",
        f"mock deliveries:    {summary['mock_deliveries']}",
    ]
    return "\n".join(lines)


def problems(summary: dict[str, object]) -> list[str]:
    """What makes a run fail as a check of I2 and I6."""
    if summary["fatal"]:
        return [summary["fatal"]]
    found = []
    if summary["dedupe_errors"]:
        found.append(f"dedupe errors: {summary['dedupe_errors']}")
    if summary["drain_checked"] and summary["drain_seconds"] is None:
        found.append("the queue did not drain")
    duplicates = summary["mock_deliveries"].get("duplicates")
    if duplicates is None:
        found.append("the mock's delivery counts are missing")
    elif duplicates:
        found.append(f"duplicate deliveries at the mock: {duplicates}")
    return found
