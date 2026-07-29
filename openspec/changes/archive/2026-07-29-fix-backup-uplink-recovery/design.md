## Context

`deploy/wwan-backup/wwan-backup.sh` keeps a QMI data session up on a Quectel EM06 over
`/dev/cdc-wdm0`, with a standby default route on `wwan0` at metric 700. A `oneshot` unit
driven by a 30-second timer both keeps that session alive and decides, by pinging strictly
through the primary interface, whether traffic should fail over to it.

It deliberately keeps off the AT ports `/dev/ttyUSB2` and `/dev/ttyUSB3`, which the SMS
gateway owns. That decoupling is correct and this change preserves it: the two services
share hardware and nothing else.

The script is `set -u` without `set -e`, so failures are individually handled or silently
ignored, and it runs as root from systemd with no state beyond `/run/wwan-backup`.

## Goals / Non-Goals

**Goals:**

- The channel recovers on its own from the modem being replaced underneath it.
- A failure to recover cannot damage the modem or make the fault harder to diagnose.
- Failover keeps working while the backup session is broken.

**Non-Goals:**

- Running `qmi-proxy` under systemd with a restart policy. It is the right long-term
  answer to a process that can go stale for six hours unnoticed, but it is an ownership
  change to a system daemon, not a fix to this script, and it is tracked separately.
- Coordinating with `sms-gate`. Both consume one modem, and a shared recovery path would
  trade a rare fault for a permanent dependency between two services that currently share
  no code.
- Diagnosing why the modem re-enumerates.

## Decisions

### Start the session from the default profile

Empirical, and the reasoning follows the evidence rather than leading it. With no session
present, an explicit `apn=internet.tele2.ru,ip-type=4` was refused with `no-service`
continuously for six hours; the default profile succeeded immediately, holding that same
APN and that same IPv4 PDP type. The values were never in dispute — the form of the
request was.

The mechanism behind the refusal is **not established** and this design does not invent
one. What is established is reproducible and sufficient to choose the path. The explicit
APN survives as configuration so the profile can be overridden if this regresses.

### Hold one client, do not release one per attempt

The obvious framing — "release the client on the failure path" — cannot be implemented.
The id is parsed out of the successful reply, and a refused request commonly prints no id
at all, so on the path where it matters there is nothing to release.

Acquiring one client, recording it, and reusing it across attempts gives the same guarantee
by construction: the count cannot grow with the number of failures because nothing new is
acquired. It also keeps the property the original `--client-no-release-cid` was chosen
for — a later teardown can address the session it started.

### Renew access on timeouts, never on refusals

This is the safeguard that keeps recovery from becoming the next incident. A refusal
(`no-service`, `CallFailed`) is the modem answering: the stack is healthy and the network
has said no. A timeout is the stack not answering, which is what a stale descriptor looks
like from outside.

Killing the proxy in response to a refusal would mean that any carrier-side outage —
exactly the condition the backup channel exists for — sends the script into repeatedly
killing a system process it does not own. Requiring several consecutive timeouts, and
bounding renewal like any other retry, keeps the cure narrower than the disease.

### Separate the two duties in the watchdog run

Session management and failover are independent duties sharing one invocation, and today
the first aborts the second: `cmd_up` exits the whole script on failure, so a QMI problem
means the primary uplink is never pinged, `fails`/`oks` never advance, and failover cannot
trigger. The fix is small — the session path returns rather than exits — but the
requirement is what matters, because the failure is invisible while only one thing is
broken.

### Bound the retrying

Every automatic loop in this change is bounded, alerts at the bound, and resets on success.
The incident is the argument: 131 unbounded attempts turned a channel that could not
connect into a modem that had to be rebooted. A mechanism that can neither succeed nor
stop makes the problem it was built to solve strictly worse.

## Risks / Trade-offs

- **The default-profile fix rests on one reproduction, not a documented cause.** → The
  behaviour was stable over six hours and reversed immediately on the alternative path. The
  explicit APN stays available as an override if it regresses.
- **Bounding the retries means the channel can stop trying while an operator is asleep.** →
  It alerts at the bound and reports its state. A backup channel that has stopped trying
  and said so is better than one that is destroying the modem quietly; the primary uplink
  is unaffected either way.
- **Restarting the proxy touches a process this script does not own.** → Gated behind
  consecutive timeouts, never refusals, and bounded. Named as a non-goal that the real
  answer is a systemd-supervised proxy.
- **Reusing one client across attempts risks reusing a client the modem considers dead**
  after a re-enumeration. → The renewal path exists precisely for that, and re-acquisition
  after renewal is part of it.

## Migration Plan

1. Deploy the script through the normal path from merged `main`.
2. Verify on the live server: with no session present, a cold start succeeds; the client id
   does not advance across repeated failures; a forced session failure still leaves the
   primary-uplink counters advancing.
3. Re-enable `wwan-watchdog.timer` and confirm one clean cycle.

Rollback is a redeploy of the previous script; there is no persistent state to migrate
beyond `/run/wwan-backup`, which is recreated each run.

## Open Questions

- **Should `qmi-proxy` run under systemd with a restart policy?** It stayed stale for six
  hours because nothing owns its lifecycle. Out of scope here, and the reason this change
  reacts to symptoms (timeouts) rather than to the proxy's age.
- ~~**How many consecutive timeouts, and what bound on renewal?**~~ Settled during
  implementation, against the 30-second timer cadence: renew after **3** consecutive
  timeouts (~90 s, past any single slow reply), at most **2** renewals per outage, and give
  up after **10** consecutive failed session attempts (~5 min).

  Giving up slows retrying rather than stopping it — one probe every **20** passes, roughly
  ten minutes. A channel that stopped entirely could never notice it had recovered, since
  nothing else would ever ask; that is a different way to be permanently down, not a
  safeguard against one. All five numbers are configurable in `/etc/default/wwan-backup`.
