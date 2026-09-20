# Design

## Which capability owns this

The first draft put everything in `modem-link`. That was wrong and the reasoning is worth
keeping, because the boundary it blurs is one this project has already paid to draw.

`modem-link` is the serial transport: link-versus-AT classification, fast-fail, reopen, the
init sequence, cancellation safety, inbox reconciliation. Its **first** requirement rests on
the very separation an IMS requirement would violate — *"restarting the link does nothing
for a radio that is merely unregistered"* — and the code says the same in one line: *"the
linker owns the link, and the watchdog owns the radio"*. The voice route is radio, carrier
and carrier-profile state. Nothing about it survives or fails with the serial port, and a
reader opening `modem-link` to learn what the link guarantees should not find Билайн's IMS
policy there.

`outbound-send` is the other tempting home, and it is worse: everything in it is framed
through *sending*, and IMS has nothing to do with sending SMS.

So the voice route gets a capability of its own. It costs one file, and it makes the
non-goal at the bottom of this document a boundary rather than a promise: if consuming
`RING`/`+CLIP` is ever built, it has a place to live that is not the serial link.

Two of the six norms stay elsewhere, because they are not about the voice route at all.
The four-way reading outcome is `modem-link`'s — it subdivides a taxonomy that capability
already defines. What gathering an alert's evidence may cost is `outbound-send`'s, and it is
a **MODIFIED** delta rather than a new requirement: that capability's existing alert
requirement states that the console's diagnostics snapshot is the collection the alert
carries, and after this change that sentence is false. A requirement whose prose has become
untrue is modified, not left standing beside a new one that contradicts it.

## Where the watcher lives

The watchdog's tick, not a loop of its own.

| candidate | cost |
|---|---|
| its own loop | a second actor on the command port, a second cadence, a second thing that can die quietly |
| the keepalive loop | runs every 30 minutes and exists to keep the modem awake; a voice route lost for 29 minutes is lost |
| **the watchdog tick** | shares its fate with the recovery ladder — see below, it is the real cost |

The registration gate is what decides it. The IMS reading is meaningful only on a registered
module, and the watchdog is the one actor that has just established exactly that: its step
polls registration first and has the answer in hand. Anywhere else the gate would mean
asking about registration a second time and treating two answers from two moments as a pair.

⚠️ **They are still two lock acquisitions.** The first draft said the watchdog "already
holds the serial lock" across its tick. It does not: `command()` takes and releases the lock
per command. The argument above survives — the two readings are adjacent and ordered, which
is what the gate needs — but it is adjacency, not atomicity, and a requirement must not be
written as if the pair were read under one lock.

⚠️ **The tick is not a 60-second cadence.** It waits on either port reporting itself gone,
with sixty seconds as a ceiling, so during a reopen storm it fires far more often — which is
to say the new IMS command fires most often exactly when the port is worst. Whatever the
reading costs, it is paid at the worst moment, which is another reason it must not be able
to raise into the step.

### Two consequences that are requirements, not implementation notes

**The observation cannot be allowed to break the ladder.** `watchdog_loop` wraps the step in
a bare `except Exception: continue`, and the step's poll carries an explicit "never raises"
contract because the 2026-07-29 incident was 316 swallowed watchdog failures. An IMS read is
an AT command and can raise. Placed before the decision, a raising read stops the ladder
advancing for as long as the fault lasts. Placed at the end, it can swallow the return value
on a hard-reset tick — and with it the settle and the `os._exit(1)` that follows, leaving
the process alive across a modem reboot it just ordered. Both re-open an incident an
archived change closed, which is why the spec says it in a SHALL rather than leaving it to
whoever writes the function.

**The observation must sit above the watchdog's switch.** `watchdog_loop` evaluates
`modem_watchdog_enabled` before the step and `continue`s, so an observation placed inside the
step is silently opt-out-able by a setting that means something else. The live spec refused
this exact coupling for the link — *"If this coupling is given its own switch, that switch
SHALL be separate from the watchdog's"* — and an archived task records the same trap being
found and fixed once already. The implementation consequence is real: the registration answer
has to come out of the step, or the loop has to poll and pass it in.

