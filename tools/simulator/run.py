import asyncio
import random
import time
import uuid
from dataclasses import dataclass

import httpx

from simulator.report import RunReport, is_drained

MESSAGES = (
    "Не можу експортувати звіт у PDF",
    "Забув пароль, як відновити доступ до акаунта?",
    "Скажіть, як змінити тариф і де знайти рахунок за минулий місяць",
    "Хочу додати нового колегу в команду і дати йому права редактора",
    "Отримую помилку 429 при запитах до вашого API",
    "Як зробити, щоб звіт щотижня автоматично приходив мені на пошту?",
    "Після експорту в CSV українські літери відображаються нерозбірливо",
    "Мені не приходить код двофакторної автентифікації, не можу увійти",
    "Яка завтра погода у Львові на вихідних?",
)
OPERATOR_HEADERS = {"X-Requested-By": "operator-ui", "Content-Type": "application/json"}
POLL_SECONDS = 1.0
POLL_ERRORS = (httpx.HTTPError, ValueError, KeyError)
# Wrong operator credentials or a missing CSRF header never fix themselves.
FATAL_STATUSES = (401, 403)


class FatalRunError(Exception):
    pass


def error_kind(error: Exception) -> str:
    if isinstance(error, httpx.HTTPStatusError):
        return f"http_{error.response.status_code}"
    return type(error).__name__


@dataclass(frozen=True)
class Options:
    base_url: str
    mock_url: str
    reply_host: str
    events: int
    duration: float
    duplicate_rate: float
    concurrent_duplicates: int
    approve: bool
    operator: tuple[str, str]
    drain_timeout: float
    seed: int | None = None


def build_event(run_id: str, index: int, options: Options, pick) -> dict[str, str]:
    ticket_id = f"SIM-{run_id}-{index}"
    return {
        "event_id": f"evt_{run_id}_{index}",
        "ticket_id": ticket_id,
        "customer_email": f"customer{index}@example.com",
        "message": pick(MESSAGES),
        "reply_url": f"http://{options.reply_host}/tickets/{ticket_id}/replies",
    }


def copies_for(draw: float, options: Options) -> int:
    if draw < options.duplicate_rate:
        return max(2, options.concurrent_duplicates)
    return 1


async def send_webhook(
    http: httpx.AsyncClient, event: dict[str, str], report: RunReport
) -> None:
    started = time.perf_counter()
    try:
        response = await http.post("/webhooks/helpdesk", json=event)
        outcome = (
            response.json().get("status", f"http_{response.status_code}")
            if response.status_code == 200
            else f"http_{response.status_code}"
        )
    except (httpx.HTTPError, ValueError) as error:
        outcome = type(error).__name__
    report.record(event["event_id"], outcome, (time.perf_counter() - started) * 1000)


async def send_events(
    http: httpx.AsyncClient, options: Options, report: RunReport, run_id: str
) -> None:
    rng = random.Random(options.seed)
    interval = options.duration / max(options.events, 1)
    started = time.monotonic()
    pending: set[asyncio.Task[None]] = set()
    for index in range(options.events):
        delay = started + index * interval - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)
        event = build_event(run_id, index, options, rng.choice)
        copies = copies_for(rng.random(), options)
        if copies > 1:
            report.copied_events += 1
        for _ in range(copies):
            task = asyncio.create_task(send_webhook(http, event, report))
            pending.add(task)
            task.add_done_callback(pending.discard)
        report.events += 1
    await asyncio.gather(*pending)


async def approve_drafts(
    http: httpx.AsyncClient,
    options: Options,
    report: RunReport,
    run_id: str,
    stop: asyncio.Event,
) -> None:
    prefix = f"SIM-{run_id}-"
    while not stop.is_set():
        try:
            await approve_once(http, options, report, prefix)
        except FatalRunError as error:
            report.fatal = str(error)
            return
        except POLL_ERRORS as error:
            # A restarting or overloaded backend must not end the run.
            report.poll_errors[error_kind(error)] += 1
        try:
            await asyncio.wait_for(stop.wait(), timeout=POLL_SECONDS)
        except TimeoutError:
            pass


async def approve_once(
    http: httpx.AsyncClient, options: Options, report: RunReport, prefix: str
) -> None:
    response = await http.get(
        "/api/tickets",
        params={"status": "draft_ready", "limit": 1000},
        auth=options.operator,
    )
    if response.status_code in FATAL_STATUSES:
        raise FatalRunError(f"operator API answered {response.status_code}")
    response.raise_for_status()
    for ticket in response.json()["items"]:
        # Only this run's tickets: the database may hold the owner's real drafts.
        if not ticket["ticket_id"].startswith(prefix):
            continue
        approved = await http.post(
            f"/api/tickets/{ticket['id']}/approve",
            content="{}",
            headers=OPERATOR_HEADERS,
            auth=options.operator,
        )
        if approved.status_code in FATAL_STATUSES:
            raise FatalRunError(f"operator API answered {approved.status_code}")
        if approved.status_code == 200:
            report.approved += 1
        elif approved.status_code != 409:
            report.approve_errors[f"http_{approved.status_code}"] += 1


async def wait_for_drain(
    http: httpx.AsyncClient, options: Options, report: RunReport
) -> None:
    report.drain_checked = options.drain_timeout > 0
    started = time.monotonic()
    while time.monotonic() - started < options.drain_timeout:
        if report.fatal:
            return
        try:
            response = await http.get("/api/stats")
            response.raise_for_status()
            counts = response.json()["counts"]
        except POLL_ERRORS as error:
            report.poll_errors[error_kind(error)] += 1
        else:
            report.final_counts = counts
            if is_drained(counts, options.approve):
                report.drain_seconds = time.monotonic() - started
                return
        await asyncio.sleep(POLL_SECONDS)


async def run(
    options: Options,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    mock_transport: httpx.AsyncBaseTransport | None = None,
) -> RunReport:
    report = RunReport()
    run_id = uuid.uuid4().hex[:8]
    timeout = httpx.Timeout(10.0)
    async with (
        httpx.AsyncClient(
            base_url=options.base_url, timeout=timeout, transport=transport
        ) as http,
        httpx.AsyncClient(
            base_url=options.mock_url, timeout=timeout, transport=mock_transport
        ) as mock,
    ):
        try:
            (await mock.post("/_debug/reset")).raise_for_status()
        except httpx.HTTPError as error:
            report.fatal = f"mock reset failed: {error_kind(error)}"
            return report
        stop = asyncio.Event()
        approver = (
            asyncio.create_task(approve_drafts(http, options, report, run_id, stop))
            if options.approve
            else None
        )
        await send_events(http, options, report, run_id)
        await wait_for_drain(http, options, report)
        stop.set()
        if approver is not None:
            await approver
        try:
            response = await mock.get("/_debug/deliveries")
            response.raise_for_status()
            report.deliveries = response.json()
        except (httpx.HTTPError, ValueError) as error:
            report.poll_errors[f"mock_{error_kind(error)}"] += 1
    return report
