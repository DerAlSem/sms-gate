## 1. Establish what the cutover depends on

- [x] 1.1 Confirm nothing that calls this gateway pins an address rather than a hostname — a precondition, not a check to run afterwards, since discovering it later means discovering it broken
      <!-- GM+ calls the API by hostname. The move is transparent to it. -->
- [x] 1.2 Establish whether the hostnames on the home server share one certificate or hold separate ones; this decides whether one broken renewal can take a neighbour with it
      <!-- Separate. Read off the wire: sms.deralsem.ru is CN=sms.deralsem.ru with itself as
           its only SAN, valid to 2026-09-14. No shared lineage, so one broken renewal cannot
           take the other with it. -->
- [x] 1.3 Record what `mprz.ru` already serves on port 443, so the addition can be confirmed additive rather than assumed to be
      <!-- Eleven hostnames: gmplus.ru + demo/parking, propevay.ru, romantsova.store,
           turbo01.ru, hrm/signage/turbo.mprz.ru, mprz.ru, and a default. All `listen 443 ssl`
           in the HTTP context, certificates issued there already. -->
- [x] 1.9 Establish how the house validates its certificate, before assuming the tunnel breaks it
      <!-- `authenticator = dns-cloudflare`. Validated over DNS, never over an inbound
           challenge — so the premise that moving the hostname breaks renewal was wrong, and
           the work it implied is withdrawn. Consequence worth keeping: the fallback path
           cannot expire out from under itself.
           Separate, pre-existing, not ours: the credential that enables this can edit the zone
           that decides where the hostname points. -->
- [x] 1.10 Clear the renewal failure that predates this change, so that a red timer afterwards means something
      <!-- `nas.deralsem.ru` resolves elsewhere now; its renewal config is disabled, a dry run
           passes for the remaining hostname, and the unit's failed state is cleared. -->
- [x] 1.4 Note that nothing in the gateway reads `X-Real-IP`, `X-Forwarded-For` or the client address — verified during review, so the header rename is not a migration; what is missing is recording the address at all, which is task 5
- [x] 1.6 Establish what the existing WireGuard on `mprz.ru` already carries — so the house is
      added without colliding with an addressing plan this change did not write
      <!-- `wg0` is not a hub of ours: mprz is a *client* on it, and its allowed ips are
           Telegram's ranges (149.154.160.0/20, 91.108.4.0/22) via a foreign endpoint — it is
           how the bots reach Telegram. Not to be touched.
           `wg-burns` is ours, mprz is the server at 10.67.67.1/24, one peer at 10.67.67.2/32.
           The house joins there as a second peer. -->
- [x] 1.8 The house's own `AllowedIPs` must name only the far end, not a default route. The
      usual `0.0.0.0/0` would send everything the house emits through `mprz.ru`, including the
      gateway's outbound webhooks and the probes the uplink watchdog uses to decide whether
      the wired link is alive — which would make failover a decision about the tunnel rather
      than about the link. The far end's side already follows the convention this needs, with
      its existing peer confined to a single address
      <!-- Done: `AllowedIPs = 10.67.67.1/32`, verified in the running interface. -->
- [x] 1.7 Check whether `mprz.ru` routes by SNI already; the decision to terminate TLS rather
      than pass it through was argued from its port 443 being ordinary HTTP, and that argument
      should rest on the file rather than on the listener
      <!-- It does not — there is no stream section at all. The earlier reading came from the
           word inside `upstream`. The argument stands, now on the files. -->

## 2. The tunnel, constrained at both ends

- [x] 2.1 Bring up the tunnel between the house and `mprz.ru`
      <!-- The house joins the estate's existing hub as a second peer on 10.67.67.3/32, added
           live with `wg set` so the peer already on it kept its session. Its own AllowedIPs
           name only the far end, never a default route. -->
