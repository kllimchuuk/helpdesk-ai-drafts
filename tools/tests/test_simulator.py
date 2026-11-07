import json
import time
from collections import Counter

import httpx
import pytest

from simulator.__main__ import emit, parse
from simulator.report import RunReport, is_drained, percentile, problems, render
from simulator.run import Options, copies_for, run


def options(**overrides: object) -> Options:
    values = {
        "base_url": "http://backend",
        "mock_url": "http://mock",
        "reply_host": "mock-helpdesk:8000",
        "events": 20,
        "duration": 0.2,
        "duplicate_rate": 0.25,
        "concurrent_duplicates": 3,
        "approve": True,
        "operator": ("operator", "operator"),
        "drain_timeout": 5.0,
        "seed": 4,
    }
    values.update(overrides)
    return Options(**values)


@pytest.mark.parametrize(
    ("fraction", "expected"), [(0.5, 50.0), (0.95, 95.0), (1.0, 100.0), (0.01, 1.0)]
)
def test_percentile_is_nearest_rank(fraction: float, expected: float) -> None:
    assert percentile([float(n) for n in range(100, 0, -1)], fraction) == expected


def test_percentile_of_nothing_is_zero() -> None:
    assert percentile([], 0.95) == 0.0


def test_drafts_waiting_for_approval_only_block_an_approving_run() -> None:
    counts = {"draft_ready": 2, "sent": 5}

    assert is_drained(counts, approving=False) is True
    assert is_drained(counts, approving=True) is False
    assert is_drained({"sending": 1}, approving=False) is False


def test_duplicated_events_go_out_as_several_simultaneous_copies() -> None:
    chosen = options(duplicate_rate=0.1, concurrent_duplicates=4)

    assert copies_for(0.05, chosen) == 4
    assert copies_for(0.5, chosen) == 1
    assert copies_for(0.05, options(duplicate_rate=0.1, concurrent_duplicates=1)) == 2


def test_dedupe_errors_count_events_accepted_twice_or_never() -> None:
    report = RunReport(events=3)
    report.record("a", "accepted", 1.0)
    report.record("a", "duplicate", 1.0)
    report.record("b", "accepted", 1.0)
    report.record("b", "accepted", 1.0)

    assert report.summary()["dedupe_errors"] == 2


