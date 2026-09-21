The unverified links come first. The ladder has two rungs and each is unproven on its own:
everything below is worth nothing if neither a Telegram message nor a flash call reaches a
МегаФон subscriber. **Start with 1.5** — it is the only probe that costs nothing and needs no
funded balance.

## 1. Prove the links before building anything

- [ ] 1.1 Owner: create the uCaller account and fund the balance — the first call fails without it. Where the credentials live is settled (2.3: `settings`, marked secret), so the account and the balance are now the whole of the blocking part
- [ ] 1.2 Place one `initCall` to `+79851600019` (the operator-confirmed МегаФон number the owner released for probes) and confirm the phone actually rings and shows a number whose last four digits match the `code` we passed. **If it does not ring, the `flash_call` rung is void** — and that is now survivable rather than fatal, provided 1.5 and 1.7 show the Gateway rung carrying it
- [ ] 1.3 Capture the live responses of `initCall` and `getInfo` verbatim into the change folder — the contract so far comes from the vendor's reference only, and no parser is written against a reference when a sample is one call away
- [ ] 1.4 Confirm from the captured `getInfo` what `cost` and `balance` actually are for our account, and whether the 0,80 ₽ list price is what we are charged
- [x] 1.5a Owner: open **gateway.telegram.org**, "Log in to Start", confirm in Telegram, then copy the token from `gateway.telegram.org/account/api`. 🔴 **This is a different door from the one that is shut:** the Gateway needs no `my.telegram.org` and no `api_id`/`api_hash` — those are the user-account route's, and their refusal on 18.09.2026 does not reach here. Costs nothing and unblocks 1.5 by itself
- [x] 1.5 **Prove the Gateway rung end to end for nothing, before any balance exists.** Free testing is tied to the login: *"you'll be able to send free verification messages to the Telegram account tied to the number you used to log in"* — so the owner logs in with the number the probe will target. Send a code we generated to it, with an explicit `ttl`, and watch the whole mechanism: the code we supplied arrives unchanged, the `delivery_status` moves, the callback is signed, `revokeVerificationMessage` withdraws it. **Done 18.09.2026 and it proved more than expected.** Our code arrives unchanged, delivery is `sent`→`delivered` in one second and `read` at 71 s, `request_cost` is 0 on an account whose `remaining_balance` is 0 — so the whole mechanism runs before any Fragment top-up. 🔴 **Revocation, however, is observably inert:** `ok/true` twice, message still on screen both times, `delivery_status` never `revoked`. Findings and their limits are in `captures/README.md`. Proves our half of the rung and nothing about a customer's reachability, which is 1.7
- [ ] 1.6 Capture the live `checkSendAbility`, `sendVerificationMessage` and callback payloads verbatim into the change folder, including the callback headers. The reference gives field names; the sample gives what is actually populated, and the signature cannot be verified against a document. **Half done 18.09.2026 — `captures/` holds `sendVerificationMessage`, `checkVerificationStatus` and `revokeVerificationMessage` with their notes. 🟢 **`checkSendAbility` arrived 20.09.2026 with task 1.7** — `probe-1.7-check-able.json` and `probe-1.7-check-declined.json`, both halves of it. Still missing: the callback — ⚠️ **which was said to ride with 1.9 for want of a public HTTPS address, and that was wrong: `sms.deralsem.ru` answers publicly from edge and reaches this house over the live `wg-burns` tunnel, so the callback can be captured as soon as there is a request to report on**.** Not tickable until both arrive
- [ ] 1.11 **Settle what the subscriber actually sees on this rung, and whether we can change any of it.** The probe's message arrived from "Verification Codes" reading *"Your code is 1173"* — no branding of ours, and in English. `sendVerificationMessage` accepts no body, so the wording is not ours to set; the one documented lever is `sender_username`, a verified channel, and it was not tried. ⚠️ **Whether the text is always English or follows the recipient's Telegram language is NOT established** and must not be assumed either way. This matters beyond taste: the spec forbids the gateway inventing default wording on the modem route precisely because a code signed by something a person does not recognise reads as fraud — and on this rung we inherit exactly that, with no template to fix it. It is also half of what task 3.1 has to describe to the parking developer
- [x] 1.7 Owner: fund the Gateway balance — *"To send messages to other Telegram users via the Gateway API, you'll need to fund your account"*, and the funding page routes through **Fragment**, not a card. That is the one friction this rung has that uCaller does not, and it is worth knowing before the account is opened rather than after. Then run `checkSendAbility` against `+79851600019`. **This is the Gateway rung's equivalent of 1.2 and it is a separate question from 1.5** — whether a МегаФон subscriber is reachable in Telegram at all decides whether the cheap rung ever runs, or whether every verification pays for a declined check before calling anyway. 🟢 **Done 20.09.2026, and it answered more than it asked.** The balance was funded through Fragment and both numbers went in one run, from derserver over the wire. **The subscriber is reachable: `checkSendAbility` against `+79851600019` confirmed, `request_cost: 0.01`, `remaining_balance: 99.99` — so the cheap rung runs.** The decline, captured for nothing against a real working number whose owner has no Telegram, is spelled **`PHONE_NUMBER_NOT_AVAILABLE`**; `DECLINE_ERRORS` is no longer empty and an ordinary unreachable subscriber no longer raises an alert. Three further findings, each of which contradicts something we had written: `remaining_balance` is the account's balance **only** in the answer to `checkSendAbility` (the send answered `0` while the account held 99.99 — 18.09 could not tell, because the account really was empty then), so Telegram's balance cannot be polled for free; revocation on the **paid** path is not inert after all — it sets `verification_status: expired`, though `delivery_status` still never becomes `revoked`; and one `updated_at` serves two delivery statuses, so it is no transition clock. 🟢 **The probe argument also became a measurement, which was the owner's condition of 20.09:** the vendor answers in **178–285 ms** over the wire against a `verification_probe_timeout` of 5 s — roughly eighteenfold headroom — so the probe stays as it is. Samples and the full reading are in `captures/README.md`
- [ ] 1.8 Confirm from the captured `RequestStatus` what `request_cost` and `remaining_balance` are for our account, and confirm a refund appears as `is_refunded` by letting one message expire unread inside a short `ttl`. **Half done 20.09.2026:** `request_cost` is `0.01` per confirmed check and `remaining_balance` is real — but only in the answer to `checkSendAbility`, which is the billed call, so the balance cannot be read for nothing (recorded as a requirement in `phone-verification`). ⚠️ **The refund half is untouched and is now the weakest thing in the change:** `is_refunded` has been absent from ten captures running, no message has ever been left to expire unread, and the ladder's economics — "a confirmed but undelivered message is refunded" — rest entirely on one sentence of the vendor's reference. 🔴 **And it cannot be bought for `0.01` after all — the reference settles that too, 20.09.2026.** The refund hangs on non-**delivery**: *"If a message is successfully delivered within the `ttl`, it will not be refunded."* A confirmed `checkSendAbility` says the subscriber is reachable, and every message we have sent was delivered within a second — so there is no way to stage a refund deliberately. It is reached only by a subscriber confirmed reachable who then is not reached, which is a wild event and not a probe. **This task's refund half is therefore not work but a watch**, and the honest options are to wait for one in production or to close it with a named refusal
- [x] 1.9 **Decided 18.09.2026: the restriction stays off.** ⚠️ **Rewritten 18.09.2026 against live measurement: all three premises this task was written on are wrong.** (1) **The house does not egress from the house's address.** `home.deralsem.ru` resolves to `46.188.29.113`, but everything this host emits leaves from **`193.233.254.161`** — measured from the gateway itself against both a proxied and a direct destination, which answered the same address. That is `ffm`, a machine in the owner's own estate on a static address, and it is the **home router** that puts traffic there: neither this host's routing table nor anything in this repo does. The router also intercepts DNS — `gatewayapi.telegram.org` answers `198.18.13.246` on the house's link, an address belonging to that proxy rather than to Telegram, and naming the carrier's resolver explicitly returns the same fake answer, so the interception is on the path and not in the choice of server. (2) **There IS a tunnel, and this task's first reading of it was wrong.** ⚠️ **Corrected 18.09.2026 after the owner objected.** `wg-quick@wg-edge` is indeed `inactive` and `disabled` — but `wg-edge` is the placeholder name this repo's documentation uses, not the deployed one. The live tunnel is **`wg-burns`**: the house at `10.67.67.3`, edge at `10.67.67.1`, and `/etc/wg-tunnel-check.env` names it outright (`UNIT=wg-quick@wg-burns`, `PEER_ADDR=10.67.67.1`), so `reach-the-gateway-on-any-uplink`'s own watchdog is watching it and exiting zero. Edge serves **`sms.deralsem.ru`** from a server block of its own, proxying to `10.67.67.3` over that tunnel, and the name answers publicly from `178.250.157.233`. 🔴 **Reading a tunnel's absence off a placeholder name was the mistake, and it costs more than this task: 1.6's missing callback sample is no longer blocked for want of a public HTTPS address, and the captures note saying there is none is wrong.** What the tunnel does not do is carry egress — the house holds exactly one route into it, `10.67.67.1`. (3) **Edge would not present its stable address to Telegram anyway.** On `mprz.ru`, whose address is `178.250.157.233`, `ip route get 149.154.167.99` answers `dev wg0 src 10.66.66.2`, and `wg0`'s routes are exactly `91.108.4.0/22` and `149.154.160.0/20` through a foreign endpoint — so egressing the vendor calls through edge would show Telegram somebody else's address while showing uCaller edge's own. The candidate set that survives is therefore two, not three: **lock to `193.233.254.161`**, which costs nothing because it is already the address, at the price of a lock this repo can neither see nor be told about when the router's configuration moves under it; or **leave the restriction off** and let the vendor-side balance be the only cap, which is 1.10. ⚠️ **And the correction above strengthens the second rather than reopening the first:** now that the tunnel is known to be live, egressing the vendor calls through it is technically available — and it would show Telegram the foreign endpoint's address behind edge's `wg0`, which is somebody else's to change and cannot be allowlisted at all. ⚠️ **The restriction's shape is undocumented** — neither `core.telegram.org/gateway` nor the API reference mentions it at all — so whether it takes one address, a list or a CIDR has to be read off the cabinet before either option can be priced 🟢 **The owner chose to leave it off, and the argument that decided it is that the address is not ours to promise.** `193.233.254.161` costs nothing to allowlist because it is already the address, but it is held by the home router's configuration — which lives in no repository, in no history, and in nobody's changelog. A lock on it fails on the day that configuration moves, it fails silently, and the first witness is a verification code that was never sent. That is a worse failure than the one the lock defends against, because the defence it buys is already bought better by 1.10: a balance sized to weeks bounds a leaked token whatever address it is spent from. ⚠️ **This decision is cabinet configuration and lands as no requirement** — the gateway's behaviour does not change either way. What it does change is that 1.10 stops being a second cap and becomes the only one
- [ ] 1.10 **Now that 1.9 has left the IP restriction off, the balance is the only cap there is — keep it deliberately small.** A leaked Gateway token is spend authority at the vendor, and this change's spend ceiling does **not** protect it: the ceiling bounds what *our gateway* asks for, while a stolen token is spent without touching our gateway at all. The vendor-side balance is the only cap that applies, so it is the cap — a top-up sized to weeks, not to years
- [x] 1.13 **Settle which field reports expiry, because our one sample and our one scenario disagree.** The spec's scenario watches `delivery_status.status` for `expired`; the 20.09.2026 capture put `expired` under **`verification_status`** while `delivery_status` read `delivered`. A gateway watching only the delivery field would have missed it. What is not established is whether the vendor's delivery vocabulary carries `expired` at all — that is a question for its reference, which has not been re-read against this. Costs nothing: it is a read, not a call. Until it is answered, nothing may be built that treats either field as the single authority on expiry. 🟢 **Answered the same day by re-reading the reference, and the answer is worse than the question.** Both vocabularies carry `expired` and they mean different things: `DeliveryStatus` is `sent`/`delivered`/`read`/`expired`/`revoked`, `VerificationStatus` is `code_valid`/`code_invalid`/`code_max_attempts_exceeded`/`expired`. The scenario was watching the right field all along — delivery expiry is the one the refund hangs on — and the sample was coherent, not contradictory. What the re-read bought instead is a named trap: **a bare `expired` is ambiguous between a refund and a shut code window**, and the spec now requires every reading of it to name its field
- [ ] 1.12 🔴 **The cheap rung does not survive a failover to the backup uplink, and that is a routing problem rather than an allowlist one.** Measured 18.09.2026 by real address bound to `wwan0`: `gatewayapi.telegram.org` and `api.telegram.org` both time out at fifteen seconds with no connection established, while `api.ucaller.ru` answers over the same interface in 0.17 s — so the interface carries traffic and it is Telegram specifically that does not arrive. The house reaches Telegram at all only through the proxy on the home router, and the backup uplink does not pass through it. Three consequences this change has to carry rather than assume away. The `tg_gateway` rung is unavailable for the whole duration of a wired outage, so the ladder spends its single acceptance bound (4.38) waiting on a rung that cannot answer before the `flash_call` rung is tried — and `flash_call` is reachable there, measured. The Gateway's signed callback cannot arrive over that uplink either, which bears on 1.6 and on whatever 1.9 decides. And the gateway's own Telegram alerting is dead in the same window, which belongs to `backup-uplink` rather than here, but which means an outage on this route reports itself to nobody. **The carrier is what drops it, and only it:** over the same `wwan0`, `cloudflare.com` answers in 0.34 s and `www.google.com` in 0.44 s, while both Telegram ranges — `149.154.167.99` and `91.108.56.130` — time out. 🔴 **And the owner has settled what that means, 18.09.2026: this is a defect, not a law.** The OpenWRT gateway at the house already exists and Telegram is fully reachable there — which is why the wired path works and why our probe over it succeeded. What is supposed to happen when the wire drops and `wwan-backup` fires is that the modem path is carried by WireGuard too. **It is not, and nothing on this host would make it so:** `ip rule` holds nothing beyond table 100 for the wired source address; a failover falls to the plain `default via 100.108.32.169 dev wwan0`; the only enabled WireGuard instance is `wg-quick@wg-burns`, whose single route is `10.67.67.1`; and `wwan-backup.sh` never touches WireGuard at all. ⚠️ **The fix is `backup-uplink`'s and not this change's** — it is the uplink that is missing its egress, and every other thing the gateway emits to Telegram during an outage is missing it identically, the operator alerts first among them. What this change owes is only to stop assuming: until that gap is closed, the `tg_gateway` rung is unavailable for the duration of a wired outage and the ladder must reach `flash_call` without spending its acceptance bound waiting on it. 🟢 **And a cheap fix is in view either way:** a route for Telegram's two ranges into `wg-burns` would reach edge, which already forwards exactly those ranges over `wg0` — which makes the rung uplink-independent, and which also puts Telegram's view of us behind an address nobody can allowlist, reinforcing what 1.9 decided

