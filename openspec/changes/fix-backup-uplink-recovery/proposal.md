## Why

On 2026-07-29 at 01:28:27 the modem re-enumerated on USB. The backup internet channel went
down with it and stayed down for six hours, until an operator worked through it by hand.
The channel is still disabled: `wwan-watchdog.timer` was stopped during the incident and
must stay stopped until this ships, because the unfixed script would reproduce the damage
at the next outage.

Four defects, each of which alone would have been survivable:

1. **A stale QMI proxy went unnoticed.** `qmicli -p` talks through a long-lived
   `qmi-proxy` process, which held a descriptor to the device node destroyed at 01:28:27.
   Every request through it was accepted and then timed out. The proxy had started 19 hours
   earlier and nothing connected its age to the failures.
2. **The cold start asks for a session in a form the network refuses.** With no session
   present, `wds-start-network` carrying an explicit `apn=internet.tele2.ru,ip-type=4` was
   refused with `no-service` continuously; the same request against the modem's default
   profile succeeded on the first attempt — and profile 1 holds that identical APN with
   that identical IPv4 PDP type.
3. **The liveness check does not see a running session**, so every run takes the full
   cold-start path — tearing the interface down and requesting a new session — instead of
   the idempotent one it exists to provide.
4. **Retrying is unbounded and each attempt leaks a QMI client.** 131 consecutive failures
   consumed the modem's finite per-service client pool (client ids climbed from 20 to 156)
   until every WDS request timed out. At that point only rebooting the modem cleared it.
   The mechanism built to restore the channel is what made it unrecoverable.

Reviewing the change turned up two more, both hidden by luck:

5. **A failure in session management aborts the whole watchdog run**, so the primary
   uplink is never tested and failover never happens. During the incident the home
   connection stayed up; had it dropped, the backup would not have taken over and nothing
   would have explained why.
6. **The network interface is never confirmed to exist** before it is torn down and
   configured, though the control device is. A re-enumeration recreates both.

## What Changes

- The data session is started from the modem's **default profile**; an explicit APN
  remains available as an override rather than as the default path.
- A QMI client is **acquired once and reused** across attempts. This replaces "release it
  on the failure path", which cannot be implemented as stated — the client id is read from
  the successful reply, so a refused request often names none.
- The liveness check reports a session that actually exists, so the idempotent path is
  taken.
- Retrying is **bounded**, alerts on reaching the bound, and resets on success.
- Access to the device — including the proxy — is renewed when requests **time out**
  repeatedly, and explicitly not when they are **refused**: a refusal is the network
  answering, and reacting to it by killing a process the uplink does not own would turn an
  ordinary carrier outage into an escalation.
- A failure in session management no longer cancels the primary-uplink check or failover.
- The network interface is confirmed present before it is configured.

## Capabilities

### New Capabilities
- `backup-uplink`: the QMI backup internet channel over the shared modem — surviving the
  device being replaced underneath it, establishing its session from the modem's own
  profile, holding one client rather than one per attempt, bounding its retries, and
  keeping its failover duty independent of its session duty.

### Modified Capabilities

None. This change touches no existing spec.

## Impact

- `deploy/wwan-backup/wwan-backup.sh` only. No Python, no schema, no API.
- Ships independently of `recover-from-serial-transport-loss`, which addresses the same
  root cause in the SMS gateway. The two share an incident, not a codebase, a deploy
  mechanism or a rollback.
- Deploying re-enables `wwan-watchdog.timer`, stopped since 2026-07-29.
