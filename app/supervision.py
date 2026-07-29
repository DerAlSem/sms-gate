"""Watching the background loops the gateway is made of.

Extracted from `app.main`'s lifespan so it can be tested: there was no test for `main.py`
at all, and the defect this replaces lived exactly there. Every loop was collected with
`asyncio.gather(..., return_exceptions=True)`, which returns each exception and then
drops it, so a loop could terminate without a single line anywhere. On 2026-07-29 that is
what happened to the loop delivering `+CDS` and `+CMTI`: no delivery reports, no inbound
SMS, and nothing able to notice.
"""

from __future__ import annotations

import asyncio
import logging
import os

from app import alerting

logger = logging.getLogger(__name__)

# How long a deliberate exit waits for its own explanation to be delivered. Bounded:
# staying up to keep trying would be a gateway that cannot exit, which is worse than one
# whose last alert was lost.
_FATAL_ALERT_DRAIN = 5.0


def _exit_service(name: str) -> None:
    """End the process, after its explanation has actually gone out.

    Alerts are queued and delivered by a background thread, so an immediate exit throws
    away whatever is still queued — including the alert saying why the gateway is
    exiting. A loud exit nobody hears is the same silence this module exists to remove.
    """
    alerting.drain(timeout=_FATAL_ALERT_DRAIN)
    os._exit(1)


def supervise(
    task: asyncio.Task,
    *,
    name: str,
    essential: bool,
    on_fatal=None,
) -> asyncio.Task:
    """Report the death of a background task, and end the service if it was essential.

    `essential` means the gateway cannot do its job without this loop, so leaving the
    process running would be a service that is up and quietly no longer working — the
    exact state the incident produced.
    """

    def _done(finished: asyncio.Task) -> None:
        # Shutdown cancels every task by design. Without this guard every deploy would
        # alert on every loop and exit instead of closing the modem and the database —
        # and `exception()` on a cancelled task raises rather than returning None.
        if finished.cancelled():
            return
        error = finished.exception()
        if error is None:
            return
        logger.error("Background loop %s died", name, exc_info=error)
        if essential:
            (on_fatal or _exit_service)(name)

    task.add_done_callback(_done)
    return task