## 2. Decide what the proposal left open

- [x] 2.1 How long a verification stays open and how many wrong codes it tolerates. **Decided 18.09.2026: five minutes and five attempts, both settings.** They coincide with numbers the gateway already holds — `delivery_timeout_seconds` is 300 and `blacklist_threshold` is 5 — so a verification neither outlives the message carrying it nor answers "enough" differently from the blacklist. Propped from below by the free repeat, unusable sooner than sixty seconds, and from above by the vendor's ten-hour block on a number that asks too often. 🔴 Diverges from the ten minutes already stated to end users in the contract at the parking developer; task 3.1 carries that letter
- [x] 2.2 Where the SMS method's text comes from now that the gateway generates the code. **Decided 18.09.2026: a per-application template, refused at accept when absent, with no built-in default.** A default is a wording decision taken silently for applications that do not share a voice — `sp_app` is `SokolParking: ####` in 446 of 448 messages, the others are free text under other names, and a code signed by something a person does not recognise reads as the fraud it resembles. The template governs the `sms_out` route only: neither paid rung carries text of ours
- [x] 2.3 Where the routing rule and the credentials live. **Decided 18.09.2026: `settings`, with every credential marked secret.** `.env` was never a candidate once the code was read — `seed_from_env()` copies a variable into `settings` only for a key with no row, so it is a one-time seed and not a home — and a value there would need a restart to change, which drops sending sessions. Precedent for the secret flag is `alert_bot_token`
- [x] 2.4 Run `system-architect` and `gap-finder` on the delta. **Done 11.09.2026**, one round, both critics, seeded with `openspec validate --strict` and `check.py`. 32 findings deduplicated to 20, each checked against the code before acceptance; the accepted ones landed as normative requirements, not as prose. The ceiling is one round and it is spent
- [x] 2.5 Whether spending on a paid route is an entitlement of the application. **Decided 18.09.2026: yes, and off by default, including for a newly issued token.** Three of the four applications never send codes, so a default of on means the first mistake in any of them is billed rather than logged. It is not routing — the rule stays keyed on the operator alone — and a refusal for want of it is never reported to the application as a vendor failure, nor quietly carried over the modem instead
- [ ] 2.6 **Owner: whether a Gateway message that was accepted and then not delivered within its `ttl` escalates to a call.** The spec's default is that it does not — the fee is refunded and the verification fails with that reason — and nothing may be built as escalation until this is answered. The argument for escalating is real: the refund makes the attempt nearly free, and the person is still standing at the barrier. The argument against is that it is the automatic escalation into a paid channel this change otherwise refuses, arrived at from the other side
- [x] 2.7 **Which word survives for the flash-call route — DECIDED by the owner 18.09.2026.** One flat field, names disambiguated: `flash_call` for the vendor's call (our modem does not participate), `call_in` for the subscriber calling our SIM, `sms_out` for our SIM sending, `sms_in` for the subscriber texting us, plus `tg_gateway`, `tg_user`, `max_user`, `app_bot`. **`call` is retired outright** — it meant two different mechanisms in two changes — and `modem` is retired in favour of `sms_out`. Applied across this change's specs and tasks and in `verify-by-inbound-contact`; `reach-people-in-messengers` records it in its own task 1.1
- [ ] 2.9 **Check whether MAX has a Gateway-shaped product, and correct the record if it does.** Raised by the owner 18.09.2026 from `@verificationcodes_bot`, which is the *receiving* surface in MAX — where codes from banks and shops land for the subscriber — and therefore not something we call. What would matter is the sending side: `business.max.ru` advertises "уведомления по номеру телефона" and "коды подтверждения", which is the Telegram Gateway shape exactly. ⚠️ **If true it partly contradicts what this repo recorded on 12.09.2026** — "в MAX номером адресовать нельзя" was established about the **Bot API** and may not hold for the business product. ⚠️ **A hard gate was reported alongside it — "since August 2025 only Russian legal entities may create and publish bots, ИП and самозанятые excluded" — and the owner's own case contradicts it in part: they hold a Russian ИП and are already registered on `business.max.ru` (18.09.2026).** So either the restriction is narrower than reported (registering is not publishing), or it has moved. Do not carry the second-hand claim forward in either direction. None of this is from the vendor's reference yet, so nothing may be built or asserted on it: the task is to read `business.max.ru` and `dev.max.ru`, establish what an ИП may actually publish, and either bring back a contract or close this with a named refusal
- [ ] 2.8 **Owner: permission to measure what share of our numbers is reachable in Telegram.** It needs no message sent and costs nothing for an unreachable number, but it means running live customer numbers through a vendor. It is the measurement that decides whether the cheap rung is worth its check: a base with little Telegram is a ladder that pays to be declined before calling anyway

