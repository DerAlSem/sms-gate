## 1. Establish what the cutover depends on

- [x] 1.1 Confirm nothing that calls this gateway pins an address rather than a hostname — a precondition, not a check to run afterwards, since discovering it later means discovering it broken
      <!-- The caller calls the API by hostname. The move is transparent to it. -->
- [x] 1.2 Establish whether the hostnames on the home server share one certificate or hold separate ones; this decides whether one broken renewal can take a neighbour with it
      <!-- Separate. Read off the wire: gateway.example.com is CN=gateway.example.com with itself as
           its only SAN, valid to 2026-09-14. No shared lineage, so one broken renewal cannot
           take the other with it. -->
- [x] 1.3 Record what `edge.example.com` already serves on port 443, so the addition can be confirmed additive rather than assumed to be
      <!-- Eleven hostnames: app.example.net + demo/parking, another.example.net, third.example.net,
           fourth.example.net, hrm/signage/turbo.edge.example.com, edge.example.com, and a default. All `listen 443 ssl`
           in the HTTP context, certificates issued there already. -->
- [x] 1.9 Establish how the house validates its certificate, before assuming the tunnel breaks it
      <!-- `authenticator = dns-cloudflare`. Validated over DNS, never over an inbound
           challenge — so the premise that moving the hostname breaks renewal was wrong, and
           the work it implied is withdrawn. Consequence worth keeping: the fallback path
           cannot expire out from under itself.
           Separate, pre-existing, not ours: the credential that enables this can edit the zone
           that decides where the hostname points. -->
- [x] 1.10 Clear the renewal failure that predates this change, so that a red timer afterwards means something
      <!-- `neighbour.example.com` resolves elsewhere now; its renewal config is disabled, a dry run
           passes for the remaining hostname, and the unit's failed state is cleared. -->
- [x] 1.4 Note that nothing in the gateway reads `X-Real-IP`, `X-Forwarded-For` or the client address — verified during review, so the header rename is not a migration; what is missing is recording the address at all, which is task 5
- [x] 1.6 Establish what the existing WireGuard on `edge.example.com` already carries — so the house is
      added without colliding with an addressing plan this change did not write
      <!-- `wg0` is not a hub of ours: mprz is a *client* on it, and its allowed ips are
           Telegram's ranges (149.154.160.0/20, 91.108.4.0/22) via a foreign endpoint — it is
           how the bots reach Telegram. Not to be touched.
           `wg-edge` is ours, mprz is the server at 10.10.10.1/24, one peer at 10.10.10.2/32.
           The house joins there as a second peer. -->
- [x] 1.8 The house's own `AllowedIPs` must name only the far end, not a default route. The
      usual `0.0.0.0/0` would send everything the house emits through `edge.example.com`, including the
      gateway's outbound webhooks and the probes the uplink watchdog uses to decide whether
      the wired link is alive — which would make failover a decision about the tunnel rather
      than about the link. The far end's side already follows the convention this needs, with
      its existing peer confined to a single address
      <!-- Done: `AllowedIPs = 10.10.10.1/32`, verified in the running interface. -->
- [x] 1.7 Check whether `edge.example.com` routes by SNI already; the decision to terminate TLS rather
      than pass it through was argued from its port 443 being ordinary HTTP, and that argument
      should rest on the file rather than on the listener
      <!-- It does not — there is no stream section at all. The earlier reading came from the
           word inside `upstream`. The argument stands, now on the files. -->

## 2. The tunnel, constrained at both ends

- [x] 2.1 Bring up the tunnel between the house and `edge.example.com`
      <!-- The house joins the estate's existing hub as a second peer on 10.10.10.3/32, added
           live with `wg set` so the peer already on it kept its session. Its own AllowedIPs
           name only the far end, never a default route. -->
- [x] 2.2 Constrain what each end may reach to the published service only, and verify from `edge.example.com` that nothing else on the home network answers — the difference between a published service and a joined network is one line of configuration
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
- [x] 3.4 Test: drop the path once — it is re-established and no alert is raised
      <!-- Done live, and it handed over the premise of the requirement as evidence: with the
           interface deleted, `systemctl is-active` still answered `active`. Supervision on
           liveness would have seen health. Two silent checks, one restart, carrying again
           after two minutes, and nothing said to the operator — a repair that worked is not
           an incident. The filter came back with the interface, which is why it hangs off the
           interface rather than off boot. -->
