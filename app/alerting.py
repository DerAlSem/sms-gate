import logging
import queue
import socket
import threading
import time

import httpx

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
_MAX_LEN = 3500


class TelegramNotifier:
    """Owns Telegram delivery: a daemon worker thread draining a bounded queue,
    plus windowed dedup. Shared by the ERROR log handler and notify().

    maybe_send(text, dedup_sig=None): dedup_sig=None always enqueues (used for
    inbound — each message is wanted); otherwise identical signatures within
    dedup_window seconds are suppressed and counted, and the next send after the
    window prepends a "(N duplicates suppressed in window)" note.
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
        self._token = token
        self._chat_id = chat_id
        self._dedup_window = dedup_window
        self._time = time_fn
        self._last_sent: dict = {}
        self._suppressed: dict = {}
        self._lock = threading.Lock()
        self._queue: queue.Queue = queue.Queue(maxsize=queue_maxsize)
        self._sender = sender or self._http_send
        if start_worker:
            threading.Thread(target=self._worker, daemon=True).start()

    def _should_send(self, sig):
        """Return (send, suppressed_count) for a dedup signature. Thread-safe."""
        now = self._time()
        with self._lock:
            last = self._last_sent.get(sig)
            if last is not None and (now - last) < self._dedup_window:
                self._suppressed[sig] = self._suppressed.get(sig, 0) + 1
                return False, 0
            suppressed = self._suppressed.pop(sig, 0)
            self._last_sent[sig] = now
            return True, suppressed

    def _rollback(self, sig, suppressed):
        """Undo a _should_send commit when the message could not be enqueued."""
        with self._lock:
            self._last_sent.pop(sig, None)
            if suppressed:
                self._suppressed[sig] = suppressed

    def maybe_send(self, text: str, dedup_sig=None) -> None:
        suppressed = 0
        if dedup_sig is not None:
            send, suppressed = self._should_send(dedup_sig)
            if not send:
                return
        if suppressed:
            text = f"({suppressed} duplicates suppressed in window)\n{text}"
        if len(text) > _MAX_LEN:
            text = text[:_MAX_LEN] + "\n…(truncated)"
        try:
            self._queue.put_nowait(text)
        except queue.Full:
            if dedup_sig is not None:
                self._rollback(dedup_sig, suppressed)

    def _worker(self) -> None:
        while True:
            text = self._queue.get()
            if text is None:               # stop sentinel
                self._queue.task_done()
                break
            try:
                self._sender(text)
            except Exception:
                # Never log here: it would re-enter the ERROR handler and recurse.
                pass
            finally:
                self._queue.task_done()

    def close(self) -> None:
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass

    def _http_send(self, text: str) -> None:
        url = _TELEGRAM_API.format(token=self._token)
        with httpx.Client(timeout=10.0) as client:
            client.post(url, json={"chat_id": self._chat_id, "text": text})


class TelegramAlertHandler(logging.Handler):
    """Thin logging handler: formats ERROR+ records and delegates delivery to a
    TelegramNotifier, deduping by the record's message TEMPLATE (record.msg) so
    `logger.error("Failed %d", id)` collapses across ids. This is the
    "system errors" notification type."""

    def __init__(self, notifier: TelegramNotifier, *, level=logging.ERROR) -> None:
        super().__init__(level=level)
        self._notifier = notifier
        self._hostname = socket.gethostname()

    def _signature(self, record: logging.LogRecord):
        return (record.name, record.levelno, record.msg)

    def format_alert(self, record: logging.LogRecord) -> str:
        lines = [
            f"\U0001F534 sms-gate {record.levelname} on {self._hostname}",
            f"logger: {record.name}",
            "",
            record.getMessage(),
        ]
        if record.exc_info:
            lines.append("")
            lines.append(logging.Formatter().formatException(record.exc_info))
        return "\n".join(lines)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = self.format_alert(record)
            self._notifier.maybe_send(text, dedup_sig=self._signature(record))
        except Exception:
            self.handleError(record)


_notifier: "TelegramNotifier | None" = None
_handler: "TelegramAlertHandler | None" = None


def setup_telegram_alerts(source) -> "TelegramAlertHandler | None":
    """Build the module TelegramNotifier whenever token+chat are present (notify()
    needs it even when system-error alerts are off), and install a
    TelegramAlertHandler on the root logger only when notify_system_errors is on.
    Returns the handler, or None when no handler was installed."""
    global _notifier, _handler
    if not source.alert_bot_token or not source.alert_chat_id:
        _notifier = None
        _handler = None
        return None
    _notifier = TelegramNotifier(
        source.alert_bot_token,
        source.alert_chat_id,
        dedup_window=source.alert_dedup_window,
    )
    if getattr(source, "notify_system_errors", True):
        _handler = TelegramAlertHandler(_notifier)
        logging.getLogger().addHandler(_handler)
        logging.getLogger(__name__).info("Telegram alerting enabled")
        return _handler
    _handler = None
    return None


def reconfigure(source) -> "TelegramAlertHandler | None":
    """Detach the previous handler + notifier, then rebuild from `source`.
    Called after alert settings change in the GUI (any "Alerting" change)."""
    global _notifier, _handler
    if _handler is not None:
        logging.getLogger().removeHandler(_handler)
        _handler = None
    if _notifier is not None:
        _notifier.close()
        _notifier = None
    return setup_telegram_alerts(source)
