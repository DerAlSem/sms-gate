import asyncio
import html
import logging
import queue
import socket
import threading
import time

import httpx

_TELEGRAM_DIRECT = "https://api.telegram.org"
_SEND_PATH = "/bot{token}/sendMessage"
# Kept for the tests and callers that formatted the whole URL themselves.
_TELEGRAM_API = _TELEGRAM_DIRECT + _SEND_PATH

# Where an alert waits when no route could carry it. The loudest failure is the one that
# silences its own reporting, and this is the only reason the operator hears about it at all.
# Bounded, because a spool that grows without limit is a second fault: on a long outage the
# useful lines are the first few and the last few, not two thousand in between.
_SPOOL_MAX = 40
# Delivered late is worth having; delivered a week late is noise wearing an alert's clothes.
_SPOOL_MAX_AGE = 24 * 3600
# WARNING-level only from this module's own failure paths: the alert handler listens at
# ERROR, so logging an alerting failure at ERROR would re-enter it and recurse.
logger = logging.getLogger(__name__)

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
        relay_base: str = "",
        spool_path=None,
    ) -> None:
        self._token = token
        self._chat_id = chat_id
        self._dedup_window = dedup_window
        self._relay_base = relay_base
        self._spool_path = spool_path
        self._time = time_fn
        self._last_sent: dict = {}
        self._suppressed: dict = {}
        # Counted and logged rather than dropped in silence. Both paths below discard a
        # notification on purpose — to keep alerting from failing the thing it reports on
        # — but discarding it *silently* makes a broken alerting path indistinguishable
        # from a system with nothing to report, and a long incident is exactly when the
        # queue is most likely to fill. WARNING, not ERROR: the handler that would feed
        # this back into itself only listens at ERROR.
        self.dropped = 0
        self.undelivered = 0
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
            self.dropped += 1
            logger.warning(
                "Alert queue full — dropped a notification (%d so far)", self.dropped
            )
            if dedup_sig is not None:
                self._rollback(dedup_sig, suppressed)

    def _drain_once(self) -> bool:
        """Deliver one queued notification. Returns False on the stop sentinel."""
        item = self._queue.get()
        if item is None:                   # stop sentinel
            self._queue.task_done()
            return False
        text, phone = item if isinstance(item, tuple) else (item, None)
        try:
            message_id = self._sender(text)
            if phone is not None:
                self._record(message_id, phone)
            # A route exists again, so whatever was held while none did can go now. After
            # the live send, not before: flushing first would spend the working route on
            # backlog and risk losing the message that proved it works.
            self._flush_spool()
        except Exception as e:
            # WARNING, never ERROR: the alert handler listens at ERROR and would
            # re-enter this path and recurse. Silence here is what made an alerting
            # path that had stopped working look like a quiet system.
            self.undelivered += 1
            logger.warning(
                "Could not deliver a notification (%d so far): %s", self.undelivered, e
            )
            self._spool(text)
        finally:
            self._queue.task_done()
        return True

    # ------------------------------------------------------------------ spool
    # The loudest failure is the one that silences its own reporting: with no route out,
    # the alert saying so takes the route that is gone. Holding it on disk is what turns
    # "you were never told" into "you were told late".

    def _spool(self, text: str) -> None:
        if self._spool_path is None:
            return
        try:
            import json
            from pathlib import Path
            p = Path(self._spool_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
            lines.append(json.dumps({"at": time.time(), "text": text}, ensure_ascii=False))
            # Oldest go first when it overflows. On a long outage the opening lines are the
            # ones that say what happened; the middle is repetition.
            if len(lines) > _SPOOL_MAX:
                lines = lines[-_SPOOL_MAX:]
            p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except Exception as e:
            logger.warning("Could not hold an undelivered notification: %s", e)

    def _flush_spool(self) -> None:
        if self._spool_path is None:
            return
        try:
            import json
            from pathlib import Path
            p = Path(self._spool_path)
            if not p.exists():
                return
            held = [l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
            p.unlink()
        except Exception as e:
            logger.warning("Could not read held notifications: %s", e)
            return
        now = time.time()
        for line in held:
            try:
                item = json.loads(line)
                age = now - float(item.get("at", now))
                if age > _SPOOL_MAX_AGE:
                    continue
                # Stamped with its age, because an alert read without one is read as now —
                # and an alert about a failover that ended hours ago, presented as current,
                # sends the operator looking for a fault that is not there.
                self._sender(
                    f"(held {int(age // 60)} min — no route out at the time)\n{item['text']}"
                )
            except Exception as e:
                logger.warning("Could not deliver a held notification: %s", e)
                # Put the rest back rather than losing them to one bad send.
                self._spool(item.get("text", line) if isinstance(item, dict) else line)
                return

    def _worker(self) -> None:
        while self._drain_once():
            pass

    def drain(self, timeout: float = 5.0) -> None:
        """Wait, briefly, for what is already queued to go out."""
        deadline = time.monotonic() + timeout
        while not self._queue.empty() and time.monotonic() < deadline:
            time.sleep(0.05)

    def close(self) -> None:
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass

    def _bases(self) -> list:
        """Routes to try, in order. The relay first, deliberately.

        The relay is the route that works during the outage this exists for, so it is the one
        that must be exercised by ordinary traffic — a path used only when things are broken
        is first tested by the breakage. The direct route stays as the fallback, which also
        covers the relay itself being down.
        """
        bases = []
        relay = (self._relay_base or "").strip().rstrip("/")
        if relay:
            bases.append(relay)
        bases.append(_TELEGRAM_DIRECT)
        return bases

    def _post_to(self, base: str, text: str):
        url = base + _SEND_PATH.format(token=self._token)
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(url, json={"chat_id": self._chat_id, "text": text,
                                          "parse_mode": "HTML"})
        if resp.status_code != 200:
            raise RuntimeError(f"{base} answered {resp.status_code}")
        try:
            return resp.json()["result"]["message_id"]
        except (ValueError, KeyError, TypeError):
            return None

    def _http_send(self, text: str):
        """Deliver by the first route that works, raising only if none did.

        A non-200 from one route is not a delivery failure while another route is untried —
        the previous version returned `None` on any bad status, which reads as "delivered, no
        id" to the caller and loses the message silently.
        """
        errors = []
        for base in self._bases():
            try:
                return self._post_to(base, text)
            except Exception as e:
                errors.append(f"{base}: {type(e).__name__}: {e}")
        raise RuntimeError("; ".join(errors))


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
    from app.config import settings as _settings
    from pathlib import Path as _Path
    _notifier = TelegramNotifier(
        source.alert_bot_token,
        source.alert_chat_id,
        dedup_window=source.alert_dedup_window,
        relay_base=getattr(source, "alert_relay_base", "") or "",
        # Beside the database, like the other runtime state, and gitignored for the same
        # reason: a spool committed from someone's machine would deliver their alerts here.
        spool_path=_Path(_settings.db_path).parent / "alert_spool.jsonl",
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
    "dispatch_error": "notify_dispatch_errors",
    # Shares the system-errors switch rather than adding one of its own: it replaces the
    # ERROR lines that switch already governed, so the same toggle keeps governing the
    # same class of message.
    "link": "notify_system_errors",
}

_EVENT_TITLE = {
    "send_error": "🔴 Send failed",
    "delivery_error": "🚫 Delivery failed",
    "inbound": "📨 Inbound",
    "dispatch_error": "📡 Webhook failed",
    "link": "🔌 Link restored",
}


def notify(event_type: str, text: str, dedup_extra=None, phone=None) -> None:
    """Send a typed operator notification if its toggle is on and a notifier is
    configured. event_type in {'send_error','delivery_error','inbound','dispatch_error',
    'link'}. Error types dedup on (event_type, dedup_extra); inbound (dedup_extra None) is
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


def drain(timeout: float = 5.0) -> None:
    """Module-level drain, so a deliberate exit can flush its own explanation.

    A no-op when alerting is not configured — an unconfigured gateway still has to be
    able to exit.
    """
    if _notifier is not None:
        _notifier.drain(timeout)
