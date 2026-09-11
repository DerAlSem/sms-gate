The unverified link comes first. Everything below task 1.2 is worth nothing if a flash call
does not reach a МегаФон subscriber, and one call answers it.

## 1. Prove the link before building anything

- [ ] 1.1 Owner: create the uCaller account and fund the balance — the first call fails without it. **The credentials have nowhere to be read from yet**: no `ucaller_*` setting exists, and `seed_from_env()` copies an environment variable into the `settings` table only for a key that has no row, so a value placed in `.env` today is read by nobody. Where they live is decided in 2.3; until then the account and the balance are the blocking part
- [ ] 1.2 Place one `initCall` to `+79851600019` (the operator-confirmed МегаФон number the owner released for probes) and confirm the phone actually rings and shows a number whose last four digits match the `code` we passed. **If it does not ring, stop: the change is void and the reserve path is `verify-by-inbound-code`**
- [ ] 1.3 Capture the live responses of `initCall` and `getInfo` verbatim into the change folder — the contract so far comes from the vendor's reference only, and no parser is written against a reference when a sample is one call away
- [ ] 1.4 Confirm from the captured `getInfo` what `cost` and `balance` actually are for our account, and whether the 0,80 ₽ list price is what we are charged

## 2. Decide what the proposal left open

- [ ] 2.1 How long a verification stays open and how many wrong codes it tolerates. A person is standing at a barrier; too short is a support call, too long is a wider guessing window against four digits
- [ ] 2.2 Where the SMS method's text comes from now that the gateway generates the code — a per-application template setting, or composed by the gateway. `SokolParking: ####` has to come from somewhere, and the application can no longer supply finished text
- [ ] 2.3 Where the routing rule lives: `settings` (changeable from the admin console, no restart) or `.env` (a restart, and a restart drops sending sessions). The requirement says "no deploy", which both satisfy
- [x] 2.4 Run `system-architect` and `gap-finder` on the delta. **Done 11.09.2026**, one round, both critics, seeded with `openspec validate --strict` and `check.py`. 32 findings deduplicated to 20, each checked against the code before acceptance; the accepted ones landed as normative requirements, not as prose. The ceiling is one round and it is spent
- [ ] 2.5 Owner: decide whether spending on a paid route is an entitlement of the application. Today any active token can open a paid verification; three of the four applications never send codes. This is a new concept in the model, and it is not routing — the rule stays keyed on the operator alone

## 3. Agree the contract with the parking developer

- [ ] 3.1 Write the integration contract for `POST /verifications`, `POST /verifications/{id}/check` and `GET /verifications/{id}` with real examples, and send it. Until `sp_app` adopts it, no МегаФон subscriber sees any improvement
- [ ] 3.2 Quote no invented number in the contract. The frozen `verify-by-inbound-code` contract went out with `+7 900 123-45-67` in it, and that is exactly the mistake to not repeat — but the fix is not "use the real one": **for the call method there is no gateway number at all** (the vendor calls, from a number nobody knows in advance), and for the SMS method the gateway does not hold its own MSISDN anywhere in its settings. The contract SHALL name digits only if the gateway holds them as configuration, and otherwise say the sender is the gateway's SIM
- [ ] 3.3 Confirm with the developer whether `sp_app` can receive a webhook, or will poll. Both are supported; the answer decides which one is documented as the recommended path

## 4. Implement, tests first

