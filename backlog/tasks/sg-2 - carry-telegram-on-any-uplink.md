---
id: SG-2
title: carry-telegram-on-any-uplink
status: To Do
assignee: []
created_date: '2026-09-25 11:58'
labels:
  - migrated
dependencies: []
references:
  - openspec/changes/carry-telegram-on-any-uplink
ordinal: 2000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
## Why

The carrier behind the backup uplink drops Telegram and nothing else. Measured on
2026-09-18 by real address bound to `wwan0`: `api.telegram.org` (149.154.166.110) and
`gatewayapi.telegram.org` (149.154.167.99) both time out at fifteen seconds, while
`cloudflare.com` answers in 0.34 s, `www.google.com` in 0.44 s and `api.ucaller.ru` in
0.17 s over that same interface. The interface carries traffic. One vendor does not arrive.

Half of the answer already exists and is not written down anywhere. A relay on the far end
of the tunnel — `deploy/nginx/edge-alert-relay.conf`, bound to the tunnel address, admitting
only the house — forwards Bot API calls out over a machine that can reach Telegram. It is
deployed and it works: from the house, `http://<tunnel-far-end>/bot<invalid>/getMe` answers
**401 in 0.21 s**, and the 401 comes from Telegram itself. The far end is reachable over the
backup uplink too — **404 in 0.28 s** over `wwan0` — so the path survives the outage it
exists for.

What is missing is that the relay covers only the callers that happen to know about it, and
no requirement says they must. Three callers do not:

- `app/telegram_poll.py` has `https://api.telegram.org` compiled into `_API`. The operator's
  replies — the channel through which an SMS is sent by hand — stop being received during a
  wired outage.
- `gatewayapi.telegram.org` is not proxied by the relay at all. That is the `tg_gateway` rung
  of `route-sends-by-operator`, whose task 1.12 is presently written as an assumption this
  change has to remove.
- `deploy/reachability/reachability-check.sh` posts to `api.telegram.org` directly, so the
  check that exists to detect an outage from outside the failure domain is itself carried by
  the path the outage removes.

And the relay is a path whose ordinary exercise cannot be taken on trust. The home router
intercepts DNS: `gatewayapi.telegram.org` resolves to `198.18.13.246` on the wired link, an
address belonging to the router's own proxy. So on the wired link the direct route answers,
through a substitution this repository does not control, and the relay can be dead for months
without a symptom — until the day the wire drops, which is the day it is needed. This project
has been bitten by exactly that shape twice, and `reach-the-gateway-on-any-uplink` was written
against it.

## What Changes

- **Every Telegram call the gateway makes goes through the relay first**, with the direct
  route as fallback — the ordering `app/alerting.py` already implements and which becomes
  normative rather than incidental. The callers that bypass it are brought in.
- **The relay carries the Gateway API as well as the Bot API.** They are separate hostnames
  with separate credentials, and the relay admits each explicitly rather than becoming a
  general forwarder.
- **The relay is exercised on a schedule, by real address**, so its death is discovered by a
  probe and not by an outage. A name resolved at the house cannot be part of that probe.
- **An alert is not silently dropped when it cannot be addressed.** `sms-gate-alert` answers
  `no alert credentials` and exits zero — observed three times on 19–20 August 2026, each
  time losing the alert it was given. Missing credentials are a fault of the gateway's
  configuration, and a fault that hides alerts must be reported as loudly as the alerts it
  ate.

## Non-goals

- **No route for Telegram's ranges into the tunnel, and no masquerade on the far end.** That
  was the shape this change started as. It was withdrawn on evidence: the far end does not
  masquerade the tunnel subnet (from the far end, `src 10.66.66.2` completes TLS to Telegram
  in 0.13 s while `src 10.67.67.1` times out at 12 s), so it would need a new NAT rule opening
  the whole subnet outward, where the relay already achieves the same thing for one protocol,
  for one caller, with `access_log off` and an allow-list, in a file this repository versions.
- **The tunnel's `AllowedIPs` stays as narrow as it is.** `reach-the-gateway-on-any-uplink`
  task 1.8 set it to the far end alone, deliberately: a wider one would send the uplink
  watchdog's own probes through the tunnel and make failover a decision about the tunnel
  rather than about the wire. This change does not touch it.
- **Nothing here fixes the carrier.** Telegram remains unreachable over `wwan0` directly, and
  the direct route remains the fallback it is today.

## Capabilities

### New Capabilities

- `outbound-reachability`: the gateway reaching the services it depends on, over whichever
  uplink is carrying traffic — which route is tried in what order, which vendors the relay
  admits, how the relay is proved alive, and what happens to a message that no route could
  carry.

## Impact

- `app/telegram_poll.py` — takes its base from configuration instead of a constant.
- `app/alerting.py` — its route ordering becomes specified; no behavioural change expected.
- `deploy/nginx/edge-alert-relay.conf` — a second vendor hostname.
- `deploy/reachability/reachability-check.sh` — goes through the relay.
- `deploy/alert-send.sh` — missing credentials stop being a silent exit.
- `openspec/changes/route-sends-by-operator/tasks.md` task 1.12 — its assumption is removed
  rather than carried; the rung becomes uplink-independent.

## Depends on

- The tunnel from `reach-the-gateway-on-any-uplink`, which is deployed and whose watchdog is
  running. That change is not yet archived, so `inbound-reachability` is not in the live spec;
  this change adds a capability of its own rather than modifying one that does not exist yet.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
# Tasks

## 1. Establish what is true before changing anything

