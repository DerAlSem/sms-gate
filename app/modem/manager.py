import asyncio
import logging
from dataclasses import dataclass

import serial_asyncio

from app.settings_store import store
from app.modem.at_commands import ATSerial, ATCommandError
from app.modem.dispatch import dispatch_inbound
from app.modem.parser import parse_cds, parse_cmti, parse_cmgr_pdu, parse_cmgl_pdu
from app.modem.pdu import decode_deliver
from app.modem import assembler
from app.db import queries

logger = logging.getLogger(__name__)


def _is_permanent_status(code: int) -> bool:
    """GSM 03.40 TP-Status: 0x40–0x5F = permanent error (SC stops trying)."""
    return 0x40 <= code <= 0x5F


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
                ref = await self._sender.send_sms(msg.phone, msg.text)
                await queries.set_message_sent(msg.message_id, ref)
                logger.info("Sent message %d, modem_ref=%d", msg.message_id, ref)
            except ATCommandError as e:
                await queries.set_message_failed(msg.message_id, str(e))
                logger.error(
                    "Failed to send message %d (app=%s to=%s text=%r): %s",
                    msg.message_id, msg.app_id or "?", msg.phone, msg.text, e,
                )
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
        row = await queries.find_message_by_modem_ref(report.modem_ref)
        if row is None:
            logger.warning(
                "+CDS for unknown/already-finalized modem_ref=%d st=%d",
                report.modem_ref, report.status_code,
            )
            return

        late = row['status'] != 'sent'
        prefix = "late +CDS" if late else "+CDS"

        if report.delivered:
            await queries.set_message_delivered(row['id'])
            logger.info("%s delivered: id=%d phone=%s", prefix, row['id'], row['phone'])
        else:
            error = f"Delivery failed, st={report.status_code}"
            await queries.set_message_delivery_failed(row['id'], error)
            logger.warning(
                "%s failed: id=%d phone=%s st=%d",
                prefix, row['id'], row['phone'], report.status_code,
            )
            if _is_permanent_status(report.status_code):
                await queries.record_permanent_fail(
                    row['phone'], error, store.blacklist_threshold,
                )

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

    async def expire_loop(self) -> None:
        """Periodically mark stale 'sent' messages as 'expired'.
        Reads the timeout from the settings store each iteration (hot-apply)."""
        logger.info("Expire loop started")
        while True:
            await asyncio.sleep(60)
            await queries.expire_stale_messages(store.delivery_timeout_seconds)


