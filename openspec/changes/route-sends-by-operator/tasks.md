The unverified links come first. The ladder has two rungs and each is unproven on its own:
everything below is worth nothing if neither a Telegram message nor a flash call reaches a
МегаФон subscriber. **Start with 1.5** — it is the only probe that costs nothing and needs no
funded balance.

## 1. Prove the links before building anything

- [x] 1.1 Owner: create the uCaller account and fund the balance — the first call fails without it. Where the credentials live is settled (2.3: `settings`, marked secret), so the account and the balance are now the whole of the blocking part
      🟢 **Done by the owner 22.09.2026** — the account exists and the balance is funded
      by card. The owner holds the API key and is ready to save it.
      ⚠️ **There is nowhere to save it yet, and that is the next session's first job.** No
      `settings` entry for uCaller exists: `Spec(` gives `tg_gateway_token` and no
      sibling. The entry is 2.3's — a secret in `settings`, never `.env`, because
      `seed_from_env` copies a variable only into a key with no row and is therefore
      already spent from the second start onwards.
      🟢 **The home exists as of 22.09.2026 — task 4.17d.** The reference was read by
      layers and the answer is **two** values, not one: `ucaller_key` (secret) and
      `ucaller_service_id`. The owner pastes each verbatim into the settings page; the
      gateway joins them into `Authorization: Bearer <key>.<service_id>` itself.
      🔴 **The earlier reading — "a single bearer string carrying both an API key and a
      service id", 08.09.2026 — was right about the header and wrong about what to
      store.** The vendor takes the pair three interchangeable ways and its cabinet hands
      the two values over separately, so a joined value would have put the dot in the
      owner's hands — and a bearer whose dot is missing or doubled looks *configured* on
      the settings page and arrives as a `401` on the first paid call. Reference captured
      verbatim in `captures/ucaller-reference-2026-09-22.md`.
- [ ] 1.2 Place one `initCall` to `+79851600019` (the operator-confirmed МегаФон number the owner released for probes) and confirm the phone actually rings and shows a number whose last four digits match the `code` we passed. **If it does not ring, the `flash_call` rung is void** — and that is now survivable rather than fatal, provided 1.5 and 1.7 show the Gateway rung carrying it
      ⚠️ **Narrowed by 1.3, not replaced by it.** The wire shapes are captured and the
      parser no longer waits on this. What only a live call can still answer: does a real
      handset ring, do the last four digits match the `code` we passed, what a charge
      actually costs (1.4), and whether a live failure to connect answers in the same
      shape the test number did. It remains the owner's call and it remains paid.
- [x] 1.3 Capture the live responses of `initCall` and `getInfo` verbatim into the change folder — the contract so far comes from the vendor's reference only, and no parser is written against a reference when a sample is one call away
      🟢 **Done 22.09.2026, both outcomes, for nothing.** Five answers in
      `captures/uc-1.3-*.json`, findings in `captures/ucaller-samples-1.3.md`: the
      credential self-test, `initCall`/`getInfo` for the reachable test number
      (`call_status: 1`) and for the unreachable one (`call_status: 0`).
      🔴 **And the first sample already broke what the reference would have been parsed
      into.** `initCall` for the unreachable number answers `status: false` with **no
      `error` and no numeric code** — carrying instead an allocated `ucaller_id`, the
      masked number, and our own code as a string under the very `code` key the
      documented error envelope uses for its number. A parser reading "not `status` →
      `code` is the error" gets `"1234"`; one reading "not `status` → nothing was
      created" throws away an authorisation that exists and has two free repeats. The
      norm is now in the spec: a refusal is told apart by the presence of `error`.
      ⚠️ Not observed at all: `call_status: -1`. Both outcomes arrived already resolved,
      so the bound on waiting for it still rests on the reference.
      🟢 **This was free and did not wait on 1.2.** The reference publishes test numbers:
      `79000000001` always succeeds, `79000000002` always fails as unreachable, and "все
      тестовые авторизации не будут тарифицироваться" — so both wire shapes, including
      `call_status: 1` and `call_status: 0`, can be captured against the live API for
      nothing as soon as the credential is in `settings`. Read 22.09.2026;
      `captures/ucaller-reference-2026-09-22.md` §8.
      ⚠️ What a test capture cannot show is a *populated* one: `phone_info` may be empty,
      a free authorisation presumably costs 0, and a parser written only against test
      answers has never seen a charge. Capture a real one too when 1.2 happens, and label
      which is which.
- [ ] 1.4 Confirm from the captured `getInfo` what `cost` and `balance` actually are for our account, and whether the 0,80 ₽ list price is what we are charged
      ⚠️ **The reference sharpens the question, 22.09.2026.** `getInfo`'s `balance` is
      documented as "Состояние баланса **до списания** этой операции" — the balance
      before this call was charged, so read as the current balance it is high by exactly
      `cost`, and a floor held against it fires one verification late. And `cost`'s type
      column says `bool` while its example carries `0.3`, which is a vendor typo worth
      not writing a parser to.
      🟢 **Half measured 22.09.2026:** the account holds **1000,00 ₽**, and it is
      identical before and after both test authorisations at `cost: 0.00` — so "test
      calls are not charged" is now a measurement rather than a promise, and `cost` is a
      number rather than the `bool` its type column claims. What is still unmeasured is a
      **charge**: the 0,80 ₽ list price is neither confirmed nor refuted, and at zero
      cost `balance` before and after a charge are indistinguishable, so the "balance
      before the charge" reading above cannot be checked on these samples either.
      🟢 **`getBalance` called 22.09.2026** — `rub_balance: 1000.00`, tariff `uni`
      («Единый»), the same number `getInfo` reports as `balance`, and the account stood at
      1000,00 ₽ after it. So uCaller's balance is pollable where Telegram Gateway's is
      not, and the inference from the missing `cost` field is not contradicted. ⚠️ It is
      still not *proved* free — a charge would only show on the next reading — and the two
      balances cannot be told apart on this account at all, because `getInfo.balance` is
      documented as the balance before the charge and there has not been a charge.
- [x] 1.5a Owner: open **gateway.telegram.org**, "Log in to Start", confirm in Telegram, then copy the token from `gateway.telegram.org/account/api`. 🔴 **This is a different door from the one that is shut:** the Gateway needs no `my.telegram.org` and no `api_id`/`api_hash` — those are the user-account route's, and their refusal on 18.09.2026 does not reach here. Costs nothing and unblocks 1.5 by itself
- [x] 1.5 **Prove the Gateway rung end to end for nothing, before any balance exists.** Free testing is tied to the login: *"you'll be able to send free verification messages to the Telegram account tied to the number you used to log in"* — so the owner logs in with the number the probe will target. Send a code we generated to it, with an explicit `ttl`, and watch the whole mechanism: the code we supplied arrives unchanged, the `delivery_status` moves, the callback is signed, `revokeVerificationMessage` withdraws it. **Done 18.09.2026 and it proved more than expected.** Our code arrives unchanged, delivery is `sent`→`delivered` in one second and `read` at 71 s, `request_cost` is 0 on an account whose `remaining_balance` is 0 — so the whole mechanism runs before any Fragment top-up. 🔴 **Revocation, however, is observably inert:** `ok/true` twice, message still on screen both times, `delivery_status` never `revoked`. Findings and their limits are in `captures/README.md`. Proves our half of the rung and nothing about a customer's reachability, which is 1.7
- [ ] 1.6 Capture the live `checkSendAbility`, `sendVerificationMessage` and callback payloads verbatim into the change folder, including the callback headers. The reference gives field names; the sample gives what is actually populated, and the signature cannot be verified against a document. **Half done 18.09.2026 — `captures/` holds `sendVerificationMessage`, `checkVerificationStatus` and `revokeVerificationMessage` with their notes. 🟢 **`checkSendAbility` arrived 20.09.2026 with task 1.7** — `probe-1.7-check-able.json` and `probe-1.7-check-declined.json`, both halves of it. Still missing: the callback — ⚠️ **which was said to ride with 1.9 for want of a public HTTPS address, and that was wrong: `sms.deralsem.ru` answers publicly from edge and reaches this house over the live `wg-burns` tunnel, so the callback can be captured as soon as there is a request to report on**.** Not tickable until both arrive
- [x] 1.7 Owner: fund the Gateway balance — *"To send messages to other Telegram users via the Gateway API, you'll need to fund your account"*, and the funding page routes through **Fragment**, not a card. That is the one friction this rung has that uCaller does not, and it is worth knowing before the account is opened rather than after. Then run `checkSendAbility` against `+79851600019`. **This is the Gateway rung's equivalent of 1.2 and it is a separate question from 1.5** — whether a МегаФон subscriber is reachable in Telegram at all decides whether the cheap rung ever runs, or whether every verification pays for a declined check before calling anyway. 🟢 **Done 20.09.2026, and it answered more than it asked.** The balance was funded through Fragment and both numbers went in one run, from derserver over the wire. **The subscriber is reachable: `checkSendAbility` against `+79851600019` confirmed, `request_cost: 0.01`, `remaining_balance: 99.99` — so the cheap rung runs.** The decline, captured for nothing against a real working number whose owner has no Telegram, is spelled **`PHONE_NUMBER_NOT_AVAILABLE`**; `DECLINE_ERRORS` is no longer empty and an ordinary unreachable subscriber no longer raises an alert. Three further findings, each of which contradicts something we had written: `remaining_balance` is the account's balance **only** in the answer to `checkSendAbility` (the send answered `0` while the account held 99.99 — 18.09 could not tell, because the account really was empty then), so Telegram's balance cannot be polled for free; revocation on the **paid** path is not inert after all — it sets `verification_status: expired`, though `delivery_status` still never becomes `revoked`; and one `updated_at` serves two delivery statuses, so it is no transition clock. 🟢 **The probe argument also became a measurement, which was the owner's condition of 20.09:** the vendor answers in **178–285 ms** over the wire against a `verification_probe_timeout` of 5 s — roughly eighteenfold headroom — so the probe stays as it is. Samples and the full reading are in `captures/README.md`
- [x] 1.8 Confirm from the captured `RequestStatus` what `request_cost` and `remaining_balance` are for our account, and confirm a refund appears as `is_refunded` by letting one message expire unread inside a short `ttl`. **Half done 20.09.2026:** `request_cost` is `0.01` per confirmed check and `remaining_balance` is real — but only in the answer to `checkSendAbility`, which is the billed call, so the balance cannot be read for nothing (recorded as a requirement in `phone-verification`). ⚠️ **The refund half is untouched and is now the weakest thing in the change:** `is_refunded` has been absent from ten captures running, no message has ever been left to expire unread, and the ladder's economics — "a confirmed but undelivered message is refunded" — rest entirely on one sentence of the vendor's reference. 🔴 **And it cannot be bought for `0.01` after all — the reference settles that too, 20.09.2026.** The refund hangs on non-**delivery**: *"If a message is successfully delivered within the `ttl`, it will not be refunded."* A confirmed `checkSendAbility` says the subscriber is reachable, and every message we have sent was delivered within a second — so there is no way to stage a refund deliberately. It is reached only by a subscriber confirmed reachable who then is not reached, which is a wild event and not a probe. **This task's refund half is therefore not work but a watch**, and the honest options are to wait for one in production or to close it with a named refusal
      🔴 **Closed 22.09.2026 by the owner: the refund half is struck and the watch is kept.**
      The first half stands measured — `request_cost` is 0.01 per confirmed check and
      `remaining_balance` is real. The refund half is not work and never was: a refund hangs on
      **non-delivery** within the `ttl`, a confirmed `checkSendAbility` says the subscriber is
      reachable, and every message this gateway has sent was delivered inside a second — so
      there is no way to stage one deliberately, and ten captures running have carried no
      `is_refunded`. Recorded rather than deleted: the ladder's economics rest on one sentence
      of the vendor's reference, and the spec now says so in those words. A row in the waiting
      registry carries the watch, with a probe that reads the database for the first refund
      actually recorded; it matures on its own if one ever arrives.
