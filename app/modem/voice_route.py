"""Whether an incoming voice call can still reach this gateway's SIM — and whether
anyone would find out if it stopped being able to.

The episode state, away from the modem and away from asyncio, because all of it is
decisions: what counts as a measurement, which reading is gated on registration and
which is not, and when a watcher that has gone quiet should say so.

Three conditions, alerted separately rather than collapsed into one "IMS is down":

- **the voice route is not available** — gated on registration, because the reading is
  negative on an unregistered module whether or not the route would otherwise be
  available. A watcher without the gate announces a lost voice route after every modem
  reset, every radio cycle and every recovery, which is the surest way to make the alert
  ignored before the first real one arrives;
- **the configuration is no longer the one this gateway set** — not gated, and raised
  even while the route still works. Every state that moves it arises precisely while
  the module is off the network, so gating it would silence it in the one scenario that
  generates it;
- **the state has not been measurable for too long** — because every mechanism above
  fails silent, and a watcher that has gone permanently quiet is otherwise
  indistinguishable from a voice route that is permanently fine.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

# The notification types these alerts are delivered as. Three, not one: the ERROR
# handler's dedup is per template and `notify`'s is per event type, so two conditions
# sharing one would let whichever arrived second hide behind the first.
ROUTE = "voice_route"
CONFIG = "voice_route_config"
STALE = "voice_route_stale"

# What this gateway wrote on 2026-09-18 and the state of record. Not "IMS is on": the
# field has three states, and the other two are an explicit local disable and the
# factory position that hands the decision to the carrier profile on the module.
CONFIGURED = 1

# How long the route's state may stay unknown before that is itself the news.
#
# The watchdog tick is at most sixty seconds and often faster, so this is sixty
# consecutive failures to measure — well past any recovery the ladder performs (a hard
# reset settles and the process restarts within minutes) and short enough that a route
# nobody can read does not stay unread for a working day. The two silencing mechanisms
# it catches are both real: `registration_ok` returns `False` for a modem that does not
# answer at all, so the gate stays shut for ever on an unanswerable modem, and an
# unparseable response becomes "not measured", which the page then renders quietly too.
STALE_AFTER = 3600.0

_MEASURED_FMT = "%Y-%m-%d %H:%M:%SZ"


@dataclass(frozen=True)
class VoiceRouteAlert:
    """One thing to tell an operator, and which notification carries it."""

    event: str      # ROUTE / CONFIG / STALE — the notify() type
    state: str      # lost | restored | drifted | unknown | known
    text: str
    good: bool      # a recovery, so the journal logs it as news and not as a problem


def _config_words(parsed: dict) -> str:
    """What the configuration digit has become, in the vendor's terms and not ours.

    🔴 `0` and `2` are two different conversations with two different people: `2` is IMS
    having been disabled on this module, `0` is nobody having decided and the carrier
    profile deciding instead. Calling them both "switched off" sends an operator looking
    for a person who does not exist.

    ⚠️ The state's NAME comes from the decoder and is not restated here. It was written
    out twice once, and two places saying what `0` means is two places that can come to
    disagree — the page would then have said one thing and the alert another about the
    same digit, and only one of them would have been wrong.
    """
    conf, name = parsed.get("ims_conf"), parsed.get("config")
    if conf == 0:
        return (f"the module has gone back to the factory position — {name} ({conf}). "
                "That is not a fault in itself: a module whose profile enables VoLTE "
                "still has a working voice route. It holds for as long as that profile "
                "does, and the profile is chosen from the SIM")
    if conf == 2:
        return f"on the module IMS now reads {name} ({conf})"
    return (f"the module reports a value this gateway does not recognise "
            f"({conf}, {name})")


class VoiceRouteWatch:
    """Edge-triggered state for the three conditions. One instance per gateway.

    Pure: it is told what was read and returns what to say. Nothing here touches the
    modem, and nothing here raises — the caller runs it beside a recovery ladder that
    must keep advancing whatever this thinks.
    """

    def __init__(self, *, stale_after: float = STALE_AFTER) -> None:
        self._stale_after = stale_after
        # Latches, one per condition. All start closed, which is what makes a route
        # already lost when the gateway starts an episode too: episode state does not
        # survive the process, and the process ends itself on the ladder's top rung and
        # on every deploy, so a watcher that only alerted on a transition it personally
        # witnessed would say nothing about a module unreachable since before it started.
        self._route_lost = False
        self._config_drifted = False
        self._stale = False
        self._measured_at: float | None = None
        self._started_at: float | None = None
        self._route_available: bool | None = None
        self._config: str | None = None

    # ------------------------------------------------------------------ observation

    def observe(
        self, *, registered: bool, parsed: dict | None, now: float
    ) -> list[VoiceRouteAlert]:
        """One reading. `parsed` is the decoder's output, or falsy for a reading that
        could not be taken or could not be parsed — the two are the same fact here."""
        if self._started_at is None:
            self._started_at = now
        alerts: list[VoiceRouteAlert] = []

        if parsed:
            alerts += self._observe_config(parsed)
            # 🔴 Only the second digit is gated. The first is a local setting the radio
            # state does not affect.
            if registered:
                alerts += self._observe_route(parsed)
                self._measured_at = now
                alerts += self._clear_stale()
                return alerts
        else:
            self._config = None
        # Nothing about the route was learned this tick: either the module answered
        # nothing usable, or it is off the network and the gate is shut. Both feed the
        # same clock, and the page must not go on showing the last value as current.
        self._route_available = None
        return alerts + self._check_stale(now)

    def _observe_config(self, parsed: dict) -> list[VoiceRouteAlert]:
        self._config = parsed.get("config")
        drifted = parsed.get("ims_conf") != CONFIGURED
        if drifted and not self._config_drifted:
            self._config_drifted = True
            return [VoiceRouteAlert(
                CONFIG, "drifted", good=False,
                text=("the IMS configuration is no longer the one this gateway set: "
                      f"{_config_words(parsed)}. Writing it back is "
                      'AT+QCFG="ims",1 and a reboot of the module — see docs/modem.md'),
            )]
        if not drifted and self._config_drifted:
            self._config_drifted = False
            return [VoiceRouteAlert(
                CONFIG, "restored", good=True,
                text="the IMS configuration is back to the one this gateway set",
            )]
        return []

    def _observe_route(self, parsed: dict) -> list[VoiceRouteAlert]:
        available = parsed.get("volte_cap") == 1
        self._route_available = available
        if not available and not self._route_lost:
            self._route_lost = True
            return [VoiceRouteAlert(
                ROUTE, "lost", good=False,
                # ⚠️ Reports the observation and stops. The gateway has no reading that
                # says why, and the vendor's own reference calls this field the
                # capability of VoLTE in its table and the IMS registration status in
                # its prose — neither of which is anybody having refused us.
                text=("the voice route is not available: the module is registered to "
                      "the network and reports VoLTE disabled. Why is not observed"),
            )]
        if available and self._route_lost:
            self._route_lost = False
            return [VoiceRouteAlert(
                ROUTE, "restored", good=True,
                text="the voice route is available again",
            )]
        return []

    # -------------------------------------------------------------------- staleness

    def _check_stale(self, now: float) -> list[VoiceRouteAlert]:
        since = self._measured_at if self._measured_at is not None else self._started_at
        if self._stale or since is None or now - since <= self._stale_after:
            return []
        self._stale = True
        ever = "since this gateway started" if self._measured_at is None else "for"
        return [VoiceRouteAlert(
            STALE, "unknown", good=False,
            text=(f"the voice route has not been measurable {ever} "
                  f"{int(now - since)}s — its state is unknown, which is not the same "
                  "as the route being lost"),
        )]

    def _clear_stale(self) -> list[VoiceRouteAlert]:
        if not self._stale:
            return []
        self._stale = False
        return [VoiceRouteAlert(
            STALE, "known", good=True,
            text="the voice route is measurable again",
        )]

    # ------------------------------------------------------------------- the page

    def snapshot(self) -> dict:
        """What the diagnostics page reports about the voice route.

        Never the last known value dressed as the current one: a reading that could not
        be taken says so, and the time beside it is when the state was last actually
        established.
        """
        if self._route_available is None:
            route = "not measured"
        else:
            route = "available" if self._route_available else "unavailable"
        return {
            "voice_route": route,
            "voice_route_config": self._config or "not measured",
            "voice_route_measured": (
                datetime.fromtimestamp(self._measured_at, timezone.utc)
                .strftime(_MEASURED_FMT)
                if self._measured_at is not None else "—"
            ),
        }