- [x] 3.5 Test: make it fail persistently (invalid key material) — the bound is reached and the operator is alerted
- [ ] 3.7 Write down the coupling 9.7 exposed, and decide whether to enforce it. On a cold
      start with the uplink already dead, the tunnel comes up only because `wg-quick` blocks
      retrying name resolution until failover switches DNS — measured at 143 seconds of
      retrying against a resolution that succeeded 10 seconds after failover. The deadline it
      is racing is `OnBootSec=90` plus two 30-second intervals, so 150 seconds is the earliest
      a failover can occur by construction. Neither number knows about the other, the retry
      budget is not ours and is not documented, and the margin between them is ten seconds.
      Raise the first check, lengthen the threshold, or meet a build of `wg` that gives up
      sooner, and the unit fails instead of waiting: recovery then falls to the tunnel
      watchdog and costs minutes rather than seconds. Either make the boot path not depend on
      the margin, or state the margin as a constraint that a change to either number must
      respect
- [ ] 3.6 Ensure an alert raised while nothing can carry it is retained and delivered later, and that the connector and the uplink cannot suppress each other's messages through the shared throttle
      <!-- Solved at the root rather than as retention alone, once the owner pointed out that
           the far end already reaches Telegram: the house now sends through a relay there,
           over the tunnel, which works on either uplink. Retention stays as the second half,
           for the case where neither route answers — held on disk, bounded, flushed when a
           route returns, and stamped with its age, because a late alert read without one is
           read as current and sends the operator after a fault that has ended.
           Retention also fixed a defect it uncovered: a non-200 used to return `None`, which
           the caller reads as "delivered, no id", so a rejected token lost every alert in
           silence.
           The shared throttle cannot collide: the two watchdogs keep their own state and do
           not go through the unit notifier.
           Verified end to end: the alert appeared in the far end's access log arriving from
           the house and in the operator's chat one second apart. That same log line was the
           finding — the Bot API carries the token in the path, so every alert was writing a
           live credential into a web server log on the busiest machine, to survive there in
           rotation and in backups. Logging is off for that block now. -->
      <!-- No longer a theoretical gap. Observed on 2026-07-30: the failover alert could not be
           delivered — `api.telegram.org` is unreachable over the mobile carrier, and the
           uplink script said so in its own log — while the restore alert eight minutes later
           arrived normally. So the operator is told the outage has ended and never that it
           began, which is the worst available shape: the one message that matters is the one
           that is lost.
           Every alert raised on the house shares this, the tunnel watchdog included. The
           reachability check does not, because it runs at the far end and reaches Telegram by
           a path of its own — which is a stronger argument for having built it than the one
           originally given. -->
      <!-- Reopened 2026-08-01. It was ticked on the strength of the relay existing, and the
           relay does exist and does work — but it was only wired into `notify-telegram.sh`
           and `wg-tunnel-check.sh`. The uplink script, which raises the failover alert that
           started all of this, still posted straight to `api.telegram.org`.
           Proven twice the same morning, by the restart tests rather than by inspection:
           `alert: Telegram unreachable after 3 attempts` at 07:30:27 and again at 07:38:22,
           both while the backup was carrying — and both RESTORE alerts delivered silently
           once the wire was back. Exactly the shape this task calls the worst available: the
           operator is told the outage ended and never that it began.
           What the tick actually recorded was that the mechanism had been built, not that
           every raiser used it. A task that says "ensure an alert is delivered" is not closed
           by the existence of a route — only by every sender taking it.
           `alert()` in `wwan-backup.sh` now tries the relay first and the direct route as
           fallback, retries covering both, matching the two scripts that were already
           correct. Retries matter more here than there: the alert is raised at the instant
           the route changes, before WireGuard has handshaked from the new source address.
           Relay half verified live 2026-08-01 10:16, and verified as a claim about routes
           rather than about delivery: Telegram's own ranges were blackholed for the duration,
           so the direct route could not have carried it. The message arrived and the journal
           recorded no failure — with the only remaining route being the relay.
           Still open, and stated precisely this time so it cannot be ticked by generosity
           again: retention is implemented in `app/alerting.py`, which is the gateway's own
           alerts. All three shell raisers — the uplink script, the tunnel watchdog and the
           unit notifier — have the relay and the fallback but no spool, so an alert raised
           while *neither* route answers is logged and dropped. That is the case this task
           names, and for those three it is still true.
           Partly compensated, and worth knowing rather than assuming: the outside
           reachability check raised and delivered both of its alerts during the cold-boot
           test — unreachable at 07:37, reachable again at 07:38 — because it runs at the far
           end and never depended on the house having a route. During the window when the
           house can carry nothing, that check is the only thing that still speaks. -->

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
      <!-- In effect now, after the installed unit was replaced by hand. It is a *copy*, not a
           link to the file in the repository, so a deploy left the unit systemd reads
           untouched and `daemon-reload` faithfully re-read the old one. The same zero-effect
           deploy happened three times in one session — this unit, and both nginx blocks. See
           11.0: three misses in a day is a property of the process, not inattention. -->
