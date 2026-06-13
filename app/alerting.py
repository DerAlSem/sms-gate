import logging
import queue
import socket
import threading
import time

import httpx

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
_MAX_LEN = 3500


class TelegramAlertHandler(logging.Handler):
    """Logging handler that pushes ERROR+ records to a Telegram chat.

    Network I/O runs in a daemon thread (never blocks the asyncio event loop).
    Identical records (same logger+level+message-template) within `dedup_window`
    seconds are suppressed and counted; the next send after the window reports
    how many were suppressed.
    """

    def __init__(
        self,
        token: str,
        chat_id: str,
        *,
        dedup_window: float = 300.0,
        sender=None,
        time_fn=time.monotonic,
        queue_maxsize: int = 100,
        start_worker: bool = True,
    ) -> None:
        super().__init__(level=logging.ERROR)
        self._token = token
        self._chat_id = chat_id
        self._dedup_window = dedup_window
        self._time = time_fn
        self._hostname = socket.gethostname()
        self._last_sent: dict = {}
        self._suppressed: dict = {}
        self._lock = threading.Lock()
        self._queue: queue.Queue = queue.Queue(maxsize=queue_maxsize)
        self._sender = sender or self._http_send
        if start_worker:
            threading.Thread(target=self._worker, daemon=True).start()

    def _signature(self, record: logging.LogRecord):
        # Keyed on the message TEMPLATE (record.msg), not the formatted message, so
        # logger.error("Failed to send message %d", mid) dedups across all ids. Log ERRORs
        # with %-style args, not pre-formatted f-strings, or every message is unique.
        return (record.name, record.levelno, record.msg)

    def _should_send(self, record: logging.LogRecord):
        """Return (send, suppressed_count). Thread-safe."""
        sig = self._signature(record)
        now = self._time()
        with self._lock:
            last = self._last_sent.get(sig)
            if last is not None and (now - last) < self._dedup_window:
                self._suppressed[sig] = self._suppressed.get(sig, 0) + 1
                return False, 0
            suppressed = self._suppressed.pop(sig, 0)
            self._last_sent[sig] = now
            return True, suppressed

    def format_alert(self, record: logging.LogRecord, suppressed: int = 0) -> str:
        lines = [
            f"\U0001F534 sms-gate {record.levelname} on {self._hostname}",
            f"logger: {record.name}",
            "",
        ]
        if suppressed:
            lines.append(f"({suppressed} duplicates suppressed in window)")
        lines.append(record.getMessage())
        if record.exc_info:
            lines.append("")
            lines.append(logging.Formatter().formatException(record.exc_info))
        text = "\n".join(lines)
        if len(text) > _MAX_LEN:
            text = text[:_MAX_LEN] + "\n…(truncated)"
        return text

    def emit(self, record: logging.LogRecord) -> None:
        try:
            send, suppressed = self._should_send(record)
            if not send:
                return
            text = self.format_alert(record, suppressed)
            try:
                self._queue.put_nowait(text)
            except queue.Full:
                # Dropped: un-arm the dedup window so this error type is not silenced
                # for the whole window despite nothing having been delivered.
                self._rollback(record, suppressed)
        except Exception:
            self.handleError(record)

    def _rollback(self, record: logging.LogRecord, suppressed: int) -> None:
        """Undo the _should_send commit when the alert could not be enqueued."""
        sig = self._signature(record)
        with self._lock:
            self._last_sent.pop(sig, None)
            if suppressed:
                self._suppressed[sig] = suppressed

    def _worker(self) -> None:
        while True:
            text = self._queue.get()
            if text is None:               # stop sentinel
                self._queue.task_done()
                break
            try:
                self._sender(text)
            except Exception:
                # Never log here: it would re-enter this handler and recurse.
                pass
            finally:
                self._queue.task_done()

    def close(self) -> None:
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        super().close()

    def _http_send(self, text: str) -> None:
        url = _TELEGRAM_API.format(token=self._token)
        with httpx.Client(timeout=10.0) as client:
            client.post(url, json={"chat_id": self._chat_id, "text": text})


_current_handler: "TelegramAlertHandler | None" = None


def setup_telegram_alerts(source) -> "TelegramAlertHandler | None":
    """Install a TelegramAlertHandler on the root logger if creds are configured.
    `source` exposes .alert_bot_token / .alert_chat_id / .alert_dedup_window (Settings
    or SettingsStore). Returns the handler, or None when alerting is disabled.
    Tracks the handler so reconfigure() can replace it."""
    global _current_handler
    if not source.alert_bot_token or not source.alert_chat_id:
        return None
    handler = TelegramAlertHandler(
        source.alert_bot_token,
        source.alert_chat_id,
        dedup_window=source.alert_dedup_window,
    )
    logging.getLogger().addHandler(handler)
    _current_handler = handler
    logging.getLogger(__name__).info("Telegram alerting enabled")
    return handler


def reconfigure(source) -> "TelegramAlertHandler | None":
    """Detach the previously-installed handler (if any), then install a fresh one
    from `source`. Called after alert settings change in the GUI."""
    global _current_handler
    if _current_handler is not None:
        _current_handler.close()
        logging.getLogger().removeHandler(_current_handler)
        _current_handler = None
    return setup_telegram_alerts(source)
