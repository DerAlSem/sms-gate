Procurement comes first here. The adapter's shape is decided by how the provider reports
delivery, and that is not knowable from a price list.

## 1. Settle the provider before designing against it

- [ ] 1.1 Get a quote for the real profile — 78 МегаФон recipients, 180 messages/month, 1–5 codes per recipient — and not the per-message list price. МегаФон tariffs A2P in per-recipient monthly packages, so the ≈530 ₽/month in the proposal is an upper bound on a shape they price differently
- [ ] 1.2 Confirm the digital-sender rate applies to OTP traffic without registering a template, and what the sender appears as on the handset. Today codes arrive from the gateway's own number, so a digital sender is not a regression — a shared name like `INFO` would be
- [ ] 1.3 Establish how the provider reports delivery: webhook we expose, or polling we schedule. This decides the size of the change; settle it before task 2
- [ ] 1.4 Confirm what happens to a message the provider itself cannot deliver, and what its failure vocabulary is — enough to map it onto `delivered` / `failed` without inventing a status

## 2. Design, with the critic layer run

- [ ] 2.1 Decide where the routing rule lives: `settings` (changeable from the admin UI, no restart) or `.env` (a restart, and a restart drops sending sessions). The requirement says "no deploy", which both satisfy; they differ in who can change it and how fast
- [ ] 2.2 Decide how a provider delivery report is matched to a message. The `+CDS` attribution — reference windows, `delivery_reports`, recency tiebreaks — is modem-route machinery and does not transfer
- [ ] 2.3 Decide whether provider-routed messages get rows in `delivery_reports` or a table of their own. Shared table means a column that is meaningless for half its rows; separate means two places to look during an incident
- [ ] 2.4 Run `system-architect` and `gap-finder` on the delta. Not yet run

## 3. Implement

- [ ] 3.1 Test: a send to an operator the rule routes to the provider is not picked up by the modem sender
- [ ] 3.2 Test (positive control): a send to any other operator still goes over the modem, unchanged
- [ ] 3.3 Test: a number with no row in `number_operators` is sent over the default route without waiting for a lookup, and the missing operator is recorded
- [ ] 3.4 Test: the operator lookup being unreachable fails no message and delays no send
- [ ] 3.5 Test: a provider identifier numerically equal to a live `+CMGS` reference never causes a report from one route to be attributed to the other route's message
- [ ] 3.6 Test: a provider authentication failure alerts the operator and does **not** reroute the message over the modem
- [ ] 3.7 Test: the application's webhook receives the same statuses for a provider-routed message as for a modem-routed one
- [ ] 3.8 Add the rule to the admin UI or to config per 2.1, with МегаФон as its only initial entry — as data, not as a branch
- [ ] 3.9 Implement the adapter and the route split
- [ ] 3.10 Update `docs/` with the second route: what it costs, how to change the rule, and how to tell from a message which route carried it

## 4. Verify against the real thing

- [ ] 4.1 Send one message over the provider route to an operator-confirmed МегаФон number and confirm it arrives — the modem route currently cannot, so this is the only proof the change works
- [ ] 4.2 Confirm the owning application saw the delivery on its existing webhook without a change on its side
- [ ] 4.3 Watch the first day's spend against the quote from 1.1