- [x] 5.3 Test: a request through the tunnel is logged with the caller's address, not the tunnel's
      <!-- Caught the first version being wrong: the house appended to the header rather than
           passing it through, and uvicorn reads the last entry, so the log carried the far
           end's tunnel address — identical on every request. A log that looks populated and
           says nothing is worse than an empty one, because nobody goes looking. -->

## 6. Serving the hostname from the far end

- [x] 6.1 Add a server block for the hostname on `edge.example.com`, beside the existing ones rather than reworking its entry point, proxying over the tunnel to the home nginx
- [x] 6.0 Serve the hostname on the house's tunnel address, so the far end has something to proxy to
      <!-- A block bound to 10.10.10.3:80 specifically, not to every address: the existing
           block redirects to https, and a wildcard listener would have caught the proxied
           request and answered it with a redirect loop. nginx prefers the more specific
           address, so the two coexist.
           The filter opened port 80 to the far end only; everything else stayed shut,
           verified again after reloading the table. -->
- [x] 6.2 Issue its certificate there and confirm renewal works — bridged for now with the
      house's own certificate, valid to 2026-09-14, so the cutover needs no window in which the
      hostname answers with the wrong certificate. Issued properly at the far end after the
      record moves, when the challenge can reach it. Do not assume the challenge works: verify
      it, since plain HTTP by hostname is demonstrably filtered on at least one path into this
      machine — routine on a machine already renewing eleven, but its renewal is shared with them, so a break here is a break for somebody else's site
- [x] 6.3 Verify the neighbouring services on `edge.example.com` are unaffected
- [x] 6.4 Verify through the tunnel, with the public record still pointing at the house — the new path proven before it carries anything

## 7. Administrative access

- [x] 7.1 Publish administrative access over the tunnel
- [x] 7.2 Restrict it before publishing it, not after — an unrestricted route on a machine that hosts everything else is open for as long as the gap between the two steps
      <!-- Not honoured in that order, and worth recording rather than glossing: the port was
           opened first and passwords refused about half an hour later, so the gap this task
           warns about is exactly what happened. The risk was low — the far end is ours and
           the account is key-holding — but the task existed to prevent the ordering, and the
           ordering is what went wrong. -->
- [x] 7.3 Test: reach the host over the tunnelled route while the wired link is up
- [x] 7.4 Document the client-side setup, since the existing command does not keep working
      <!-- It turned out to be two hops rather than the client-side connector the first draft
           expected — that requirement belonged to the third-party edge and went with it. A
           ProxyJump entry makes it one command, which matters because it is needed precisely
           when nobody is in the mood to reconstruct it. -->

## 8. Cutover

- [x] 8.1 Confirm the direct path can still serve, and write down the rollback action, before the record moves
- [x] 8.2 Point `gateway.example.com` at `edge.example.com`
- [x] 8.3 Verify from outside that the gateway itself serves the response
- [x] 8.4 Verify by a real call from the real caller, not only by hand — a hand-made request does not reproduce what the caller does
      <!-- Closed by ordinary traffic rather than a staged test. The access log shows the call
           arriving from the far end's own public address: the caller resolves the hostname to the
           machine it runs on and connects to it, so the hairpin works — the one thing about
           this topology that could only be answered by the real caller.
           It also surfaced a second consumer nobody had mentioned, on a different address, so
           the cutover moved more than the one caller anybody had in mind. -->