- [x] 1.9 **Decided 18.09.2026: the restriction stays off.** ⚠️ **Rewritten 18.09.2026 against live measurement: all three premises this task was written on are wrong.** (1) **The house does not egress from the house's address.** `home.deralsem.ru` resolves to `46.188.29.113`, but everything this host emits leaves from **`193.233.254.161`** — measured from the gateway itself against both a proxied and a direct destination, which answered the same address. That is `ffm`, a machine in the owner's own estate on a static address, and it is the **home router** that puts traffic there: neither this host's routing table nor anything in this repo does. The router also intercepts DNS — `gatewayapi.telegram.org` answers `198.18.13.246` on the house's link, an address belonging to that proxy rather than to Telegram, and naming the carrier's resolver explicitly returns the same fake answer, so the interception is on the path and not in the choice of server. (2) **There IS a tunnel, and this task's first reading of it was wrong.** ⚠️ **Corrected 18.09.2026 after the owner objected.** `wg-quick@wg-edge` is indeed `inactive` and `disabled` — but `wg-edge` is the placeholder name this repo's documentation uses, not the deployed one. The live tunnel is **`wg-burns`**: the house at `10.67.67.3`, edge at `10.67.67.1`, and `/etc/wg-tunnel-check.env` names it outright (`UNIT=wg-quick@wg-burns`, `PEER_ADDR=10.67.67.1`), so `reach-the-gateway-on-any-uplink`'s own watchdog is watching it and exiting zero. Edge serves **`sms.deralsem.ru`** from a server block of its own, proxying to `10.67.67.3` over that tunnel, and the name answers publicly from `178.250.157.233`. 🔴 **Reading a tunnel's absence off a placeholder name was the mistake, and it costs more than this task: 1.6's missing callback sample is no longer blocked for want of a public HTTPS address, and the captures note saying there is none is wrong.** What the tunnel does not do is carry egress — the house holds exactly one route into it, `10.67.67.1`. (3) **Edge would not present its stable address to Telegram anyway.** On `mprz.ru`, whose address is `178.250.157.233`, `ip route get 149.154.167.99` answers `dev wg0 src 10.66.66.2`, and `wg0`'s routes are exactly `91.108.4.0/22` and `149.154.160.0/20` through a foreign endpoint — so egressing the vendor calls through edge would show Telegram somebody else's address while showing uCaller edge's own. The candidate set that survives is therefore two, not three: **lock to `193.233.254.161`**, which costs nothing because it is already the address, at the price of a lock this repo can neither see nor be told about when the router's configuration moves under it; or **leave the restriction off** and let the vendor-side balance be the only cap, which is 1.10. ⚠️ **And the correction above strengthens the second rather than reopening the first:** now that the tunnel is known to be live, egressing the vendor calls through it is technically available — and it would show Telegram the foreign endpoint's address behind edge's `wg0`, which is somebody else's to change and cannot be allowlisted at all. ⚠️ **The restriction's shape is undocumented** — neither `core.telegram.org/gateway` nor the API reference mentions it at all — so whether it takes one address, a list or a CIDR has to be read off the cabinet before either option can be priced 🟢 **The owner chose to leave it off, and the argument that decided it is that the address is not ours to promise.** `193.233.254.161` costs nothing to allowlist because it is already the address, but it is held by the home router's configuration — which lives in no repository, in no history, and in nobody's changelog. A lock on it fails on the day that configuration moves, it fails silently, and the first witness is a verification code that was never sent. That is a worse failure than the one the lock defends against, because the defence it buys is already bought better by 1.10: a balance sized to weeks bounds a leaked token whatever address it is spent from. ⚠️ **This decision is cabinet configuration and lands as no requirement** — the gateway's behaviour does not change either way. What it does change is that 1.10 stops being a second cap and becomes the only one
- [x] 1.13 **Settle which field reports expiry, because our one sample and our one scenario disagree.** The spec's scenario watches `delivery_status.status` for `expired`; the 20.09.2026 capture put `expired` under **`verification_status`** while `delivery_status` read `delivered`. A gateway watching only the delivery field would have missed it. What is not established is whether the vendor's delivery vocabulary carries `expired` at all — that is a question for its reference, which has not been re-read against this. Costs nothing: it is a read, not a call. Until it is answered, nothing may be built that treats either field as the single authority on expiry. 🟢 **Answered the same day by re-reading the reference, and the answer is worse than the question.** Both vocabularies carry `expired` and they mean different things: `DeliveryStatus` is `sent`/`delivered`/`read`/`expired`/`revoked`, `VerificationStatus` is `code_valid`/`code_invalid`/`code_max_attempts_exceeded`/`expired`. The scenario was watching the right field all along — delivery expiry is the one the refund hangs on — and the sample was coherent, not contradictory. What the re-read bought instead is a named trap: **a bare `expired` is ambiguous between a refund and a shut code window**, and the spec now requires every reading of it to name its field
- [ ] 1.12 🔴 **The cheap rung does not survive a failover to the backup uplink, and that is a routing problem rather than an allowlist one.** Measured 18.09.2026 by real address bound to `wwan0`: `gatewayapi.telegram.org` and `api.telegram.org` both time out at fifteen seconds with no connection established, while `api.ucaller.ru` answers over the same interface in 0.17 s — so the interface carries traffic and it is Telegram specifically that does not arrive. The house reaches Telegram at all only through the proxy on the home router, and the backup uplink does not pass through it. Three consequences this change has to carry rather than assume away. The `tg_gateway` rung is unavailable for the whole duration of a wired outage, so the ladder spends its single acceptance bound (4.38) waiting on a rung that cannot answer before the `flash_call` rung is tried — and `flash_call` is reachable there, measured. The Gateway's signed callback cannot arrive over that uplink either, which bears on 1.6 and on whatever 1.9 decides. And the gateway's own Telegram alerting is dead in the same window, which belongs to `backup-uplink` rather than here, but which means an outage on this route reports itself to nobody. **The carrier is what drops it, and only it:** over the same `wwan0`, `cloudflare.com` answers in 0.34 s and `www.google.com` in 0.44 s, while both Telegram ranges — `149.154.167.99` and `91.108.56.130` — time out. 🔴 **And the owner has settled what that means, 18.09.2026: this is a defect, not a law.** The OpenWRT gateway at the house already exists and Telegram is fully reachable there — which is why the wired path works and why our probe over it succeeded. What is supposed to happen when the wire drops and `wwan-backup` fires is that the modem path is carried by WireGuard too. **It is not, and nothing on this host would make it so:** `ip rule` holds nothing beyond table 100 for the wired source address; a failover falls to the plain `default via 100.108.32.169 dev wwan0`; the only enabled WireGuard instance is `wg-quick@wg-burns`, whose single route is `10.67.67.1`; and `wwan-backup.sh` never touches WireGuard at all. ⚠️ **The fix is `backup-uplink`'s and not this change's** — it is the uplink that is missing its egress, and every other thing the gateway emits to Telegram during an outage is missing it identically, the operator alerts first among them. What this change owes is only to stop assuming: until that gap is closed, the `tg_gateway` rung is unavailable for the duration of a wired outage and the ladder must reach `flash_call` without spending its acceptance bound waiting on it. 🟢 **And a cheap fix is in view either way:** a route for Telegram's two ranges into `wg-burns` would reach edge, which already forwards exactly those ranges over `wg0` — which makes the rung uplink-independent, and which also puts Telegram's view of us behind an address nobody can allowlist, reinforcing what 1.9 decided

## 2. Decide what the proposal left open

- [x] 2.1 How long a verification stays open and how many wrong codes it tolerates. **Decided 18.09.2026: five minutes and five attempts, both settings.** They coincide with numbers the gateway already holds — `delivery_timeout_seconds` is 300 and `blacklist_threshold` is 5 — so a verification neither outlives the message carrying it nor answers "enough" differently from the blacklist. Propped from below by the free repeat, unusable sooner than sixty seconds, and from above by the vendor's ten-hour block on a number that asks too often. 🔴 Diverges from the ten minutes already stated to end users in the contract at the parking developer; task 3.1 carries that letter
- [x] 2.2 Where the SMS method's text comes from now that the gateway generates the code. **Decided 18.09.2026: a per-application template, refused at accept when absent, with no built-in default.** A default is a wording decision taken silently for applications that do not share a voice — `sp_app` is `SokolParking: ####` in 446 of 448 messages, the others are free text under other names, and a code signed by something a person does not recognise reads as the fraud it resembles. The template governs the `sms_out` route only: neither paid rung carries text of ours
- [x] 2.3 Where the routing rule and the credentials live. **Decided 18.09.2026: `settings`, with every credential marked secret.** `.env` was never a candidate once the code was read — `seed_from_env()` copies a variable into `settings` only for a key with no row, so it is a one-time seed and not a home — and a value there would need a restart to change, which drops sending sessions. Precedent for the secret flag is `alert_bot_token`
- [x] 2.4 Run `system-architect` and `gap-finder` on the delta. **Done 11.09.2026**, one round, both critics, seeded with `openspec validate --strict` and `check.py`. 32 findings deduplicated to 20, each checked against the code before acceptance; the accepted ones landed as normative requirements, not as prose. The ceiling is one round and it is spent
- [x] 2.5 Whether spending on a paid route is an entitlement of the application. **Decided 18.09.2026: yes, and off by default, including for a newly issued token.** Three of the four applications never send codes, so a default of on means the first mistake in any of them is billed rather than logged. It is not routing — the rule stays keyed on the operator alone — and a refusal for want of it is never reported to the application as a vendor failure, nor quietly carried over the modem instead
- [x] 2.7 **Which word survives for the flash-call route — DECIDED by the owner 18.09.2026.** One flat field, names disambiguated: `flash_call` for the vendor's call (our modem does not participate), `call_in` for the subscriber calling our SIM, `sms_out` for our SIM sending, `sms_in` for the subscriber texting us, plus `tg_gateway`, `tg_user`, `max_user`, `app_bot`. **`call` is retired outright** — it meant two different mechanisms in two changes — and `modem` is retired in favour of `sms_out`. Applied across this change's specs and tasks and in `verify-by-inbound-contact`; `reach-people-in-messengers` records it in its own task 1.1
- [x] 2.9 **Closed 21.09.2026 with a named refusal, and the refusal stands on two independent walls.** Read from the vendor's own pages that day; the whole record, with verbatim quotes and edition dates, is in `proposal.md` under "MAX advertises the Gateway shape and sells no product behind it, 21.09.2026". In short: the owner read the page correctly and the wording is **`<meta name="description">` and `<meta name="keywords">`** — *"уведомления по номеру телефона, кодов подтверждения"*, *"альтернатива SMS"*, *"2FA в мессенджере"* — while the page itself sells чат-боты, мини-приложения, каналы and Цифровой ID, and `selectionservices` names those four as the whole of what a verified profile may connect. 🔴 **Wall one:** no API method addresses a phone number — `dev.max.ru/docs-api` carries `chatId` and `user_id` and not one occurrence of `phone` (positive controls run, so the empty result is a fact about the page); every телефон in that reference travels **inbound**, via `request_contact`. The 12.09.2026 record needed no correction, only a citation. 🔴 **Wall two, the harder one:** *Требования*, «Редакция от 16.12.25», clause 1.5 forbids a Developer to publish an Приложение that uses *"API либо иную техническую интеграцию … для … отправки **Авторизационных сообщений**"* — defined in the *Правила* as one-time codes for authentication or verification against third-party resources — *"за исключением случаев, прямо предусмотренных Договором с Компанией **вне зависимости от наличия технической возможности**"*. The clause closes the workaround by name. The only door left is a negotiated contract, which is an **owner** move (`partner_support@max.ru`), not code. **The ИП gate is answered and the reported restriction refuted from the vendor, not second-hand:** connection and the *Правила* footnote ¹ admit юрлица, ИП and самозанятые (Цифровой ID: ЮЛ and ИП only); физлица and нерезиденты cannot verify at all. ⚠️ Both documents change silently by their own terms — the edition dates are what pins this, and a re-read is cheap

## 3. Agree the contract with the parking developer

- [x] 3.1 Settle the contract's shape here, then hand it over — **there is nothing to reconcile
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
      Settled 21.09.2026 by reconciling the four against the code rather than by
      choosing them again, because all four were already built: `/verifications` is
      plural on every one of the four doors (`app/api/router.py`);
      `verification_ttl_seconds` ships at **300 s**; the push carries
      `verification_id` and **no `id` at all** (4.15a); and `routes.ALL_ROUTES` holds
      the eight names flat, with `rule` validating against exactly that set. So the
      task closed as a sverka, as the handoff predicted.
      🔴 **What the sverka found is a fifth substance nobody had named, and it is
      recorded as 3.4:** the number a subscriber must dial or text reaches the
      application only inside an English `instruction` string. The four settled items
      were all about vocabulary and shape; this one is about whether the application
      can put a Russian screen in front of a person at all, and it is not ours to
      settle alone.
- [ ] 3.2a Then write the integration contract with real examples and hand it over, once the shape is settled and not before — the owner's condition of 18.09.2026. Until `sp_app` adopts it, no МегаФон subscriber sees any improvement
      🟡 **Half done, and the half that remains is not ours.** The document is written:
      `docs/verification-api.md`, 21.09.2026 — the four doors with real request and
      response bodies, the push, the four vocabularies (routes, statuses, check
      outcomes, confirmation methods), and the semantics a consumer would otherwise
      discover by shipping. **Handing it over is the owner's act**, his condition of
      18.09.2026, and this task stays open until he has done it.
      English, like `docs/delivery-webhook.md` — the closest analogue and the other
      document in `docs/` that calls itself an integration contract. `ru`-only
      `verification-rungs.md` is addressed to whoever runs the gateway; this one is
      addressed to a developer outside it. **Decided by me; the owner may overturn it**,
      and the Russian half is mechanical to add if he wants one.
      Held to the code by `tests/test_verification_contract_doc.py` — 17 guards, bitten
      by 25 mutations with no survivors, half of them played against the *code* rather
      than the document, because a contract that only guards its own prose rots in the
      one direction that matters. The guards already earned themselves: the first draft
      of the poll's field table was missing `created_at` and `confirmed_at`.
- [x] 3.2 Quote no invented number in the contract. **The draft carries TWO placeholders, not one** — `+79001234567` in the JSON example and `+7 900 123-45-67` in the screen copy — and both must go before it is handed over. (An earlier note here said one of them had gone out in the frozen `verify-by-inbound-code` contract; nothing went out — see 3.1.) The fix is not "use the real one": **for the call method there is no gateway number at all** (the vendor calls, from a number nobody knows in advance), and for the SMS method the gateway does not hold its own MSISDN anywhere in its settings. The contract SHALL name digits only if the gateway holds them as configuration, and otherwise say the sender is the gateway's SIM
      Closed 21.09.2026 the only way that survives the next draft: the contract prints
      **no telephone number anywhere**, and the rule is enforced on the *shape* of a
      number rather than on the two strings the old draft happened to carry — the next
      placeholder will be different digits, and a guard listing yesterday's passes on
      tomorrow's. `test_the_document_prints_no_telephone_number` fails on any run of
      five or more digits; its paired positive control fails if the document stops
      explaining that `gateway_msisdn` ships blank, because a document that had merely
      gone quiet about numbers would satisfy the first guard perfectly.
      Where digits are genuinely needed the contract points at the `instruction` string,
      which the gateway interpolates from `gateway_msisdn` — the one place the estate
      holds them as configuration, exactly as this task requires.
- [x] 3.3 Confirm with the developer whether `sp_app` can receive a webhook, or will poll. Both are supported; the answer decides which one is documented as the recommended path
      **Decided by the owner 22.09.2026 without waiting for the answer, because the
      recommendation is ours and not theirs: polling.** Both paths stay supported and neither
      is deprecated. The reason is the threshold, and the threshold decides whether any
      МегаФон subscriber ever sees an improvement — polling asks nothing of `sp_app`: no
      public address, no signature check, no handling of a push that arrives twice. And the
      screen is already open in front of the person, so a poll a second inside a five-minute
      window is tens of requests rather than load. `docs/verification-api.md` renamed the
      section that was called "Polling is the floor" to say what we recommend rather than
      what is merely possible.