## 3. Agree the contract with the parking developer

- [ ] 3.1 Settle the contract's shape here, then hand it over — **there is nothing to reconcile
      with.** 🔴 The owner said on 18.09.2026, twice, that the contract was never given to the
      parking developer: *«контракт отдадим, когда поймем, что и как по итогу»*. The earlier text
      of this task read the opposite from an artifact believed sent on 07.09.2026 and built four
      «divergences already in the developer's hands» on it; a draft that was written is not a
      draft that was sent, and every task that treated the difference as a negotiation was work
      against a party that does not yet exist. What survives is the substance, which is now ours
      alone to choose: plural `/verifications` rather than singular `/verify`; a lifetime of five
      minutes rather than ten (2.1); the verification id in a field distinct from `id`; and the
      method vocabulary, settled by the owner on 18.09.2026 as one flat field — `sms_out`,
      `sms_in`, `call_in`, `flash_call`, `tg_gateway`, `tg_user`, `max_user`, `app_bot`.
- [ ] 3.2a Then write the integration contract with real examples and hand it over, once the shape is settled and not before — the owner's condition of 18.09.2026. Until `sp_app` adopts it, no МегаФон subscriber sees any improvement
- [ ] 3.2 Quote no invented number in the contract. **The draft carries TWO placeholders, not one** — `+79001234567` in the JSON example and `+7 900 123-45-67` in the screen copy — and both must go before it is handed over. (An earlier note here said one of them had gone out in the frozen `verify-by-inbound-code` contract; nothing went out — see 3.1.) The fix is not "use the real one": **for the call method there is no gateway number at all** (the vendor calls, from a number nobody knows in advance), and for the SMS method the gateway does not hold its own MSISDN anywhere in its settings. The contract SHALL name digits only if the gateway holds them as configuration, and otherwise say the sender is the gateway's SIM
- [ ] 3.3 Confirm with the developer whether `sp_app` can receive a webhook, or will poll. Both are supported; the answer decides which one is documented as the recommended path

## 4. Implement, tests first

🟢 **The base capability's core is being built in `verify-by-inbound-contact`, by the
owner's decision of 19.09.2026 — do not build it twice.** Landed there already: the
`verifications` and `verification_rungs` tables, the `verification_ttl_seconds` /
`verification_max_attempts` / `verification_retention_days` settings, and the store's
conditional confirm, attempt limit, ownership scoping, expiry sweep and retention
(`app/db/queries.py`, `tests/test_verification_store.py`). The doors and the route
chooser follow there.

What stays here: everything vendor-side — the uCaller and Telegram Gateway adapters,
the callback signature, the `sms_out` template, the cost ledger's vendor half, and the
operator routing rule itself. Those are blocked on accounts and balances (1.1, 1.7)
rather than on code.


- [ ] 4.1 Test: a verification for an operator the rule routes to `flash_call` is not picked up by the modem sender, and one routed to `sms_out` is
      🔴 **Half of this is now a live hazard rather than an open test, and it was created
      by 4.6a.** The modem sender refuses anything whose **first** rung in the rule is
      not `sms_out`. A verification the ladder deliberately routed to a modem rung
      standing behind a paid one would therefore be refused by the sender — the ladder
      chose `sms_out`, and the sender asks the rule instead of asking what was chosen.
      It is unreachable today because nothing enqueues an `sms_out`-borne code: the
      carrier is task 4.17, blocked on 1.1. **When 4.17 lands, the item handed to
      `enqueue` has to carry what the ladder selected**, and this test is what must
      fail until it does. Asserting "flash_call is not picked up" alone would be hollow
      in the way twice caught on this change.