## Why the reading is gated on registration rather than filtered afterwards

The vendor reading's second digit — `<VoLTE_cap>` — is zero on an unregistered module
whether or not the route would otherwise be available. Measured 2026-09-18: after
`AT+CFUN=1,1` the module sat outside the network for about three minutes and read zero
throughout, then came back at `1,1`.

- **Debounce it** — alert only after N consecutive zeroes. Rejected: it turns a three-minute
  reset into a four-minute one and still alerts on a longer outage, while delaying the real
  loss by exactly the debounce.
- **Filter after the fact** — read it always, suppress the alert when unregistered.
  Rejected on the grounds `decode_servicedomain` already states: a value read but not to be
  believed gets rendered somewhere, and "voice route: unavailable" on a page during a reset
  is the same wrong statement without the notification.
- **Gate the reading** — while unregistered, the route's availability is *not measured* and
  says so. Chosen.

⚠️ **The rejection of debounce assumes the unregistered window is the only false-positive
source, and that assumption is not measured.** A module attaches to the network first and to
IMS afterwards, so there may be a window where registration is true and the second digit is
still zero — and every soft recovery walks through it, releasing as soon as registration
answers. Task 1.4 exists to measure whether that window is real and how long it is. If it
is, the gate widens to "registered and settled" or the debounce comes back, and this section
is rewritten rather than quietly left standing.

**Only the second digit is gated.** The first is a local setting the radio state does not
affect — the vendor stores it automatically and it takes effect on the next reboot — and
every state that moves it off `1` arises precisely while the module is off the network:
a stored setting that did not survive a reset, a replaced module, or an MBN re-selected for
a swapped SIM, which §1.2.1 of the reference says restores the NV item to the profile's
default. Gating it would silence the most valuable alert this change has, in the one
scenario that generates it.

## The two digits are two conditions, not one severity

🔴 **This section was written against a guess at the vendor's field names and has been
rewritten against the reference itself (task 1.1, `captures/`).** What follows is what
Quectel documents; the paragraph it replaces named the two digits `<enabled>` and
`<admitted>` and drew an operator's next action from that naming. Both names were wrong, and
one of the actions they implied was wrong with them.

`+QCFG: "ims",<IMS_conf>,<VoLTE_cap>`, per the LTE-A(Q) IMS Application Note V1.0 §2.3.1,
whose §1.1 lists EP06 Series:

| field | vendor's values |
|---|---|
| `<IMS_conf>` | `0` — whether IMS is enabled is decided by the default in the **MBN file**; `1` — enable compulsorily; `2` — disable compulsorily |
| `<VoLTE_cap>` | `0` — VoLTE disabled; `1` — VoLTE enabled |

Collapsing them is still wrong, and the reason survives the correction: the two are asked of
different things. But the two things are not the two the first draft named.

**The first digit is ours.** It is not "IMS is on"; it is *what this gateway asked for*, and
it has three states, not two. `1` is what was written on 2026-09-18 and is the state of
record. `0` is the factory position — **defer to the carrier profile** — and is therefore not
a fault at all on its own: a module reading `0,1` has a working voice route supplied by its
MBN. `2` is an explicit local disable and has never been seen on this module.

So the alert on this digit is **not** "IMS has been switched off". It is *the configuration
this gateway relies on is no longer the one it set* — true of `0` and of `2` alike, needing
the same remedy (write `1`, accept a reboot), and worth raising even while the route still
works, because a `0` whose MBN happens to enable VoLTE loses it the moment the profile
changes. ⚠️ The earlier text would have alerted on `0` as a failure and been wrong about
`0,1`, and would have called `2` by the same name as `0` and been wrong about the cause.