- [x] 3.4 🔴 **The number the subscriber must dial or text reaches the application only inside an English sentence.** `RouteOffer` is `{route, instruction}`, and `instruction` is built in `routes._instruction` by interpolating `gateway_msisdn` into an English template — "Call {number} from the number being verified…". The gateway does not translate it: `docs/i18n.md` covers the admin UI and nothing else, and there is no gettext anywhere in `app/verification/`. So an application whose person reads Russian has two options and both are bad — show them English, or re-word it and have nowhere to read the digits from but a regular expression over our prose. **The remedy is a field, not a translation:** the estate holds the number as configuration and can hand it over as data, leaving the wording to the application that owns the screen. Additive, so no consumer breaks. **Owner's call**, because the contract's substance was settled by him on 18.09.2026 and this is a fifth item added to it; named here rather than built so the decision is his. Until it is decided, the contract says so in as many words — `docs/verification-api.md`, "The instruction is English"
      ✅ **Decided 22.09.2026: the field is added.** `RouteOffer.number` carries the address
      as data beside the sentence, filled on the rungs that ask the subscriber to reach us
      (`call_in`, `sms_in`) and `null` wherever the gateway is the one that acts — on those
      there is nothing to dial, and an address handed back would invite an application to
      send somebody to a number that is expecting nothing.
      **Additive, and guarded as a property of the schema rather than claimed in prose**:
      `RouteOffer` still constructs without the field. That guard is written against the
      model directly and deliberately — the door always passes the field, so every guard
      driven through HTTP stays green whether the default exists or not, and the promise
      would break with the whole suite passing.
      `bite-the-number-as-data.sh`, four mutations: the field assembled and then dropped at
      the door (implemented-but-unreachable, the shape this change has paid for three
      times), the number handed back on **every** rung, the field disagreeing with the prose
      — worse than no field, because an application will trust the data — and the default
      removed. Contract updated: the example carries the field, and the paragraph asking the
      developer to "say so if you need them as data" is replaced by an instruction **not** to
      parse digits out of our prose, which would make our wording an unwritten contract that
      breaks the day somebody improves a sentence.

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


- [x] 4.1 Test: a verification for an operator the rule routes to `flash_call` is not picked up by the modem sender, and one routed to `sms_out` is
      🔴 **Half of this is now a live hazard rather than an open test, and it was created
      by 4.6a.** The modem sender refuses anything whose **first** rung in the rule is
      not `sms_out`. A verification the ladder deliberately routed to a modem rung
      standing behind a paid one would therefore be refused by the sender — the ladder
      chose `sms_out`, and the sender asks the rule instead of asking what was chosen.
      🔴 **Closed by 4.17b on 21.09.2026, and the prediction in this task was right
      about the hazard and wrong about the carrier.** The carrier was never 1.1's to
      unblock — the modem needs no account — and the fact the sender has to honour does
      not ride on the queued item at all: it is read from `messages.verification_id`,
      because the restart resume path re-enqueues from rows and would drop anything
      carried in the queue. `tests/test_the_modem_rung_carries_a_code.py` holds it,
      including the restart shape and the positive control that ordinary free text on
      the same rule is still refused.
      **What is left of this task is its first half** — that a verification for an
      operator the rule routes to `flash_call` is not picked up by the modem sender —
      and at **placement** it is unreachable by construction, measured 21.09.2026 and
      re-checked 22.09.2026 against the same three files: `sms_carrier` is the only thing
      that creates a verification-owned message, it runs only where `ladder.walk` walks to
      `sms_out`, and `placement.ladder_from` returns either the rule's own list from the
      chosen rung onwards or the chosen rung **alone**. A guard written against placement
      is green and empty.
      🔴 **The one state that does reach it was written 22.09.2026, and the answer in it
      is the opposite of what this task predicted.** The state is *time*: the ladder reads
      the rule when it places and the sender reads it again when it sends, and between
      those two reads lie a queue, a retry backoff and the restart resume path. An
      operator moved wholly onto the paid rungs during an outage is exactly the change
      made inside that window, and every code already queued for them then belongs to an
      operator the rule routes to `flash_call`. The sender carries it — the owner's
      decision of 21.09.2026, task 4.17b — because refusing it would fail a code for a
      rule that changed after the person was told to expect it, and spend the
      verification's one placement to say so.
      Built and bitten: `test_a_rule_re_pointed_after_placement_does_not_strand_the_code`
      in `tests/test_the_modem_rung_carries_a_code.py`, with the positive control that
      ordinary text on that same re-pointed rule is still refused, and four mutations in
      `bite-rule-repointed-after-placement.sh` — one of which leaves 4.17b's own guard
      green and reddens only this one, which is what earns it its place. The norm and its
      scenario are now in the spec rather than only in this note.
      🔴 **Struck by the owner 22.09.2026 — the first half, and the task closes with it.** The
      behaviour it asks for was decided against by name on 21.09.2026, so it cannot be satisfied
      and not for want of work. What stands in its place is the norm that the rung is honoured
      for the whole life of the message, its scenario, its guard and its four mutations.
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
- [x] 4.8 Test: `call_status: 1` does not confirm a verification; only a correct code at `/check` does
      Held twice and at two altitudes, because one of them alone is satisfied by a carrier
      nothing calls: `test_a_placed_call_does_not_confirm_the_verification` drives the
      carrier, and `test_a_placed_call_leaves_the_verification_awaiting_a_code` drives a
      real `POST /verifications/{id}/route` through the registry, the rule and placement
      and then reads the row. Bitten by mutation 3 of `bite-flash-call.sh`, which reads a
      failure to connect as a placed call and turns eight guards red.
- [x] 4.9 Test: `call_status: -1` that never resolves within the bound is recorded as unknown, not as success and not as failure
      🔴 **Unknown needed a word of its own, and the ladder did not have one.** Every
      existing outcome is wrong here in an expensive direction: advancing buys the same
      code at the other vendor while this call is already placed and paid for, and failing
      tells the application the code is not coming while a phone may be about to ring. So
      `ladder.UNRESOLVED` with its own branch — the ladder stops and the verification stays
      pending on its own deadline.
      ⚠️ **And this is the ordinary case on this rung rather than the exotic one.** The
      vendor takes "от 1 сек до 1 минуты" to decide; the ladder's whole patience ships at
      ten seconds, and a person is standing in front of a synchronous HTTP request for all
      of it. Waiting longer is not available.
      🔴 **What is therefore NOT built is learning the outcome afterwards.** A
      `call_status` that resolves in the vendor's fortieth second is read by nobody: the
      rung keeps its `unresolved` row and its `ucaller_id`, and the verification ends on
      its own deadline unless a code is checked. Closing it is a sweep over open
      `flash_call` rungs inside `announce_verification_outcomes`, which is the one pass
      that already sees every ending and already asks a vendor (`_withdraw_outstanding_message`).
      Named in `flash_carrier`'s docstring and given task 4.17e rather than left to be
      discovered.
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
- [x] 4.12 Test: a second request for the same number inside the vendor's per-number window is refused by us with a wait reason, and no vendor call is placed
      Both halves, and the second one could not be asked until 22.09.2026: until the call
      rung existed, "no vendor call is placed" passed against a gateway that had no way to
      place one. Four guards in `tests/test_the_call_rung_is_reachable.py`, driving real
      HTTP through the real registry, rule and placement and counting `ucaller.init_call`
      itself — the refusal naming the wait, no rung recorded and no verification left
      hanging, the window holding the **whole ladder** rather than the call rung alone
      (a second request selecting Telegram is refused before either vendor is contacted),
      and the positive control that a request after the window is called. **Eleven
      mutations bite**, in `bite-window-from-the-door.sh`.
      ⚠️ **Found while doing this: the requirement's backing note named `bite-limits.sh`,
      and no such file has ever existed here** — not in the working tree, not in any
      commit reachable from any ref. The enforcement's seven named mutations were never
      saved as a script and cannot be re-run. The note has been corrected to say so; whether
      that script gets written is the owner's call, and it is not blocking.
- [x] 4.13 Test: a repeat inside the free window uses `initRepeat` and keeps the same code; a retried vendor call carrying the same idempotency key does not place a second call
      🔴 **The first half may have no subject. Measured 22.09.2026: `initRepeat` over GET
      answered `405`,** where the same GET form worked for `getService`, `initCall`,
      `getInfo` and `getBalance` in the same series. Two readings and the measurement does
      not separate them. **Both have since been tested, and the answer is
      settled: the method is unavailable to this account.** POST with `{"uid":…}` and
      `Content-Type: application/json` — the reference's own form — answered `405` too;
      and on 22.09.2026 at 08:01 a fresh authorisation was raised on the test number,
      left for sixty-five seconds, and then `getInfo` and `initRepeat` were called **in
      one command, back to back**: the vendor reported `repeatable: true` and
      `repeat_times: 2`, and refused `405` in the same breath. So it is not the window,
      not the HTTP method, and not the allowance — the vendor codes those `11` and `12`
      and returned neither, ever. Why is invisible from outside: tariff, a cabinet
      setting, or a mechanism being retired. Captures: `uc-1.3-getInfo-window-open.json`
      beside `uc-1.3-initRepeat-405.json`. ⚠️ **The first half of this task is therefore void rather than unwritten, and
      striking it is the owner's to do** — a refusal is recorded by the owner before
      archiving, not by the session that found it. The spec has been brought in line
      meanwhile: the free repeat is written as unavailable, the operative path is a new
      paid verification with a changed identifier, and the gateway is forbidden to call
      `initRepeat` while it answers `405` or to present a repeat as free. Nothing is
      blocked by this — the safe path was already the one the requirement mandated for
      want of a sample. The only avenue left is the vendor's cabinet or support, which is
      the owner's too. Detail in `captures/ucaller-samples-1.3.md`.
      The second half — idempotency via `unique` — is untouched by this: `unique` has
      never been passed in any capture.
      🟢 **The second half is now the whole of this task**, and it is buildable: `unique`
      is a UUID v4 we generate and send, and nothing about it depends on the vendor's
      repeat.
      ⚠️ **And `getInfo` is not stable for one `ucaller_id`:** the same authorisation read
      minutes later came back `repeatable: false` with **no `repeat_times` field at all**
      (`captures/uc-1.3-getInfo-unreachable-later.json` beside the first). A reader that
      treats `repeat_times` as present because `repeatable` once was `true` breaks on an
      ordinary expiry rather than on a vendor fault.
      🔴 **Struck by the owner 22.09.2026 — the first half, and the task closes with it.** The
      free repeat is unavailable to this account and that is separated by probe rather than
      supposed; the spec already mandates the safe path, so nothing was ever blocked by it. The
      only avenue left is the vendor's cabinet or support, which is the owner's. A row in the
      waiting registry carries it with a probe that re-asks `initRepeat`: if a tariff, a cabinet
      setting or support ever opens the method, it comes back on its own rather than being
      remembered.
      **The second half is built and bitten**, and it is now the whole of the task: the
      idempotency key is derived from the attempt row's id, survives a restart and has the
      vendor's UUID v4 shape — three guards in `tests/test_ucaller_adapter.py`.
      ⚠️ **What is deliberately not built is a reader for `exists`.** The vendor sets it only
      when `unique` was passed, `unique` has been passed in no capture, so the field has never
      been observed — and the external-contract gate forbids behaviour on an unobserved field.
      It is also unreachable today: nothing retries `initCall`, and nothing calls a carrier
      twice for one rung row, so a guard on it would be green and empty. Both facts are in the
      spec, and the sample arrives for free with the first paid probe (task 1.2).
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
- [x] 4.17 Implement the verification endpoints, the code store and the uCaller adapter against the samples captured in 1.3
      The endpoints and the code store landed with the doors; what this task still owed on
      22.09.2026 was the uCaller half, and it is built in two pieces against the samples of
      1.3 rather than against the reference alone.
      **The wire** — `app/verification/ucaller.py`, below the credential it already held.
      `initCall`, `getInfo`, `getBalance`, both envelope shapes, the vendor's error codes
      split by *who the refusal is about*, and the idempotency key. 40 guards in
      `tests/test_ucaller_adapter.py`, 14 mutations in `bite-ucaller-adapter.sh`, no
      survivors.
      **The rung** — `app/verification/flash_carrier.py`, plus `ladder.UNRESOLVED`, a probe,
      an entry in `placement.carriers_for` and `PLACED_HERE`, and the instruction the person
      is given. 20 guards in `tests/test_flash_call_carrier.py`, 8 in
      `tests/test_the_call_rung_is_reachable.py`, 18 mutations in `bite-flash-call.sh`.
      🔴 **`initRepeat` is absent from `VENDOR_METHODS` as a value a test reads**, not as a
      habit: the spec forbids calling a method that answered `405` with the repeat window
      open, and a list the exclusion is readable from is the difference between a decision
      and an omission.
      🔴 **The door was minting `0000`.** Four digits, and outside uCaller's stated range of
      0001–9999 — so one verification in ten thousand could not have used this rung at all
      and would have advanced to another one silently, which is the failure this whole
      change exists to remove. Fixed at the producer (`_new_code` redraws) rather than at
      the rung, because a guard at the rung makes a rung unavailable for a bug of ours.
      ⚠️ **Reachability was asked before it could be answered the way 4.56 answered it.**
      `tests/test_the_call_rung_is_reachable.py` drives real HTTP through the real registry,
      rule and placement, including the crossing — a МегаФон subscriber the Gateway declines
      is called instead, two vendor identifiers against one code. Four of its eight guards
      are red under mutations 15–18, which are the four ways the rung could have shipped
      looking finished.
      ⚠️ **What is not built is the outcome that arrives after the ladder's bound: 4.17e.**
