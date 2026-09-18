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
