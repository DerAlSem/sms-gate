import asyncio
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

from app.config import settings
from app.settings_store import store
from app.modem import at_commands
from app.modem.at_commands import ATSerial, ATCommandError, ModemFailure, ModemTransportError
from app.modem.delivery_dispatch import spawn_delivery_dispatch
from app.modem.dispatch import dispatch_inbound
from app.modem.errors import is_retryable
from app.modem.health import ModemHealth, COOLDOWN, HARD, OK, SOFT, STALL, TRANSPORT, WAIT
from app.modem.parser import parse_cds, parse_cmti, parse_cmgr_pdu, parse_cmgl_pdu, describe_tp_status
from app.modem.pdu import decode_deliver, inbound_pdu_key
from app.modem.pdu_encode import encode_submit
from app.modem import assembler
from app.modem.diag import (
    decode_cpin, decode_reg, decode_csq, decode_cops,
    decode_csca, decode_qnwinfo, decode_qcsq,
)
from app.db import queries
from app.alerting import notify

logger = logging.getLogger(__name__)


def _is_permanent_status(code: int) -> bool:
    """GSM 03.40 TP-Status: 0x40–0x5F = permanent error (SC stops trying)."""
    return 0x40 <= code <= 0x5F


_WD_INTERVAL = 60
_WD_FAIL_THRESHOLD = 3
_WD_HARD_RESET_COOLDOWN = 1800
_WD_HARD_RESET_SETTLE = 40

# Ceiling on one recovery. It is not just the AT commands: recovery must first take the
# serial port, which a six-part send can hold for `max_sms_parts` x (prompt + response +
# drain) — minutes. Without a stated ceiling the gate-closed window is unbounded and the
# sender's backstop below would be a number picked against nothing.
_RECOVERY_TIMEOUT = 300.0
# `AT+COPS=0` acknowledges a request to reselect, not a completed attach. Sending during
# the reattach produces precisely the failures recovery exists to stop.
_RECOVERY_SETTLE = 30.0
_RECOVERY_POLL = 2.0
# How long to wait before re-checking a message held back because the modem is off the
# network. The outages seen in production last a minute or two, so re-checking on the
# shortest configured backoff step is the natural granularity.
_HOLD_RETRY_FALLBACK = 30
# Backstop for a gate that never reopens. Derived from the ceiling above rather than
# guessed, and necessarily longer than _WD_HARD_RESET_SETTLE, since the hard path keeps
# sending suspended until the process exits. Not a scheduling knob — an escape hatch.
_SEND_GATE_TIMEOUT = _RECOVERY_TIMEOUT + _RECOVERY_SETTLE + 60.0

# How long a deduplication key is kept. It guards against re-reading a copy still in
# modem memory, and that copy is deleted by the first scan that recognises the key — so a
# week outlives what it guards by a wide margin, while keeping the table from growing
# without end.
_INBOUND_SEEN_RETENTION = 7 * 24 * 3600

# Per attempt, on top of its scheduled delay: the failing exchange itself (a prompt
# timeout plus the drain, or a full response timeout) and one retry-scheduler tick.
_ATTEMPT_ALLOWANCE = 60
# One episode of waiting for the serial port behind a long multipart send, which holds
# it for `max_sms_parts` x (prompt + response + drain).
_PORT_CONTENTION_ALLOWANCE = 240


def _hard_reset_marker() -> Path:
    return Path(settings.db_path).parent / "modem_hard_reset_at"


def _hard_reset_on_cooldown() -> bool:
    p = _hard_reset_marker()
    if not p.exists():
        return False
    try:
        return (time.time() - float(p.read_text().strip())) < _WD_HARD_RESET_COOLDOWN
    except (ValueError, OSError):
        return False


def _mark_hard_reset() -> None:
    try:
        _hard_reset_marker().write_text(str(time.time()))
    except OSError:
        pass


_DIAG_QUERIES = [
    ("sim",        "AT+CPIN?",   decode_cpin),
    ("eps_reg",    "AT+CEREG?",  decode_reg),
    ("cs_reg",     "AT+CREG?",   decode_reg),
    ("ps_reg",     "AT+CGREG?",  decode_reg),
    ("signal",     "AT+CSQ",     decode_csq),
    ("operator",   "AT+COPS?",   decode_cops),
    ("smsc",       "AT+CSCA?",   decode_csca),
    ("net_info",   "AT+QNWINFO", decode_qnwinfo),
    ("signal_lte", "AT+QCSQ",    decode_qcsq),
]


@dataclass
class OutgoingMessage:
    message_id: int
    phone: str
    text: str
    app_id: str = ""