- [ ] 4.1 Test: a verification for an operator the rule routes to `call` is not picked up by the modem sender, and one routed to `modem` is
- [ ] 4.2 Test (positive control): a plain send to any operator not in the rule still goes over the modem, unchanged
- [ ] 4.3 Test: the rule matches `МЕГАФОН` and `МегаФон` identically, and matches a name with surrounding whitespace. **This test fails on any implementation built on SQLite `upper()`/`LIKE` or on `==`**
- [ ] 4.4 Test: a number with no row in `number_operators` takes the default route without waiting for a lookup, and the missing operator is recorded
- [ ] 4.5 Test: the operator lookup being unreachable fails nothing and delays nothing
- [ ] 4.6 Test: arbitrary text addressed to an operator routed to `call` is `failed` at once with a reason naming the operator, notifies the app, alerts the operator, issues no AT command and consumes no retry
- [ ] 4.7 Test: an application-supplied code is rejected by `POST /verifications`
- [ ] 4.8 Test: `call_status: 1` does not confirm a verification; only a correct code at `/check` does
- [ ] 4.9 Test: `call_status: -1` that never resolves within the bound is recorded as unknown, not as success and not as failure
- [ ] 4.10 Test: a confirmed verification cannot be confirmed twice; an expired one cannot be confirmed; wrong codes exhaust the attempt limit and further checks are refused even when the right code follows
- [ ] 4.11 Test: two verifications open at the same time for one number do not share a code
- [ ] 4.12 Test: a second request for the same number inside the vendor's per-number window is refused by us with a wait reason, and no vendor call is placed
- [ ] 4.13 Test: a repeat inside the free window uses `initRepeat` and keeps the same code; a retried vendor call carrying the same idempotency key does not place a second call
- [ ] 4.14 Test: a vendor authentication failure or an insufficient balance alerts the operator and reroutes nothing over the modem
- [ ] 4.15 Test: a verification outcome pushed to the application is distinguishable from a message status push, so a verification id cannot be read as a message id
- [ ] 4.16 Implement the routing rule as data per 2.3, with МегаФон as its only initial entry — as data, not as a branch, and with no `app_id` in the rule
- [ ] 4.17 Implement the verification endpoints, the code store and the uCaller adapter against the samples captured in 1.3
- [ ] 4.18 Implement the per-operator count of refusals, reachable from the admin console — the rule outlives the outage that justified it, and nothing else will say so
- [ ] 4.19 Update `docs/` with the second route: what it costs, how to change the rule, how to tell from a verification which route carried it, and what to do when МегаФон recovers
- [ ] 4.20 Test: a verification belonging to one application cannot be read, checked or exhausted by another — by id, with a valid token
- [ ] 4.21 Test: a blocked number is refused a verification, and a call that fails to connect does not advance that number's permanent-failure count
- [ ] 4.22 Test: the code appears in no API response, no alert and no log line, and stops being readable once the verification is terminal
- [ ] 4.23 Test: a verification whose vendor-reported code differs from the requested one fails with that reason rather than matching digits the vendor never dialled
- [ ] 4.24 Test: a stored routing rule that cannot be parsed alerts and does not route as an empty rule; an entry naming an unknown route is refused at save time; an operator name with surrounding whitespace still matches
- [ ] 4.25 Test: the refusal alert fires on stock settings (`notify_send_errors` off) and is deduplicated per operator and route
- [ ] 4.26 Test: the spend ceiling refuses a paid verification with its own reason, places no vendor call, and is not reported to the application as a vendor failure
- [ ] 4.27 Test: a verification carried by the modem whose message fails or expires fails the verification, and that message raises no message-status push
- [ ] 4.28 Test: the expiry sweep expires an untouched verification and notifies once; the writer-enumeration test covers verification state writers
- [ ] 4.29 Test: two concurrent checks confirm at most once and consume at most one attempt
- [ ] 4.30 Implement verification retention and the destruction of a terminal verification's code
- [ ] 4.31 Make a single verification visible in the admin console beside the messages for the same number — route, vendor outcome, whether it was confirmed, recorded cost. The counters answer "how much", and a support call is always about one person

## 5. Verify against the real thing

- [ ] 5.1 Run one verification end to end to `+79851600019` on the production host: the call arrives, the digits are read, `/check` confirms, and the outcome reaches the application. The modem route cannot reach that number at all today, so this is the only proof the change works
- [ ] 5.2 Confirm a non-МегаФон verification still arrives as an SMS, unchanged, on the same code path — **to a number the owner has released for probes, not to a customer**. This host carries live customer traffic, and a verification sent to prove a code path still reaches a real person's phone
- [ ] 5.3 Confirm the new refusal fires on a message the owner originates to a МегаФон number, and that the count in 4.18 registers it. **Owner's call whether to also wait for `gmp_app`'s next real message** — as originally written, the first witness of the new behaviour is a customer's message rather than a probe
- [ ] 5.4 Watch the first week's spend against the cost recorded in 1.4
