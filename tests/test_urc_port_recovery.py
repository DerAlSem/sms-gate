"""The unsolicited-result port recovers on the same terms as the command port.

It used to be opened by hand inside `reader_loop`, with no lock, no shared failure
classification and no awareness of the recovery gate. Giving it a reopen loop of its own
would produce two bounded budgets that can each decide to end the service, and a second
reopener able to race the settling period after a deliberate modem reset — a window that
exists precisely so that nothing touches a rebooting modem.
"""

import asyncio

import pytest

import app.modem.manager as mgr
from app.modem.at_commands import ModemTransportError
from app.modem.manager import ModemManager


@pytest.fixture(autouse=True)
def _fast_recovery(monkeypatch):
    monkeypatch.setattr(mgr, "_RECOVERY_SETTLE", 0.05)
    monkeypatch.setattr(mgr, "_RECOVERY_POLL", 0.005)
    monkeypatch.setattr(mgr, "_RECOVERY_TIMEOUT", 2.0)


class FakeLink:
    """Either port, with its link state and its reopen scripted."""

    def __init__(self, name, reopen=True):
        self.port = name
        self.usable = True
        self.link_lost = asyncio.Event()
        self.reopens = 0
        self.inits = []
        self._reopen = reopen

    def lose(self):
        self.usable = False
        self.link_lost.set()

    async def registration_ok(self):
        if not self.usable:
            raise ModemTransportError(f"link to {self.port} is not open")
        return True

    async def reconnect(self, *, init=True):
        self.inits.append(init)
        if not self._reopen:
            return False
        self.usable = True
        self.reopens += 1
        return True

    async def list_all_sms(self, timeout=10.0):
        return "\r\nOK\r\n"

    def link_snapshot(self):
        return {"link": "open" if self.usable else "lost",
                "link_last_good": "—", "link_reopens": self.reopens}


def _mgr(sender=None, urc=None):
    m = ModemManager("/dev/ttyUSB2", "/dev/ttyUSB1")
    m._sender = sender or FakeLink("/dev/ttyUSB2")
    m._reader_link = urc or FakeLink("/dev/ttyUSB1")
    return m


def test_a_re_enumeration_taking_both_ports_is_one_coordinated_recovery():
    sender, urc = FakeLink("/dev/ttyUSB2"), FakeLink("/dev/ttyUSB1")
    sender.lose()
    urc.lose()
    m = _mgr(sender, urc)

    assert asyncio.run(m._watchdog_step()) == "soft"
    assert (sender.reopens, urc.reopens) == (1, 1)
    assert m._modem_gate.is_set() is True


def test_losing_only_the_urc_port_still_reaches_the_shared_recovery():
    """It cannot be polled, only observed — so without folding it into the poll, losing it
    is silent and total: no +CDS, no +CMTI, and every health check passing."""
    urc = FakeLink("/dev/ttyUSB1")
    urc.lose()
    m = _mgr(urc=urc)

    assert asyncio.run(m._watchdog_step()) == "soft"
    assert urc.reopens == 1
    assert m._sender.reopens == 0, "a working command port must not be replaced"


def test_the_urc_port_is_reopened_without_an_init_sequence_of_its_own():
    """The design's open question, settled: it has no writer, so it cannot issue the URC
    subscription — that is applied through the command port and takes effect for both."""
    urc = FakeLink("/dev/ttyUSB1")
    urc.lose()
    m = _mgr(urc=urc)

    asyncio.run(m._watchdog_step())
    assert urc.inits == [False]


def test_the_command_port_is_reopened_before_the_urc_port():
    """So the subscription is back in place before the port carrying its results starts
    listening."""
    order = []
    sender, urc = FakeLink("/dev/ttyUSB2"), FakeLink("/dev/ttyUSB1")
    for link in (sender, urc):
        original = link.reconnect

        async def wrapped(*, init=True, _link=link, _original=original):
            order.append(_link.port)
            return await _original(init=init)

        link.reconnect = wrapped
    sender.lose()
    urc.lose()

    asyncio.run(_mgr(sender, urc)._watchdog_step())
    assert order == ["/dev/ttyUSB2", "/dev/ttyUSB1"]


def test_an_unreopenable_urc_port_reaches_the_same_service_exit():
    urc = FakeLink("/dev/ttyUSB1", reopen=False)
    urc.lose()
    m = _mgr(urc=urc)

    assert asyncio.run(m._watchdog_step()) == "soft"
    assert asyncio.run(m._watchdog_step()) == "hard"


def test_the_reader_does_not_reopen_during_the_settling_period_after_a_hard_reset():
    """The blunt rung leaves the gate closed on purpose and the process exits during the
    settle. Nothing must touch a rebooting modem in the meantime."""
    urc = FakeLink("/dev/ttyUSB1")
    urc.lose()
    m = _mgr(urc=urc)
    m._modem_gate.clear()          # as `_recover(..., reopen=False)` leaves it

    async def run():
        waiting = asyncio.create_task(m._await_link_restored())
        await asyncio.sleep(0.05)
        done = waiting.done()
        waiting.cancel()
        return done

    assert asyncio.run(run()) is False
    assert urc.reopens == 0, "the reader must not reopen anything on its own"


def test_the_reader_resumes_once_the_shared_recovery_has_put_the_port_back():
    urc = FakeLink("/dev/ttyUSB1")
    urc.lose()
    m = _mgr(urc=urc)

    async def run():
        waiting = asyncio.create_task(m._await_link_restored())
        await asyncio.sleep(0.02)
        assert not waiting.done()
        await m._watchdog_step()   # the one coordinated recovery
        await asyncio.wait_for(waiting, timeout=1.0)

    asyncio.run(run())
    assert urc.reopens == 1


def test_the_watchdog_wakes_on_a_loss_reported_by_either_port():
    m = _mgr()

    async def run():
        m._reader_link.lose()
        started = asyncio.get_event_loop().time()
        await m._wait_for_tick()
        return asyncio.get_event_loop().time() - started

    assert asyncio.run(run()) < 1.0, "a reported loss must not wait out a whole interval"


def test_a_disabled_watchdog_still_restarts_on_a_lost_urc_port(monkeypatch):
    """Silencing the watchdog is a judgement call about an unhealthy *modem*. A port that
    does not exist is not that kind of call."""
    from app.settings_store import store

    monkeypatch.setitem(store._cache, "modem_watchdog_enabled", "false")
    exits = []
    monkeypatch.setattr(mgr.os, "_exit", lambda code: exits.append(code))

    m = _mgr()
    m._reader_link.lose()

    async def run():
        # One tick: the loop would go round again, so it is cancelled after the exit.
        task = asyncio.create_task(m.watchdog_loop())
        await asyncio.sleep(0.1)
        task.cancel()

    asyncio.run(run())
    assert exits == [1]