- [x] 4.2 Test (positive control): a plain send to any operator not in the rule still goes over the modem, unchanged
      Taken **in the same file and the same session as 4.6**, not after it: three times
      on this change a guard has stood green over a place nothing could reach, and the
      last two were caught only because a positive control sat beside them. Four
      controls carry it — an operator with no entry (`*`), a number with no
      `number_operators` row at all (`?`), the identical МегаФон send once its entry is
      rewritten to `sms_out`, and the two undiverted sends asserting `attempts == 1` and
      a PDU actually handed to the modem. The third is the one with teeth: it is the
      same message, the same harness and the same modem as the refusal beside it, and
      the only thing that differs is the rule.
- [x] 4.3 Test: the rule matches `МЕГАФОН` and `МегаФон` identically, and matches a name with surrounding whitespace. **This test fails on any implementation built on SQLite `upper()`/`LIKE` or on `==`**
- [x] 4.4 Test: a number with no row in `number_operators` takes the default route without waiting for a lookup, and the missing operator is recorded
      `tests/test_send_path_operator_lookup.py`. 🔴 **"Without waiting" turned out to
      name the DOOR and not the gateway, and settling that was the owner's**
      (20.09.2026): the application's answer does not wait, the sender does, under a
      bound of its own. Taken literally — nobody waits anywhere — this task would have
      **defeated 4.6 on the message 4.6 exists for**: the first text ever addressed to a
      МегаФон subscriber would be routed against an empty cache, take the `?` entry,
      which ships pointing at the modem, and go out over the route that operator has
      been rejecting. The test named for that race is the first in the file.
      The recording half is `messages.routed_route` + `messages.routed_operator`, written
      by the sender at the moment it decides — the only moment both facts are true
      together, since a later lookup fills `number_operators` in and would make the
      message look as though it had been routed for an operator nobody knew at the time.
      **Two columns rather than one, and that is the guarantee:** `routed_operator IS
      NULL` alone cannot tell an unresolved operator from a row older than the column,
      while `routed_route IS NOT NULL AND routed_operator IS NULL` is exactly "routed
      without a known operator".
- [x] 4.5 Test: the operator lookup being unreachable fails nothing and delays nothing
      Same file. "Delays nothing" was **not** held before today — every send of an
      unresolved number waited `voxlink_timeout` at the door — and it is asserted on the
      clock rather than on a mock: a bound living inside the thing being waited for is
      not a bound, and `voxlink.lookup` fails open on `httpx` errors only. Stated as a
      run of twelve sends rather than one, because the failure is cumulative: a bound
      spent per message turns a dead lookup into a queue that never drains, and one
      message cannot show that.
- [x] 4.4a Implement the division of waiting — the door spawns the lookup, the sender resolves under `operator_lookup_bound`
      Entered as its own task for the reason 4.14a and 4.6a were: 4.4 and 4.5 are test
      tasks, and what they needed did not exist.
      `app/api/router.py` spawns `record_operator` with a strong reference instead of
      awaiting it; `ModemManager._operator_for` reads the cache and, only where it holds
      no operator at all, waits on the lookup under `operator_lookup_bound` (its own
      setting, 5 s — `voxlink_timeout` bounds how patient one HTTP call is, this bounds
      how long a message may sit in a single-file queue while its way out is decided).
      **A stale row is used as it stands:** it still names an operator, refreshing it
      changes no decision this rule can make, and every send behind it would pay.
      Expiry, a raise and an answer naming nobody are one outcome — `?` answers.
      🔴 **The suite reached the real network for the first time in its life, and that
      was this task's doing.** `record_operator` used to be awaited only at the door,
      which most tests bypass; now the sender calls it, so every send of an unresolved
      number made an HTTP request — slow where voxlink is unreachable and
      **non-deterministic where it is not**, which is how one existing test went red
      against somebody else's database. Closed by `conftest._no_real_operator_lookup`,
      which replaces the name `httpx` **inside `app.lookup.voxlink`** and nothing else:
      the first attempt set `AsyncClient` on the shared module object and took the
      Gateway adapter's transport down with it, in nine red tests.
      Ten mutations in `bite-lookup.sh`, all red — among them one that survived the
      first round and was right to: NULL and blank are not the same test, and the fold
      that makes a blank operator absent exists for the writer that has not been written
      yet.
- [x] 4.6 Test: arbitrary text addressed to an operator routed to `flash_call` is `failed` at once with a reason naming the operator, notifies the app, alerts the operator, issues no AT command and consumes no retry
      `tests/test_send_path_refuses_an_uncarryable_route.py`, fifteen tests, each of the
      five claims asserted separately — four of them can hold while the fifth does not.
      Thirteen mutations in `bite-send-refusal.sh`, all red.
      🔴 **Two of those thirteen survived the first round, and what they found was
      real:** declaring `tg_gateway` able to carry words, and making an unknown route
      carry everything, left every send-path test green. The send path asks "is this
      item assigned to me?" before it asks "could the assigned route carry it?", so the
      declaration only ever decided the wording of the reason — a second filter above it
      swallowing the mutation, which is the failure `_gates.md` names. The remedy was to
      assert the declaration where it lives (`routes.carries`) rather than through a
      path that dominates it, plus one test on the wording the declaration feeds
      directly. A third survivor is benign and left alone: deleting the `rule.refuses`
      branch still refuses, because the general path refuses identically — it is kept
      for the empty-list case and for a reason an operator can act on.
      ⚠️ The verification half of this mechanism is **task 4.1 and is not reachable
      yet**: no carrier enqueues an `sms_out`-borne code, because that is task 4.17.
      When it lands, the guard below refuses it on any operator whose first rung is
      paid, and 4.1 is what must catch that.
- [x] 4.6a Implement the refusal on the send path — `rule.route_for` called from `_send_one`, before `encode_submit` and before the modem gate
      Entered as its own task for the reason 4.14a was: 4.6 is a test task, and the
      mechanism under it did not exist at all. `rule.route_for` was called from nowhere
      on the send path, and the requirement it serves was marked `[unbacked]`.
      **This is the first change on this branch that alters live behaviour.** Plain text
      to a МегаФон subscriber stops going out: the shipped rule routes that operator to
      `[tg_gateway, flash_call]`, and neither rung has a field for words. The owner chose
      it as the next task on 20.09.2026 knowing that.
      🔴 **The alert is raised by `refusals.record` on the `routing` event, not by
      `_finally_fail`.** `_finally_fail` notifies `send_error`, which ships **off** — a
      refusal carried only by it is silent on exactly the installs that have the rule in
      force, which is all of them. This is the trap task 4.25 already caught once.
      **The send path is the missing producer of the refusal count.** Until now
      `refusals.record` had one caller, `ladder.walk`, which has no live caller of its
      own; the seventy-odd refusals a month the count was built for are these.
      Where each piece sits: `routes._CARRIES` and `routes.carries` declare what a route
      can carry (absent means cannot — the three messenger routes have no adapter and no
      wire contract anybody has read); `ModemManager._refuse_what_the_rule_routes_elsewhere`
      reads the operator from the cache without waiting for a lookup, reads the rule live,
      and refuses unless the **first** route named is `sms_out`; `ModemManager._refuse`
      counts first and fails second, so that the record that outlives the message is the
      one written under the fewer assumptions.
      ⚠️ **Written on the assumption that the door resolves the operator first, and
      that assumption lasted one task.** It was true here: `record_operator` was awaited
      before `create_message`, so the cache always held the row by the time the sender
      read it. 4.4a removed that, and moved the resolving into the sender under a bound
      of its own — see 4.4. Nothing in this task was wrong; the reason it was safe moved.
