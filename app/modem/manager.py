import asyncio
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

import serial_asyncio

from app.config import settings
from app.settings_store import store
from app.modem.at_commands import ATSerial, ATCommandError
from app.modem.delivery_dispatch import spawn_delivery_dispatch
from app.modem.dispatch import dispatch_inbound
from app.modem.errors import is_permanent_failure, is_retryable
from app.modem.parser import parse_cds, parse_cmti, parse_cmgr_pdu, parse_cmgl_pdu, describe_tp_status
from app.modem.pdu import decode_deliver
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
# Backstop for a gate that never reopens. Derived from the ceiling above rather than
# guessed, and necessarily longer than _WD_HARD_RESET_SETTLE, since the hard path keeps
# sending suspended until the process exits. Not a scheduling knob — an escape hatch.
_SEND_GATE_TIMEOUT = _RECOVERY_TIMEOUT + _RECOVERY_SETTLE + 60.0

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
        self._read_port = read_port
        self._baudrate = baudrate
        self._queue: asyncio.Queue[OutgoingMessage] = asyncio.Queue()
        self._inbound_indices: asyncio.Queue[int] = asyncio.Queue()
        self._bg_tasks: set[asyncio.Task] = set()
        # Ids the sender holds queued or in flight. The scheduler skips them, so a
        # message cannot be enqueued twice and sent twice.
        self._held: set[int] = set()
        self._wd_fails = 0
        self._wd_soft_tried = False
        # Which problem the current unhealthy streak is about. The ladder's progress
        # belongs to one problem: without this, a soft recovery for a registration
        # outage would let the next stall skip straight to a hard reset.
        self._wd_cause: str | None = None
        # Evidence that the modem accepts commands but cannot get messages out. Ids
        # rather than a count, so one message's four attempts are one piece of evidence
        # about one destination — not three about the hardware.
        self._stalled_ids: set[int] = set()
        self._stall_exhausted = False
        # Set means the modem is usable. The watchdog closes it around recovery so
        # neither a send nor an inbound read is issued into a radio that is off or has
        # just come back.
        self._modem_gate = asyncio.Event()
        self._modem_gate.set()

    def _note_send_failure(self, message_id: int, error: str, *, exhausted: bool) -> None:
        """Record a failed send as possible evidence about the modem.

        A permanent failure is neutral: it neither counts nor clears, because it says
        something about the destination. Letting it clear would let a stream of bad
        numbers mask a genuinely dead radio.
        """
        if is_permanent_failure(error):
            return
        self._stalled_ids.add(message_id)
        if exhausted:
            self._stall_exhausted = True

    def _note_send_success(self) -> None:
        """A modem that just sent something is not stalled."""
        self._clear_stall()

    def _clear_stall(self) -> None:
        self._stalled_ids.clear()
        self._stall_exhausted = False

    @property
    def _stalled(self) -> bool:
        """Whether the send path believes the modem needs recovering.

        Either several different messages have failed, or one has used up its whole
        ladder — roughly eight minutes in which nothing got out. The second clause
        carries this gateway: at around a dozen messages a day, waiting for three
        distinct ones would take hours.
        """
        if not store.send_stall_recovery_enabled:
            return False
        return self._stall_exhausted or len(self._stalled_ids) >= _WD_FAIL_THRESHOLD

    async def _await_modem_gate(self, what: str = "sending") -> None:
        if self._modem_gate.is_set():
            return
        logger.info("%s suspended while the modem is recovered", what.capitalize())
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
            if reopen:
                await self._await_reattach()
        finally:
            self._clear_stall()
            if reopen:
                self._modem_gate.set()

    async def connect(self) -> None:
        await self._sender.connect()
        await self._sender.init()

    async def disconnect(self) -> None:
        await self._sender.close()

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
        except ATCommandError as e:
            await self._handle_send_failure(msg, e, attempt, reached_sent)
            return
        self._note_send_success()
        logger.info(
            "Sent message %d in %d part(s) on attempt %d", msg.message_id, total, attempt
        )

    async def _handle_send_failure(
        self, msg: OutgoingMessage, error: ATCommandError, attempt: int, reached_sent: bool
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
        reader, _ = await serial_asyncio.open_serial_connection(
            url=self._read_port, baudrate=self._baudrate
        )
        buf = b''
        while True:
            try:
                chunk = await asyncio.wait_for(reader.read(256), timeout=1.0)
                buf += chunk
            except asyncio.TimeoutError:
                pass

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
            except ATCommandError as e:
                logger.error("Inbound processing failed for index %d: %s", index, e)
            except Exception:
                logger.exception("Unexpected error processing inbound index %d", index)
            finally:
                self._inbound_indices.task_done()

    async def _process_inbound_pdu(self, pdu_hex: str, index: int) -> None:
        """Decode PDU → assembler → delete from SIM → dispatch (if message is complete)."""
        try:
            sms = decode_deliver(pdu_hex)
        except ValueError as e:
            # Not a DELIVER (e.g. a stale status report) or a corrupt PDU.
            # Raw hex is logged — delete it so it does not accumulate in modem memory.
            logger.warning("Skipping PDU index=%d: %s pdu=%s", index, e, pdu_hex)
            await self._sender.delete_sms(index)
            return
        full = await assembler.handle_inbound(sms.sender, sms.text, sms.concat)
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
        """Drain whatever SMS already sit in modem memory at startup."""
        try:
            response = await self._sender.list_all_sms()
        except ATCommandError as e:
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
            except ATCommandError as e:
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
            except ATCommandError as e:
                logger.warning("Keepalive AT+CREG? failed: %s", e)

    async def _watchdog_step(self) -> str:
        registered = await self._sender.registration_ok()
        # A modem that answers every command and still cannot send is unhealthy too.
        # One check, one ladder — two independent recovery paths would race each other
        # over a single serial port.
        stalled = self._stalled
        cause = None if registered and not stalled else (
            "registration" if not registered else "stall"
        )
        if cause is None:
            if self._wd_fails or self._wd_soft_tried:
                logger.info("Modem healthy again")
            self._wd_fails = 0
            self._wd_soft_tried = False
            self._wd_cause = None
            return "ok"

        if self._wd_cause is not None and cause != self._wd_cause:
            # The problem changed. Progress up the ladder belongs to the problem that
            # earned it: without this reset, a soft recovery for a registration outage
            # would let the next stall skip straight to a hard reset and a restart —
            # the stall's very first action.
            logger.info(
                "Modem problem changed from %s to %s — restarting the ladder",
                self._wd_cause, cause,
            )
            self._wd_fails = 0
            self._wd_soft_tried = False
        self._wd_cause = cause

        if cause == "stall":
            logger.warning(
                "Modem is registered but cannot send (%d message(s) failed, "
                "budget exhausted: %s)",
                len(self._stalled_ids), self._stall_exhausted,
            )
        self._wd_fails += 1
        if self._wd_fails < _WD_FAIL_THRESHOLD:
            return "wait"
        if not self._wd_soft_tried:
            logger.warning("Modem unhealthy: %s (%dx) — soft recovery", cause, self._wd_fails)
            await self._recover(self._sender.soft_recover)
            self._wd_soft_tried = True
            self._wd_fails = 0
            return "soft"
        if _hard_reset_on_cooldown():
            logger.error(
                "Modem still unhealthy; hard reset on cooldown — check antenna/operator"
            )
            await self._recover(self._sender.soft_recover)
            self._wd_fails = 0
            return "cooldown"
        # Two distinct ERROR templates, not one with a parameter: the Telegram handler
        # deduplicates on the template, so a shared one would hide whichever cause came
        # second behind the first.
        if cause == "stall":
            logger.error(
                "Modem cannot send and does not recover; hard reset + service restart"
            )
        else:
            logger.error("Modem unrecoverable; hard reset + service restart")
        _mark_hard_reset()
        # Not reopened: watchdog_loop sleeps for the settle period and then exits, and
        # nothing must touch a rebooting modem in the meantime.
        await self._recover(self._sender.hard_reset, reopen=False)
        return "hard"

    async def watchdog_loop(self) -> None:
        """Periodically ensure the modem is registered; soft/hard recover if not."""
        logger.info("Modem watchdog started")
        while True:
            await asyncio.sleep(_WD_INTERVAL)
            if not store.modem_watchdog_enabled:
                self._wd_fails = 0
                self._wd_soft_tried = False
                self._wd_cause = None
                # Recovery is the operator's job now, so stop accumulating a suspicion
                # nothing will act on.
                self._clear_stall()
                continue
            try:
                action = await self._watchdog_step()
            except Exception:
                logger.exception("Watchdog step failed")
                continue
            if action == "hard":
                await asyncio.sleep(_WD_HARD_RESET_SETTLE)
                os._exit(1)

    async def collect_diagnostics(self) -> list[dict]:
        """Read-only modem health snapshot via the existing serial lock. An AT
        liveness pre-check short-circuits a wedged modem; one failing query never
        breaks the sweep. Never raises."""
        try:
            await self._sender.command("AT", timeout=2.0)
        except Exception as e:
            return [{"key": "alive", "cmd": "AT",
                     "error": f"modem not responding: {type(e).__name__}: {e}"}]

        out: list[dict] = []
        for key, cmd, decoder in _DIAG_QUERIES:
            item = {"key": key, "cmd": cmd}
            try:
                raw = await self._sender.command(cmd, timeout=2.0)
                item["raw"] = raw.strip()
                item["parsed"] = decoder(raw)
            except ATCommandError as e:
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