- [x] 4.17e Learn the outcome of a call the vendor had not decided within the ladder's bound
      Split out of 4.17 on 22.09.2026 and closed the same day. The vendor takes up to a
      minute to set `call_status`; the ladder waits ten seconds because a person is in
      front of a synchronous request — so `unresolved` is this rung's ordinary ending, and
      until this existed it was permanent: the subscriber the vendor could not reach
      watched the verification expire rather than being told the call failed.
      `flash_carrier.resolve_outstanding`, run from `announce_verification_outcomes` — the
      one pass that already sees every way a verification can end and already asks a
      vendor. **First in that pass, before expiry**, because an ending learned in the same
      interval the window ran out in would otherwise be reported as "expired", which is the
      one thing that did not happen.
      🔴 **The money is settled whether or not anybody is still waiting.** A verification
      that expired while the vendor was thinking still owes its rung a `cost`: the weekly
      reconciliation (5.4) compares what was recorded against what the balance fell by, and
      a charge with no row is exactly the disagreement it exists to find. What is *not*
      overwritten is the ending such a verification already had.
      ⚠️ **The give-up is an age and it lives in the query**, not a story told about the
      rung: past the verification's own lifetime the answer can change nothing a person
      sees, so the rung stops being chased and keeps saying `unresolved` — truthful, and
      one request per sweep cheaper for ever against a vendor that rate-limits per IP.
      9 guards in `tests/test_the_call_outcome_that_arrives_late.py`, 11 mutations in
      `bite-late-call-outcome.sh`, no survivors. Two of them found real holes first: the
      sweep's balance reading was watched by nobody, and the age bound was asserted only
      through SQL nothing drove.
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
- [x] 4.17b Implement the `sms_out` rung — the carrier, the message it creates, and the sender honouring what the ladder chose
      Split out of 4.17 on 21.09.2026 because the rest of 4.17 is the **uCaller** adapter
      and is blocked on 1.1, while this needs no account, no balance and no vendor: the
      modem is ours. It had been read as blocked for a week on that bundling alone.
      `app/verification/sms_carrier.py` composes from the application's template, creates
      the message with `verification_id` set, records the routing, and queues it. A
      missing template is `INCAPABLE` rather than `DECLINED`: a decline is a statement
      about the subscriber, and a rung that appears to decline everybody is a rung taken
      out of the rule for the wrong reason.
      🔴 **`placement.PLACED_HERE` was wrong and the ladder already knew it.** The comment
      there said the modem sender picks its own work up and a ladder placing it would
      place it twice — a mechanism nothing had built. Meanwhile `ladder._MODEM_ROUTES`
      and the withholding rule of 20.09.2026 are a branch about the modem rung standing
      **inside** a ladder, and under that reading they were unreachable. The modem is now
      placed like every other rung this gateway acts on.
      🔴 **The hazard 4.1 named is closed, and not where 4.1 expected.** The sender asks
      the rule afresh and refuses anything whose **first** rung is not `sms_out`, so a
      verification the ladder placed on the modem *behind* a paid rung would have been
      refused — naming `tg_gateway` in the reason, on a message the ladder had already
      decided. The ownership is read from the **database**, not from the queued item: the
      restart resume path builds its items out of `messages` rows alone, so a fact
      carried in the queue would be dropped by the one path that re-sends, and the
      symptom would be a code refused on its retry.
- [x] 4.17c **Owner: whether a consumer may choose `sms_out`, given that offering it
      retires `sms_in`.** Registering the probe is four lines and was written and
      withdrawn on 21.09.2026, because measuring it showed a collision nothing had
      named: `_sms_in_probe` and an `sms_out` probe hold on exactly the same thing,
      `modem.link_in_service`, and `sms_in` is dropped whenever anything earlier in the
      order proved itself. The shipped order names `sms_out` second and `sms_in` last,
      so `sms_out` proving is `sms_in` **never being offered again** — and `sms_in` is
      the whole subject of the sibling change `verify-by-inbound-contact`. Two more
      collide and neither is settled: the offer is not filtered by the routing rule, so
      the rung would be offered for the one operator the rule diverts away from it; and
      an application with no template would be offered a rung that cannot compose its
      code (4.47). Until this is answered `sms_out` is reachable only as a **ladder
      continuation** — a rule naming it behind a rung that can be chosen — which is what
      backs 4.27 today.
      🟢 **Answered «можно» by the owner, 21.09.2026, and the two collisions are settled
      rather than accepted.**
      **`sms_in` is not retired.** It was only ever going to be because both probes were
      written on `link_in_service`, which is the *conjunction* of two ports. They are two
      directions and now two properties on the manager: `can_transmit` (the command port)
      for `sms_out`, `can_receive` (the URC port) for `sms_in`. The state that keeps
      `sms_in` alive is a sender port gone with the reader alive — exactly the state in
      which asking the person to text us is the right offer rather than the dear one.
      ⚠️ Both properties were unguarded when first written: every probe test runs against
      a fake modem, and wiring each to the *other* port left the whole suite green. Held
      now by `tests/test_link_visibility.py` on the real manager.
      🔴 **The rule is part of the precondition, and it is read in the probe.** An
      operator the rule diverts away from the modem is not offered the modem: the answer
      would be honoured — a rung the rule does not name is carried alone, the owner's
      other decision of the same day — and the code would go out over the route that
      operator has been rejecting, reached through the **offer** rather than through the
      ladder. In the probe rather than at the door because `offer` has three call sites
      and a rule read at each is a census; a probe is asked once, about this number.
      The operator is read from the cache and never looked up: the application's answer
      does not wait for enrichment, and a number with no row takes the `?` entry, which
      is what that entry is for. Nine mutations bite, none survive.
      **What this does not do is 4.47** — the template refusal at accept, which only
      becomes answerable now that the rung can be chosen.
- [x] 4.17d Declare uCaller's credential in `settings` and assemble its bearer — the half of 4.17 the reference alone settles, so that the owner's key has somewhere to go before any sample exists
      Split out of 4.17 on 22.09.2026 for the same reason 4.17b was: the rest of 4.17 is
      a parser and waits on samples (1.3), while *how the vendor is authenticated* is
      answered by the reference and by nothing else. The owner had the key in his hands
      and no row to put it in.
      Reference read by layers and captured verbatim —
      `captures/ucaller-reference-2026-09-22.md`, which supersedes the 08.09.2026
      reading. `ucaller_key` (secret) and `ucaller_service_id` in `app/settings_store.py`;
      `app/verification/ucaller.py` joins them into
      `Authorization: Bearer <key>.<service_id>` or returns nothing at all.
      🔴 **Two rows rather than the joined bearer, and that is a failure mode rather than
      a preference.** The settings page says "задано" about any row that is not blank, so
      a bearer with a missing or doubled dot is indistinguishable from a working one
      there and announces itself as the vendor's `401` on the first *paid* call. Two rows
      are each pasted verbatim, and a missing half reads as "не задано".
      Six guards in `tests/test_ucaller_credentials.py`, eight mutations in
      `bite-ucaller.sh`, no survivors: the dot dropped, the halves swapped, one half
      accepted as a whole credential, the paste left unstripped, the reader taking the
      key twice, the secret declared not secret, the row shipped with a value, and the
      second half never declared. The page was rendered in both locales — the secret is a
      `password` field with no `value` attribute, the service id a plain field showing
      its value.
      ⚠️ **Declared is not called.** The settings page reads the rows; the vendor is
      called by nothing until 4.17 lands the adapter, and `flash_call` has no probe
      registered and is therefore never offered. Said out loud in the module and in the
      spec rather than left to be discovered.
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
- [x] 4.19 Update `docs/` with the two paid rungs: what each costs, how to change the rule **and its order**, how to top up each of the two balances, how to tell from a verification which rung carried it and what it cost, which application is entitled to spend, and what to do when МегаФон recovers
      `docs/verification-rungs.md`, new, in Russian and linked from both halves of the
      README. Russian because its reader is whoever keeps the gateway — the person who
      tops up a balance and edits the rule — and the console they do it in defaults to
      Russian; the English-only documents in `docs/` are for integrators.
      🔴 **The first draft stated a vendor's promise as our measurement.** It said a send
      by the `request_id` of a paid ability check is free, which is what the adapter is
      built on — and `captures/README.md` records the opposite: on 20.09.2026 the send
      answered the *same* `request_cost` as the check, an echo of the request's price, and
      whether a second charge was taken is not visible in the samples at all. Caught by
      reading the captures rather than the code, which is where an assertion about a vendor
      has to be checked. The document now marks it as unmeasured, and a guard holds it
      marked.
      The prose is not guarded and deliberately so — a guard over wording fails on every
      honest edit and is proof-read away. What is guarded is every identifier and number
      the document states as fact: the ten settings it names still exist, it still names
      them, the seven defaults it prints are the shipped ones, the rule it quotes is the
      rule that ships (compared as parsed data, so reformatting is free and changing the
      meaning is not), and `?` is still explained as "the lookup did not answer" rather
      than by the reading it replaced on 20.09.2026.
      Six mutations bite, four of them by these guards alone.
      Proofread through `ru-check` against the full corpus; twenty findings applied. Two
      were **not** taken, and both refusals are decisions rather than oversights: the
      proposed fix for the balance measurement said the send's answer carried no balance
      at all, and the captures say otherwise — the field is there with `0`, in all three
      captured sends, which is a stronger and fully measured way to make the same point,
      and that is what the document now says. And the non-breaking-space rules (R30, R44,
      R68) are declined by repository convention: `README.md` and `captures/README.md`
      hold zero of them, and one file carrying invisible characters is an inconsistency
      rather than typography.
      🔴 The heaviest finding was one no guard could have caught: **`счёт` meant both
      "the vendor's account" and "the refusal counter"** in a document whose first section
      is about money. The counter is now `счётчик отказов` throughout.
- [x] 4.20 Test: a verification belonging to one application cannot be read, checked or exhausted by another — by id, with a valid token
      Held already — `get_verification` and every conditional update in
      `check_verification` are scoped by `app_id` — and bitten on both: unscoping either
      reddens. The guard here drives all three verbs from a **valid** token of another
      application and spends more than the limit's worth of wrong codes at it, because
      exhausting is the quiet verb: a stranger need read nothing and can still burn a
      person's five attempts at a barrier they are standing at. Paired with the positive
      control that the owner's own three calls answer, without which the negative passes
      on a door that refuses everybody.
- [x] 4.21 Test: a blocked number is refused a verification, and a call that fails to connect does not advance that number's permanent-failure count
      **The first half is built and bites** (21.09.2026,
      `tests/test_verification_api.py`). It was not, despite a test named for it: the
      guard asserted the 422 and the word `blacklist` and nothing about "without opening
      anything". 🔴 Measured, not suspected — moving the blacklist check to *after*
      `create_verification`, so a blocked number is refused having had a row opened, a
      live code generated and every probe spent, left the **whole suite** green. The
      quiet half is the one that mattered: an open verification on a blacklisted number
      is a live code in the store for a number the gateway has decided not to write to,
      and `open_codes_for` counts it against every later request for that number. Both
      halves are asserted now, with a positive control on the same door.
      **The second half closed 22.09.2026**, once there was a call to fail.
      `tests/test_a_failed_call_is_not_a_bad_number.py`: `record_permanent_fail` has one
      caller in the application — the modem's delivery-report path — and both of the call
      rung's failing endings are **driven** against a live database rather than read,
      because an absence reads as satisfied in code that never runs the path. The carrier's
      not-connected branch and `resolve_outstanding`, which is the ending a later change
      forgets: by the time it runs it is already failing the verification and recording the
      cost, which is exactly the shape "and mark the number bad" gets added to.
      Mutations inverted to match — they write in what must not be there —
      `bite-call-is-not-a-bad-number.sh`, six bites.
      ⚠️ Two neighbours left standing and named rather than quietly built: the
      requirement's **normalisation** scenario has no guard at this door (the validator is
      the send's own and `tests/test_phone.py` covers the function, but nothing drives an
      unnormalised number through `POST /verifications`); and the blacklist is checked at
      `POST /verifications` and **not** at `POST /verifications/{id}/route`, so a number
      blocked inside an open verification's window still reaches the paid ladder. Neither
      is 4.21's text.
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
- [x] 4.23 Test: a verification whose vendor-reported code differs from the requested one fails with that reason rather than matching digits the vendor never dialled
      Failed rather than adopted — the branch this change chose of the two the requirement
      allows, because adopting means rewriting a live verification's code from a vendor's
      word and the code is the one value here that is never written twice. The operator is
      woken, because from the outside this is indistinguishable from every subscriber
      suddenly typing the wrong code and every instance of it has been paid for.
      🔴 **Both places the vendor states a code are read**, and that is not belt and
      braces: `initCall` answers a `code` and `getInfo` answers one of its own, and a check
      at one end only is a check the other end walks past. Mutations 5 and 6 of
      `bite-flash-call.sh` take one end each.
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
- [x] 4.27 Test: a verification carried by the modem whose message fails or expires fails the verification, and that message raises no message-status push
      🔴 **The previous handoff called this "live and blocked by nothing" and it was
      neither — the same unmeasured word, one day later.** It had no message to own:
      `enqueue` had four call sites (the API, the admin console twice, the restart
      resume) and not one of them belonged to a verification, `placement.carriers_for`
      built one carrier and it was `tg_gateway`, and no row in this schema had ever
      carried a verification's code. The requirement says "the message it **creates**",
      so the producer is inside the task rather than beside it: 4.17b below.
      Built on the door rather than on the writers. `spawn_delivery_dispatch` has eight
      call sites in the sender and the norm is "no message-status push for a
      verification's message"; a census of eight stales the day a ninth is added, and
      `dispatch_delivery` is the one place all eight pass through and already reads the
      row the decision is made from.
      Both halves are guarded and both bite. `sent` and `delivered` leave the
      verification open — a rule that ended it on any status would end every
      modem-carried verification the moment its code went out — and `fail_verification`
      moves a `pending` row only, so a late `expired` cannot take a login away from
      somebody who already confirmed. The announcement rides the existing sweep rather
      than being pushed from here: one announcer sees every way a verification ends, so
      a writer added later cannot be a writer that forgot (the rule 4.28 counts).
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
- [x] 4.30 Implement verification retention and the destruction of a terminal verification's code
      The destruction half was built and genuinely held: all five terminal writers null the
      code, and dropping it from any one of them reddens. What was missing was the question
      asked of the *next* writer — so the rule now stands on 4.28's census, per statement
      rather than per function, and `check_verification`'s two endings are counted
      separately. Measured: a new terminal writer, added and dutifully registered in the
      census after it failed, left the whole suite green.
      🔴 **The retention half had two holes and both were invisible.** `prune_verifications`
      could be deleted from `announce_verification_outcomes` outright with the suite green —
      the query was guarded and its placement was not, which is exactly how a retention rule
      becomes a comment. And the prune removed the verification while **leaving its rungs
      standing**: `verification_rungs` has no foreign key and no retention of its own, so
      what survived was the vendor's reference for a message placed to a subscriber, kept
      for the life of the database and reachable by no screen, since every reader of the
      table goes through a live `verification_id`.
      Ten mutations bite. One survived at first and was the fixture rather than the
      predicate: an open verification *past* the window had no rung in the control, so
      dropping `status != 'pending'` from the rung deletion — the mirror of the guard one
      table up — changed nothing observable. The range is now bitten on both sides.
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
- [x] 4.38 Test: one acceptance bound covers the whole ladder, not each rung — a slow first rung does not double the time the application waits, and the response still names a method rather than pending
      Closed 21.09.2026 with the door (4.56). The bound is the new setting
      `verification_ladder_bound`, and ten seconds is a ceiling rather than an
      expectation: the Gateway answers in 178–285 ms over the wired path (1.7) and times
      out at **fifteen** on the failed-over one (1.12), which is the one case where this
      number decides anything.
      🔴 **The load-bearing half was the unguarded one, and it is not in `ladder.walk`.**
      There is no `wait_for` there and there must not be: cancelling a carrier between a
      confirmed ability check and the record of its `request_id` would leave a fee nobody
      can attribute. What `walk` does is hand each rung what is left of the one bound, and
      every carrier must put that on its own vendor call — so the whole guarantee rested on
      two lines in `tg_carrier`, and **both vendor methods carry a default** (5 s on the
      check, 10 s on the send). A carrier that omitted the bound would not fail; it would
      quietly take fifteen seconds against a bound of one. Measured: no test anywhere read
      back the `timeout` its fake vendor recorded — checked with a positive control on the
      same grep, because an empty search is not a finding. Guarded now with a bound
      narrower than either default, plus the control that a wider bound follows.
      ⚠️ **And the first version of the verify measurement asked the wrong question** — "the
      second rung is reached anyway". A rung that consumes the whole bound leaves the next
      one nothing, and dividing the bound per rung is precisely what this task forbids. The
      claim that belongs there is that the ladder **stops**, records `unanswered` (possibly
      charged, never a decline) and leaves the verification in flight; the continuation is
      a separate case, driven with a delay inside the bound.
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
- [x] 4.47 Test: an application with no template is refused **at accept** for a `sms_out`-routed verification, and is **not** refused for a paid-rung one, because neither paid rung carries text of ours
      🔴 **Re-measured 21.09.2026, and the blocker is not the one the handoff of that
      morning named.** That one said the task is unreachable because `sms_out` has no
      probe, so a verification routed to it does not exist. The scenario's words are
      "for a number whose operator **is routed** `sms_out`" — routed by the *rule*, which
      the accept door can read without any offer, so that reading was too narrow.
      The real blocker is the owner's decision of 21.09.2026 that **a rung the rule does
      not name is still carried, alone**: a consumer that picks `tg_gateway` for a number
      the rule routes `[sms_out]` is honoured, and the Telegram rung carries the code with
      no text of ours. So the rule naming `sms_out` does **not** mean this verification
      needs a template, and refusing at accept would refuse a request the gateway can in
      fact fulfil — which is the same requirement's other half ("SHALL NOT accept a
      request it already knows it cannot fulfil" cuts both ways).
      It becomes answerable the moment `sms_out` can be **chosen** (4.17c): then "every
      rung this verification can reach needs our words" is a question with an answer.
      🟢 **Built 21.09.2026, once 4.17c made the rung choosable.** The property lives in
      `app/verification/routes.py` beside `_CARRIES` — `needs_our_words` and the
      conjunction `carries_a_code_without_our_words` — and the door asks it of **the
      offers that are left**, never of the rule. The requirement's own words were
      narrowed in the spec to match, deliberately and with the reason recorded there:
      keyed on the rule it would refuse requests the gateway can fulfil.
      Three positive controls, because the refusal follows the rung rather than the
      application: the same estate with a template, the same estate with the paid rung
      available, and the inbound rungs. Seven mutations bite. One survived first — the
      `carries` half of the conjunction, unreachable through the door because every rung
      the registry can offer today carries a code — and it is held directly on the
      vocabulary, against the three messenger rungs that carry nothing.
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
- [x] 4.49 Test: a vendor credential written to `.env` for a key that already has a row in `settings` is not used, and the value in `settings` stays in force
      Precedence held and is now asserted at the `Authorization` header that leaves for the
      vendor rather than at `store.tg_gateway_token`: what the requirement forbids is the
      environment's value reaching the vendor, and an attribute agreeing with the row while
      something downstream re-read the environment would satisfy the weaker claim. Paired
      with the control that a key with no row *is* seeded from the environment, without
      which a seeder that ignored it entirely would pass.
      The blank row is its own guard, because blank is the state every estate ships in: the
      first start writes it, so from the second start `.env` has already lost even on a
      gateway nobody configured — the estates least likely to notice a decision made for
      them.
      🔴 **There are two environment surfaces and the obvious census sees only one.**
      "Never in the environment" is a claim about every line in `app/`, so the readers are
      enumerated off the syntax tree — and that census reports a clean bill while
      `app/config.py` reads `.env` on every start through `BaseSettings(env_file=".env")`,
      with no `os.environ` anywhere for a census to find. A credential declared there is the
      defect in its purest form: read from `.env` at every start, absent from the settings
      page, unchangeable without a restart. Both surfaces are now asserted, the second as a
      whitelist of one — `admin_password` is the console's own door and is in `.env` on
      purpose, so that a bad settings write cannot lock an operator out of the page they
      would fix it from.
      Seven mutations bite.