- [x] 4.7 Test: an application-supplied code is rejected by `POST /verifications`
      The mechanism was already there and already guarded — `refuse_a_supplied_code` in
      `app/api/schemas.py`, and the inherited
      `test_an_application_supplied_code_is_refused`. Bitten rather than believed:
      disarming the validator reddens. What the inherited guard did not say is that the
      refusal happens **before** a row exists, so a request rejected late would leave the
      number carrying a live code nobody asked for. Said now, with the positive control
      that a request naming only the number is still accepted.
- [ ] 4.8 Test: `call_status: 1` does not confirm a verification; only a correct code at `/check` does
- [ ] 4.9 Test: `call_status: -1` that never resolves within the bound is recorded as unknown, not as success and not as failure
- [x] 4.10 Test: a confirmed verification cannot be confirmed twice; an expired one cannot be confirmed; wrong codes exhaust the attempt limit and further checks are refused even when the right code follows
      🔴 **Two of the three conditions were held by a second filter and nothing said so.**
      `status = 'pending'` and `attempts < ?` can each be deleted from the confirming
      update with the suite green: a terminal verification has had its code nulled, so the
      update fails on `code = ?` instead. Measured, not reasoned. The guards therefore put
      the code **back** into a terminal row before offering it — the only way to assert
      about the condition that is not the one already proved. The day destruction is
      deferred, which is what 4.30 is about, the guarantee would otherwise be held by
      nothing.
      The attempt-ceiling branch turned out to answer wrongly in a reachable state; that
      is 4.10a.
- [x] 4.11 Test: two verifications open at the same time for one number do not share a code
      🔴 **The guard was hollow and the mechanism unguarded entirely.** The inherited
      `test_two_open_verifications_for_one_number_do_not_share_a_code` asserts what
      `open_codes_for` reports and never that the second code *differs*: replacing the
      door's `_new_code(await queries.open_codes_for(phone))` with `_new_code(set())` left
      the suite green.
      The obvious replacement would have been barely better — with ten thousand codes two
      random draws collide once in ten thousand runs — so the source of digits is scripted
      inside `app.api.router` and the collision made certain. Paired with the control that
      a code live on **another** number is no collision, or the door would exhaust its
      hundred draws on a busy gateway.
      🔴 **The handoff's reachability question is answered yes, by measurement.**
      `POST /verifications` refuses only a blocked number and a ladder that can prove
      nothing; the vendors' per-number window (4.12) is evaluated when a rung is walked,
      not when a verification is opened. The guard is not hollow for want of the state.
- [x] 4.10a Answer an exhausted-by-a-lowered-ceiling verification with the word that is true
      Found by 4.10 and fixed here, because a test task must not carry an implementation.
      The attempt ceiling is a **setting**: lowering `verification_max_attempts` while
      verifications are open leaves rows pending with more attempts spent than the limit
      now allows, and `check_verification`'s explaining branch answered `expired` for them
      — inside their own deadline, which is the one thing that had not happened. It now
      asks the database whether the deadline has passed (the row's times were written by
      SQLite's clock; comparing them against this process's is the two-clock mistake every
      conditional update in that module avoids) and answers `no_attempts_left` otherwise.
      **A row both out of time and out of attempts is called `expired`** — the deadline is
      the older word and the one the application was told at creation, so it is the one
      the person can see the truth of on their own screen. A choice, guarded as one, and
      the owner may overturn it.
- [ ] 4.12 Test: a second request for the same number inside the vendor's per-number window is refused by us with a wait reason, and no vendor call is placed
- [ ] 4.13 Test: a repeat inside the free window uses `initRepeat` and keeps the same code; a retried vendor call carrying the same idempotency key does not place a second call
- [x] 4.14 Test: a vendor authentication failure or an insufficient balance alerts the operator and reroutes nothing over the modem
      `tests/test_vendor_failure_spares_the_modem.py`, five mutations in
      `bite-modem.sh`. 🔴 **The handoff's premise was wrong and measuring it is what
      caught it.** It read "the behaviour already holds, only a guard is missing".
      It does not hold in the shape that sentence implies: driven directly,
      `ladder.walk` **does** carry a verification over an `sms_out` rung after the
      vendor refused us — measured before a line of the test was written. What
      actually holds is narrower and is what the requirement names: **automatic
      failover is absent.** The rungs walked are exactly `rule.route_for`'s answer,
      the gateway appends nothing, and the rule in force names no modem rung behind
      the paid ladder. A modem rung behind a paid one is configuration with an
      operator's name on it, and the positive control asserts the gateway carries it
      — without that control, every other assertion here would pass on a modem
      carrier nothing could ever have reached.
      🔴 **The first stand was hollow in the way this change keeps rediscovering:**
      the second paid rung carried, so the ladder stopped there and a mutation
      appending `sms_out` to the walk left all four tests green. The stand now lets
      nothing carry — which is also the real shape of the day the norm is for: a
      rotated token refuses `tg_gateway` and `flash_call` has no adapter yet (1.1).
      The out-of-credit half rides the same walk: running out has no captured error
      string in eleven samples, so it arrives as an `ok: false` the gateway cannot
      place — `unclassified`, loud, advancing as past a decline, and never onto the
      modem.
- [x] 4.14a Implement the withholding of a modem rung that stands behind a rung whose vendor refused **us** — the owner's decision of 20.09.2026, taken on the question 4.14 opened
      Entered as its own task rather than folded into 4.14: 4.14 is a test task, and
      what the measurement under it found was a **behaviour** nobody had specified.
      `ladder._MODEM_ROUTES` and the withholding branch of `ladder.walk`; the rung is
      recorded with the new outcome `withheld` rather than skipped, because a rung that
      vanishes from the row list is a verification whose failure has no reason on any
      screen. No second alert: the refusal already woke the operator with its vendor
      named.
      🔴 **The norm is narrow on purpose, and the positive control is what holds it
      there.** It turns on who the vendor refused and nothing else — a decline of the
      *subscriber* still falls through to the modem the rule names, because that is a
      statement about one person rather than about this gateway. A mutation widening the
      condition to every advancing outcome turns that control red. `WITHHELD` needs no
      migration: `verification_rungs.outcome` carries no CHECK constraint.
- [x] 4.15 Test: a verification outcome pushed to the application is distinguishable from a message status push, so a verification id cannot be read as a message id
      🔴 **The answer was no, and the code was wrong — see 4.15a.** The body named its kind
      (`"object": "verification"`) and still carried the verification's number in `id`, the
      field the message contract names its own subject in. `failed` and `expired` are words
      both bodies use, so a receiver keyed on `id` and `status` — the whole of the older
      contract — acted on it and marked an unrelated message. The guard reads the message
      contract off a **real** message push rather than off a remembered description of it,
      because the description is what rots. Five mutations bite, including one that moves the
      message contract underneath the guard, and one that gives the verification body a
      `message_id` carrying the same number — which body-to-body comparison alone cannot see.
- [x] 4.15a Implement the distinction: the verification push carries its subject in
      `verification_id` and no `id` at all
      Not a second field beside `id` — `id` is gone from the body. A verification number
      sitting in `id` is readable as a message identifier whatever else the body says, and the
      requirement forbids exactly that. Measured on a file-backed database: message 1 and
      verification 1 collide from the first row of each table, so the two spaces overlap at
      once rather than eventually. The push has never reached a customer — the verification
      door is not on `master` — so no live receiver is owed a migration.
- [x] 4.16 Implement the routing rule as a typed `settings` entry per 2.3, with МегаФон as its only initial entry and its value an **ordered list** — `[tg_gateway, flash_call]` — as data, not as a branch, and with no `app_id` in the rule
      Built 20.09.2026 as the typed setting `operator_routes` in
      `app/verification/rule.py`. Two entries name no operator — `*` for an
      operator with no entry and `?` for one that could not be resolved — and
      `refuse` is a way of declining rather than a way out. Matching is NFKC +
      strip + `casefold`, in Python and never in SQL. Eight mutations bite.