- [ ] 1.1 Read the Telegram Gateway API reference for **where the credential travels** —
      path or header — and record the answer here with the reference's own wording. The
      relay clause and the `access_log` argument both depend on it, and the captures in
      `route-sends-by-operator/captures/` are responses: they do not show the request. ⚠️ Not
      to be inferred from the Bot API's shape
- [ ] 1.2 Establish whether the relay is actually in use on the production host: whether
      `ALERT_RELAY_BASE` is set in `/opt/sms-gate/.env` and whether `alert_relay_base` is set
      in the gateway's own settings. **Needs the owner's `sudo`** — the file is `0600 smsgate`.
      A working relay and a used relay are different claims, and only the first is measured
      (401 from Telegram in 0.21 s through the tunnel, 2026-09-18)
- [ ] 1.3 Identify what raised the three `no alert credentials` alerts of 19–20 August 2026
      (`cf-ddns` text, no matching systemd unit found) and whether it runs as a user that can
      read the env file. The answer decides whether 5.1 is the whole fix or half of it
- [ ] 1.4 Read the far end's firewall for which ports the tunnel address admits, and confirm
      the path-prefix decision in `design.md` is the cheap one. Needs `sudo` on the far end;
      note that `10.67.67.1:8080` already listens, so the "22, 80 and 443 only" comment in
      `deploy/nginx/edge-alert-relay.conf` may be stale

## 2. The relay carries the Gateway API

- [ ] 2.1 Add the Gateway API to `deploy/nginx/edge-alert-relay.conf` under a path prefix the
      relay strips, leaving `location /` and every existing caller untouched
- [ ] 2.2 Carry the `allow`/`deny` and `access_log off` decisions onto the new clause, with
      the reason written from 1.1 rather than copied from the Bot API's
- [ ] 2.3 Update the file's header comment: it says the relay forwards "Bot API calls", which
      stops being the whole truth here, and its "ports 22, 80 and 443" line is the one 1.4 may
      contradict
- [ ] 2.4 **Owner-run:** deploy the relay change on the far end and reload nginx. Short lines,
      no `&&`. Verify from the house that `/` still answers 401 from Telegram and that the new
      prefix reaches the Gateway API

## 3. No caller holds a vendor address of its own

- [ ] 3.1 Failing test first: `app/telegram_poll.py` calls the configured base, not
      `api.telegram.org`. Today `_API` is a module constant, so the test pins the behaviour
      that does not exist yet
- [ ] 3.2 Make `telegram_poll` take its base from the same setting `alerting` reads, direct
      route as fallback, and keep `getUpdates` long-poll semantics intact through the relay —
      the relay's `proxy_read_timeout` must outlast the poll timeout or long polling becomes a
      502 every cycle
- [ ] 3.3 Failing test first, then fix: `deploy/reachability/reachability-check.sh` goes
      through the relay. ⚠️ This is the check that watches from outside the failure domain;
      confirm it still fails when the gateway is genuinely unreachable, or it becomes a check
      that only proves the relay
- [ ] 3.4 Test that pins `app/alerting.py`'s existing order — relay first, direct as fallback
      — so the ordering stops being incidental. No behaviour change expected
- [ ] 3.5 Sweep for any remaining literal vendor address in `app/` and `deploy/`, and either
      route it or record why it stays direct

## 4. The relay is proved before it is needed

- [ ] 4.1 A scheduled probe from the house that calls the relay with a deliberately invalid
      token and requires an answer **from the vendor** (401) rather than from the relay's
      nginx (502). No name is resolved at the house; no message is sent
- [ ] 4.2 Failure raises an operator alert, once per outage, through the ordinary alert path
- [ ] 4.3 Test the probe against both shapes: vendor-answered 401 passes, nginx-produced 502
      fails. A probe that cannot tell them apart is the failure this requirement exists for

## 5. A fault in the alerting is not reported as a delivered alert

- [ ] 5.1 Failing test first: `deploy/alert-send.sh` exits non-zero when it has no token or no
      chat, instead of logging the alert text and exiting zero
- [ ] 5.2 The units that call it treat that exit as a failure the operator can see, by the
      `OnFailure=` pattern already used in `deploy/sms-gate.service`
- [ ] 5.3 Confirm the spool is untouched by this path: missing credentials mean nobody to
      deliver to, so the alert is not held — the bounded spool exists for the other case

## 6. Verification

- [ ] 6.1 Full test suite green. ⚠️ Memory records the suite as red from two causes, one of
      them a missing venv in worktrees — establish the baseline **before** the first edit, or
      a pre-existing failure will be read as this change's
- [ ] 6.2 Conformance sweep: each SHALL in `specs/outbound-reachability/spec.md` against the
      code that implements it, before archiving
- [ ] 6.3 Prove the relay path end to end on the backup uplink **without dropping the wire** —
      bind the probe to `wwan0` and reach the far end by address (measured reachable:
      404 in 0.28 s to `178.250.157.233` over `wwan0`, 2026-09-18). Production carries live
      customer traffic; the wire is not a test instrument

## 7. Neighbouring change

- [ ] 7.1 Rewrite task 1.12 of `route-sends-by-operator`: its premise "the gateway's own
      Telegram alerting is dead in the same window" is contradicted by the working relay, and
      the `tg_gateway` rung stops being unavailable during a wired outage once 2.x lands. ⚠️
      That task is another change's obligation not to assume — correct it, do not delete it
- [ ] 7.2 Supersede the project memory `telegram-is-blocked-on-the-backup-uplink`: what the
      carrier blocks is still true, that the gateway has no way around it is not. Supersede,
      do not erase — the lesson is the correction
<!-- SECTION:NOTES:END -->