class ModemManager:
    def __init__(self, send_port: str, read_port: str, baudrate: int = 115200) -> None:
        self._sender = ATSerial(send_port, baudrate)
        # The port carrying unsolicited results, given the same transport as the command
        # port rather than being opened by hand inside `reader_loop`. It gets the shared
        # failure classification, the shared usable/unusable state and the shared reopen
        # for free — which is the point: two bounded reconnectors, each able to end the
        # process, is the worse failure.
        self._reader_link = ATSerial(read_port, baudrate)
        self._read_port = read_port
        self._baudrate = baudrate
        self._queue: asyncio.Queue[OutgoingMessage] = asyncio.Queue()
        self._inbound_indices: asyncio.Queue[int] = asyncio.Queue()
        self._bg_tasks: set[asyncio.Task] = set()
        # Ids the sender holds queued or in flight. The scheduler skips them, so a
        # message cannot be enqueued twice and sent twice.
        self._held: set[int] = set()
        # Modem belief and the recovery ladder live together in one object: they are one
        # invariant, and spreading them across this class is what let a stall inherit a
        # recovery performed for a different problem.
        self._health = ModemHealth(_WD_FAIL_THRESHOLD, _WD_FAIL_THRESHOLD)

    # Thin views onto the health object, kept because this class reads them in several
    # places and because they are what the tests observe.
    @property
    def _modem_gate(self) -> asyncio.Event:
        return self._health.gate

    @property
    def _wd_fails(self) -> int:
        return self._health.fails

    @_wd_fails.setter
    def _wd_fails(self, value: int) -> None:
        self._health.fails = value

    @property
    def _wd_soft_tried(self) -> bool:
        return self._health.soft_tried

    @_wd_soft_tried.setter
    def _wd_soft_tried(self, value: bool) -> None:
        self._health.soft_tried = value

    @property
    def _stalled_ids(self) -> set[int]:
        return self._health.failed_ids

    def _note_send_failure(self, message_id: int, error: str, *, exhausted: bool) -> None:
        self._health.note_send_failure(message_id, error, exhausted=exhausted)

    def _note_send_success(self) -> None:
        self._health.note_send_success()

    def _clear_stall(self) -> None:
        self._health.clear_stall()

    @property
    def _stalled(self) -> bool:
        return self._health.stalled(enabled=store.send_stall_recovery_enabled)

    async def _await_modem_gate(self, what: str = "sending") -> None:
        if self._modem_gate.is_set():
            return
        # Not `capitalize()`: it lowercases the rest, which turns "reading URCs" into
        # "reading urcs" in the one log line an operator reads during an outage.
        logger.info(
            "%s suspended while the modem is recovered", what[0].upper() + what[1:]
        )
        try:
            await asyncio.wait_for(self._modem_gate.wait(), timeout=_SEND_GATE_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning(
                "Recovery gate still closed after %.0fs — resuming %s anyway",
                _SEND_GATE_TIMEOUT, what,
            )

    async def _await_reattach(self) -> None:
        """Hold on after recovery until the modem is actually back on the network."""
        loop = asyncio.get_event_loop()
        deadline = loop.time() + _RECOVERY_SETTLE
        while loop.time() < deadline:
            # A remedy that could not put the port back has nothing to reattach. Polling
            # a link known to be gone spends the settle period proving it again, and the
            # ladder's next rung — the restart — is waiting on the other side of it.
            if not self._sender.usable:
                return
            try:
                if await self._sender.registration_ok():
                    return
            except Exception:
                pass
            await asyncio.sleep(_RECOVERY_POLL)
        logger.warning(
            "Modem had not re-registered %.0fs after recovery — resuming anyway",
            _RECOVERY_SETTLE,
        )

    async def _recover(self, action, *, reopen: bool = True) -> None:
        """Run a recovery operation with sending suspended.

        Clearing the evidence is part of recovering, not tidiness: a stall only lifts on
        a successful send, and on a quiet gateway there may be nothing to send for an
        hour — the stall would survive untouched and drive the ladder to a service
        restart on evidence already acted upon. Escalating further has to be earned by
        messages failing again.
        """
        self._modem_gate.clear()
        try:
            try:
                await asyncio.wait_for(action(), timeout=_RECOVERY_TIMEOUT)
            except asyncio.TimeoutError:
                logger.error("Recovery did not finish within %.0fs", _RECOVERY_TIMEOUT)
            except Exception:
                # A remedy the gateway could not carry out counts as attempted. Every
                # rung here is an AT command, so a fault that stops AT commands reaching
                # the modem stops every rung — and if that escapes, the step never
                # returns the level that ends the process. Escalation must not depend on
                # the modem cooperating with its own recovery.
                logger.exception("Recovery could not be carried out — counting it as attempted")
            if reopen:
                await self._await_reattach()
        finally:
            self._clear_stall()
            if reopen:
                self._modem_gate.set()

    async def _reopen_link(self) -> None:
        """Put the link back in place, instead of restarting the service to get it back.

        Runs as a recovery action, so sending and inbound reading are already suspended on
        the gate and the whole thing is bounded by `_RECOVERY_TIMEOUT`. It reports failure
        by leaving the link unusable rather than by raising: the ladder reads the link's
        own state on the next tick, and an exhausted reopen is an ordinary outcome with a
        remedy waiting, not an error to log a traceback for.
        """
        if not self._sender.usable and not await self._sender.reconnect():
            logger.error("Could not reopen the link — the service will be restarted")
            return
        if not self._reader_link.usable:
            # Second, and without an init sequence of its own — the design's open question,
            # settled here. It has no writer, so it cannot issue commands at all; the URC
            # subscription that matters is applied through the command port above and
            # takes effect for both. Reopening it after that ordering is deliberate: the
            # subscription is back in place before this port starts listening for what it
            # produces.
            if not await self._reader_link.reconnect(init=False):
                logger.error(
                    "Could not reopen %s — the service will be restarted", self._read_port
                )
                return
        # The reconciliation the restart used to provide for free, and the reason this
        # change could otherwise make inbound delivery *worse* than the restart it
        # replaces: SMS accumulate in modem memory while the link is down, and the +CMTI
        # announcing them go with the link. Without this they would sit unread until some
        # later restart.
        self._drop_queued_inbound_indices()
        await self.scan_inbox()

    def _drop_queued_inbound_indices(self) -> None:
        """Discard indexes announced before the outage; the scan supersedes them.

        They cannot stand in for the scan — they describe what was announced before the
        link died, not what arrived while nothing was listening — and reading them
        afterwards means reading slots the scan has just emptied and the modem is free to
        refill.
        """
        dropped = 0
        while True:
            try:
                self._inbound_indices.get_nowait()
            except asyncio.QueueEmpty:
                break
            self._inbound_indices.task_done()
            dropped += 1
        if dropped:
            logger.info(
                "Dropped %d inbound index(es) superseded by the inbox scan", dropped
            )

    async def connect(self) -> None:
        # Waits for the device rather than failing outright: a restart provoked by a lost
        # link lands while the modem is still re-enumerating, and treating that as fatal
        # would turn the remedy into an indefinite outage.
        await self._sender.connect(wait_for_device=at_commands._DEVICE_WAIT)
        await self._sender.init()

    async def disconnect(self) -> None:
        await self._sender.close()
        await self._reader_link.close()

    async def enqueue(self, message_id: int, phone: str, text: str, app_id: str = "") -> None:
        # Held before the message is queued, never after: the scheduler skips held ids,
        # and a gap here would let it claim a message the sender is about to send.
        self._held.add(message_id)
        await self._queue.put(OutgoingMessage(message_id, phone, text, app_id))

    def _retry_deadline(self) -> int:
        """How long a message may stay `pending` before the gateway gives up on it.

        Derived from the backoff so the budget and the deadline cannot disagree — but the
        margin has to cover more than "a slow final attempt", which is what the first
        version assumed and got wrong. Between two scheduled attempts the clock also
        absorbs the failing attempt itself (a prompt timeout plus the drain, or a full
        response timeout), one scheduler tick of granularity, and possibly a wait for the
        serial port behind a six-part send that can hold it for minutes.

        With the old `sum(backoff) + 120` the last attempt fell outside the deadline
        whenever attempts ran slowly: the message was swept as `never transmitted`
        having used three of its four attempts, so the ladder was quietly one short of
        what the spec promises.
        """
        backoff = store.send_retry_backoff_parsed
        return (
            sum(backoff)
            + (len(backoff) + 1) * _ATTEMPT_ALLOWANCE
            + _PORT_CONTENTION_ALLOWANCE
        )

    async def sender_loop(self) -> None:
        """Pick messages from queue and send via modem."""
        logger.info("Sender loop started")
        while True:
            msg = await self._queue.get()
            try:
                await self._send_one(msg)
            except Exception:
                # Anything that is not an AT failure — an encoder bug, a SQLite error,
                # a raise inside the part callback. Before this the exception escaped
                # `while True` and killed the sender permanently, in silence.
                logger.exception(
                    "Unhandled error sending message %d (app=%s to=%s)",
                    msg.message_id, msg.app_id or "?", msg.phone,
                )
                await self._finally_fail(msg, "internal error while sending", attempt=0)
            finally:
                # In `finally` so a held id is released down every path; a leaked one
                # would make the message invisible to the scheduler forever.
                self._held.discard(msg.message_id)
                self._queue.task_done()

    async def _send_one(self, msg: OutgoingMessage) -> None:
        parts = encode_submit(msg.phone, msg.text, ref=msg.message_id % 256)
        if len(parts) > store.max_sms_parts:
            error = f"message too long: {len(parts)} parts > max {store.max_sms_parts}"
            logger.warning(
                "Rejected message %d (app=%s to=%s): %s",
                msg.message_id, msg.app_id or "?", msg.phone, error,
            )
            await self._finally_fail(msg, error, attempt=0, dedup="too_long")
            return

        # Before claiming, so a message held back by recovery consumes no attempt: a
        # recovery window costs a message time, never chances.
        await self._await_modem_gate()

        if await self._hold_while_unregistered(msg):
            return

        total = len(parts)
        # Counted before any byte goes out, so an attempt cut short by a crash leaves
        # the message unscheduled rather than looking untouched.
        attempt = await queries.begin_message_attempt(msg.message_id)
        reached_sent = False

        async def on_part_sent(seq: int, ref: int) -> None:
            nonlocal reached_sent
            await queries.add_message_part(msg.message_id, ref, seq, total)
            if seq == 1:
                reached_sent = True
                await queries.set_message_sent(msg.message_id, ref)
                spawn_delivery_dispatch(msg.message_id, "sent")

        try:
            await self._sender.send_sms_pdu(parts, on_part_sent)
        except ModemTransportError as e:
            # The link went while this message was in hand. Holding is allowed only when
            # nothing of it reached the modem — no byte written *and* no part accepted.
            # A multipart whose first part was accepted must not be held: the retry would
            # transmit that part a second time under the same concatenation reference.
            if not e.pdu_submitted and not reached_sent:
                await self._hold_after_claim(msg, e)
                return
            await self._handle_send_failure(msg, e, attempt, reached_sent)
            return
        except ATCommandError as e:
            await self._handle_send_failure(msg, e, attempt, reached_sent)
            return
        self._note_send_success()
        logger.info(
            "Sent message %d in %d part(s) on attempt %d", msg.message_id, total, attempt
        )

    async def _hold_while_unregistered(self, msg: OutgoingMessage) -> bool:
        """Decline to transmit while the modem is definitively off the network.

        Asked fresh rather than taken from the watchdog's once-a-minute sample: refusing
        to send must not rest on minute-old information. The message keeps its whole
        budget, because it was never offered to the network — and the pending deadline
        still terminates it, so declining cannot become indefinite retention.
        """
        try:
            if await self._sender.registration_state() is not False:
                return False    # registered, or we could not tell — try it
            reason = "held: modem not registered"
        except ModemTransportError:
            # Not "could not tell". That reading exists because a gateway which stops
            # sending whenever it cannot ask a question is worse than one that tries and
            # reports a real failure — but here there is nothing to ask: the port is not
            # there, and writing into it cannot succeed. Asked *before* the attempt is
            # claimed, so the message keeps its whole budget.
            reason = "held: link to the modem is gone"

        backoff = store.send_retry_backoff_parsed
        delay = backoff[0] if backoff else _HOLD_RETRY_FALLBACK
        await queries.schedule_message_retry(msg.message_id, delay, reason)
        logger.info(
            "Holding message %d (app=%s to=%s): %s — retrying in %ds",
            msg.message_id, msg.app_id or "?", msg.phone, reason, delay,
        )
        return True

    async def _hold_after_claim(self, msg: OutgoingMessage, error: ModemFailure) -> None:
        """Decline a message whose attempt was already claimed, giving the claim back.

        The link can go after `begin_message_attempt` and before any byte is written —
        the mode switch that opens a send is itself a command. Without giving the claim
        back the message would carry a spent attempt *and* no schedule, which makes it
        invisible to the scheduler until its deadline: declined and then stranded, which
        is worse than either.
        """
        backoff = store.send_retry_backoff_parsed
        delay = backoff[0] if backoff else _HOLD_RETRY_FALLBACK
        reason = f"held: {error}"
        await queries.hold_message_after_attempt(msg.message_id, delay, reason)
        logger.info(
            "Holding message %d (app=%s to=%s): %s — retrying in %ds, attempt returned",
            msg.message_id, msg.app_id or "?", msg.phone, error, delay,
        )

    async def _handle_send_failure(
        self, msg: OutgoingMessage, error: ModemFailure, attempt: int, reached_sent: bool
    ) -> None:
        text = str(error)
        backoff = store.send_retry_backoff_parsed
        exhausted = attempt > len(backoff)
        self._note_send_failure(msg.message_id, text, exhausted=exhausted)
        retryable = is_retryable(
            text,
            pdu_submitted=getattr(error, "pdu_submitted", False),
            already_sent=reached_sent,
        )
        if retryable and attempt <= len(backoff):
            delay = backoff[attempt - 1]
            await queries.schedule_message_retry(msg.message_id, delay, text)
            logger.warning(
                "Attempt %d for message %d (app=%s to=%s) failed: %s — retrying in %ds",
                attempt, msg.message_id, msg.app_id or "?", msg.phone, text, delay,
            )
            # One alert per window regardless of message: the operator wants to know the
            # gateway is struggling, not to receive one message per deferral.
            notify("send_error",
                   f"{msg.phone} (id {msg.message_id}): attempt {attempt} failed, "
                   f"retrying in {delay}s — {text}",
                   dedup_extra="retrying", phone=msg.phone)
            return

        logger.warning(
            "Failed to send message %d (app=%s to=%s text=%r) after %d attempt(s): %s",
            msg.message_id, msg.app_id or "?", msg.phone, msg.text, attempt, text,
        )
        await self._finally_fail(msg, text, attempt)

    async def _finally_fail(
        self, msg: OutgoingMessage, error: str, attempt: int, dedup: str | None = None
    ) -> None:
        """The one place a send path writes `failed` — and therefore the one place the
        owning app is told the gateway has stopped trying."""
        await queries.set_message_failed(msg.message_id, error)
        spawn_delivery_dispatch(msg.message_id, "failed", error)
        suffix = f" (after {attempt} attempts)" if attempt > 1 else ""
        notify("send_error",
               f"{msg.phone} (id {msg.message_id}): {error}{suffix}",
               dedup_extra=dedup or error, phone=msg.phone)

    async def retry_loop(self, interval_seconds: int = 15) -> None:
        """Re-queue messages whose next attempt is due, and give up on the too-old."""
        logger.info("Retry loop started")
        while True:
            await asyncio.sleep(interval_seconds)
            try:
                await self._retry_step()
            except Exception:
                # A failing tick must not stop the scheduler: it is the only thing that
                # moves a retrying message, and its death would be silent.
                logger.exception("Retry step failed")

    async def _retry_step(self) -> None:
        deadline = self._retry_deadline()

        for row in await queries.stale_pending_messages(deadline):
            if row["id"] in self._held:
                continue                      # still being transmitted
            error = row["last_attempt_error"] or "never transmitted"
            await queries.set_message_failed(row["id"], error)
            spawn_delivery_dispatch(row["id"], "failed", error)
            logger.warning(
                "Gave up on message %d after %ds pending: %s", row["id"], deadline, error
            )

        for row in await queries.due_pending_messages(deadline):
            if row["id"] in self._held:
                continue
            # The number may have been blacklisted since acceptance — by a delivery
            # report on a different message, for instance. Both other enqueue paths
            # check; a retry must not be the way around it.
            if await queries.is_phone_blocked(row["phone"]):
                error = "number blacklisted while pending"
                await queries.set_message_failed(row["id"], error)
                spawn_delivery_dispatch(row["id"], "failed", error)
                continue
            logger.info(
                "Re-queueing message %d for attempt %d", row["id"], row["attempts"] + 1
            )
            await self.enqueue(row["id"], row["phone"], row["text"], row["app_id"])

    async def reader_loop(self) -> None:
        """Listen on read port for +CDS delivery reports."""
        logger.info("Reader loop started on %s", self._read_port)
        await self._reader_link.connect(wait_for_device=at_commands._DEVICE_WAIT)
        buf = b''
        while True:
            try:
                chunk = await self._reader_link.read_urc(timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except ModemTransportError as e:
                # It no longer raises out of the loop to end the service. Ending it is the
                # last remedy, not the first — and it deliberately does not reconnect on
                # its own either: a second bounded reconnector could race the settling
                # period after a deliberate modem reset, a window that exists precisely so
                # nothing touches a rebooting modem, and could decide to end the service
                # in parallel with the watchdog. Reporting the link gone is enough; the
                # one coordinated recovery either puts this port back or ends the process.
                logger.error("Reader link lost: %s", e)
                buf = b''      # a half-line from before the outage is not a URC
                await self._await_link_restored()
                continue
            buf += chunk

            while b'\n' in buf:
                line, buf = buf.split(b'\n', 1)
                decoded = line.decode(errors='replace').strip()
                if not decoded:
                    continue
                logger.debug("Serial read: %r", decoded)

                if decoded.startswith('+CDS:'):
                    report = parse_cds(decoded)
                    if report:
                        await self._handle_cds(report)
                elif decoded.startswith('+CMTI:'):
                    index = parse_cmti(decoded)
                    if index is not None:
                        logger.info("+CMTI: index=%d enqueued", index)
                        await self._inbound_indices.put(index)

    async def _await_link_restored(self) -> None:
        """Wait for the one coordinated recovery to put this port back.

        Nothing is reopened here. Waiting on the recovery gate is what keeps this port
        away from a modem that is deliberately being reset: the hard rung leaves the gate
        closed on purpose and the process exits during the settle, so this simply never
        gets a turn.
        """
        while not self._reader_link.usable:
            await self._await_modem_gate("reading URCs")
            if self._reader_link.usable:
                return
            # The gate is open and the port is still gone: the watchdog has not reached
            # this observation yet. Its own tick is what acts on it.
            await asyncio.sleep(_RECOVERY_POLL)

    async def _handle_cds(self, report) -> None:
        row = await queries.find_message_by_part_ref(report.modem_ref)
        if row is None:
            logger.warning(
                "+CDS for unknown/already-finalized part ref=%d st=%d",
                report.modem_ref, report.status_code,
            )
            return

        message_id = row['message_id']
        phone = row['phone']

        if report.delivered:
            await queries.set_part_delivered(report.modem_ref)
            if await queries.message_parts_all_delivered(message_id):
                await queries.set_message_delivered(message_id)
                spawn_delivery_dispatch(message_id, "delivered")
                logger.info("+CDS delivered: id=%d phone=%s", message_id, phone)
            else:
                logger.info(
                    "+CDS part delivered: id=%d seq=%d (awaiting other parts)",
                    message_id, row['seq'],
                )
        else:
            await queries.set_part_failed(report.modem_ref)
            desc = describe_tp_status(report.status_code)
            error = f"Delivery failed: {desc}"
            await queries.set_message_delivery_failed(message_id, error)
            spawn_delivery_dispatch(message_id, "failed", error)
            logger.warning(
                "+CDS failed: id=%d phone=%s %s",
                message_id, phone, desc,
            )
            if _is_permanent_status(report.status_code):
                await queries.record_permanent_fail(
                    phone, error, store.blacklist_threshold,
                )
            notify("delivery_error", f"{phone} (id {message_id}): {desc}",
                   dedup_extra=report.status_code, phone=phone)

    async def inbound_loop(self) -> None:
        """Read SMS at indexes posted from reader_loop, persist, then delete from SIM."""
        logger.info("Inbound loop started")
        while True:
            index = await self._inbound_indices.get()
            # Reading the SIM during recovery fails against a radio we switched off, and
            # the index is dropped for good — the message would sit unread until the
            # next restart's inbox scan.
            await self._await_modem_gate("inbound reading")
            try:
                response = await self._sender.read_sms(index)
                pdu_hex = parse_cmgr_pdu(response)
                if pdu_hex is None:
                    logger.warning("Could not parse +CMGR for index %d: %r", index, response)
                else:
                    await self._process_inbound_pdu(pdu_hex, index)
            except ModemFailure as e:
                logger.error("Inbound processing failed for index %d: %s", index, e)
            except Exception:
                logger.exception("Unexpected error processing inbound index %d", index)
            finally:
                self._inbound_indices.task_done()

    async def _process_inbound_pdu(self, pdu_hex: str, index: int) -> None:
        """Decode PDU → assembler → delete from SIM → dispatch (if message is complete)."""
        key = inbound_pdu_key(pdu_hex)
        if await queries.inbound_pdu_seen(key):
            # Persisted by an earlier read whose delete never happened — the link died
            # in between. Finish that job rather than deliver the message a second time.
            logger.info(
                "Inbound index %d was already handled — deleting the modem's copy", index
            )
            await self._sender.delete_sms(index)
            return
        try:
            sms = decode_deliver(pdu_hex)
        except ValueError as e:
            # Not a DELIVER (e.g. a stale status report) or a corrupt PDU.
            # Raw hex is logged — delete it so it does not accumulate in modem memory.
            logger.warning("Skipping PDU index=%d: %s pdu=%s", index, e, pdu_hex)
            await self._sender.delete_sms(index)
            return
        full = await assembler.handle_inbound(sms.sender, sms.text, sms.concat)
        # Marked between persisting and deleting, not after the delete: the delete is a
        # serial round-trip, and a dying link is exactly what interrupts it. What is left
        # unguarded is one database write instead of one AT exchange — and it fails in the
        # safe direction, since a crash there costs a duplicate rather than the message.
        await queries.mark_inbound_pdu_seen(key)
        await self._sender.delete_sms(index)
        if full is not None:
            logger.info("Inbound saved: phone=%s len=%d", sms.sender, len(full))
            # Do not await dispatch — fire-and-forget; errors are logged internally.
            self._spawn_dispatch(sms.sender, full)

    def _spawn_dispatch(self, phone: str, text: str) -> None:
        """Fire-and-forget dispatch with a strong reference: the event loop holds
        tasks weakly, and a sleeping retry-ladder could be collected by the GC."""
        notify("inbound", f"{phone}: {text}", phone=phone)
        task = asyncio.create_task(dispatch_inbound(phone, text))
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def scan_inbox(self) -> None:
        """Drain whatever SMS already sit in modem memory.

        Run at startup and again every time the link is restored in place — which is what
        makes the deduplication above load-bearing rather than theoretical.
        """
        try:
            gone = await queries.prune_inbound_seen(_INBOUND_SEEN_RETENTION)
        except Exception:
            # Housekeeping must never be the reason inbound goes unread.
            logger.exception("Could not prune the inbound deduplication keys")
        else:
            if gone:
                logger.info("Pruned %d expired inbound deduplication key(s)", gone)
        try:
            response = await self._sender.list_all_sms()
        except ModemFailure as e:
            logger.warning("Inbox scan failed: %s", e)
            return
        items = parse_cmgl_pdu(response)
        if not items:
            logger.info("Inbox scan: empty")
            return
        logger.info("Inbox scan: found %d stored SMS", len(items))
        for index, pdu_hex in items:
            try:
                await self._process_inbound_pdu(pdu_hex, index)
            except ModemFailure as e:
                logger.error("Failed to drain index %d: %s", index, e)
            except Exception:
                logger.exception("Unexpected error draining index %d", index)

    async def parts_flush_loop(self, max_age_seconds: int = 300) -> None:
        """Periodically finalises incomplete multipart groups (a part was lost)."""
        logger.info("Parts flush loop started, max_age=%ds", max_age_seconds)
        while True:
            await asyncio.sleep(60)
            try:
                for phone, text in await assembler.flush_stale_parts(max_age_seconds):
                    self._spawn_dispatch(phone, text)
            except Exception:
                logger.exception("Parts flush failed")

    async def keepalive_loop(self, interval_seconds: int = 1800) -> None:
        """Periodically query network registration so the operator sees the modem as active."""
        logger.info("Keepalive loop started, interval=%ds", interval_seconds)
        while True:
            await asyncio.sleep(interval_seconds)
            try:
                response = await self._sender.check_registration()
                logger.info("Keepalive AT+CREG? -> %s", response.strip())
            except ModemFailure as e:
                logger.warning("Keepalive AT+CREG? failed: %s", e)

    async def _poll(self) -> tuple[bool, bool]:
        """Ask the modem whether it is registered. Returns (registered, link_lost).

        Never raises. The watchdog acts on doubt, and an exception is a stronger form of
        doubt than a negative answer — but for five hours on 2026-07-29 an exception was
        no answer at all: it escaped this step before the ladder was consulted and was
        swallowed by the loop above, so nothing was ever counted.
        """
        try:
            registered = await self._sender.registration_ok()
        except ModemTransportError as e:
            logger.warning("Registration poll found the link gone: %s", e)
            return False, True
        except Exception:
            logger.exception("Registration poll failed")
            return False, False
        # The URC port counts as the link too. It carries every +CDS and +CMTI, and losing
        # it is silent and total — but it cannot be polled, only observed. Folding it in
        # here is what gives both ports one cause, one ladder and one recovery, instead of
        # two budgets that can each decide to end the process.
        if not self._reader_link.usable:
            logger.warning("The link to %s is gone", self._read_port)
            return registered, True
        return registered, False

    async def _watchdog_step(self) -> str:
        registered, link_lost = await self._poll()
        # A modem that answers every command and still cannot send is unhealthy too.
        # One check, one ladder — not because two would race over the port (the gate and
        # the serial lock already prevent that) but because there must be exactly one
        # escalation counter and one place that decides to end the process.
        stalled = self._stalled
        previous = self._health.cause
        action = self._health.decide(
            registered=registered,
            stalled=stalled,
            hard_reset_allowed=not _hard_reset_on_cooldown(),
            link_lost=link_lost,
        )
        cause = self._health.cause

        if action == OK:
            if previous is not None:
                logger.info("Modem healthy again")
            return OK
        if previous is not None and cause != previous:
            logger.info(
                "Modem problem changed from %s to %s — restarting the ladder",
                previous, cause,
            )
        if cause == STALL:
            logger.warning(
                "Modem is registered but cannot send (%d message(s) failed, "
                "budget exhausted: %s)",
                len(self._health.failed_ids), self._health.budget_exhausted,
            )
        if action == WAIT:
            return WAIT

        # The remedy belongs to the cause, not to the level. For a lost link neither
        # level is an AT command: the port is not there to carry one, and an
        # implementation that kept the old level-to-command mapping would spend the whole
        # escalation writing into a missing port — the incident's failure mode, reached
        # by a different route.
        if cause == TRANSPORT:
            if action == SOFT:
                # The gentle rung is no longer "wait and see". A re-enumeration is
                # physically a device disappearing for a few seconds, and paying for it
                # with a process restart drops the in-memory send queue and re-runs
                # startup. Reopening the port turns that restart cycle into a pause. The
                # blunt rung is unchanged: the restart is what an exhausted reopen earns.
                logger.error("Link to the modem is gone — reopening the port in place")
                await self._recover(self._reopen_link)
                return SOFT
            logger.error(
                "Link to the modem is still gone after reopening; restarting the service"
            )
            return HARD

        if action == SOFT:
            logger.warning("Modem unhealthy: %s — soft recovery", cause)
            await self._recover(self._sender.soft_recover)
            return SOFT
        if action == COOLDOWN:
            logger.error(
                "Modem still unhealthy; hard reset on cooldown — check antenna/operator"
            )
            await self._recover(self._sender.soft_recover)
            return COOLDOWN
        # Two distinct ERROR templates, not one with a parameter: the Telegram handler
        # deduplicates on the template, so a shared one would hide whichever cause came
        # second behind the first.
        if cause == STALL:
            logger.error(
                "Modem cannot send and does not recover; hard reset + service restart"
            )
        else:
            logger.error("Modem unrecoverable; hard reset + service restart")
        _mark_hard_reset()
        # Not reopened: watchdog_loop sleeps for the settle period and then exits, and
        # nothing must touch a rebooting modem in the meantime.
        await self._recover(self._sender.hard_reset, reopen=False)
        return HARD

    async def _wait_for_tick(self) -> None:
        """Wait for the next poll, or for someone to report the link gone.

        The send path meets a lost link first, and at the moment it matters. Making that
        observation wait up to a full interval to be noticed is a minute spent already
        knowing the answer. The event is cleared once taken, so a link that stays lost
        still escalates on the ordinary cadence rather than spinning.
        """
        # Either port: the reader loop meets its own loss first, and it has no other way
        # to ask for a recovery.
        waiters = [
            asyncio.ensure_future(link.link_lost.wait())
            for link in (self._sender, self._reader_link)
        ]
        try:
            done, _ = await asyncio.wait(
                waiters, timeout=_WD_INTERVAL, return_when=asyncio.FIRST_COMPLETED
            )
            if done:
                logger.info("Watchdog woken early: a link was reported gone")
        finally:
            for waiter in waiters:
                waiter.cancel()
            self._sender.link_lost.clear()
            self._reader_link.link_lost.clear()

    async def watchdog_loop(self) -> None:
        """Periodically ensure the modem is registered; soft/hard recover if not."""
        logger.info("Modem watchdog started")
        while True:
            await self._wait_for_tick()
            if not store.modem_watchdog_enabled:
                # Recovery is the operator's job now, so stop accumulating a suspicion
                # nothing will act on.
                self._health.forget()
                # A lost link is the exception, and deliberately not covered by this
                # switch. It exists so an operator can take over judgement about an
                # unhealthy *modem* — whether to cycle its radio, whether to reset it.
                # A port that does not exist is not that kind of judgement call: there is
                # no policy under which the right answer is to keep writing to it, and
                # silencing the watchdog to investigate a flapping registration should
                # not silently opt out of ever recovering the port.
                if not (self._sender.usable and self._reader_link.usable):
                    logger.error(
                        "Link to the modem is gone while the watchdog is disabled — "
                        "restarting the service anyway"
                    )
                    await asyncio.sleep(_WD_HARD_RESET_SETTLE)
                    os._exit(1)
                continue
            try:
                action = await self._watchdog_step()
            except Exception:
                logger.exception("Watchdog step failed")
                continue
            if action == "hard":
                await asyncio.sleep(_WD_HARD_RESET_SETTLE)
                os._exit(1)

    def health_snapshot(self) -> dict:
        """What the gateway itself believes about the modem, for the admin page.

        The link is reported alongside it, because until now the page said what the
        gateway believed about the *modem* — whether it is recovering, whether sends have
        stalled — and nothing at all about the link underneath. During the incident the
        only external symptom was silence and the only evidence was a traceback in the
        journal. A link being reopened over and over is precisely the condition an
        operator should not have to read logs to see.
        """
        snapshot = self._health.snapshot(held=len(self._held), stalled=self._stalled)
        snapshot.update(self._sender.link_snapshot())
        snapshot["urc_link"] = "open" if self._reader_link.usable else "lost"
        return snapshot

    async def collect_diagnostics(self) -> list[dict]:
        """Read-only modem health snapshot via the existing serial lock. An AT
        liveness pre-check short-circuits a wedged modem; one failing query never
        breaks the sweep. Never raises."""
        # First, so the operator sees it before the readings: during a recovery the radio
        # is deliberately off, and an unannotated snapshot reads as a dead modem.
        state = [{"key": "gateway", "cmd": "—", "parsed": self.health_snapshot()}]

        try:
            await self._sender.command("AT", timeout=2.0)
        except Exception as e:
            return state + [{"key": "alive", "cmd": "AT",
                             "error": f"modem not responding: {type(e).__name__}: {e}"}]

        out: list[dict] = list(state)
        for key, cmd, decoder in _DIAG_QUERIES:
            item = {"key": key, "cmd": cmd}
            try:
                raw = await self._sender.command(cmd, timeout=2.0)
                item["raw"] = raw.strip()
                item["parsed"] = decoder(raw)
            except ModemFailure as e:
                item["error"] = str(e)
            except Exception as e:
                item["error"] = f"{type(e).__name__}: {e}"
            out.append(item)
        return out

    async def expire_loop(self) -> None:
        """Periodically mark stale 'sent' messages as 'expired'.
        Reads the timeout from the settings store each iteration (hot-apply)."""
        logger.info("Expire loop started")
        while True:
            await asyncio.sleep(60)
            # Bulk writer: one sweep can expire many messages, and each owes its app a
            # notification — hence the returned ids rather than a bare UPDATE.
            for message_id in await queries.expire_stale_messages(
                store.delivery_timeout_seconds
            ):
                spawn_delivery_dispatch(message_id, "expired")