- [x] 4.50 Test: a rung whose credential is absent is not attempted, alerts on stock settings, and the ladder advances past it — the one place where a configuration gap costs money rather than traffic, and therefore the one that must be loud
      Built for the case of a route nothing is configured to carry: not attempted,
      alerted on stock settings (`notify_routing_errors` defaults on), ladder advances.
      The credential-shaped half closed 21.09.2026 with the door — 🔴 **but by a different
      mechanism than the obvious reading of this task, and the obvious reading is not
      reachable.** A blank token does not produce a carrier that fails at the vendor and it
      does not produce an absent carrier the ladder walks into either: the registry
      **re-proves the offer on selection**, the Gateway probe holds on the token, and the
      door refuses the selection as `route_not_offered` having placed nothing. So the door's
      half is the re-proof, guarded as such; `carriers_for` leaving a tokenless rung out of
      the map is guarded directly, because nothing at the door can reach it; and the
      absent-carrier path itself stays guarded one layer down, where `flash_call` reaches it
      for real on every declined subscriber. Three mechanisms, three guards, and naming which
      one closes this task mattered — a guard written against the wrong one would have been
      green and empty.
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
- [x] 4.56 🔴 **The `tg_gateway` rung can be selected and nothing places it — a route offered that then quietly fails, which is the one thing this capability's own norm forbids by name.** Found 21.09.2026 while writing the contract, by asking what a consumer would actually get for each route the door offers. `_tg_gateway_probe` holds on a non-blank token alone, so the rung is offered on any estate whose operator has entered `tg_gateway_token`; `POST /verifications/{id}/route` accepts it, records the rung as `selected`, and then handles only `call_in` (shorten the window) and `sms_in` (hand back the code). **`ladder.walk` — and through it `tg_carrier`, which is the half that actually sends — has no caller anywhere in `app/`**, only in tests. The person is told to expect a Telegram message, no message is sent, and five minutes later the verification expires with a null reason. ⚠️ **Latent rather than live:** the verification doors are not on `master`, and the token ships blank, so nothing today reaches it — but it is reachable by a settings edit and not by a deployment, which makes it a defect rather than an unbuilt feature. The proper fix is the door that walks the ladder (4.38 and 4.17, both blocked); the cheap one is to stop offering a rung nothing can place, which is what the registry already does for every other unbuilt route and would cost one line. **Which of the two is the owner's call**, because the cheap one makes the Gateway token look inert to an operator who has just entered it. Named in `docs/verification-api.md` meanwhile, because a contract silent about it reads as a promise. 🔴 **DECIDED by the owner 21.09.2026: the proper cure, not the cheap one** — build the door that walks the ladder, so a selected `tg_gateway` actually sends. ⚠️ **The parenthetical above says 4.17 blocks it, and that is now in doubt:** `ladder.walk` takes `rungs`, `gates`, `carriers` and `bound` from its caller, and the tests already drive it with `rungs=(TG_GATEWAY,)` and a `carriers` dict holding only the Gateway. A door assembled with the Gateway carrier alone would therefore land without uCaller, with the second rung skipped loudly under 4.50's norm. **Measured from call sites only, not from the door's requirements — re-check that first**, because the whole shape of this work depends on it
      🟢 **CLOSED 21.09.2026. The doubt is settled: 4.17 does not block.** Re-measured from
      the door's requirements rather than its call sites — all four arguments `walk` demands
      were assembled from what `app/` already held (`rule.route_for`,
      `gates.for_paid_ladder`, `tg_carrier.carrier`, and one new setting) and the walk was
      driven both ways. Confirming: carried, recorded with the vendor's reference and cost.
      Declining: `flash_call` skipped loudly and the verification failed naming both rungs.
      uCaller is only the second rung's **carrier**, and its absence is the already-built,
      already-guarded `absent` path.
      The door is `app/verification/placement.py` plus `_walk_the_ladder` in
      `app/api/router.py`. Two owner decisions shaped it, both taken 21.09.2026 after the
      measurement raised them: the ladder settles **inside** `/route` and the answer names
      the rung that carried; and a rung the rule does not name for that operator is carried
      **alone**, honouring the consumer's pick.
      🔴 **The measurement found three defects the handoff had not seen, and one of them
      would have blocked every Gateway selection.** They are 4.56a, 4.56b and 4.56c below.