- [x] 2.2 Constrain what each end may reach to the published service only, and verify from `mprz.ru` that nothing else on the home network answers — the difference between a published service and a joined network is one line of configuration
      <!-- `AllowedIPs` alone did nothing for this: it constrains routing, not access, and the
           tunnel simply gives the host another address on which everything bound to 0.0.0.0
           answers. Twenty-odd services did, including file sharing and the gateway's own port.
           Closed with a filter on the interface rather than by binding services, so a service
           added tomorrow is not exposed by default.
           The part that would have been missed: half those ports are Docker containers reached
           by DNAT, so they arrive on the *forward* path and an input chain alone would have
           left them open while the check appeared to pass. -->
- [x] 2.5 Password authentication over the tunnel: reachable now from a machine hosting eleven public applications, so a compromise there becomes a brute-force attempt against the house over a private channel nobody watches
      <!-- Refused for the tunnel's addresses only, so the local network keeps what it had.
           Written at the end of the main configuration rather than into the include
           directory: the include is processed near the top, and a Match block runs to the end
           of the file, so it would have captured every global setting below it. Verified both
           ways before reloading, and verified refused from the far end afterwards. -->
- [x] 2.3 Run it as a unit, enabled, ordered so it comes up after the network and does not depend on the primary uplink specifically
- [x] 2.4 Verify exactly one instance is carrying the tunnel, so a manual test run cannot survive the cutover and compete with the unit

## 3. Supervision that tests traffic, and an alert that can fire

- [x] 3.1 Supervise on the path being established, not on the process being alive — the failure that has cost this project two changes is "alive and moving nothing"
- [x] 3.2 Give the unit an explicit restart bound and an `OnFailure=` handler following the pattern already in `deploy/sms-gate.service`; without a bound the unit restarts for ever, never enters failure, and the alert never fires
      <!-- Solved, but not by that pattern, and the departure is deliberate. `OnFailure=` fires
           on a unit entering failure, which a timer-driven probe never does — it exits
           non-zero once per silent check and systemd has no way to tell a two-minute failover
           from a fault a restart cannot fix. The bound therefore lives in the probe, which
           does know: restart after two silent checks, speak after two fruitless restarts. -->
- [x] 3.3 Record why the bound is the number it is, as its neighbour does
- [ ] 3.4 Test: drop the path once — it is re-established and no alert is raised
      <!-- Exercised against a substitute address and unit, which proves the state machine but
           not the restart. Owed live, and deliberately deferred to the live session in group 9
           rather than dropping the network twice. -->
- [x] 3.5 Test: make it fail persistently (invalid key material) — the bound is reached and the operator is alerted
- [ ] 3.6 Ensure an alert raised while nothing can carry it is retained and delivered later, and that the connector and the uplink cannot suppress each other's messages through the shared throttle

## 4. Watching from outside the failure domain

- [x] 4.1 Add a check of the public hostname from outside the house that asserts the gateway served the response, not merely that the name answered
- [x] 4.2 Route its alert somewhere that does not depend on the gateway being reachable
- [x] 4.3 Test: stop the far end serving the hostname while the gateway is healthy, and confirm the operator is told
      <!-- Triggered by pointing the probe at a path the gateway does not serve rather than by
           breaking the live front end, so what is proven is detection and delivery — one alert
           on the third failure, none before. The branch that matters most, a 200 carrying
           somebody else's body, was exercised separately against a neighbouring site. -->

## 5. The gateway records where requests come from

- [x] 5.1 Record the originating address from the forwarding header on every request; the connection the gateway sees is the tunnel's
      <!-- Through uvicorn's own proxy-header handling rather than a middleware of ours: the
           access log is the audit trail either way, and code written to duplicate it would
           only be more to test. Trusted from the loopback alone, which the bind below makes
           the only place it can arrive from. -->
- [x] 5.2 Bind uvicorn to the loopback — it listens on all interfaces today, so the application is reachable from the home network regardless of any of this
- [ ] 5.3 Test: a request through the tunnel is logged with the caller's address, not the tunnel's

## 6. Serving the hostname from the far end

