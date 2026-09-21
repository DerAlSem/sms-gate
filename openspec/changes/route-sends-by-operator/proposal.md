## Why

The gateway has exactly one way to reach a subscriber: the modem. That was never a design
decision, it was the absence of one — and the assumption underneath it is that the SIM will
keep being allowed to carry this traffic. It has already been withdrawn once: this SIM has
been blocked before, and on 06.09.2026 at about 18:30 MSK messages bound for a МегаФон
subscriber began coming back `0x63` (service rejected) while every other operator delivered
normally in the same minutes.

A probe that day sent six messages to one operator-confirmed МегаФон number, differing in
wording, in alphabet, and in whether they carried a code at all. All six were rejected
identically. The cause is the sender's route to that operator. Nothing in the message and
nothing in this codebase can change it.

**The recurring event is not "МегаФон is refusing".** It is "the modem route stopped working
for some part of the estate", and its blast radius has been total before. A branch that
names МегаФон would encode the shape of one symptom; the next withdrawal would need code
again, during an outage, which is the worst moment to be writing any.

**Owner's decision, 08.09.2026:** the second route is not a second way to send SMS. It is
https://developer.ucaller.ru — a flash call, where the code is the last four digits of the
calling number. Our modem does not participate at all; the vendor's infrastructure calls the
subscriber's phone. It is therefore a way to deliver a *verification code*, and only that.

## What Changes

- **A verification stops being an SMS the application composes.** The application asks the
  gateway to verify a number; the gateway generates the code, chooses how to deliver it, and
  answers whether a code the person typed is the right one. This is the contract already
  drafted for `verify-by-inbound-contact` (renamed from `verify-by-inbound-code` on
  18.09.2026) — the same door, with a third method behind it. 🔴 **That contract was never
  sent to the parking developer**; the owner said so on 18.09.2026 and the earlier claim here
  was wrong.
- **A send acquires a route.** The modem stops being the only way out and becomes one route
  of three: Telegram's Gateway API, uCaller's flash call, and itself.
- **The paid way out is a ladder, not a route** — Telegram Gateway first, the flash call
  behind it — so that a subscriber the Gateway cannot reach costs nothing before the call is
  placed. Owner's decision of 18.09.2026.
- **Route selection is a configured rule keyed on the recipient's operator**, not a branch.
  Today it carries one entry — МегаФон to `[tg_gateway, flash_call]` — set without deploying code,
  and the *order* of that list is part of what is configured.
- **Spending on a paid route is an entitlement of the application, off by default.** Three of
  the four applications never send codes; today any active token could open a paid
  verification.
- **The text of an SMS-carried code comes from a per-application template**, and an
  application without one is refused rather than given wording the gateway invented.
- **The rule and both vendors' credentials live in `settings`**, marked secret, changeable
  without a restart. `.env` is at most a one-time seed and never the place a value lives.
- **A message that its operator's route cannot carry is failed at once**, not attempted and
  not silently rerouted. A flash call carries four digits and nothing else; free text,
  a link, or a multipart notice cannot travel it.

Explicitly **not** in this change, by the owner's decisions of 07–08.09.2026:

- **no automatic failover between the modem and the paid way out.** A route that starts
  failing does not reroute itself, in either direction. The ladder added on 18.09.2026 is not
  that: its rungs are both paid, its order is configured rather than discovered, it advances
  only on a rung *declining to carry* rather than on one failing after it accepted, and the
  spend ceiling that made escalation unsafe to talk about in the first place is now a norm of
  this change rather than a future one.
- **no migration of the other operators.** The modem keeps МТС, Билайн, Теле2 and the rest.
- **`verify-by-inbound-contact` (renamed from `verify-by-inbound-code`) is not edited by this
  change, but it now edits this one.** It was frozen on 08.09.2026 as the reserve path and
  unfrozen by the owner on 12.09.2026. On 18.09.2026 the owner decided its routes are rungs
  **inside `phone-verification`** rather than a capability of their own, so that change carries
  `MODIFIED` and `REMOVED` blocks against requirements authored here — including the removal of
  `A verification request names only the number, and the gateway answers with the method`, which
  its list-of-routes answer replaces. 🔴 **It must not be archived before this change**, or
  those blocks address requirements the living spec does not hold and merge silently into
  nothing; its `check-base.sh` and the registry row `sms-gate/20260918-04` hold that order.

## Measured, not quoted

From the gateway's own ledger on the production host, read on 08.09.2026. Two figures
carried in the first draft of this proposal were wrong and are corrected here.