class FakeService:
    """The backend and the mock as the simulator sees them, in memory."""

    def __init__(self) -> None:
        self.tickets: dict[str, dict] = {}
        self.events: set[str] = set()
        self.deliveries: Counter[str] = Counter()

    def backend(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/webhooks/helpdesk":
            event = json.loads(request.content)
            if event["event_id"] in self.events:
                return httpx.Response(200, json={"status": "duplicate"})
            self.events.add(event["event_id"])
            ticket_id = f"id-{len(self.tickets)}"
            self.tickets[ticket_id] = {
                **event,
                "id": ticket_id,
                "status": "draft_ready",
            }
            return httpx.Response(200, json={"status": "accepted"})
        if path == "/api/stats":
            counts = Counter(ticket["status"] for ticket in self.tickets.values())
            return httpx.Response(200, json={"counts": counts, "total": len(counts)})
        if path == "/api/tickets":
            assert request.headers["authorization"].startswith("Basic ")
            items = [t for t in self.tickets.values() if t["status"] == "draft_ready"]
            return httpx.Response(200, json={"items": items})
        if path.endswith("/approve"):
            assert request.headers["x-requested-by"] == "operator-ui"
            ticket = self.tickets[path.split("/")[3]]
            ticket["status"] = "sent"
            self.deliveries[ticket["id"]] += 1
            return httpx.Response(200, json=ticket)
        return httpx.Response(404)

    def mock(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/_debug/reset":
            return httpx.Response(204)
        total = sum(self.deliveries.values())
        return httpx.Response(
            200, json={"total": total, "unique": len(self.deliveries), "duplicates": 0}
        )


async def test_a_run_sends_every_event_approves_and_reports() -> None:
    service = FakeService()

    report = await run(
        options(),
        transport=httpx.MockTransport(service.backend),
        mock_transport=httpx.MockTransport(service.mock),
    )
    summary = report.summary()

    assert summary["events"] == 20
    assert summary["webhook_requests"] > 20
    assert summary["responses"]["accepted"] == 20
    assert summary["dedupe_errors"] == 0
    assert summary["approved"] == 20
    assert summary["drain_seconds"] is not None
    assert summary["final_counts"] == {"sent": 20}
    assert summary["mock_deliveries"]["total"] == 20
    assert all(
        ticket["reply_url"].startswith("http://mock-helpdesk:8000/tickets/SIM-")
        for ticket in service.tickets.values()
    )
    assert "p95" in render(summary)


def test_the_command_line_follows_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPERATOR_PASSWORD", "secret")

    parsed, json_path = parse(
        [
            "--events",
            "500",
            "--duration",
            "600",
            "--duplicate-rate",
            "0.2",
            "--concurrent-duplicates",
            "5",
            "--approve",
            "--json",
            "out.json",
        ]
    )

    assert (parsed.events, parsed.duration) == (500, 600.0)
    assert (parsed.duplicate_rate, parsed.concurrent_duplicates) == (0.2, 5)
    assert parsed.approve is True
    assert parsed.operator == ("operator", "secret")
    assert json_path == "out.json"


async def test_the_run_never_approves_tickets_it_did_not_send() -> None:
    """--approve must not send the owner's real drafts."""
    service = FakeService()
    service.tickets["owner"] = {
        "id": "owner",
        "ticket_id": "T-1042",
        "status": "draft_ready",
    }

    report = await run(
        options(events=3, drain_timeout=1.0),
        transport=httpx.MockTransport(service.backend),
        mock_transport=httpx.MockTransport(service.mock),
    )

    assert service.tickets["owner"]["status"] == "draft_ready"
    assert report.approved == 3


async def test_transient_backend_errors_do_not_lose_the_report() -> None:
    service = FakeService()
    failures = {"/api/tickets": 1, "/api/stats": 2}

    def flaky(request: httpx.Request) -> httpx.Response:
        left = failures.get(request.url.path, 0)
        if left:
            failures[request.url.path] = left - 1
            if left == 2:
                return httpx.Response(503, json={"code": "database_unavailable"})
            raise httpx.ConnectError("backend restarting")
        return service.backend(request)

    report = await run(
        options(events=5),
        transport=httpx.MockTransport(flaky),
        mock_transport=httpx.MockTransport(service.mock),
    )
    summary = report.summary()

    assert summary["poll_errors"] == {"ConnectError": 2, "http_503": 1}
    assert summary["drain_seconds"] is not None
    assert summary["final_counts"] == {"sent": 5}


def test_the_report_counts_copied_events_and_splits_dedupe_errors() -> None:
    report = RunReport(events=3, copied_events=1)
    report.record("a", "accepted", 1.0)
    report.record("a", "accepted", 1.0)
    report.record("b", "accepted", 1.0)

    summary = report.summary()

    assert summary["copied_events"] == 1
    assert summary["accepted_twice"] == 1
    assert summary["never_accepted"] == 1
    assert summary["dedupe_errors"] == 2


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, []),
        ({"dedupe_errors": 1}, ["dedupe errors: 1"]),
        ({"drain_seconds": None}, ["the queue did not drain"]),
        ({"drain_seconds": None, "drain_checked": False}, []),
        (
            {"mock_deliveries": {"duplicates": 2}},
            ["duplicate deliveries at the mock: 2"],
        ),
        ({"mock_deliveries": {}}, ["the mock's delivery counts are missing"]),
        ({"fatal": "operator API answered 401"}, ["operator API answered 401"]),
    ],
)
def test_problems_decide_the_exit_status(changes: dict, expected: list[str]) -> None:
    summary = {
        "dedupe_errors": 0,
        "drain_seconds": 3.0,
        "drain_checked": True,
        "mock_deliveries": {"duplicates": 0},
        "fatal": None,
        **changes,
    }

    assert problems(summary) == expected


def test_json_on_stdout_stays_parseable(capsys: pytest.CaptureFixture[str]) -> None:
    emit(RunReport(events=1).summary(), "-")

    captured = capsys.readouterr()
    assert json.loads(captured.out)["events"] == 1
    assert "p95" in captured.err


async def test_rejected_operator_credentials_stop_the_run_at_once() -> None:
    """No more webhooks, and so no more provider calls, once approving is hopeless."""
    service = FakeService()

    def refuse_operator(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/api/tickets"):
            return httpx.Response(401, json={"code": "operator_auth_required"})
        return service.backend(request)

    started = time.monotonic()
    report = await run(
        options(events=50, duration=10.0, drain_timeout=30.0),
        transport=httpx.MockTransport(refuse_operator),
        mock_transport=httpx.MockTransport(service.mock),
    )
    elapsed = time.monotonic() - started
    summary = report.summary()

    assert summary["fatal"] == "operator API answered 401"
    assert problems(summary) == ["operator API answered 401"]
    assert elapsed < 2.0
    assert summary["events"] < 5


async def test_a_failed_mock_reset_stops_the_run_before_sending() -> None:
    service = FakeService()

    report = await run(
        options(events=5),
        transport=httpx.MockTransport(service.backend),
        mock_transport=httpx.MockTransport(lambda request: httpx.Response(500)),
    )

    assert problems(report.summary()) == ["mock reset failed: http_500"]
    assert service.events == set()


async def test_unexpected_approve_answers_are_counted() -> None:
    service = FakeService()

    def refuse_approve(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/approve"):
            return httpx.Response(500)
        return service.backend(request)

    report = await run(
        options(events=2, drain_timeout=1.5),
        transport=httpx.MockTransport(refuse_approve),
        mock_transport=httpx.MockTransport(service.mock),
    )

    assert report.summary()["approve_errors"]["http_500"] >= 2
    assert report.approved == 0


async def test_a_run_without_a_drain_wait_only_sends() -> None:
    service = FakeService()

    report = await run(
        options(events=2, approve=False, drain_timeout=0.0),
        transport=httpx.MockTransport(service.backend),
        mock_transport=httpx.MockTransport(service.mock),
    )

    assert problems(report.summary()) == []