- [x] 6.1 Add a server block for the hostname on `mprz.ru`, beside the existing ones rather than reworking its entry point, proxying over the tunnel to the home nginx
- [x] 6.0 Serve the hostname on the house's tunnel address, so the far end has something to proxy to
      <!-- A block bound to 10.67.67.3:80 specifically, not to every address: the existing
           block redirects to https, and a wildcard listener would have caught the proxied
           request and answered it with a redirect loop. nginx prefers the more specific
           address, so the two coexist.
           The filter opened port 80 to the far end only; everything else stayed shut,
           verified again after reloading the table. -->
- [ ] 6.2 Issue its certificate there and confirm renewal works — bridged for now with the
      house's own certificate, valid to 2026-09-14, so the cutover needs no window in which the
      hostname answers with the wrong certificate. Issued properly at the far end after the
      record moves, when the challenge can reach it. Do not assume the challenge works: verify
      it, since plain HTTP by hostname is demonstrably filtered on at least one path into this
      machine — routine on a machine already renewing eleven, but its renewal is shared with them, so a break here is a break for somebody else's site
- [x] 6.3 Verify the neighbouring services on `mprz.ru` are unaffected
- [x] 6.4 Verify through the tunnel, with the public record still pointing at the house — the new path proven before it carries anything

## 7. Administrative access

- [x] 7.1 Publish administrative access over the tunnel
- [x] 7.2 Restrict it before publishing it, not after — an unrestricted route on a machine that hosts everything is open for as long as the gap between the two steps
      <!-- Not honoured in that order, and worth recording rather than glossing: the port was
           opened first and passwords refused about half an hour later, so the gap this task
           warns about is exactly what happened. The risk was low — the far end is ours and
           the account is key-holding — but the task existed to prevent the ordering, and the
           ordering is what went wrong. -->
- [x] 7.3 Test: reach the host over the tunnelled route while the wired link is up
- [ ] 7.4 Document the client-side setup, since the existing command does not keep working

## 8. Cutover

- [ ] 8.1 Confirm the direct path can still serve, and write down the rollback action, before the record moves
- [ ] 8.2 Point `sms.deralsem.ru` at `mprz.ru`
- [ ] 8.3 Verify from outside that the gateway itself serves the response
- [ ] 8.4 Verify by a real call from GM+, not only by hand — a hand-made request does not reproduce what the caller does
- [ ] 8.5 Verify the gateway's outbound duties are unaffected: delivery webhooks still arrive
- [ ] 8.6 Confirm the home server's own renewal still works for its remaining hostnames

## 9. Prove it under the failure it exists for

- [ ] 9.1 Live: pull the wired link, confirm the hostname is still served by the gateway once failover completes
- [ ] 9.2 Live: measure the re-establishment time from when the backup carries traffic, and record the figure in the spec
- [ ] 9.3 Live: check how the source-routing rule in `wwan-backup.sh` affects the tunnel's sockets across a failover, and decide what remains of that rule's inbound purpose once the direct path is retired
- [ ] 9.4 Live: confirm administrative access works while the wired link is down — the half of the remedy easiest to leave untested
- [ ] 9.5 Live: restore the wired link, confirm traffic returns with nothing switched by hand
- [ ] 9.6 Live: restart the host and confirm the path returns
- [ ] 9.7 Live: restart the host *while the wired link is down* and confirm the path comes up over the backup — the case that will actually happen

## 10. Soak, then retire the direct path

- [ ] 10.1 Run on the tunnel for a soak period covering at least one real uplink failure
- [ ] 10.2 Re-check that the direct path can still serve, so rollback stays real for as long as it is claimed
- [ ] 10.3 Bind the hostname's home server block to the tunnel address, so it is no longer served over the public one
- [ ] 10.4 Verify a request to the house's address with this hostname is no longer served
- [ ] 10.5 Verify `nas.deralsem.ru` still serves and still renews — retirement by binding rather than by firewall exists precisely so this holds
- [ ] 10.6 Record that rollback is now two steps, and that it is not an emergency remedy

## 11. Ship

- [ ] 11.1 Document the topology, both machines' parts in it, and the rollback
- [ ] 11.2 Archive so the `inbound-reachability` requirements land in `openspec/specs/`