**The second digit is not the carrier's answer.** The first draft said `1,0` *"is the
carrier: nothing local will fix it and a reboot will not help"*. The reference does not
support that, and does not settle what the field is: its parameter table calls `<VoLTE_cap>`
*"the capability of VoLTE"*, while its prose one page earlier says *"you can check the IMS
registration status by `AT+QCFG="ims"`"*. Two different quantities, in one document, and
neither of them is "the network refused you".

The 2026-09-18 observation — zero for three minutes off the network, then one — fits both
readings and chooses neither. So the gateway reports this digit as **the voice route's
availability, cause unnamed**. That is not a retreat: `outbound-send` already requires that
an alert *"SHALL NOT name a cause the gateway did not observe"*, and "the carrier refuses
us" is exactly such a cause. The first draft asked this change to break a rule its own
sibling capability enforces.

⚠️ **What the alert still cannot distinguish** is *why* the first digit stopped being `1`.
The reference names one path the first draft did not consider and which needs no reboot of
ours at all (§1.2.1): *"if an NV item of the MBN files is changed through AT command, when
the MBN is activated or deactivated, the previously configured NV item will recover to
default"* — and §1.2.3 selects the MBN automatically from the SIM's IMSI. A SIM swap silently
reverts the setting. A replaced module and a reset NV remain indistinguishable too: the sweep
reads no identity of the hardware at all, no IMEI, no ICCID. Task 2.5 decides whether to add
one; until then the alert names the condition and not its cause, which is the standard this
project already holds alerts to.

## Splitting the alert sweep from the page's

`_alert_observations` runs the whole sweep and hands it to `summarise_for_alert`, which uses
four readings.

⚠️ **The first draft said the filter "already exists" and is merely applied to the results.
That is false, verified by grep: `_ALERT_READINGS` is referenced nowhere in the repository,
and the four keys are hardcoded in the function body.** So the split is not a rewiring of an
existing declaration — it is creating the declaration that was assumed to exist. That is why
the requirement asks for *one* declaration serving both the asking and the printing: two
lists here drift silently, and `summarise_for_alert` renders a reading it did not get as
`?`, which is indistinguishable from a modem that did not answer.

The alert path keeps its liveness pre-check and its "observations unavailable" fallback.
Neither is affected by asking for fewer readings.

## What this change deliberately leaves open

**The gateway does not switch IMS on, and does not re-arm it.** Writing the setting takes
effect only after a module reboot, and an init sequence that reboots the module turns every
reconnect into an outage, on a gateway whose whole `modem-link` spec is built around
reconnecting without one.

🔴 **Task 1.2 is answered, and it does not close this the way the draft expected.** The
reference settles the power cycle without spending one: *"the configuration will be saved
automatically"* (§2.3.1), so the setting does survive. What it also names is a second way to
lose it that needs no reboot of ours — §1.2.1, an MBN activated or deactivated restores the
NV item to the profile's default, and §1.2.3 selects the MBN automatically from the SIM's
IMSI, while §1.2.2 warns that *"not all operator MBN files enable IMS by default"*. A SIM
swap is therefore a silent disarm.

That strengthens the case for watching and does **not** by itself argue for re-arming: a
gateway that rewrites the setting is a gateway that reboots the module, and it would do so
at exactly the moment a new SIM is being brought up. Re-arming stays a requirement this
change does not have, to be argued in its own right rather than smuggled in as a fix — but
it is now a known gap with a named trigger, not an unexamined one.

**Roaming is not handled.** The registration check counts roaming as registered, while a
visited network commonly will not carry a roaming subscriber's VoLTE — so a roaming module
would produce an endless "route unavailable" episode with no remedy. The reference says
nothing about `<VoLTE_cap>` under roaming either way. For a fixed gateway on Билайн this is
rare, but it is exactly the shape that teaches an operator to ignore the alert. Recorded as
an open question rather than gated on, because gating on it without a measurement would be
guessing.

**Nothing consumes `RING` / `+CLIP`.** They arrive and are logged as unhandled. Turning an
incoming call into an authorisation is a separate change under the new capability, and it
carries a decision that is the owner's alone. What this change does is make sure the
capability is not lost again, unseen, while that question is open.
