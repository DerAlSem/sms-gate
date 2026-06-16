import asyncio
import html
import logging
import queue
import socket
import threading
import time

import httpx

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
_MAX_LEN = 3500
_BODY_MAX = _MAX_LEN - 200   # headroom for the title line + tags


def _instance_label() -> str:
    """Label for notifications: the configured instance_name, or the hostname."""
    from app.settings_store import store
    return store.instance_name or socket.gethostname()


def _bounded(plain: str, budget: int) -> str:
    """HTML-escape `plain`, bounding the escaped result to `budget` chars without
    ever splitting a generated entity. Truncation happens on the plain prefix
    (escape is applied to a whole prefix), so callers can safely wrap the result
    in tags — the tags stay whole."""
    esc = html.escape(plain)
    if len(esc) <= budget:
        return esc
    plain = plain[:budget]
    esc = html.escape(plain)
    while len(esc) > budget and plain:
        plain = plain[:-1]
        esc = html.escape(plain)
    return esc + "…"


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
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None
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

    def _record(self, message_id, phone) -> None:
        """Persist a Telegram message_id -> phone mapping for reply→SMS. Runs from
        the worker thread; schedules the async DB write on the captured event loop."""
        if self._loop is None or message_id is None:
            return
        from app.db import queries
        try:
            asyncio.run_coroutine_threadsafe(
                queries.add_notify_ref(message_id, phone), self._loop)
        except Exception:
            pass

    def maybe_send(self, text: str, dedup_sig=None, phone=None) -> None:
        suppressed = 0
        if dedup_sig is not None:
            send, suppressed = self._should_send(dedup_sig)
            if not send:
                return
        if suppressed:
            text = f"({suppressed} duplicates suppressed in window)\n{text}"
        if len(text) > _MAX_LEN:
            text = text[:_MAX_LEN] + "\n…(truncated)"
        item = (text, phone) if phone is not None else text
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            if dedup_sig is not None:
                self._rollback(dedup_sig, suppressed)

    def _worker(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:               # stop sentinel
                self._queue.task_done()
                break
            text, phone = item if isinstance(item, tuple) else (item, None)
            try:
                message_id = self._sender(text)
                if phone is not None:
                    self._record(message_id, phone)
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

    def _http_send(self, text: str):
        url = _TELEGRAM_API.format(token=self._token)
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(url, json={"chat_id": self._chat_id, "text": text,
                                          "parse_mode": "HTML"})
        if resp.status_code != 200:
            return None
        try:
            return resp.json()["result"]["message_id"]
        except (ValueError, KeyError, TypeError):
            return None


class TelegramAlertHandler(logging.Handler):
    """Thin logging handler: formats ERROR+ records and delegates delivery to a
    TelegramNotifier, deduping by the record's message TEMPLATE (record.msg) so
    `logger.error("Failed %d", id)` collapses across ids. This is the
    "system errors" notification type."""

    def __init__(self, notifier: TelegramNotifier, *, level=logging.ERROR) -> None:
        super().__init__(level=level)
        self._notifier = notifier

    def _signature(self, record: logging.LogRecord):
        return (record.name, record.levelno, record.msg)

    def format_alert(self, record: logging.LogRecord) -> str:
        lines = [
            f"<b>🔴 {html.escape(record.levelname)} · {html.escape(_instance_label())}</b>",
            f"<code>{html.escape(record.name)}</code>",
            _bounded(record.getMessage(), 500),
        ]
        if record.exc_info:
            tb = logging.Formatter().formatException(record.exc_info)
            lines.append(f"<pre>{_bounded(tb, _MAX_LEN - 800)}</pre>")
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


_EVENT_TOGGLE = {
    "send_error": "notify_send_errors",
    "delivery_error": "notify_delivery_errors",
    "inbound": "notify_inbound",
}

_EVENT_TITLE = {
    "send_error": "🔴 Send failed",
    "delivery_error": "🚫 Delivery failed",
    "inbound": "📨 Inbound",
}


def notify(event_type: str, text: str, dedup_extra=None, phone=None) -> None:
    """Send a typed operator notification if its toggle is on and a notifier is
    configured. event_type in {'send_error','delivery_error','inbound'}.
    Error types dedup on (event_type, dedup_extra); inbound (dedup_extra None) is
    never deduped."""
    from app.settings_store import store

    if _notifier is None:
        return
    toggle = _EVENT_TOGGLE.get(event_type)
    if toggle is None or not store.get(toggle):
        return
    head = f"<b>{html.escape(_EVENT_TITLE[event_type])} · {html.escape(_instance_label())}</b>"
    body = f"{head}\n{_bounded(text, _BODY_MAX)}"
    dedup_sig = (event_type, dedup_extra) if dedup_extra is not None else None
    _notifier.maybe_send(body, dedup_sig=dedup_sig, phone=phone)