- [x] 4.56a 🔴 **The door's own `selected` row is money, and it refuses the selection that wrote it.** Found 21.09.2026 by measurement, not by reading: `paid_attempts_since` and `paid_attempts_for_number` count **every** `verification_rungs` row on a paid route whatever its outcome — deliberately, because an ability check that never answered may have been charged without our learning its `request_id`. So the `selected` row `POST /route` wrote for its own bookkeeping already counted as a paid attempt **before this session**, meaning selecting `tg_gateway` spent one unit of the spend ceiling and one of the subscriber's allowance while placing nothing. With the door walking the ladder it would have been worse in two ways: two rows per attempt, halving both ceilings for the one rung that actually spends; and, since that row is a paid attempt aged zero seconds against a `verification_min_gap_seconds` of fifteen, the per-number gate would have refused **every** Gateway selection with `too_soon` — while looking exactly like a gate doing its job. Fixed by writing the row only for the rungs nothing is placed for; the ladder writes its own, before the carrier is called, which is the ordering the money depends on
- [x] 4.56b **The consumer's claim silently won over the rung that carried.** `ladder.walk` marked the carrying rung with `select_route`, which writes only where `route IS NULL` — correct for a walk nobody claimed first, and wrong for a door that must claim before spending. The claim would have stood and the verification would have named a rung that declined it: the defect this capability forbids by hand, and one already guarded a layer down by `test_the_verification_names_the_rung_that_carried_it_not_the_first_tried`, arriving by the door. Fixed with `queries.set_carrying_route` — the one sanctioned move of a verification from one route to another, refusing to move one that has stopped being open
- [x] 4.56c **A gate's refusal left the verification pending with a route claimed and nothing placed.** `ladder.walk` returns a gate refusal without failing the verification, and rightly: there was no attempt, and a rung row would file a refusal of ours under what the vendors did. But the caller claimed the route before walking, so the ending is the caller's debt. Placed in `placement.place` rather than in the HTTP handler, so that a second door cannot be a door that forgot — the same reason `gates.for_paid_ladder` exists
- [x] 4.57 **Nothing supplies `callback_url`, so the vendor is never told where to report.** Found 21.09.2026 while assembling the carrier. `tg_carrier.carrier` takes `callback_url` and `sender_username`, both defaulting to blank, and **no caller anywhere in `app/` supplies either** — there is no setting holding this gateway's own public address (the census of `Spec(` finds `voxlink_url` and `alert_relay_base` and nothing else). The consequence is the shape of 4.56 in a different place: `POST /verifications/tg-callback` is built, signed-callback verification is built and guarded (4.43), the revocation sweep is built (4.42) — and if the vendor takes its callback address per request, none of it can ever fire in production, so a message that is accepted and then not delivered inside its `ttl` reports itself to nobody and 4.39's mechanism is unreachable. ⚠️ **What is measured is our side only:** whether the Gateway also accepts an account-side callback URL at `gateway.telegram.org` is **not established**, and no capture speaks to it — the external-contract gate forbids asserting the vendor has no such setting from our code's silence. So the work is two-part: read the vendor's own reference or the account page for where a callback address may live, and then either a setting holding our public base URL or a recorded finding that the account holds it. `sender_username` rides along: it is the only lever on what the subscriber actually sees (task 1.11) and has never been tried 🟢 **Answered 21.09.2026, and the answer was the awkward one: the address is ours to send, every time.** The vendor's reference was read by layers and so was the cabinet. `core.telegram.org/gateway/api`: `callback_url` is a parameter of `sendVerificationMessage` ("An HTTPS URL where you want to receive delivery reports related to the sent message, 0-256 bytes"), and all three prose mentions under *Report delivery* are phrased around the request — "When you include a `callback_url` parameter in your request", "All reports submitted to your `callback_url`, **if you provided one**". The `<meta>` layer holds six tags and none of them speaks to it. `gateway.telegram.org`, both layers: zero occurrences of `callback` or `webhook` in the raw HTML and zero in `/js/gateway.js`, the bundle that carries the cabinet's own behaviour — and its API-settings form enumerates what it submits, `{account_id, ip_list}`, so that enumeration is exhaustive by construction rather than by reading. Positive control on the same file and grep: `ip_list` five times, plus `revokeToken`, `getLogHistory`, `saveApiSettings`. ⚠️ **What stays unread is the cabinet behind the login** — I hold no account — so the negative is about those two layers and says so. Built: setting `tg_gateway_callback_base` (new `callbackbase` type — HTTPS and the vendor's 256-byte bound checked at save time, trailing slash normalised away), the address assembled by `tg_callback.url_for` from `tg_callback.PATH`, which is the same name the router registers the door under, and supplied at `placement.carriers_for`. Blank ships and stays legitimate: the rung carries, and the loss — no delivery report, no `expired` ending, no refund record — is said out loud once per assembly. `sender_username` rides along as `tg_gateway_sender_username`; what the reference actually says about it is in 1.11. Norm and backing: 'A callback nobody is told about never arrives'
- [x] 4.57a **The parameter every caller forgot had a default, and that is the whole defect class.** `tg_carrier.carrier` took `callback_url: str = ""`, so the one production caller omitting it was indistinguishable from one deciding it — and no test could tell either, because every assertion in the suite read what the carrier *returned* rather than what it *handed on*. The default is gone: the address is keyword-required, blank is a legitimate answer but it has to be given, and seven call sites were made to say it. `sender_username` keeps its default deliberately — absent, the vendor sends under its own name, which is visible and breaks nothing; absent, `callback_url` switches off a whole mechanism silently. ⚠️ **The suite stayed green throughout the defect's life**, which is the reason the new guard reads back what reaches the adapter and checks the door's path against the live route table rather than against the source

- [x] 4.58 The blacklist is asked on the **boundary of the paid ladder**, not only at the door that opens a verification
      The owner's decision of 22.09.2026, and the hole it closes is money. `POST /verifications`
      refuses a blocked number before opening anything and that is guarded — but a number can
      be blocked **while a verification is already open**, by a delivery report crossing
      `blacklist_threshold` on another message or by an operator's hand, and the selection door
      never asked again. The window is the verification's own deadline, five minutes wide, and
      inside it the ladder placed a **paid call** to somebody this gateway had decided not to
      write to at all.
      🔴 **Put in `gates.for_paid_ladder` rather than in `select_verification_route`, and that
      is the whole of the design.** The invariant belongs on the boundary where state changes
      irreversibly — the moment before anything is contacted — and not on a census of the doors
      that reach it; a census is never complete and goes stale in silence, while the gate list
      exists precisely so that a door added later cannot be a door that forgot one. First in
      the order, ahead of the entitlement: a blocked number is not a matter of degree, it is a
      decision already taken not to contact this person at any price for any application.
      Four guards in `tests/test_the_call_rung_is_reachable.py` — the call rung, the cheap rung
      (a confirming `checkSendAbility` is billed, so that one spends too), the positive control
      that an unblocked number is still called, and **a guard on the invariant itself**, which
      assembles the real gate list and requires that *something* in it refuses without naming
      which. `bite-blocked-reaches-no-vendor.sh`, four mutations.
      ⚠️ **The fourth is the one that earns the invariant guard**, and it taught something the
      first draft of this note had wrong: moving the check out to the door reddens **two**
      tests, not one. The invariant guard, because the gate list no longer carries it — and the
      door-level guard too, because a door-level refusal leaves the verification **open**,
      where the gate ends it: the route was claimed before the walk, so `placement.place` fails
      it with the reason. The move is not an equivalent rearrangement; it also changes what the
      person is left with, which is a verification hanging with nothing behind it.

- [x] 4.59 The number is normalised **before the operator is read**, and that is guarded at this door
      The requirement argued for it all along and nothing asked. The validator was there —
      `VerificationCreateRequest.phone` runs the same `validate_and_normalize` the send's
      schema runs — and `tests/test_phone.py` guards the function; what stood unasked is the
      consequence: **the operator table is keyed on the normalised number.** An unnormalised
      one resolves to no operator, takes the rule's unknown-operator entry, and for a МегаФон
      subscriber that entry is the modem — the route this whole change exists to route away
      from. The request succeeds, the number is perfectly valid, and the code goes out over the
      route that has been failing.
      Driven through the real door in the national spelling rather than asserted on the
      validator's presence, with the control that both spellings are offered the same ladder.
      `bite-normalised-before-the-operator.sh`, three mutations: the validator removed here,
      the validator reduced to an existence check that returns its input unchanged, and the
      conversion broken at the shared source. **The second is the point** — it is what a
      validator decays into, and "the validator is visible in the code" would have passed it.

- [x] 4.60 Eleven bites are named in the spec as the basis of a norm and **were never written**
      Found by the circle of 22.09.2026 and then measured rather than eyeballed: `bite-carrier.sh`,
      `bite-code.py`, `bite-credentials.sh`, `bite-ladder.sh`, `bite-lookup.sh`, `bite-modem.sh`,
      `bite-refusals.sh`, `bite-rule.sh`, `bite-template.sh`, `bite-verif-view.sh` and
      `bite-withhold.sh` exist in no commit reachable from any ref — checked one name at a time,
      with `bite-limits.sh` as the positive control so an empty answer could not be a search that
      never ran. This is the `bite-limits.sh` lesson eleven more times: **a reference to a bite is
      a claim about the code like any other.** The spec is corrected already — every such sentence
      now says the mutations were *reasoned*, not run — so what remains here is the work, not the
      honesty: write them, or strike the reasoning and let the named `tests/…` file stand alone.
      Three of the eight requirements written after the 11.09 circle rest on one of these.
      **В работе с 22.09.2026. `bite-code.py` написан и прогнан — 21 мутация, выживших нет**,
      против `tests/test_the_code_and_who_may_spend_it.py`; это самый крупный из
      одиннадцати и единственный, на который ссылались ЧЕТЫРЕ требования сразу. Он нашёл
      две настоящие дыры, а не подтвердил готовое:
      🔴 подтверждающий апдейт по `app_id` был не охранён — через дверь предъявляется
      только НЕВЕРНЫЙ код, поэтому `code = ?` держит апдейт независимо от владения, а
      собственное чтение двери отвечает 404 раньше матчера: два фильтра перед тем самым,
      который проверяли. Матчер теперь спрашивается напрямую, чужим `app_id` и ВЕРНЫМ
      кодом, с контролем от владельца;
      🔴 концовка ПОДМЕТАНИЯ не охранялась: `code = NULL` из `expire_due_verifications`
      снимался молча. Спрятал её счёт по ПИСАТЕЛЯМ вместо концовок — `check_verification`
      держит две из них, поэтому «все три» покрывали подтверждённую и исчерпавшую, а
      подметённую нет. Это концовка человека, которому так и не позвонили, — самая частая
      из четырёх и та, за которой никто не возвращается.
      **`bite-ladder.sh` (девять) и `bite-carrier.sh` (восемь) написаны и прогнаны
      22.09.2026** — все семнадцать красные. Две мутации пришлось перенаправить, и оба
      урока общие:
      ⚠️ мутировать ЗНАЧЕНИЕ константы исхода (`REFUSED = "declined"`) бесполезно — сторож
      сравнивает исход с той же константой, и мутация вырождается в тождество на данных
      самого теста. Различает отказ вендора от отказа абонента карта `_OUTCOME` носителя,
      туда мутация и переехала;
      ⚠️ скрипт, гонявший только «свой» файл тестов, объявил выжившей мутацию «понёс и
      упал — лестница едет дальше», хотя сторож на неё есть — в СОСЕДНЕМ файле. Оба
      скрипта теперь гоняют оба файла: свойство лежит поперёк границы.
      **`bite-modem.sh` (пять) и `bite-withhold.sh` (шесть) написаны и прогнаны
      22.09.2026** — все одиннадцать красные. ⚠️ Контроль `bite-modem.sh` пришлось
      перецелить: «снять словарь отказов абонента» не делает отказ отказом НАМ — он
      проваливается в `unclassified`, который модем не удерживает. Различает не
      отсутствие ветви, а её исход, поэтому мутация теперь возвращает `REFUSED` всему.
      **`bite-lookup.sh` (два), `bite-credentials.sh` (четыре) и `bite-verif-view.sh`
      (пять) написаны и прогнаны 22.09.2026** — все одиннадцать красные, перенаправлять
      не пришлось ничего.
      **Закрыто 22.09.2026: все одиннадцать написаны и прогнаны, 83 мутации, выживших
      нет.** Последние три — `bite-rule.sh` (восемь), `bite-template.sh` (девять),
      `bite-refusals.sh` (тринадцать). Ни одной фразы «скрипт никогда не был написан» в
      спеке не осталось; каждое основание теперь называет прогон.
      🔴 **Итог, который дороже самих скриптов: укус — это не подтверждение, а поиск.**
      Одиннадцать скриптов дали две настоящие дыры (обе в `bite-code.py`: подтверждающий
      апдейт без владельца и неохраняемая концовка подметания) и четыре мутации,
      покрасневшие только со второго прицеливания — тождество на константе исхода, узкий
      файл тестов вместо обоих, «снятая ветвь» вместо изменённого исхода, и календарный
      день, расширявший все три окна вместо одного. Восемь скриптов легли с первого
      захода: значит сторожа под ними были настоящими, а не только названными.
      ⚠️ Три ловушки якорей, каждая оплачена: отступ в четыре пробела там, где ожидались
      восемь (`template._entry`); одинарная кавычка внутри якоря, которую bash не
      переживает без `'"'"'` (обошли, заменив хвост выражения на `or`); и мутация,
      оставляющая ДВА `WHERE` подряд — синтаксическая ошибка краснит всё и выглядит как
      сильная находка.
      Набор 1317 зелёных при тех же шести унаследованных падениях.

- [x] 4.61 🔴 The ladder's gates are asked by the rungs of the walk, not by the door it came through
      **This is the finding both critics reached independently, and it makes the capability
      unusable on the day it ships.** `placement.place` hands `gates.for_paid_ladder` to every
      walk, and `PLACED_HERE` includes `sms_out`; three of those four gates are about money.
      `may_spend` ships `0` for every application (`migrate.py`) and the shipped rule sends every
      operator it does not name to `["sms_out"]` alone — so on stock settings a modem verification
      is refused `422` with "does not hold the entitlement to spend on a paid route", having spent
      nothing and having had nothing to spend. Two more doors into the same hole: a busy *paid*
      hour silences *free* modem sends through `ceiling_gate`, and one paid attempt on the number
      eight seconds ago refuses a free one through `per_number_gate`. Fix is local — the walk's
      rungs are already computed on the line above the gate list. **Bite must include the mutation
      that only the new guard catches:** the suite is green on this today because the door test
      switches `may_spend` on for the whole file and the modem test never reaches the door.
      **Built 22.09.2026.** `for_paid_ladder` takes `rungs` with no default; `place` reads the
      ladder once and hands the same list to both. `bite-free-walk-asks-no-money.sh`, five
      mutations, no survivors. Two of them are why this guard is not a restatement of a
      neighbour — deciding on the *first* rung, and assembling the list from the rung the
      consumer named — and a rule naming a free rung ahead of a paid one is what they catch.
      ⚠️ The fifth survived its first run and the predicate was **not** the thing to change:
      on a ladder of one rung that mutation is the identity. The hole was real, and a
      door-level test for the mixed ladder is what closed it. Suite 1303 green on the same
      six inherited failures.

- [x] 4.62 🔴 The number's paid limits are decided and taken in one act
      Read-then-act: `ladder.walk` runs every gate, and only afterwards writes the row recording
      this attempt. Two verifications for one number — which this capability **explicitly
      permits** — selecting a paid rung together both read an empty history, both pass, and both
      reach a vendor inside the fifteen-second gap. The route claim does not close it: `select_route`
      is keyed on `id`, and these are two ids. Cost is not the second call, it is the vendor
      holding the number for ten hours.
      ⚠️ **The obvious remedy is wrong and the spec already says why:** writing the `attempting`
      row before the gate makes it a paid attempt aged zero seconds against a minimum gap of
      fifteen, so it refuses the very selection that wrote it. The shape has to be the one this
      capability already uses for confirming a code — a single conditional operation that decides
      and records together.
      **Built 22.09.2026.** The limits left the gate list entirely: `queries.claim_paid_rung`
      is one `INSERT … SELECT … WHERE` carrying all three of them as clauses, and `ladder.walk`
      writes every paid rung through it — so the enforcement sits on the boundary where the
      money moves rather than on a list a door has to remember to assemble, and the guard hands
      `walk` an **empty** gate list on purpose. The refusal's *reason* is still read afterwards,
      from the same history, because naming which of the three refused is for whoever reads the
      answer and never for the decision.
      🔴 **The named trap has a second floor nobody named.** A ladder claims its second paid
      rung while the first one's row is zero seconds old, so a claim counting its own walk
      refuses the ladder the right to advance at all — and every neighbouring guard stays green,
      because they all walk a ladder of one rung that carries. The claim therefore excludes this
      verification's own rungs, and a test for the mixed ladder is what holds it.
      `bite-limits-in-one-act.sh`, five mutations, no survivors; the one that matters is the
      decision and the record split into **two statements with the same conditions** — a test
      asserting merely that a limit exists stays green on it.
      ⚠️ Three older bite scripts had anchors into the code this moved, and **two of them were
      already stale before this task** — `bite-window-from-the-door.sh` #1 and
      `bite-blocked-reaches-no-vendor.sh` #1 both anchored on the two-argument
      `for_paid_ladder` that 4.61 had already replaced, so they had been printing "якорь не
      нашёлся" rather than a verdict. All three re-pointed and re-run: 11, 7 and 4 red
      respectively. `bite-limits.sh` #5 is now surgical — it shortens the *day* window to
      seconds-since-midnight instead of widening all three — and kills only the rolling-window
      test, where before it killed three positive controls with it.
      Suite 1310 green on the same six inherited failures.

- [x] 4.63 A carrier holds the ladder's bound as a deadline, not as a duration
      `tg_carrier` hands the same `seconds_left` to `checkSendAbility` and again to
      `sendVerificationMessage`; `flash_carrier`, under the same norm, takes a deadline at entry
      and spends what is left. One rung can therefore spend the ladder's whole budget twice: the
      door answers at about eighteen seconds against a promise of ten, and the next rung is never
      tried because the walk finds the bound gone. The old wording — "each carrier applies it to
      its own vendor calls" — is satisfied by exactly the wrong implementation, which is why it
      has been rewritten. Fix is four lines, copied from the carrier that already does it right.
      **Built 22.09.2026**, and it was four lines. `bite-bound-is-a-deadline.sh`, four
      mutations, no survivors. The guard carries a positive control because "the second call
      got less" is satisfied by flooring everything at `0.1`, which breaks the rung outright —
      a one-inequality guard would have been a hole facing the other way. Suite 1305 green.

- [x] 4.64 The gateway's own number is normalised, or refused, when it is saved
      `Spec("gateway_msisdn", "str", …)` has no validator, and the value goes out to applications
      as **data** in `RouteOffer.number` — the field exists precisely so a consumer can build a
      `tel:` on it without reading our prose. A national spelling is how a person ordinarily
      writes it, and every other door in this estate normalises on the way in. The failure is
      mute: the subscriber dials nothing, the window closes, and the verification reports
      `expired`, indistinguishable from a person who never called. The precedent is in this same
      change — `callbackbase` is a validated setting type, added for the identical reason.
      **Built 22.09.2026**, and the precedent held: `gateway_msisdn` is now the setting type
      `msisdn`, normalised and validated in `normalize_raw`/`validate_raw` exactly where
      `callbackbase` is. It reuses `app.phone.validate_and_normalize` against
      `store.phone_region` — the same call the public send door makes on a subscriber's
      number, which is literally what the norm asks for. Blank still saves: blank is the
      shipped state of an estate with no number, and refusing it would make that estate
      unsavable. No new setting key, so the census guard
      `test_spec_has_all_soft_keys` is untouched.
      🔴 **The instructive mutation is the fifth, and it refuted my own prediction.** Moving
      the check to the *use* (normalising inside `routes._number_for`) was expected to leave
      the door test green and only the setting tests red. It left the door test RED too: the
      field gets normalised while the sentence beside it is still composed from the same raw
      value, so the door-side fix produces the one thing this requirement forbids by name — a
      field that disagrees with its sentence. Checking at the save is not merely earlier, it
      is the only place the two can agree.
      `bite-the-number-normalised-when-saved.sh`, five mutations, no survivors.
      Suite 1315 green on the same six inherited failures.

- [x] 4.65 "Nobody is watching this vendor's balance" is answerable without an event, and said as loudly as the floor
      Both unwatched states in `balance.observe` exit through `logger.warning`; the floor they
      belong to wakes the operator through `notify`. Worse, `observe` runs only when a balance has
      arrived — that is, only once the rung is already carrying — so the rung nobody has used yet,
      which is the case the norm was written about, says nothing at all. **Owner's call which
      channel**: a row beside the rung in the console, a check at startup, or `notify`.
      **Решение владельца 22.09.2026: проверка на старте И `notify`. Построено в тот же
      день.** `balance.report_unwatched_rungs` ждётся в lifespan `app/main.py` прежде, чем
      что-либо можно верифицировать, и обе «не следит никто» ветви `observe` теперь будят
      оператора вместо лога. Рунг без учётных данных из доклада исключён: он не
      предлагается вовсе и не тратит ничего, а доклад о нём на каждом старте учит
      игнорировать канал — тот же довод, которым отчёт об отказах исключает `*` и `?`.
      🔴 Стартовая половина охраняется **через AST**, а не грепом: `assert "<имя>" in
      source` зеленеет от строки импорта, а вызов после `yield` — это проверка на
      выключении. Сторож требует `await` этого имени внутри `lifespan` и ДО `yield`.
      `bite-nobody-is-watching.sh`, семь мутаций, выживших нет.

- [x] 4.66 What a credential rotation costs is stated — and the owner decides whether it is softened
      A rotation takes effect with no restart, so messages already bought keep reporting, signed
      with the key just replaced; every one is rejected. The callback is the **only** path a
      refund ever takes, so a rotation silently drops the refunds for messages in flight and
      leaves recorded spend above money actually spent — the one direction this ledger is written
      elsewhere to forbid. The norm now states the cost. 🔴 **Owner's decision** whether the
      previous credential is honoured for a grace period no shorter than the message window
      (which weakens the signature check, deliberately), or the loss is only made visible. The
      cheap half is separable and already named by the spec as unmet: clock skew and bad
      signatures are counted under one key, so a rotation looks exactly like an attack.
      **Решение владельца 22.09.2026: потерю сделать ВИДИМОЙ, не смягчать.** Прежний ключ
      не честится ни секунды — проверка подписи не ослаблена ничем. Взята и дешёвая
      половина: `tg_gateway.callback_refusal` отвечает, КОТОРАЯ половина отказала (`stale`
      или `signature`), счётчик считает их порознь, и подписный отказ поднимает один
      дедуплицированный алерт, называющий оба прочтения и несущий число рунгов, ещё
      ждущих отчёта (`queries.rungs_awaiting_report`), — ровно те сообщения, чьи возвраты
      ротация роняет.
      🔴 **Две из восьми мутаций нашли дыры в сторожах, написанных в тот же час.** Порядок
      двух проверок не был утверждён ничем: при проверке подписи ПЕРВОЙ всё, что вне окна
      и вдобавок плохо подписано, считается проблемой учётных данных — то есть всякий, кто
      дотягивается до этой публичной двери, получает кредитный алерт как инструмент,
      послав просроченный мусор. Окно — это ровно то, что уже сделало такой трафик
      безвредным. И число в алерте утверждалось только как «число»: понадобился стенд с
      уже отчитавшимся рунгом и с рунгом, который никогда не покупали, чтобы утвердить,
      что ни тот, ни другой в риск не засчитываются.
      `bite-rotation-is-not-an-attack.sh`, восемь мутаций, выживших нет.

## 5. Verify against the real thing

- [ ] 5.1 Run one verification end to end to `+79851600019` on the production host: the call arrives, the digits are read, `/check` confirms, and the outcome reaches the application. The modem route cannot reach that number at all today, so this is the only proof the change works
- [ ] 5.2 Confirm a non-МегаФон verification still arrives as an SMS, unchanged, on the same code path — **to a number the owner has released for probes, not to a customer**. This host carries live customer traffic, and a verification sent to prove a code path still reaches a real person's phone
- [ ] 5.3 Confirm the new refusal fires on a message the owner originates to a МегаФон number, and that the count in 4.18 registers it. **Owner's call whether to also wait for `gmp_app`'s next real message** — as originally written, the first witness of the new behaviour is a customer's message rather than a probe
- [ ] 5.4 Watch the first week's spend against the costs recorded in 1.4 and 1.8 — **both balances**, and with refunds subtracted. A week whose recorded spend and whose two `remaining_balance` readings disagree is either an unattributed possibly-charged check or a refund that was not reflected, and both have counters to look at
- [ ] 5.5 Run one verification end to end over the **Gateway rung** on the production host, to a number reachable in Telegram that the owner has released for probes: the message arrives, the code is ours, `/check` confirms, the signed callback is accepted, and the outcome reaches the application. Until this runs, the cheap rung is proved only off the production host
- [ ] 5.6 Watch one verification **cross the rungs** in production — a МегаФон number the Gateway declines, followed by a call — and confirm the two rungs are recorded as two attempts of one verification, with two vendor identifiers and one code. This is the only proof that the ladder is a ladder rather than two routes that happen to be configured together
- [ ] 5.7 Confirm on stock settings that an unconfigured rung is loud: with the Gateway credential absent, a paid verification alerts and completes by call. **This is the failure mode that costs money quietly**, and the only one in the change where a configuration gap does

## 6. Findings of the conformance sweep, 22.09.2026

Шесть чекеров прочитали двадцать требований, утверждавших «код это делает» (шестнадцать
`[backed]` и четыре без аннотации вовсе): **256 backed, 14 contradicted, 4 unbacked**.
Злой проход по выжившим убил одну находку и сузил две; ложных убийств нет.
Вердикты — `sweep-2026-09-22-*.md` рядом с этим файлом.

Убито: «исключение собственного хода из лимитов противоречит счёту по рунгам» — исключение
написано SHALL'ом той же дельты (`spec.md:1276`), и два платных рунга идут к РАЗНЫМ
вендорам, так что ни один не видит двух авторизаций.

- [x] 6.1 🔴 The owning application reads its own verification code out of `GET /sms/{id}`
      Воспроизведено сквозным прогоном: `select` → `GET /sms/1` отдал
      `'SokolParking: 3164 is your code'` → `POST /check` вернул `confirmed`. На рунге
      `sms_out` код живёт в `messages.text` (`sms_carrier.py:79-81`), а дверь сообщения
      отдаёт `text` владельцу (`router.py:72-80`). Требование «The code never appears
      outside the matcher» этим нарушено, и нарушено в пользу того, кто код заказал:
      приложение закрывает верификацию само, не дождавшись человека. Сторож
      `tests/test_the_code_and_who_may_spend_it.py:484` двери не видит — он перечисляет
      пути по префиксу `startswith("/verifications")` и ищет поле `code`, а течёт `text`.
      Лечится кодом: не отдавать `text` сообщения, несущего `verification_id`, и
      перечислять двери по моделям, а не по префиксу пути.
      **Сделано 22.09.2026.** Граница — в `queries.get_message`, единственном месте, где
      строка `messages` уходит владеющему приложению: `AND verification_id IS NULL`, и
      дверь отвечает 404. Не вычищенным текстом: код обнуляется на каждом терминальном
      окончании, а цифры в `text` живут вечно, так что вычистка перестала бы чистить ровно
      тогда, когда верификация кончилась; и этот id приложению никогда не выдавался —
      вебхук на сообщение верификации не шлётся с задачи 4.27. Перечисление в
      `tests/test_the_code_and_who_may_spend_it.py:470` расширено с префикса `/verifications`
      на ВСЕ модели роутера; добавлены два сторожа — дверь на сообщении с `verification_id`
      и положительный контроль на обычном. Укус: `bite-code.py` вырос до **21** мутации
      (№20 открывает дверь всем сообщениям, №21 закрывает всем), все красные, выживших нет.
      ⚠️ Спека должна догнать: `specs/phone-verification/spec.md:1017` говорит «seven of
      `bite-code.py`'s mutations» — теперь девять. Правка отложена в общий заход 6.11–6.14,
      потому что любая правка `specs/` снимает отметку круга.

- [x] 6.2 An unreadable routing rule leaves a verification offered, recorded and unplaced
      Воспроизведено: нечитаемый `operator_routes` → `POST /verifications/{id}/route`
      отвечает `500`, верификация остаётся `pending` с `route='tg_gateway'` и пустым
      `rungs` — то есть ровно тем состоянием, которое SHALL 1217 запрещает первой фразой.
      `placement.py:137` зовёт `rule.route_for` без `except UnreadableRule`, тогда как
      оба других читателя правила её ловят (`manager.py:695`, `probes.py:157`).
      Лечится кодом.
      **Сделано 22.09.2026.** `placement.place` ловит `UnreadableRule` и отвечает отказом
      ТЕМ ЖЕ каналом, каким отвечает отказ гейта: `Walk(refused_by="the routing rule")`,
      422 у двери и концовка на верификации — потребителю это одно и то же событие
      (ничего не поставлено, ничего не списано, и вендор ни при чём).
      🔴 Прочитать нечитаемое как ПУСТОЕ правило и «нести рунг в одиночку» — не лечение, и
      отвергается теми же словами, что у двух других читателей: пустым правило отправляет
      трафик отведённого оператора обратно на маршрут, который его отвергает, а здесь этот
      маршрут платный. «Несётся в одиночку» — норма про рунг, которого правило НЕ НАЗЫВАЕТ,
      а нечитаемое не сказало ни этого, ни чего-либо ещё.
      Два сторожа в `tests/test_the_door_that_walks_the_ladder.py` (отказ + положительный
      контроль «читаемое правило всё ещё ходит»), новый укус
      `bite-the-rule-at-the-selection.sh` — три мутации, все красные: дефект как найден,
      «прочитано как пустое» и контроль «отказано всегда». ⚠️ Мутация №1 сперва была
      написана снятием `try` и покраснела СИНТАКСИСОМ — красное от нечитаемого файла не
      укус, а поломка; переписана на подмену класса исключения. Набор: 1317 зелёных.

- [x] 6.3 `seed_from_env` writes settings past the typed validation that the doors rely on
      Корень предыдущей задачи и ещё одной: `settings_store.py:658-675` пишет значения из
      окружения сырыми, не зовя ни `normalize_raw`, ни `validate_raw`. Тем же прогоном
      `GATEWAY_MSISDN="8 (926) 123-45-67"` доехал до приложения в `RouteOffer.number`, а
      `OPERATOR_ROUTES="{not a list"` лёг в `settings` и стал предусловием 6.2.
      Норма «нормализован или отказан в момент сохранения» держится у одной двери и не
      держится у второй — притом что аннотация требования утверждает, что «вторая дверь
      не может забыть». Лечится кодом.
      **Сделано 22.09.2026.** `seed_from_env` гонит каждое значение через ту же пару, что
      и `set_many`: `normalize_raw` → `validate_raw`. Непрошедшее **не пишется вовсе** —
      ключ остаётся с shipped-умолчанием, и следующий старт пожалуется снова; строка с
      умолчанием, записанная вместо отказанного значения, заглушила бы жалобу навсегда.
      Значение в строке лога показывается, только если настройка не секрет: сообщение
      валидатора цитирует отказанное, а токен, отказанный по форме, положил бы себя в лог
      шлюза, который нарочно держит учётные данные вне окружения.
      🔴 Фикс завёл зависимость: `msisdn` нормализуется ПРОТИВ `phone_region`, а регион
      лежит в списке спека НИЖЕ номера. Обходом списка по порядку казахский номер
      нормализовался бы против российского региона на том самом старте, который просил
      Казахстан, — молча. Поэтому ключи, которые читают сами нормализаторы, идут первыми
      (`_READ_BY_THE_NORMALISERS`), а принятое значение кладётся в кэш по ходу, как это
      делает `set_many`. Сторож на это есть (мутация 8), и он тихий без неё.
      Шесть сторожей в `tests/test_the_gateways_own_number_is_normalised_when_saved.py`,
      укус `bite-the-number-normalised-when-saved.sh` вырос с пяти мутаций до **восьми**
      (6 — дефект как найден, 7 — контроль «не сеет ничего», 8 — снятый порядок), все
      красные. Набор: 1315 зелёных.
      ⚠️ Спека должна догнать: аннотация требования говорит «turns five red» — теперь
      восемь. Правка отложена в общий заход 6.11–6.14.

- [x] 6.4 The verification door blocks on refreshing a stale operator row
      Замер: протухшая, но присутствующая строка (`МТС`, −400 дней при TTL 7 дней)
      держит `POST /verifications` 3.01 секунды. `router.py:182` зовёт `record_operator`
      безусловно, а `lookup/operator.py:35-40` пропускает только свежую строку и уходит в
      `voxlink.lookup`; бюджетом оказывается `voxlink_timeout`, а не `operator_lookup_bound`.
      Против «Nothing SHALL be delayed … or stale» и «The bound SHALL be spent only where
      the cache holds no operator at all». В отправителе (`manager.py:605-608`) сделано
      правильно — дверь отстала от него. Лечится кодом.
      **Сделано 22.09.2026.** Решение переехало из `ModemManager._operator_for` в
      `app.lookup.operator.resolve_within_bound`, и дверь зовёт ЕГО: протухшая строка
      берётся как есть, `operator_lookup_bound` тратится только там, где оператора нет
      вовсе, и ничего не падает ни от истечения бюджета, ни от исключения. Метод
      отправителя остался — на нём стоит шов, которым рулят его собственные тесты, — но
      стал делегатом: два вызывающих, обязанных решать одинаково, это одна функция, либо
      одна функция и копия, которая отстаёт.
      ⚠️ Шов переехал вместе с функцией: десять тестов `test_send_path_operator_lookup.py`
      правили `manager_mod.record_operator`, теперь правят `operator_mod.record_operator`
      — иначе подмена целит в имя, которого никто не читает. Три из них покраснели сразу,
      то есть шов был живой, а не декоративный.
      Три новых сторожа (протухшее не обновляется; бюджет тратится на неизвестного;
      положительный контроль «оператор всё-таки записан до ответа»), укус `bite-lookup.sh`
      вырос с двух мутаций до **пяти**. Набор: 1320 зелёных.

- [ ] 6.5 A paid ability check can be confirmed, charged and then abandoned unsent
      Сужено злым проходом: сценарий воспроизведён (плата `0.01` записана,
      `sendVerificationMessage` не вызван), но три из четырёх заявленных триггеров
      недостижимы — истечение отрезано порогом `TTL_MIN=30 s` (`tg_carrier.py:91-98`),
      «отмены» в коде нет вовсе, подтверждение чужим рунгом закрыто запросами. Остаётся
      исчерпание попыток через `/check` внутри ~250-мс окна вендора, наносимое владельцем
      токена самому себе. Норма (`outbound-routing/spec.md:461-463`) исключения не знает.
      Лечится спекой (назвать исключение) или кодом (повторная отправка тем же
      `request_id` бесплатна и делает плату возвратной).
      **Решено 22.09.2026: лечится СПЕКОЙ, и правка уходит в общий заход 6.11–6.14.**
      Кодовый вариант не годится ни в одной из двух форм. Отправить «всё равно» нечего:
      к этому моменту верификация окончена, а код обнулён на терминальном окончании, —
      значит пришлось бы либо воскрешать код, либо слать человеку сообщение о
      верификации, которая уже провалена. Повторный вызов с тем же `request_id` запрещён
      тем же требованием абзацем ниже: вендор отвечает на него ошибкой, а не вторым
      сообщением. Остаётся назвать исключение: верификация, кончившаяся между
      подтверждённой проверкой способности и отправкой, — законное основание не
      отправлять; плата записана честно (`cost` и `vendor_ref` на строке рунга), вред
      наносит себе владелец токена, и человек не теряет ничего.

- [x] 6.6 The status-writer census counts function names, not status writes
      Прогнано поверх копии `queries.py` со вторым `UPDATE … status='rejected'` внутри
      существующей `set_message_delivered` и без своего `spawn_delivery_dispatch`:
      `census: GREEN`, `call-site guard: GREEN`. `tests/test_delivery_hooks.py:60` сверяет
      `set(KNOWN_STATUS_WRITERS)` — только ИМЕНА; объявленный статус не читает никто.
      Требование говорит «every code path», сторож считает функции. Живого дефекта
      сегодня нет, дыра — в сторожe. Верификационная половина
      (`test_verification_outcome_reaches_the_app.py:245-259`) сделана строже и ту же
      мутацию роняет. Лечится кодом теста по её образцу.
      **Сделано 22.09.2026.** `KNOWN_STATUS_WRITERS` стал картой «имя → МНОЖЕСТВО
      записываемых статусов», а перепись разбирает половину `SET` отдельно от `WHERE`:
      два писателя выбирают строки по статусу, в котором те УЖЕ находятся, и условие —
      противоположность записи. Связанный `?` пишется как `?`, а не угадывается.
      Укус новый — `bite-status-writers.sh`, три мутации. Порядок был обратный обычному:
      укус написан ДО правки и показал дыру живьём — мутация 1 (второй `UPDATE ... SET
      status = 'rejected'` внутри `set_message_delivered`) прошла **7 passed**, то есть
      сторож был зелен на нарушении. После правки все три красные, включая контроль
      «новый писатель отдельной функцией» — без него правка выглядела бы как перепись,
      которая вообще ничего не проверяет. Набор: 1320 зелёных.

- [x] 6.7 A bare `expired` puts two different facts in one console line
      `tg_callback.py:146-148` пишет `outcome='expired'` голым словом, а заметку про
      возврат кладёт в `reason`. Воспроизведено обычной последовательностью:
      `v.status='expired'`, `v.reason='expired'` и `r.outcome='expired'` встают в одну
      строку консоли (`admin/templates/messages.html:171`) из двух разных фактов —
      вендорского истечения сообщения и нашего собственного окна (`queries.py:1644`).
      Половина «act on» при этом держится: ни одна ветка не сравнивает
      `verification_rungs.outcome` с `'expired'`, возврат живёт отдельной колонкой.
      Лечится кодом (`delivery_expired` / `window_expired`) либо спекой.
      **Сделано 22.09.2026 — КОДОМ, и спека тут права безоговорочно:**
      `spec.md:426` запрещает записывать и действовать на голый `expired` прямым текстом,
      «every reading of that word SHALL name which of the two fields it came from».
      Исход рунга из вендорского поля доставки пишется как `delivery_expired`
      (`_outcome_word` в `tg_callback.py`; остальные слова вендора идут своими),
      собственное окно пишет `reason='window_expired'`, а СТАТУС верификации остаётся
      `expired` — это слово принадлежит её полю (`spec.md:246`).
      ⚠️ Побочно закрыт дрейф контракта: `docs/verification-api.md` утверждал «`expired`
      arrives with no reason», а код всегда писал туда слово. Теперь абзац говорит
      правду. Сторожа у этого утверждения не было — ни один тест
      `test_verification_contract_doc.py` его не читал.
      Три сторожа, новый укус `bite-expiry-names-its-field.sh` — три мутации, все
      красные, включая контроль «переименовано всё подряд» (он теряет `delivered`,
      `read` и `revoked`, то есть чинит имя ценой факта). Набор: 1323 зелёных.

- [x] 6.8 A paid rung records no operator, so «routed without a known operator» is uncountable
      `routed_operator` пишет единственное место (`queries.py:1866`) и только с трёх
      модемных путей (`manager.py:721,749`, `sms_carrier.py:85`); `verification_rungs` и
      `verifications` оператора не держат вовсе, а `tg_carrier`/`flash_carrier` строк в
      `messages` не создают. Требование `outbound-routing/spec.md:289-349` велит записывать
      случай, «so that the case is countable rather than invisible» — на платных рунгах он
      невидим. Лечится кодом.
      **Сделано 22.09.2026.** `verifications.routed_operator` — аддитивная колонка
      (миграция `_add_column_if_missing`, откат = выкатить старый код: до этой правки её
      не читает никто), пишется ОДИН раз на ходку из `ladder.walk` и ДО отказов: случай,
      выпадающий из счёта ровно тогда, когда его отказали, — та же невидимость.
      На верификации, а не на каждом рунге: это один факт на ходку — лестница есть ответ
      правила для оператора ЭТОГО абонента, и все её рунги поехали за одного и того же.
      🔴 Неизвестный пишется СЛОВОМ `?`, а не NULL-ом: NULL не отличает «поехало ни за
      кого» от «строка старше колонки», и число, по которому пересматривают правило, тихо
      включило бы всю историю. Слово — то же, что у правила (`rule.UNKNOWN`), и написано
      символом, которого не может быть в имени сети; равенство двух написаний держит
      отдельный сторож, иначе они разойдутся молча.
      Превращение `None` → `?` стоит на ГРАНИЦЕ записи, а не у вызывающего: вызывающий,
      который обязан помнить, — вызывающий, который забудет, и записал бы он NULL.
      Четыре сторожа, новый укус `bite-routed-operator-is-countable.sh` — четыре мутации,
      все красные. Набор: 1327 зелёных.

- [x] 6.9 A fee that bought nothing is recorded but not readable beside the spend
      Исход `unanswered` на рунге записывается, но «the count is readable beside the
      attributed spend» не исполняется: во всём `app/` единственный агрегат
      (`queries.py:429`) не про деньги, `SUM(cost)` нет нигде. Лечится кодом.
      **Сделано 22.09.2026 вместе с 6.10 — это три сценария одного требования.**
      `queries.verification_spend(period)` даёт по платному маршруту четыре числа, и их
      четыре потому, что любое складывание теряет чей-то вопрос: `attempts`, `spend`
      (суммы вендоров; возврат уже обнулил свою строку в `record_rung_delivery`, так что
      вычитать никому не надо), `refunded` (видимо рядом со спендом, который уже
      уменьшен: молча усохшее число нечем проверить) и 🔴 `possibly_charged` — СЧЁТ, а не
      сумма: у платы, чей `request_id` до нас не доехал, числа нет вовсе. Сложенная со
      спендом, она была бы догадкой; выброшенная — балансом, уезжающим без причины.

- [x] 6.10 A month's spend and a per-application spend are not answerable
      Данные записаны (`verification_rungs.cost`, `verifications.app_id`), а запроса или
      отчёта, дающего ответ, нет ни в `queries.py`, ни в админке. Два SHALL'а требования
      «What verifications cost is visible before the bill is» этим не исполнены.
      Лечится кодом.
      **Сделано 22.09.2026.** `verification_spend_by_app(period)` отвечает «кто потратил»
      из `verifications.app_id`; обе таблицы выведены на `/admin/stats` — там же, где
      период и остальные счётчики, потому что «читаемо» это ЭКРАН, а не запрос.
      Приложения, не потратившие ничего, отсутствуют, а не стоят нулём: «какие вообще
      есть приложения» — вопрос другой страницы. Бесплатные рунги в отчёт не попадают:
      строка нулей под модемом приглашает спросить, у какого он вендора.
      «Месяц» здесь — катящиеся 30 дней, и страница так и подписана: `app/periods.py`
      объясняет, почему календарный якорь проигрывает на умолчании.
      ⚠️ Укус поймал дыру в МОЁМ сторожe: страница рисует `3.50` дважды (по маршруту и по
      приложению), поэтому проверка по числу оставалась зелёной с ОТКЛЮЧЁННОЙ таблицей
      маршрутов. Сторож переписан на предложения пустого состояния — единственные строки,
      уникальные для каждой таблицы.
      Девять сторожей (`tests/test_what_verifications_cost_is_answerable.py`), новый укус
      `bite-what-verifications-cost.sh` — пять мутаций, все красные. Набор: 1336 зелёных.

- [ ] 6.11 Five annotations claim «nothing in production calls this yet», and production does
      Аннотация — такое же утверждение о коде, как SHALL, и эти пять устарели вслед за
      появлением `placement.place`. Поимённо: `outbound-routing/spec.md:607`
      («the gate has no production caller» — а он `router.py:274,304` → `placement.py:168`
      → `gates.py:188`, роутер смонтирован `main.py:131`); блок 728-815 («Counted is not
      produced» — ложно обеими половинами: `ladder.walk` зовётся из `placement.py:162`, а
      у `refusals.record` второй вызыватель `manager.py:751`); `spec.md:181-262`
      («Nothing in production reads the bearer yet … `flash_call` has no probe registered» —
      `probes.py:78`, `router.py:94`, `placement.py:122-128`, `ucaller.py:369-489`, и сама
      заявка это кусает в `bite-flash-call.sh:116`); там же («Still unbacked: every
      rung-skipping clause below» — код есть: `ladder.py:281-291`, `:77`,
      `settings_store.py:79`, `ladder.py:265-267`, `:308-313`);
      `phone-verification/spec.md`, требование 1215+ («The second rung is `flash_call` and
      nothing carries it, task 4.17, blocked on 1.1» — обе задачи закрыты, `tasks.md:8` и
      `:555`, а докстринг `placement.py:88-92` говорит обратное аннотации).
      🔴 Последняя опаснее прочих: на установке с ключом uCaller отклонённый Gateway-ом
      абонент получает платный звонок, а спека обещает громкий пропуск. Лечится спекой.

- [ ] 6.12 The verification capability describes three doors and the contract carries four
      Требование 11-121 говорит, что шлюз отвечает МЕТОДОМ, а `POST /verifications`
      возвращает список предложений и не ставит ничего: метод называется только в
      `POST /verifications/{id}/route`. Противоречие настоящее, и неправа СПЕКА —
      требование строк 1215+ той же дельты существует только при отдельной двери выбора
      («offered, selected, recorded», «walked before the selection is answered»), а
      контракт `docs/verification-api.md:17-30` несёт четыре двери. Устарели вступительный
      абзац требования, два его сценария и перечень владения `spec.md:26-29`.
      Лечится спекой.

- [x] 6.13 The annotation promises seven mutations that do not exist
      `outbound-routing/spec.md:181-262` обещает «seven mutations» за средовую половину
      учётных данных. Укуса, гоняющего `tests/test_credentials_do_not_live_in_the_environment.py`,
      нет ни в одном из 27 `bite-*.sh`, ни в `bite-code.py`, ни в 414 коммитах истории.
      Тот же дефект заявка уже ловила на `phone-verification/spec.md:623` — это второй
      случай, а не первый. Лечится написанным укусом либо снятым числом.
      **Сделано 22.09.2026 — укус НАПИСАН, число оставлено правдой.**
      `bite-credentials-not-in-the-environment.sh`, ровно семь мутаций, все красные, и
      разложены по ДВУМ поверхностям окружения, потому что ломаются они по-разному:
      `os.environ` в `app/` (старшинство строки над переменной, пустая строка, контроль
      «не сеется ничего», сеятель перестал читать окружение — после этого перепись
      «ровно один читатель» проходит впустую, и её вторая половина именно это ловит, и
      два написания второго читателя: `os.environ` и `from os import getenv`) и
      `BaseSettings(env_file=".env")` в `app/config.py`, где чтение делает pydantic и ни
      одного `os.environ` для переписи нет вовсе. Правки спеки не потребовалось.

- [x] 6.14 The annotation promises five mutations of the dispatch shape that nobody runs
      Сужено: по адресу 764-893 находка убита («seven red» и «mutation 9» сходятся —
      `bite-nobody-is-watching.sh:51-103`, `bite-flash-call.sh:87`), но она настоящая по
      адресу `phone-verification/spec.md:752`: пять мутаций формы рассылки не гоняет
      никто, а `bite-late-call-outcome.sh` — про поздний исход звонка, не про это.
      Лечится написанным укусом либо снятым числом.
      **Сделано 22.09.2026 — укус НАПИСАН, число оставлено правдой.**
      `bite-the-push-is-not-a-message.sh`, ровно пять мутаций, все красные, и пятая —
      та самая, которую обещала аннотация: контракт СООБЩЕНИЯ уезжает под сторожем
      (`id` → `message_id`), и сторож обязан сказать «контракт переехал, перечитай этот
      тест», а не зазеленеть на сравнении, потерявшем смысл. Остальные четыре: предмет
      снова в `id`; предмет в `message_id` (поля, которого у сообщения нет вовсе, —
      сравнение двух тел его поймать не может); номер в двух полях сразу; тело перестало
      называть свой род. Правки спеки не потребовалось.