- [ ] 4.17 Implement the verification endpoints, the code store and the uCaller adapter against the samples captured in 1.3
- [x] 4.17a Implement the Telegram Gateway adapter against the samples captured in 1.6 — `checkSendAbility`, `sendVerificationMessage` carrying our own `code` and a `ttl` taken from the verification's remaining lifetime, `revokeVerificationMessage`, and the signed callback. `checkVerificationStatus` is deliberately not used: the attempt counter stays here
      Built 20.09.2026 in `app/verification/tg_gateway.py` (the three vendor calls, the
      tolerant parser, and `callback_verifies`) and `app/verification/tg_callback.py`
      (the door, mounted at `POST /verifications/tg-callback` with no application token,
      because the vendor holds none). 45 tests across
      `tests/test_tg_gateway_adapter.py`, `tests/test_tg_callback.py` and
      `tests/test_route_probes.py`; sixteen load-bearing guards checked by mutation.
      ⚠️ **Implemented is not reachable.** `check_send_ability` and
      `send_verification_message` have **no production caller** — the ladder that drives
      them is 4.16 and the route chooser, and neither exists yet. Everything downstream
      of a message the vendor already took is live; nothing yet sends one.
- [x] 4.18 Implement the per-operator count of refusals, reachable from the admin console — the rule outlives the outage that justified it, and nothing else will say so
      Built 20.09.2026 as `app/verification/refusals.py` plus the table
      `route_refusals`: a row per refusal, not a running total, because the
      question is also "how many **since this entry came into force**" and a
      total cannot be asked that afterwards. At seventy a month a row each costs
      nothing. **In the database, not in the process** — the rule is reviewed on a
      scale of months and this gateway is deployed on a scale of days.
      Grouped on the folded operator name in Python: the two spellings of МегаФон
      counted apart make the rule look half as expensive as it is, and this is the
      one direction that matters. Shown at `/admin/stats` under the same period
      control as the other counters — the counters page, not a new surface.
      ⚠️ **Counted is not produced.** The only caller is `ladder.walk`, which has
      no production caller of its own. The producer of the measured seventy a
      month is the send-path refusal, task 4.6, and it calls `record` the same way.
- [x] 4.18a Implement the way to observe recovery — the requirement carried a SHALL
      and no task at all until 20.09.2026, and the owner chose the alert over the
      probe send: the probe puts a real message in front of a real person.
      `refusals.review_step` reconciles what is in force and reports an entry that
      has outlived `operator_route_review_days` (30), once per period, naming what
      it has cost per application. Hourly from `main.py` as the non-essential
      `routing-review` loop. Reconciled on the tick rather than by a save hook: a
      rule can change by paths that never pass through the console, and a record
      kept only by the console dates those to never.
      🔴 **This is the first thing on this branch that executes in production.**
      It reads the rule and writes its own table; after thirty days it raises one
      alert per operator entry.
- [ ] 4.19 Update `docs/` with the two paid rungs: what each costs, how to change the rule **and its order**, how to top up each of the two balances, how to tell from a verification which rung carried it and what it cost, which application is entitled to spend, and what to do when МегаФон recovers
- [x] 4.20 Test: a verification belonging to one application cannot be read, checked or exhausted by another — by id, with a valid token
      Held already — `get_verification` and every conditional update in
      `check_verification` are scoped by `app_id` — and bitten on both: unscoping either
      reddens. The guard here drives all three verbs from a **valid** token of another
      application and spends more than the limit's worth of wrong codes at it, because
      exhausting is the quiet verb: a stranger need read nothing and can still burn a
      person's five attempts at a barrier they are standing at. Paired with the positive
      control that the owner's own three calls answer, without which the negative passes
      on a door that refuses everybody.
- [ ] 4.21 Test: a blocked number is refused a verification, and a call that fails to connect does not advance that number's permanent-failure count
- [x] 4.22 Test: the code appears in no API response, no alert and no log line, and stops being readable once the verification is terminal
      The response half is enumerated **from the router**, not from a list kept in the
      test: a census of surfaces is never complete and goes stale in silence, and the next
      door added to this capability is exactly the one a list would miss.
      The log and alert halves are driven over a path where the code genuinely travelled
      to the vendor and the rung then failed loudly — a guard on a path the code never
      reached would be the hollow shape this branch has already paid for three times.
      ⚠️ `caplog` is levelled on the gateway's own loggers, not on the root: root at DEBUG
      turns on asyncio's task reprs, and a coroutine repr carries its arguments — the code
      among them. That is the harness printing the secret, not the gateway.
      The destruction half covers all three terminal endings in one run. The rung-failure
      ending was the one the inherited guards missed, though it is where every walked
      ladder arrives when nothing carried the code.
      🔴 A field-shaped guard cannot hold this requirement: `reason` is free text and it is
      not ours. That is 4.22a.
- [x] 4.22a Keep a vendor's words from carrying the code out to the application
      Found by 4.22 and given its own number for the same reason 4.10a has one.
      🔴 **Measured 21.09.2026: a `reason` carrying the code reached
      `GET /verifications/{id}` and the console's expanded row with the whole suite
      green.** Every guard on this requirement watched the *fields*, and a field of type
      `str` says nothing about what is inside it. `reason` is filled from a vendor's error
      string and from an exception's message, and neither is ours to write — so the
      requirement cannot be held by writing careful strings.
      `_without_the_code` in `app/db/queries.py` takes the verification's own code out of
      any free text about to be stored against it, at the three writes that accept such
      text. Placed at the **write** because the readers are many — the poll, the console,
      an alert quoting a reason — and a census of readers is never complete, while there is
      exactly one place the text becomes stored. Replaced visibly (`****`) rather than
      removed: a reason that silently loses a word reads as a vendor that said less than it
      did.
      ⚠️ The samples captured from the live Gateway show no code echo today. That is
      precisely why the guard is not written against them: it would be held up by somebody
      else's habit.
      ⚠️ `record_verification_rung` has no caller reaching it with a reason today —
      `ladder.walk` writes that row before it has anything to say. Guarded by calling the
      border directly, or an unreachable scrub with no guard on it gets deleted as dead.
- [ ] 4.23 Test: a verification whose vendor-reported code differs from the requested one fails with that reason rather than matching digits the vendor never dialled
- [x] 4.24 Test: a stored routing rule that cannot be parsed alerts and does not route as an empty rule; an entry naming an unknown route is refused at save time; an operator name with surrounding whitespace still matches
- [x] 4.25 Test: the refusal alert fires on stock settings (`notify_send_errors` off) and is deduplicated per operator and route
      🔴 **The handoff sent the previous session at the wrong alert.** It named
      `dedup_extra="absent:{route}"` in `ladder._attempt`, which belongs to a
      different requirement — a route nothing is configured to carry. This task's
      own scenario says "a **message is refused for want of a usable route**", and
      no such refusal existed anywhere in the code: `rule.route_for` has no caller
      in the sending path, and `ladder.walk`'s rule-refusal branch wrote no log
      line and raised no alert. So 4.18 and 4.25 turned out to be one mechanism
      that was missing, not a guard on one that was there.
      The guard drives the **real** `notify` over a fake notifier rather than
      patching `notify` itself: the toggle lives inside `notify`, and patching it
      would step over the half of the task that says "on stock settings".
- [x] 4.26 Test: the spend ceiling refuses a paid verification with its own reason, places no vendor call, and is not reported to the application as a vendor failure
      `gates.ceiling_gate` in `app/verification/gates.py`, counted over the rungs of
      both paid routes in rolling windows. The test asserts on the carrier not being
      called rather than on the outcome, and on no rung row existing: a refusal of ours
      inside the vendors' count would be our refusal reported as their failure.
