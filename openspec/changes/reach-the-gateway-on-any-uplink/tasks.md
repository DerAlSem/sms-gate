## 1. Establish the facts the cutover depends on

- [ ] 1.1 Confirm the tunnel's credentials still authenticate and the tunnel is known to the account, before anything is pointed at it
- [ ] 1.2 Check whether anything reads `X-Real-IP` — application, logs, alerting — since nginx stops setting it for this hostname
- [ ] 1.3 Decide the ingress target: straight to `127.0.0.1:30080` as configured, or through nginx to keep one serving path; record the reason either way
- [ ] 1.4 Confirm the neighbouring hostname on the shared renewal timer and what its challenge depends on

## 2. Run the connector under supervision

- [ ] 2.1 Add a systemd unit for the connector, with automatic restart
- [ ] 2.2 Make repeated failure to stay up reach the operator, not only the journal — this is the component whose silent death this change would otherwise introduce
- [ ] 2.3 Start it and confirm it registers, with the hostname still resolving to the direct path — the tunnel proven before it carries anything
- [ ] 2.4 Verify: reach the service through the tunnel's own hostname while the public record still points elsewhere

## 3. Administrative access through the tunnel

- [ ] 3.1 Add the `ssh://` ingress
- [ ] 3.2 Gate it with an access policy, and verify a request without it is refused — an ungated SSH ingress trades an outage for an exposure
- [ ] 3.3 Set up and document the client side, since non-HTTP services need the connector on the client too; the old command does not keep working
- [ ] 3.4 Test: reach the host over the tunnelled route while the wired link is up

## 4. Certificate renewal, before it can break

- [ ] 4.1 Move renewal off the challenge the tunnel takes away, by whichever shape can be demonstrated
- [ ] 4.2 Force a renewal and confirm it succeeds — proved, not assumed
- [ ] 4.3 Confirm the neighbouring hostname still renews
- [ ] 4.4 Confirm the renewal survives the cutover too, by re-running it after step 5

## 5. The cutover

- [ ] 5.1 Write down the rollback command and confirm the direct path can still serve before removing it from duty
- [ ] 5.2 Point the hostname at the tunnel: proxied `CNAME` to `<tunnel-id>.cfargotunnel.com`
- [ ] 5.3 Verify from outside: the service answers and the request arrives via the edge
- [ ] 5.4 Verify the gateway's own outbound duties are unaffected — delivery webhooks still reach their destination
- [ ] 5.5 Confirm nothing that calls this gateway pins an address rather than a hostname

## 6. Prove it under the failure it exists for

- [ ] 6.1 Live: pull the wired link, and confirm the hostname keeps answering once failover completes
- [ ] 6.2 Live: measure the unreachable window across that failover, and record the figure in the spec rather than an estimate
- [ ] 6.3 Live: confirm administrative access works while the wired link is down — the half of the remedy that is easy to leave untested
- [ ] 6.4 Live: restore the wired link and confirm traffic returns without anything being switched by hand
- [ ] 6.5 Live: kill the connector and confirm it restarts and the operator hears about it

## 7. Ship

- [ ] 7.1 Document the topology, the rollback, and the client-side setup for administrative access
- [ ] 7.2 Record the accepted privacy cost where an operator will meet it, not only in the change
- [ ] 7.3 Archive so the `inbound-reachability` requirements land in `openspec/specs/`
