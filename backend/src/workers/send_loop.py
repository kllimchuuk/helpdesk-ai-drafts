import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from delivery.helpdesk_client import HelpdeskClient
from delivery.schemas import SendOutcome, SendResult
from tickets.repository import TicketRepository
from tickets.schemas import ClaimedSend
from workers.backoff import backoff_seconds
from workers.queue_loop import QueueLoop, log

NO_DRAFT = "no_draft: the approved ticket has no reply text"
INTERNAL_ERROR = "internal_error: unexpected error while sending"
SENDS_EXHAUSTED = "lease_expired: the worker stopped during every send attempt"


@dataclass(frozen=True)
class SendPolicy:
    concurrency: int = 10
    lease_seconds: float = 120.0
    poll_seconds: float = 1.0
    max_attempts: int = 8
    backoff_base_seconds: float = 5.0
    backoff_cap_seconds: float = 300.0
    retry_ambiguous: bool = False


class SendLoop(QueueLoop[ClaimedSend]):
    name = "Send"

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        helpdesk: HelpdeskClient,
        policy: SendPolicy,
    ) -> None:
        super().__init__(
            session_factory,
            concurrency=policy.concurrency,
            poll_seconds=policy.poll_seconds,
        )
        self._helpdesk = helpdesk
        self._policy = policy

    async def _claim_batch(
        self, tickets: TicketRepository, limit: int
    ) -> list[ClaimedSend]:
        await tickets.expire_stale_sends(retry_ambiguous=self._policy.retry_ambiguous)
        return await tickets.claim_for_sending(limit, self._policy.lease_seconds)

    async def _process(self, ticket: ClaimedSend) -> None:
        if ticket.attempt > self._policy.max_attempts:
            # Only reachable through expired leases (a send that keeps killing its
            # worker); the last of those attempts may have arrived.
            await self._settle(ticket, SendOutcome(SendResult.UNKNOWN, SENDS_EXHAUSTED))
            return
        if not ticket.reply:
            await self._settle(ticket, SendOutcome(SendResult.FAILED, NO_DRAFT))
            return
        try:
            outcome = await self._helpdesk.send_reply(
                ticket.reply_url,
                ticket_id=ticket.ticket_id,
                message=ticket.reply,
                idempotency_key=str(ticket.id),
            )
        except Exception:
            # Whatever broke may have done so after the request left: ambiguous.
            log(logging.ERROR, "Sending failed unexpectedly", ticket, exc_info=True)
            outcome = SendOutcome(SendResult.UNKNOWN, INTERNAL_ERROR)
        await self._settle(ticket, outcome)

    async def _settle(self, ticket: ClaimedSend, outcome: SendOutcome) -> None:
        result = outcome.result
        exhausted = ticket.attempt >= self._policy.max_attempts
        if result == SendResult.UNKNOWN and self._policy.retry_ambiguous:
            # Out of attempts it stays unknown: send_failed would tell the operator
            # that a reply which may have arrived certainly did not.
            result = SendResult.UNKNOWN if exhausted else SendResult.RETRY
        if result == SendResult.RETRY and exhausted:
            result = SendResult.FAILED
        if result == SendResult.DELIVERED:
            await self._write(ticket, "sent", lambda t: t.mark_sent(ticket))
        elif result == SendResult.RETRY:
            delay = backoff_seconds(
                ticket.attempt,
                base=self._policy.backoff_base_seconds,
                cap=self._policy.backoff_cap_seconds,
            )
            await self._write(
                ticket,
                "retry",
                lambda t: t.retry_send(
                    ticket, delay_seconds=delay, error=outcome.detail
                ),
            )
        elif result == SendResult.FAILED:
            await self._write(
                ticket,
                "send_failed",
                lambda t: t.fail_send(ticket, error=outcome.detail),
            )
        else:
            await self._write(
                ticket,
                "send_unknown",
                lambda t: t.park_unknown(ticket, error=outcome.detail),
            )
