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
from app.modem.dispatch import dispatch_inbound
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
        self._wd_fails = 0
        self._wd_soft_tried = False

    async def connect(self) -> None:
        await self._sender.connect()
        await self._sender.init()

    async def disconnect(self) -> None:
        await self._sender.close()

    async def enqueue(self, message_id: int, phone: str, text: str, app_id: str = "") -> None:
        await self._queue.put(OutgoingMessage(message_id, phone, text, app_id))

    async def sender_loop(self) -> None:
        """Pick messages from queue and send via modem."""
        logger.info("Sender loop started")
        while True:
            msg = await self._queue.get()
            try:
                parts = encode_submit(msg.phone, msg.text, ref=msg.message_id % 256)
                if len(parts) > store.max_sms_parts:
                    error = f"message too long: {len(parts)} parts > max {store.max_sms_parts}"
                    await queries.set_message_failed(msg.message_id, error)
                    logger.warning(
                        "Rejected message %d (app=%s to=%s): %s",
                        msg.message_id, msg.app_id or "?", msg.phone, error,
                    )
                    notify("send_error",
                           f"{msg.phone} (id {msg.message_id}): {error}",
                           dedup_extra="too_long", phone=msg.phone)
                    continue

                total = len(parts)

                async def on_part_sent(seq: int, ref: int) -> None:
                    await queries.add_message_part(msg.message_id, ref, seq, total)
                    if seq == 1:
                        await queries.set_message_sent(msg.message_id, ref)

                await self._sender.send_sms_pdu(parts, on_part_sent)
                logger.info("Sent message %d in %d part(s)", msg.message_id, total)
            except ATCommandError as e:
                await queries.set_message_failed(msg.message_id, str(e))
                logger.warning(
                    "Failed to send message %d (app=%s to=%s text=%r): %s",
                    msg.message_id, msg.app_id or "?", msg.phone, msg.text, e,
                )
                notify("send_error",
                       f"{msg.phone} (id {msg.message_id}): {e}",
                       dedup_extra=str(e), phone=msg.phone)
            finally:
                self._queue.task_done()

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
        if await self._sender.registration_ok():
            if self._wd_fails or self._wd_soft_tried:
                logger.info("Modem re-registered")
            self._wd_fails = 0
            self._wd_soft_tried = False
            return "ok"
        self._wd_fails += 1
        if self._wd_fails < _WD_FAIL_THRESHOLD:
            return "wait"
        if not self._wd_soft_tried:
            logger.warning("Modem not registered (%dx) — soft recovery", self._wd_fails)
            await self._sender.soft_recover()
            self._wd_soft_tried = True
            self._wd_fails = 0
            return "soft"
        if _hard_reset_on_cooldown():
            logger.error("Modem still not registered; hard reset on cooldown — check antenna/operator")
            await self._sender.soft_recover()
            self._wd_fails = 0
            return "cooldown"
        logger.error("Modem unrecoverable; hard reset + service restart")
        _mark_hard_reset()
        await self._sender.hard_reset()
        return "hard"

    async def watchdog_loop(self) -> None:
        """Periodically ensure the modem is registered; soft/hard recover if not."""
        logger.info("Modem watchdog started")
        while True:
            await asyncio.sleep(_WD_INTERVAL)
            if not store.modem_watchdog_enabled:
                self._wd_fails = 0
                self._wd_soft_tried = False
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
            await queries.expire_stale_messages(store.delivery_timeout_seconds)


