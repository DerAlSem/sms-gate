## 1. Establish what the cutover depends on

- [ ] 1.1 Confirm nothing that calls this gateway pins an address rather than a hostname — a precondition, not a check to run afterwards, since discovering it later means discovering it broken
- [x] 1.2 Establish whether the hostnames on the home server share one certificate or hold separate ones; this decides whether one broken renewal can take a neighbour with it
      <!-- Separate. Read off the wire: sms.deralsem.ru is CN=sms.deralsem.ru with itself as
           its only SAN, valid to 2026-09-14. No shared lineage, so one broken renewal cannot
           take the other with it. -->
- [ ] 1.3 Record what `mprz.ru` already serves on port 443, so the addition can be confirmed additive rather than assumed to be
- [x] 1.4 Note that nothing in the gateway reads `X-Real-IP`, `X-Forwarded-For` or the client address — verified during review, so the header rename is not a migration; what is missing is recording the address at all, which is task 5
- [ ] 1.5 **Renewal on the home server is already failing, before this change touches anything.**
      `nas.deralsem.ru` no longer resolves to the house — it points at a third machine — so its
      challenge is delivered elsewhere and `certbot.service` exits in failure on every run.
      This matters here because the same failure is what moving `sms.deralsem.ru` would
      produce: a new breakage would be indistinguishable from the existing red, and would be
      read as pre-existing. Clear it first, so that after the cutover a failing timer means
      something
- [ ] 1.6 Establish what the existing WireGuard on `mprz.ru` already carries — it runs `wg0`
      (10.66.66.2/24, as a client of something else) and `wg-burns` (10.67.67.1/24, as the
      server) — so the house is added without colliding with an addressing plan this change
      did not write
- [ ] 1.7 Read the `stream` block already present in `mprz.ru`'s `nginx.conf`; the decision to
      terminate TLS rather than pass it through was argued from its port 443 being ordinary
      HTTP, and that argument should rest on the file rather than on the listener

## 2. The tunnel, constrained at both ends

- [ ] 2.1 Bring up the tunnel between the house and `mprz.ru`
- [ ] 2.2 Constrain what each end may reach to the published service only, and verify from `mprz.ru` that nothing else on the home network answers — the difference between a published service and a joined network is one line of configuration
- [ ] 2.3 Run it as a unit, enabled, ordered so it comes up after the network and does not depend on the primary uplink specifically
- [ ] 2.4 Verify exactly one instance is carrying the tunnel, so a manual test run cannot survive the cutover and compete with the unit

## 3. Supervision that tests traffic, and an alert that can fire

- [ ] 3.1 Supervise on the path being established, not on the process being alive — the failure that has cost this project two changes is "alive and moving nothing"
- [ ] 3.2 Give the unit an explicit restart bound and an `OnFailure=` handler following the pattern already in `deploy/sms-gate.service`; without a bound the unit restarts for ever, never enters failure, and the alert never fires
- [ ] 3.3 Record why the bound is the number it is, as its neighbour does
- [ ] 3.4 Test: drop the path once — it is re-established and no alert is raised
- [ ] 3.5 Test: make it fail persistently (invalid key material) — the bound is reached and the operator is alerted
- [ ] 3.6 Ensure an alert raised while nothing can carry it is retained and delivered later, and that the connector and the uplink cannot suppress each other's messages through the shared throttle

## 4. Watching from outside the failure domain

- [ ] 4.1 Add a check of the public hostname from outside the house that asserts the gateway served the response, not merely that the name answered
- [ ] 4.2 Route its alert somewhere that does not depend on the gateway being reachable
- [ ] 4.3 Test: stop the far end serving the hostname while the gateway is healthy, and confirm the operator is told

## 5. The gateway records where requests come from

- [ ] 5.1 Record the originating address from the forwarding header on every request; the connection the gateway sees is the tunnel's
- [ ] 5.2 Bind uvicorn to the loopback — it listens on all interfaces today, so the application is reachable from the home network regardless of any of this
- [ ] 5.3 Test: a request through the tunnel is logged with the caller's address, not the tunnel's

## 6. Serving the hostname from the far end

- [ ] 6.1 Add a server block for the hostname on `mprz.ru`, beside the existing ones rather than reworking its entry point, proxying over the tunnel to the home nginx
- [ ] 6.2 Issue its certificate there and confirm renewal works
- [ ] 6.3 Verify the neighbouring services on `mprz.ru` are unaffected
- [ ] 6.4 Verify through the tunnel, with the public record still pointing at the house — the new path proven before it carries anything

## 7. Administrative access

- [ ] 7.1 Publish administrative access over the tunnel
- [ ] 7.2 Restrict it before publishing it, not after — an unrestricted route on a machine that hosts everything is open for as long as the gap between the two steps
- [ ] 7.3 Test: reach the host over the tunnelled route while the wired link is up
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