- [ ] 4.27 Test: a verification carried by the modem whose message fails or expires fails the verification, and that message raises no message-status push
- [x] 4.28 Test: the expiry sweep expires an untouched verification and notifies once; the writer-enumeration test covers verification state writers
      The sweep half was already held and bites four ways (the sweep not called, the sweep
      taking rows that have not expired, the announcer's claim made unconditional, the
      announcer fed open rows).
      🔴 **The second half did not exist.** What stood there was a *rule* — no writer marks its
      own row announced — applied to a regular expression over the file's text, and it was
      blind three ways and noisy a fourth. Blind: a write with its fields in another order, a
      write with the status bound as a parameter, and an f-string, which is not a string
      constant at all — and the expiry sweep itself is an f-string, so the guard was silent
      about the one writer this task names. Measured: two new terminal writers, each marking
      its own row announced, left the whole suite green. Noisy: the 500-character window
      around a match reached into the next function, so an unrelated writer added below a
      genuine one raised a false alarm — a guard that cries wolf is proof-read away.
      The census is now taken off the syntax tree, holds each writer by name and by the
      statuses it writes, and the rule is applied per writer rather than per text window.
      Five mutations bite and a sixth — a non-terminal neighbour marking rows announced — is
      correctly silent, which the old guard was not.
- [x] 4.29 Test: two concurrent checks confirm at most once and consume at most one attempt
      🔴 **The second half was unasserted.** Confirming at most once was guarded;
      "consumes at most one attempt" was not, and bumping the attempt count inside the
      already-confirmed branch — leaving the answer word alone — left the suite green.
      That branch is reached by a person double-tapping Confirm with the **right** code,
      which is the ordinary way to reach it, and an attempt spent there taxes a person for
      the gateway's own race. Paired with the control that a wrong code still costs
      exactly one, or an implementation that never counts would satisfy it.
- [ ] 4.30 Implement verification retention and the destruction of a terminal verification's code
- [x] 4.31 Make a single verification visible in the admin console beside the messages for the same number — every rung attempted, each rung's vendor outcome, whether it was confirmed, recorded cost and whether it was refunded. The counters answer "how much", and a support call is always about one person
      Built 20.09.2026 in the expanded row of `/admin/messages`, under the
      conversation — the owner's choice of placement on 20.09.2026, and the
      literal reading of "beside the messages for the same number": a support
      call arrives with a person's number, not with a verification id.
      `verifications_for_phone` **lists its columns instead of starring them**,
      and that is the guarantee rather than a style — `SELECT *` hands a live
      code to a template, on the one screen that renders a subscriber's number
      beside their conversation (task 4.22).
      Five mutations bite. One started green and was understood: starring the
      columns leaks nothing today because the template never prints `v.code` —
      the same shape as 4.51, and answered the same way, with a guard on the row
      the query produces directly.
      ⚠️ **One assertion here is a tripwire rather than a guard**: since 4.54 a
      refund zeroes the recorded cost, so there is no gross figure anywhere for a
      screen to print, and the test that forbids it cannot go red against today's
      code. It is kept for the day somebody adds one back.

### The ladder

- [x] 4.32 Test: the order of the rungs comes from the rule, not from the code — rewriting an entry from `[tg_gateway, flash_call]` to `[flash_call, tg_gateway]` while the service is running reverses which rung is tried first, with no restart
      The driver takes the order as data and never decides it; the test
      rewrites the entry mid-run and watches the order follow.
- [x] 4.33 Test: a `checkSendAbility` that declines costs nothing, advances to `flash_call`, and records the decline against the `tg_gateway` rung
- [x] 4.34 Test: a `checkSendAbility` that confirms is followed by **exactly one** `sendVerificationMessage` carrying that `request_id`, no call is placed, and the confirmed check is never abandoned
      With 4.35: the confirmed check is recorded with its `request_id` and cost
      **before** the send, and the send is made exactly once.
- [x] 4.35 Test: the same `request_id` is never sent twice — the second send is not attempted, because the vendor answers it with an error rather than a second message
- [x] 4.36 Test: a `checkSendAbility` that does not answer within the bound advances to `flash_call` **and** is counted as possibly-charged spend attributable to no verification. **This test fails on any implementation that treats a timeout as a decline**, which is the natural way to write it and the way that hides money
- [x] 4.37 Test: the spend ceiling and the application's entitlement are evaluated **before** any rung is contacted — a refusal by either makes no ability check at all. Assert on the vendor client not being called, not on the outcome
      Both gates now exist and are passed in by `gates.for_paid_ladder(app_id, phone)`,
      which assembles all three — entitlement, ceiling, per-number limits — in one
      place, so that a door added later cannot be a door that forgot one. Three
      mutations guard the assembly by dropping each gate in turn.
      ⚠️ **Assembled is not reached.** `for_paid_ladder` has no production caller: the
      door that walks the paid ladder belongs to `verify-by-inbound-contact` and does
      not exist yet. The same caveat as 4.17a, and for the same reason.
- [ ] 4.38 Test: one acceptance bound covers the whole ladder, not each rung — a slow first rung does not double the time the application waits, and the response still names a method rather than pending
      The ladder's half is built and guarded (`tests/test_ladder_walk.py`). The
      response naming a method rather than pending is the door's half and is not built.
- [x] 4.39 Test: a message the Gateway accepted and then did not deliver within its `ttl` fails the verification with that reason, places **no** call, and records the refund. This is the open question 2.6 pinned as the default until the owner decides otherwise
      Already held by `app/verification/tg_callback.py`; what was missing was a
      guard that no call follows, and it exists now that a ladder could place one.
- [x] 4.40 Test: the `ttl` handed to the vendor is the verification's remaining lifetime, not a constant of the adapter's

### The Gateway's own outcomes

- [x] 4.41 Test: `delivered` and `read` leave the verification open and unconfirmed; only a correct code at `/check` confirms it
      The two existing assertions said `pending` and stopped there, which an implementation
      that confirms nothing at all satisfies. **Open** means more than **not confirmed**: it
      means the code can still do its work, so one verification is carried the whole way —
      delivered, read, then confirmed by its own code at the check door — with the negative
      half beside it, that a delivered message does not make a wrong code right. Four
      mutations bite: `delivered` confirming, `read` closing, the check door confirming any
      code, and the check door confirming none.
- [x] 4.42 Test: a verification carried by `tg_gateway` that becomes confirmed, expired or out of attempts revokes its outstanding message at the vendor
      Hung on `announce_verification_outcomes` — the one pass that sees all three
      endings, so a writer added later cannot be a writer that forgot.
- [x] 4.43 Test: a callback whose signature does not verify changes no state and is counted; so is a correctly signed one whose timestamp is outside the tolerance; a correctly signed and timely one updates the recorded delivery outcome
      All three branches had named green tests, and the count was genuinely asserted — the
      predicted hole was not there. **Two others were, and both were found by biting.**
      🔴 The replay guard asserted only the verification's own row, not the rung: a callback
      refused on its timestamp could still write the rung's delivery outcome and the whole
      suite stayed green. "Changes no state" is the whole of the requirement and the rung is
      state; the edit that reaches it ("record what the vendor said, just do not act on it")
      is a plausible one in its own right.
      🔴 The tolerance window was guarded in one direction only. Narrowing `abs(now - sent_at)`
      to `now - sent_at` left the suite green — and a window with no far edge is a window a
      captured callback stays valid in for ever, because the timestamp is signed and cannot be
      moved back inside a bound that does not exist.
      Seven mutations bite, and the zero-tolerance control fails loudly rather than silently.
      ⚠️ **Named, not taken:** both rejection kinds are counted under one key, so a run of
      clock skew reads as a run of bad signatures. The module's own docstring says the kinds
      are counted apart because they mean different things, and here they are not. The
      requirement does not demand the split. **Owner's.**