⚠️ **`upper()` and `LIKE` in SQLite are ASCII-only.** `number_operators` holds МегаФон under
two spellings — `МЕГАФОН` (120 numbers) and `МегаФон` (57) — and a case-insensitive match
silently counts only one of them. Every figure below matches both spellings explicitly. The
first attempt at this table did not, and undercounted МегаФон by half.

Messages per month, by originating application:

| App | Jun | Jul | Aug | 01–08.09 |
|---|---|---|---|---|
| `sp_app` (parking) — total | 314 | 276 | 265 | 183 |
| `sp_app` → МегаФон | 55 | 94 | 46 | 77 |
| `gmp_app` — total | 29 | 178 | **297** | 71 |
| `gmp_app` → МегаФон | 6 | 36 | **63** | 18 |
| `mprz_bot` → МегаФон | 0 | 0 | 2 | 6 |
| `turbo_route_bot` → МегаФон | 12 | 4 | 0 | 1 |

**Half the МегаФон traffic is not the parking app.** In August — the last full month —
МегаФон received 111 messages, of which 46 came from `sp_app` and 63 from `gmp_app`, which
is growing (6 → 36 → 63). This is the fact that shapes the change: a flash call can serve
`sp_app` completely and `gmp_app` not at all.

**What each application sends** (448 `sp_app` and 368 `gmp_app` messages since 01.08):

| | `sp_app` | `gmp_app` |
|---|---|---|
| carries a four-digit run | 446 of 448 | 325 of 368 |
| carries a five-digit-or-longer run | **0** | 237 |
| carries a link | **0** | 19 |
| text length | 8–26 chars | 11–472 chars |

`sp_app` is one template, `SokolParking: ####`, and nothing else. `gmp_app` is free text.

**The refusal is heavy, not total.** Between 06.09 18:30 MSK and 08.09, 55 messages went to
МегаФон numbers: 49 failed and **6 were genuinely delivered** — real `+CDS` reports, with
`delivery_inferred = 0`, so not the sweep's inference. Roughly one in nine still gets
through, spread across both days rather than clustered before the block bit. That does not
save the channel — a confirmation code that arrives 11% of the time is unusable — but
"0 of 16" from the earlier note was a small sample, and the true shape is a filter, not a
wall.