- [x] 8.5 Verify the gateway's outbound duties are unaffected: delivery webhooks still arrive
      <!-- A message went sent → delivered with both webhooks accepted by the caller. The
           gateway's outbound path never depended on how it is reached, and now that is
           observed rather than assumed. -->
- [x] 8.6 Confirm the home server's own renewal still works for its remaining hostnames

## 9. Prove it under the failure it exists for

- [x] 9.1 Live: pull the wired link, confirm the hostname is still served by the gateway once failover completes
      <!-- Not by pulling it: the watchdog decides the wire is dead by pinging through it, so
           dropping those probes with a rule produced a real failover — the backup taking the
           preferred metric, traffic genuinely leaving over it — while inbound on the wire
           stayed as a lifeline. Safer than an outage nobody at the house could undo, and it
           exercises the same mechanism. Paired with a scheduled undo applied *before* the
           break, so losing contact could not leave it in place. -->
- [x] 9.2 Live: measure the re-establishment time from when the backup carries traffic, and record the figure in the spec
- [x] 9.3 Live: check how the source-routing rule in `wwan-backup.sh` affects the tunnel's sockets across a failover, and decide what remains of that rule's inbound purpose once the direct path is retired
      <!-- The rule was present throughout and did not pin the tunnel: it matches on the
           primary interface's source address, and WireGuard's socket is not bound to one, so
           once the routing table preferred the backup the packets left with the backup's
           address and the rule stopped matching. The worry was unfounded, which is worth as
           much as if it had been right.
           Its inbound purpose is a separate question, still open: it exists so replies to
           connections arriving on the wire go back out the wire, and that is what the direct
           path in group 10 is about. -->
- [x] 9.4 Live: confirm administrative access works while the wired link is down — the half of the remedy easiest to leave untested
- [x] 9.5 Live: restore the wired link, confirm traffic returns with nothing switched by hand
- [x] 9.6 Live: restart the host and confirm the path returns
      <!-- Returned unaided, everything back: tunnel carrying, the source-routing rule, the
           backup session up two seconds after boot, and the access log again showing distinct
           caller addresses rather than one repeated tunnel address.
           It also retired a hazard that had been argued from the files and was not real. The
           house serves the hostname on `listen 10.67.67.3:80`, an address that does not exist
           until the tunnel is up; nginx and wg-quick share `After=network-online.target` with
           no ordering between them, nginx has no `Restart=`, and `nginx -t` cannot catch it
           because it does not bind. That reads as a boot-order race that leaves the whole
           front end dead. It is not one: a neighbouring block already listens on `80` without
           an address, so nginx opens a single wildcard socket per port and dispatches the
           address-specific blocks in process. `ss` confirms only `0.0.0.0:80` is ever bound.
           Worth keeping because the reasoning was sound and the conclusion still wrong — and
           because the protection is incidental. A future change that removes the last
           wildcard `listen 80` from this host would create the race for real, silently. -->
- [x] 9.7 Live: restart the host *while the wired link is down* and confirm the path comes up over the backup — the case that will actually happen
      <!-- Passed: the path came back over the backup with no intervention, about three
           minutes after boot. Measured 2026-08-01, boot at 07:34:47 — interface created at
           14s, backup session up at 15s, first uplink check at 90s, failover at 154s, the
           endpoint finally resolved at 164s, hostname served over `wwan0` by 187s.
           Done without touching the cable, which the owner could not do easily: the wire was
           blacked out at the output hook from before the network was configured, dropping
           everything the host originates over it while letting replies to tracked inbound
           TCP through, so the operator kept a way in over the very link under test. Undone by
           a timer counted from boot, so losing contact could not strand it.
           The blackout had to drop UDP wholesale rather than exempt established flows. The
           far end still holds this host's last endpoint on the wire, so a conntrack exemption
           would have let it keep the tunnel alive over the link the test claims is down, and
           the test would have passed without proving anything.
           What actually saved it was not what this change built. `wg-quick` does not fail on
           name resolution — it blocks in its own retry loop, here for 143 seconds, until
           failover flipped DNS and the name resolved. The tunnel watchdog never came into it.
           See 3.7: that rescue rests on a margin nobody has written down. -->