- [x] 4.44 Test: the attempt counter is this gateway's — a wrong code on a `tg_gateway` verification consumes one of our five and calls no vendor endpoint to decide it

### Entitlement, template, credentials

- [x] 4.45 Test: an application whose entitlement is off is refused a paid verification with a reason naming the entitlement, no vendor is contacted, nothing goes over the modem instead, and the refusal is not reported as a vendor failure
      A schema change rather than a setting: `apps.may_spend`, read per call so the
      switch needs no restart, operated at `POST /admin/apps/entitlement`. Being active
      stays the stronger switch — a deactivated application does not spend whatever its
      entitlement says. "Nothing over the modem instead" is guarded by counting the
      `messages` rows after the refusal, not by reading the reason string.
- [x] 4.46 Test: a newly issued token is refused a paid verification — the entitlement defaults to off, and this is the positive control for 4.45
      And the half a schema change gets wrong silently: a second test builds `apps` in
      its pre-change shape, populates it, then migrates, and asserts the row that
      predates the column comes out switched off. A default that reached only new rows
      would leave the guarantee empty on exactly the installations that have the defect.
- [ ] 4.47 Test: an application with no template is refused **at accept** for a `sms_out`-routed verification, and is **not** refused for a paid-rung one, because neither paid rung carries text of ours
- [x] 4.48 Test: a template with no code placeholder, with two, or with an unknown one is refused at save time
      Built 20.09.2026 as `app/verification/template.py` behind the typed setting
      `verification_templates` — a **setting**, not a schema: the requirement says
      "per application, in the manner `delivery-dispatch` already configures a
      dispatch route per application", and a column in `apps` would pay with a
      migration for what `settings` already does. Not carried by `delivery_dispatch`
      itself, which demands a `webhook_url` on every entry.
      Two norms beyond the three asked for, both recorded in the spec: one
      application named twice is refused (order of the list would decide, silently),
      and an unreadable setting is never read as an absence of templates.
      Composing uses `replace`, never a formatter: a template is operator-supplied
      text, and `{0}` in a formatter reaches into the arguments.
      Nine mutations bite. Two started green and were understood rather than
      rewritten: the blank-template branch is shadowed by the placeholder count
      (the guard now asserts the **reason**, which is the only thing that branch
      produces), and save-time normalising is shadowed by `parse` stripping on read
      (the guard now asserts the **stored** form, which is what the page re-reads).
- [ ] 4.49 Test: a vendor credential written to `.env` for a key that already has a row in `settings` is not used, and the value in `settings` stays in force
- [ ] 4.50 Test: a rung whose credential is absent is not attempted, alerts on stock settings, and the ladder advances past it — the one place where a configuration gap costs money rather than traffic, and therefore the one that must be loud
      Built for the case of a route nothing is configured to carry: not attempted,
      alerted on stock settings (`notify_routing_errors` defaults on), ladder advances.
      The credential-shaped half — a rung whose token is blank — belongs with the
      wiring that decides which carriers exist, and that is the door's.
- [x] 4.51 Test: the settings page reports each vendor credential as configured or not and renders neither value
      Already held; the task was the guard. `tests/test_vendor_credentials.py`
      reads the page in **both** locales — the console's default is Russian, and a
      guard written against the English wording alone would pass while the Russian
      page said nothing. Four mutations bite. One of them started green and was kept
      after being understood: the view may hand a secret's value to the template and
      the page still leaks nothing, because the markup ignores it for a password
      field — so the whole guarantee rested on one line of markup. There is now a
      guard on the row the view produces as well. **Half empty:** uCaller has no
      credential to report (task 1.1), so what is guarded is one vendor of two.

### Money across two vendors

- [x] 4.52 Test: the spend ceiling counts both rungs together — verifications that advance from the first rung to the second reach it even though neither rung reaches it alone
      With its control: five on each rung does **not** reach a ceiling of eleven, so it
      is the count that refuses and not the mixing of two routes. Every attempt counts,
      including the free ones — an ability check that never answered may have been
      confirmed and billed without our learning its `request_id`, which is the spend
      most likely to be invisible.
- [x] 4.53 Test: the balance floor is held against each vendor separately, and the alert names which vendor it is about
      `app/verification/balance.py`. 🔴 The floor is never polled: `remaining_balance`
      is the account's balance only in the answer to a **confirming** ability check,
      which is the billed call, so the floor is held against what arrives with ordinary
      traffic. The test drives the carrier through a check reporting 2.5 and a send
      reporting 9999 and asserts the floor fires on the check's number — a gateway that
      believed the send would announce that a draining account had refilled itself.
      A rung with no floor configured is reported as unwatched rather than read as fine.
      ⚠️ The uCaller floor ships at zero: that rung has no account (1.1) and no observed
      cost, so any number would be a guess dressed as a setting.
- [x] 4.54 Test: a request the vendor reports as refunded lowers the recorded spend for that verification to nothing, rather than keeping the charge with a note beside it
      `record_rung_delivery` zeroes the cost on an affirmative refund; `refunded` keeps
      the fact and the vendor's own words stay in `reason`. A settled refund is not
      recharged by a later write, and that rule sits at the write rather than in a note.
      🔴 Backed by no observation: the refund path cannot be reached by a probe, so the
      tests drive the recording directly and claim nothing about having seen one.
      The two-state `refunded` column is untouched — the three-state column is the debt
      of `verify-by-inbound-contact`, which owns the table.
- [x] 4.55 Test: the per-number limits are applied to the ladder as a whole, not to the `flash_call` rung alone — a second request inside the window is refused before the Gateway is asked, because the Gateway publishes no limits and silence is not their absence
      The window is rolling rather than a calendar day, and the count is taken
      over the rung attempts of both paid routes.

## 5. Verify against the real thing

- [ ] 5.1 Run one verification end to end to `+79851600019` on the production host: the call arrives, the digits are read, `/check` confirms, and the outcome reaches the application. The modem route cannot reach that number at all today, so this is the only proof the change works
- [ ] 5.2 Confirm a non-МегаФон verification still arrives as an SMS, unchanged, on the same code path — **to a number the owner has released for probes, not to a customer**. This host carries live customer traffic, and a verification sent to prove a code path still reaches a real person's phone
- [ ] 5.3 Confirm the new refusal fires on a message the owner originates to a МегаФон number, and that the count in 4.18 registers it. **Owner's call whether to also wait for `gmp_app`'s next real message** — as originally written, the first witness of the new behaviour is a customer's message rather than a probe
- [ ] 5.4 Watch the first week's spend against the costs recorded in 1.4 and 1.8 — **both balances**, and with refunds subtracted. A week whose recorded spend and whose two `remaining_balance` readings disagree is either an unattributed possibly-charged check or a refund that was not reflected, and both have counters to look at
- [ ] 5.5 Run one verification end to end over the **Gateway rung** on the production host, to a number reachable in Telegram that the owner has released for probes: the message arrives, the code is ours, `/check` confirms, the signed callback is accepted, and the outcome reaches the application. Until this runs, the cheap rung is proved only off the production host
- [ ] 5.6 Watch one verification **cross the rungs** in production — a МегаФон number the Gateway declines, followed by a call — and confirm the two rungs are recorded as two attempts of one verification, with two vendor identifiers and one code. This is the only proof that the ladder is a ladder rather than two routes that happen to be configured together
- [ ] 5.7 Confirm on stock settings that an unconfigured rung is loud: with the Gateway credential absent, a paid verification alerts and completes by call. **This is the failure mode that costs money quietly**, and the only one in the change where a configuration gap does