**Cost.** uCaller charges 0,80 ₽ per verification (the landing page offers "from 0,4" at
volume; the docs' worked example shows `cost: 0.3`). At the three-month mean of 65 `sp_app`
verifications to МегаФон per month, that is **≈ 52 ₽/month**, against 2,92 ₽ per SMS at
P1SMS — the provider the first draft of this change was written around — which would have
been ≈ 190 ₽/month for the same traffic. The vendor's two free repeats per verification are
not charged.

## The single unverified link

**We have never proved that a flash call reaches a МегаФон subscriber.** The whole change
stands on it. Voice availability is not SMS availability: a busy line, a diversion, a
call-blocker app or a hidden-number filter each break a call where an SMS would have
arrived, and none of them show up until tried.

It costs one call to `+79851600019` (an operator-confirmed МегаФон number the owner has
released for probes) once an API key exists. **Task 1.1, before anything else is built.**

**The ladder of 18.09.2026 adds a second unverified link rather than removing the first.**
Whether that number is reachable in Telegram at all is equally unknown, and it decides which
rung ever runs in practice: a subscriber base with no Telegram is a ladder whose first rung is
always declined, paying for the check to learn nothing. The measurement the messenger session
called cheap and refused to take without permission — what share of these numbers is reachable —
is the same question, and it stays the owner's to give.

What is genuinely cheaper here is the *mechanism* probe, as opposed to the reachability one: the
vendor states that `sendVerificationMessage` is **"always free of charge when used to send codes
to your own phone number"**, so the Gateway rung can be proved end to end — code supplied by us,
`ttl`, delivery report, callback signature — for nothing, against the owner's own number, before
any balance is funded. That probe does not answer whether a *customer's* МегаФон number is
reachable; it answers whether our half works, which is the half we can fix.

Neither rung is proved by the other. A ladder whose first rung is unproven and whose second is
unproven has two ways to be void, and the tasks keep them apart.

## Checked against the messenger work, 12.09.2026

The owner parked this change on 11.09 to deliver codes over Telegram and MAX instead, with a
standing instruction to check with that work before returning here. Done 12.09; the facts below
came from that session, not from this code, and none of them is a decision.

**By mechanism, the messenger path covers the parking app completely.** It carries arbitrary
text including links (4096 characters on Telegram, 4000 on MAX), needs no prior binding — a
user account addresses a subscriber by phone number directly — and therefore works for a
*first* login, which is the parking case. It needs **no change in `sp_app` at all**: the ladder
sits behind the existing `POST /sms/send`, and the answer merely gains an optional "carried by"
field. Where a flash call serves `sp_app` and cannot serve `gmp_app` at all, this serves both.

**By share, nobody has measured it.** How many parking numbers are actually reachable on
Telegram or MAX is unknown. It is cheap to measure without sending anything, but it means
running live customer numbers through a third-party unofficial API, and that is the owner's
decision to give.

**This change's endpoint is not made redundant by it.** `POST /verifications` exists for one
reason that does not go away: with uCaller the code is born at the vendor — it is the last four
digits of the calling number — so the application cannot know it. For a messenger or an SMS
there is no such need.

⚠️ **Two conflicts the owner has to settle, and neither is resolvable from code:**

1. **Telegram's Gateway API is a direct competitor to uCaller and was not in this proposal.**
   Official, delivers a code by phone number with no bot and no binding, `checkSendAbility`
   *before* sending, `checkVerificationStatus` for the code the person typed, a TTL of 30–3600
   seconds, and roughly a dollar a month at the measured 111 МегаФон messages — the same order
   of price as uCaller's 0,80 ₽.

   Read from the vendor's own reference on 12.09.2026, because the first draft of this paragraph
   got it wrong and a peer session caught it. A confirmed sendability check is **not** free —
   *"If the ability to send is confirmed, a fee will apply according to the pricing plan"* — but
   it is not a second charge either: *"Within the scope of a `request_id`, only one fee can be
   charged. Calling `sendVerificationMessage` once with the returned `request_id` will be free
   of charge"*, and *"If a message is **not** delivered within the specified `ttl`, the request
   fee will be refunded automatically"*.

   So the axis that matters here survives the correction, in a narrower form: **an unreachable
   subscriber costs nothing either way** — a negative check is free, and a positive check whose
   message then fails to arrive is refunded. Against that, this change pays for a *placed call*
   and learns nothing about whether the person read the digits: `call_status: 1` means the call
   was made, which this proposal already states says nothing about the subscriber seeing the
   number. And the single unverified link above — whether a flash call reaches a МегаФон
   subscriber at all — is answerable here only by buying a balance and trying.

   The owner has seen this option and chose user accounts for the *messenger* work; that does
   not settle it for the paid fallback, which is this change.
2. **The messenger ladder's bottom rung is "SMS / uCaller" — automatic escalation into a paid
   channel.** This change forbids exactly that, by the owner's decision of 07–08.09, on the
   grounds that escalation without a spend ceiling turns a fault into an unbounded bill. The
   ceiling now exists as a norm here (see `outbound-routing`), so the two can be reconciled —
   but as written the two designs contradict each other, and the reconciliation is a decision.

**A new legal branch appeared that this change's Telegram note does not cover.** The user-account
route carries its own exposure — Telegram restricts an account on spam reports, naming links
among the triggers, first for days and on repeat permanently; the MAX library in question
declares itself an unofficial internal API; MAX's official client surface is an application-only
programme. Our own open branch (a bot asking for a phone number as grounds for login) is
untouched by their design and remains unresolved and waiting on a lawyer — both belong in front
of the same lawyer.

## The paid way out becomes a ladder, 18.09.2026

**Owner's decision, taken on the reconciliation above.** The competitor the messenger session
found does not replace uCaller and is not made to choose against it: it goes *in front* of it.
A verification for an operator routed to the paid way out first asks Telegram's Gateway whether
the subscriber can be reached there, and only a subscriber it cannot reach is worth the price of
a call.

The reason is the shape of the two vendors' billing, not a preference between them:

- **an unreachable subscriber costs nothing.** `checkSendAbility` refusing is free;
- **a reachable one costs one fee, and only one.** *"Within the scope of a `request_id`, only
  one fee can be charged. Calling `sendVerificationMessage` once with the returned `request_id`
  will be free of charge"*;
- **a code that does not arrive is refunded.** *"If a message is not delivered within the
  specified `ttl`, the request fee will be refunded automatically"*;
- **uCaller charges for a call that was placed**, and `call_status: 1` says nothing about
  whether anyone read the digits.

🔴 **What this is not: a free probe.** The vendor is explicit that *"if the ability to send is
confirmed, a fee will apply"*. The first draft of the messenger reconciliation got this wrong
and was corrected on 12.09.2026 against the reference; the correction survives here as a design
constraint rather than a footnote. A confirmed check is money already spent, so **every gate
that could refuse a verification — the blacklist, the per-number limits, the application's
entitlement, the spend ceiling — is evaluated before the ladder is touched at all**, and a
confirmed check is always followed by the send it paid for. A check that times out is worse than
either outcome: it may have been confirmed and charged at the vendor without our learning the
`request_id`, and such a fee can be neither spent nor refunded. It is counted separately,
because otherwise it appears only as a balance that drifts.

**What the ladder does not fix.** It widens how a *code* reaches a МегаФон subscriber and does
nothing at all for the applications that are not sending codes. `sendVerificationMessage` takes
a code and no message body, so `gmp_app`'s free text with links has no more of a field to travel
in than a flash call gave it. The cost to the other applications, stated below, is unchanged.

**What it adds that the call route never had: evidence.** The Gateway reports `sent`,
`delivered`, `read`, `expired` or `revoked`. The change's single unverified link — does a paid
route reach a МегаФон subscriber — becomes answerable from the vendor's own report on this rung,
and stays unanswerable except by asking a person on the other. The two rungs will therefore never
be equally well evidenced, and their success rates are not comparable quantities.

**What it costs in new failure points, honestly.** A second prepaid account that can run out; a
second credential that can be wrong; a second vendor that can be slow rather than refusing, which
turns the cheap rung off silently and shows up only as a bill. Hence: the balance floor is held
against each vendor separately, every alert names which vendor it is about, the spend ceiling
counts the two rungs together rather than each alone, and an abandoned ability check is counted.

## MAX advertises the Gateway shape and sells no product behind it, 21.09.2026

Task 2.9, read from the vendor's own pages on 21.09.2026. The owner was right about what
`business.max.ru` says, and the wording is **metadata, not a product page** — it lives in the
page head and nowhere in the page:

> `<meta name="description">` — *"Единая платформа для уведомлений по номеру телефона, кодов
> подтверждения, рассылок и автоматизации процессов через мини-приложения и чат-боты"*
>
> `<meta name="keywords">` — *"…уведомления по номеру, … подтверждение кода, альтернатива SMS,
> … 2FA в мессенджере…"*

The visible page sells four things and none of them is that: чат-боты, мини-приложения, каналы,
Цифровой ID. `dev.max.ru/docs/maxbusiness/selectionservices` names the same four as the whole of
what a verified profile may connect. There is no fifth door, no price list, no `sendCode`.

**Wall one — nothing in the API can address a phone number.** The reference at
`dev.max.ru/docs-api` addresses `chatId` and `user_id`; the string `phone` does not occur in it
at all (checked with `chatId` and `user_id` as positive controls, so the empty result is a fact
about the page rather than about the grep). Every mention of a телефон in that reference travels
**inbound**: the `request_contact` button, by which a person hands their own number to a bot they
have already opened. So the record of 12.09.2026 — *"в MAX номером адресовать нельзя"* — needs no
correction after all. It needed a citation, and now has one.

**Wall two — the contract forbids it outright, and this is the harder wall.** *Требования к
содержанию и функциональности Приложений Разработчиков*, `dev.max.ru/docs/legal/requirements`,
«Редакция от 16.12.25», clause 1.5 among the things a Developer is forbidden to publish:

> *"используют API либо иную техническую интеграцию с Программным обеспечением Компании для
> формирования, передачи или отправки **Авторизационных сообщений**, Транзакционных сообщений и
> Сервисных сообщений, а также для рассылки рекламных и маркетинговых или иных массовых сообщений
> пользователям, **за исключением случаев, прямо предусмотренных Договором с Компанией вне
> зависимости от наличия технической возможности**."*

And the term is defined to be exactly our traffic — *Правила размещения*,
`dev.max.ru/docs/legal/rules`, «Редакция от 11.06.26»:

> *"**Авторизационные сообщения** — сообщения, содержащие либо инициирующие передачу одноразовых
> кодов (в т.ч. QR-коды), токенов, ссылок, или иных данных, которые действительны для одного
> сеанса, операции или транзакции, и предназначены для аутентификации, идентификации или
> верификации при взаимодействии со сторонними информационными ресурсами."*

🔴 **The clause anticipates the workaround and closes it by name.** *"Вне зависимости от наличия
технической возможности"* means a route that happens to work is still forbidden — so no amount of
ingenuity with bots, channels or mini-apps turns this into a permitted rung. The single exception
is a *Договор с Компанией*: a negotiated contract, not a self-serve product. That is an owner
move (`partner_support@max.ru`, or the «Поддержка MAX для бизнеса» chat), and until such a
contract exists nothing on this rung may be built or asserted.

**The ИП gate, answered from the vendor and not second-hand.** The reported restriction — "since
August 2025 only Russian legal entities may create and publish bots, ИП and самозанятые excluded"
— is **not what the vendor's current pages say**, in either direction the task warned about:

> `dev.max.ru/docs/maxbusiness/connection` — *"Подключение к платформе MAX для партнёров и её
> сервисам — чат-ботам, мини-приложениям, каналам — доступно для юрлиц, ИП и самозанятых, которые
> являются резидентами РФ. Подключение к сервису Цифрового ID доступно только для юрлиц и ИП
> (резидентов РФ)"*, and *"Физические лица и нерезиденты пока не смогут пройти верификацию"*.
>
> The *Правила* define the Developer who publishes — footnote ¹ — as *"Юридическое лицо,
> индивидуальный предприниматель, … а также лица, применяющие специальный налоговый режим «Налог
> на профессиональный доход» (Самозанятые)"*.

So an ИП may publish bots, mini-apps, channels and Digital ID; a самозанятый everything but
Digital ID. Registering is not narrower than publishing here — the same three categories carry
both. The restriction as reported does not hold, and it is recorded as refuted rather than
carried forward.

⚠️ **Both quoted documents change silently by their own terms** — the *Требования* say so in
6.1: changes take effect on publication, with no notice. The edition dates above are what pins
this verdict; a re-read is cheap and is what should happen before anyone acts on it.

**Two facts found here that belong to `reach-people-in-messengers`, not to this change.** They
are recorded and deliberately not acted on from this branch:

- MAX *does* have a verification primitive, and it is the **inbound** shape our sibling change is
  named after: the `request_contact` button returns `attachments[].type: "contact"` with a payload
  `{vcf_info, max_info, hash}`, where `hash == HMAC-SHA256(access_token, vcf_info)` and `vcf_info`
  is a VCARD carrying `TEL;TYPE=cell:79990000000` — the number **without** a `+`, as uCaller also
  returns it. Matching the hash proves the person controls the number bound to their MAX account.
  It still requires the person to have opened the bot, so it is not a route we can initiate;
- the user-side terms, `legal.max.ru/ps`, forbid *"использовать без специального на то разрешения
  Компании автоматизированные скрипты (программы, боты, краулеры) … для взаимодействия с Сервисом
  и его функциональностью"*. That change's proposal records that **no** cited term permits an
  automated user account to carry traffic; there is now a cited term that **forbids** it absent
  permission. It belongs in front of the same lawyer as the rest of that question.

## Capabilities

### New Capabilities

- `outbound-routing`: which way out a message or a verification takes, what the rule is, in
  what order the paid ways out are tried, who is allowed to pay for them, where their
  credentials live, and what happens when the chosen route cannot carry what it was handed.
- `phone-verification`: verifying that a person holds a phone number — the request, the
  code, the choice of method, and the answer to "is this the right code".

### Modified Capabilities

- `outbound-send`: a message may now be refused before the modem is touched, because its
  operator's route cannot carry text.
- `delivery-dispatch`: the same per-application routes now carry verification outcomes as well
  as message statuses, and the two must not be mistakable for each other. The live capability
  fixes both the body and the rule that every status writer notifies, so carrying a second kind
  of thing over it changes it and cannot be left undeclared.

## What this costs the other applications

`gmp_app`, `mprz_bot` and `turbo_route_bot` do not send codes and cannot use either paid route:
a flash call has no text field, and the Gateway's verification message has no body of ours.
Their МегаФон traffic — about 70 messages a month and growing — will be **failed at accept
time** with a named reason instead of failing after the retry ladder. Owner's decision of
08.09.2026, taken with this consequence stated: the outcome is the same failure either way,
delivered sooner and with a reason a human can act on.

Two hazards follow, and both are tasks rather than prose:

1. **If МегаФон recovers and the rule is left set, those applications stay broken silently.**
   The refusal must be countable per operator, so the rule's cost is visible.
2. **The parking app must adopt the new endpoint before any of this helps a single person.**
   Until it does, МегаФон users get nothing new. The gateway side can be finished and
   verified independently, but the outcome for a customer waits on the parking developer.

## Open questions — design, not implementation

**All three of the questions this chapter carried are answered, and so is the entitlement the
critic round left open. The owner took all four on 18.09.2026**, and they are norms now rather
than questions:

1. **How long a verification stays open, and how many attempts it allows** — five minutes and
   five attempts, as settings. Both coincide with numbers the gateway already holds:
   `delivery_timeout_seconds` is 300 and `blacklist_threshold` is 5. 🔴 It also diverges from
   the contract already in the parking developer's hands, which states ten minutes; that
   letter is task 3.1 and it is the owner's to send.
2. **Where the SMS method's text comes from** — a per-application template, refused at accept
   when absent, with no built-in default. A default would be a wording decision taken silently
   for applications that do not share a voice.
3. **Where the routing rule lives** — `settings`, marked secret where it is a credential.
   `.env` was never a candidate once the code was read: `seed_from_env()` copies a variable
   into `settings` only for a key with no row, so it is a one-time seed and not a home.
4. **Whether spending on a paid route is an entitlement of the application** — yes, and off by
   default, including for a newly issued token.

**What remains open, and both are new rather than carried over:**

1. **Whether a Gateway message that was accepted and then not delivered within its `ttl`
   escalates to a call.** The spec's default is that it does not: the fee is refunded and the
   verification fails with that reason. The argument for escalating is that the refund makes it
   nearly free, and it is a real argument — which is why this is an open question and not an
   omission. Nothing may be built as escalation until it is decided.
2. ~~**Which word survives for the flash-call route.**~~ ✅ **Decided by the owner 18.09.2026:**
   one flat field, names disambiguated — `flash_call` (the vendor dials), `call_in` (the
   subscriber calls our SIM), `sms_out` (our SIM sends), `sms_in` (the subscriber texts us),
   `tg_gateway`, `tg_user`, `max_user`, `app_bot`. `call` is retired outright and `modem` is
   retired in favour of `sms_out`. Applied throughout this change.

## Status

**Rewritten 08.09.2026** from the P1SMS draft of 07.09.2026, on the owner's decision to use
uCaller. **Critiqued 11.09.2026** — one round, both critics, seeded with the mechanical pass;
32 findings deduplicated to 20 and checked against the code before being accepted. Three were
corrected by that check: the unknown-operator hole is narrower than reported, because
`record_operator` is awaited before a message is created and resolves a first-time number
synchronously; what it did confirm is that the requirement claiming nothing is delayed cited
that same code as its evidence. The round added 22 scenarios and one capability delta
(`delivery-dispatch`), and it is closed — the ceiling is one round.

Two of its findings were left for the owner rather than written as norms: an entitlement
deciding which applications may spend on a paid route (today any active token can), and the
rewriting of tasks 5.2 and 5.3, which as written prove the change on live customer traffic. The
first is now a norm — see below. The second is still the owner's, and tasks 5.2 and 5.3 carry
it.

**Parked 11.09.2026, unparked 18.09.2026, and updated the same day** with the owner's answers to
all four open decisions and with the ladder. The intent is the one this change was written for —
get a code to a МегаФон subscriber without the modem — so this is an update to it and not a
change of its own. **The critic round is not reopened**: the ceiling is one round and it was
spent on 11.09.2026. What ran instead, before and after this update, is the mechanical pass —
`openspec validate --strict`, `check.py`, and a diff of scenario names against the pre-update
census of 70.

The vendor contracts behind the two paid rungs were taken from official references and neither
from a live sample:

- **uCaller**, read 08.09.2026 — satisfies the external-contract gate for `initCall`, `getInfo`
  and `initRepeat`. The `inboundCallWaiting` webhook is deliberately absent from this change:
  its payload fields are not in the documentation, and a parser for it may not be written from
  guesses.
- **Telegram Gateway**, read 18.09.2026 — `checkSendAbility`, `sendVerificationMessage`,
  `checkVerificationStatus` and `revokeVerificationMessage`, with their parameters, the
  `RequestStatus` / `DeliveryStatus` objects, the `ttl` range of 30–3600 s, the fee and refund
  rules quoted above, and the callback's `X-Request-Timestamp` / `X-Request-Signature` headers.
  Its callback *is* documented, which is why this change may specify verifying it where it may
  not specify parsing uCaller's.

**No live sample has been captured for either.** Tasks 1.3 and 1.6 exist to capture them, and no
adapter is written before they are.