## 10. Soak, then retire the direct path

- [ ] 10.1 Run on the tunnel for a soak period covering at least one real uplink failure
- [ ] 10.2 Re-check that the direct path can still serve, so rollback stays real for as long as it is claimed
- [ ] 10.3 Bind the hostname's home server block to the tunnel address, so it is no longer served over the public one
- [ ] 10.4 Verify a request to the house's address with this hostname is no longer served
- [ ] 10.5 Verify `neighbour.example.com` still serves and still renews — retirement by binding rather than by firewall exists precisely so this holds
- [ ] 10.6 Record that rollback is now two steps, and that it is not an emergency remedy

## 11. Ship

- [x] 11.0 Close the gap this change tripped over: a unit file committed and deployed does not
      reach systemd, because the installed unit is a copy rather than a link to the repository.
      Nothing notices the divergence — the deploy reports success, the service restarts, and
      the change is simply absent. It happened silently for `RestartSec` in 0.12.0 too, where
      the manual copy was remembered; here it was not. Either link the unit to the deployed
      tree so content follows a deploy, or teach the deploy hook to install and reload it —
      both need a decision about the privileges the hook holds, which is why this is named
      rather than quietly patched
      <!-- Two findings from 2026-08-01 that change what this task may do.
           First, it cannot be answered by installing everything from the repository. Four of
           the five files that had diverged differ *on purpose*: this repository publishes
           the shape and not the address, so `wg-tunnel-check.{sh,service,timer}` and the
           house's nginx block carry example values while the machine carries real ones.
           Installing them would point the tunnel watchdog at an address nothing answers on —
           where its own guard exits 2 and it silently stops watching — reference an
           `EnvironmentFile` that does not exist on this host, and rewrite the nginx block to
           a hostname the caller does not use. A deploy would take the gateway down. So the
           prerequisite is to move every machine-specific value out of files the deploy will
           overwrite, using the mechanism the repository already has and this host skipped
           (`/etc/wg-tunnel-check.env`, `/etc/default/wwan-backup`); the nginx block stays out
           of any manifest, since `listen` and `server_name` do not parameterise.
           Second, the failure mode is quieter than "the file did not arrive". Installing by
           hand from `/opt/sms-gate` reports success while copying whatever that tree happens
           to hold — which, if the deploy has not run, is the previous version. Observed
           today: an install ran, said nothing, and left the old script in place. Whatever
           this task builds must make the source of the install unambiguous, not merely
           automatic. -->
      <!-- Answered by teaching the hook to install, with the privilege decision taken rather
           than avoided: a root-owned installer outside the deployed tree, reached by NOPASSWD
           sudo, carrying its own manifest. A push can change what is installed but not where,
           because a manifest a push could edit is not a manifest. The consequence is stated
           in the file itself — push access is now equivalent to root here, since a unit names
           a command, and that cannot be narrowed away while deploys install units at all.
           The prerequisite came first and was the larger half: machine values moved into
           `/etc/wg-tunnel-check.env` and a systemd drop-in, because `EnvironmentFile` reaches
           the script but not `After=`/`Wants=` — a gap that had forced the unit to be edited
           in place, which is how it diverged and then missed the alert-relay fix for months.
           Verified end to end 2026-08-01, not by inspection: a real unit change was pushed and
           the deploy printed `installing units from e506dd3` / `installed
           /etc/systemd/system/wwan-backup.service` / `daemon-reload`. All nine managed files
           now match the repository; the only remaining divergence is the nginx block, excluded
           on purpose.
           Two things it deliberately does not do. It installs nothing carrying published
           placeholders, since that would point a monitor at an address nothing answers on. And
           it restarts no services: stopping `wwan-backup` drops the backup data session, which
           during a wired outage would take the only working uplink with it.
           One defect found by running it: the first version read the commit with `git -C
           /opt/sms-gate`, which is a work tree with no `.git`, so it printed "unknown commit" —
           the exact ambiguity the line existed to remove, wearing the shape of an answer. It
           now reads the bare repository and warns when the tree does not match the commit. -->

- [x] 11.1 Document the topology, both machines' parts in it, and the rollback
- [ ] 11.2 Archive so the `inbound-reachability` requirements land in `openspec/specs/`
