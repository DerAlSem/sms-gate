## 1. Vocabulary, configuration and their refusals

- [x] 1.1 **Method vocabulary — SETTLED by the owner on 18.09.2026.** One flat field, names
      disambiguated; not the two axes this task proposed. The values are `sms_out` (the
      gateway's SIM sends), `sms_in` (the subscriber texts the gateway), `call_in` (the
      subscriber calls the gateway's SIM), `flash_call` (uCaller dials — our modem does not
      participate), `tg_gateway`, `tg_user`, `max_user`, `app_bot`. Three of this change's four
      values are adopted verbatim; **only `modem` changes, to `sms_out`.** The deltas here stop
      being provisional on the wire values and SHALL be updated to that name — this session did
      not touch this change's spec files, because they belong to whoever is driving it.
      Decided in `verify-by-inbound-contact` task 1.1 and applied there and in
      `route-sends-by-operator`.
- [ ] 1.2 Typed setting: per message class, the ordered list of routes. Refused at save
      time with the offending part named. Absent or empty means the modem alone.
- [ ] 1.3 Typed setting: `app_id` → permitted brands with one default; brand → exactly one
      account. Refused at save when an account is bound to two brands, and when an
      application has permitted brands but no default.
- [ ] 1.4 Typed setting: the message-class rule, and the per-account and per-recipient
      rate bounds. Refused at save when the sum of rung deadlines exceeds the first retry
      interval.
- [ ] 1.5 Failing tests first for 1.2–1.4, each including its refusal case and the
      unparsable-rule alert.

## 2. Class, ladder and the seam with the modem path

- [ ] 2.1 Classifier, with a test asserting the **literal** live templates:
      `SokolParking: 1234` is the four-digit code class, and a 472-character message with
      a link is free text. A text matching no class takes the named default.
- [ ] 2.2 Route interface with four outcomes — accepted, miss, unavailable, indeterminate
      — and a configured deadline per call.
- [ ] 2.3 The ladder: offer in configured order, stop at the first acceptance, skip a
      route that cannot carry the class or is unavailable, **stop entirely** on
      indeterminate. The modem is always last; when no earlier rung accepts, hand the
      message to the existing modem path untouched. The ladder writes no terminal status.
- [ ] 2.4 Test that an indeterminate outcome does not reach a lower rung. This is the
      double-code defect; it is the one test that must exist before any route ships.
- [ ] 2.5 Never substitute another brand's account. Test with the permitted account forced
      into each of `limited`, `logged out` and `missing` by fixture, not by waiting for
      reality.
- [ ] 2.6 Record the route before the status write; expose it in `GET /sms/{id}`, the
      delivery webhook and the admin conversation view.
- [ ] 2.7 Accept `force_sms` and a list of routes to skip; refuse an unknown name with 422
      naming it; give each 422 cause its own `error` key.
- [ ] 2.8 Migration: route column, class column, the durable rung ledger, the rate
      records, the disclosure records, the messenger suppression list. **Backfill `modem`
      on every message that already reached `sent`.** Verify on a copy of the production
      database that the backfill leaves no `sent`-or-later message with a null route.
- [ ] 2.9 Enumerating test over every path that creates an outbound message — today
      `app/api/router.py:29`, `app/telegram_poll.py:70`, `app/admin/router.py:229` and
      `:264`, `app/modem/manager.py:680` — that fails when one of them bypasses the ladder.
- [ ] 2.10 Modem evidence is gathered only over messages offered to the modem rung, and
      does not persist across a period with none offered.
- [ ] 2.11 Blacklist suppression counts modem-reported deliveries only.

## 3. Telegram user account (`tg_user`)

- [ ] 3.1 **Capture the real errors first**, before the classifier is written: on
      `+79851600019` and on a number known to have no Telegram account, record what
      Telethon actually raises for no-account, for privacy-restricted, for flood-wait and
      for a connection lost after the request. Store the captures with the change.
- [ ] 3.2 Wrap Telethon behind the route interface: login, session, resolve, send, undo the
      contact entry. No Telethon type crosses the interface.
- [ ] 3.3 Map each captured error to one of the four outcomes, citing the capture. Anything
      uncaptured is indeterminate.
- [ ] 3.4 Durable rate bounds and the atomic claim; test the restart case by restarting.
- [ ] 3.5 Session marked secret, excluded from backups and from git; 2FA set; a rehearsed
      re-login on the probe account, with the code withheld from inbound dispatch and from
      the alert channel.

## 4. MAX user account (`max_user`)

- [ ] 4.1 Capture the real errors first, as in 3.1, through PyMax.
- [ ] 4.2 Wrap PyMax behind the same interface: `search_by_phone`, `add_contact`,
      `send_message`, and the removal of the contact afterwards.
- [ ] 4.3 Test that any client failure or hang fails only this route and that the ladder
      still reaches the modem.
- [ ] 4.4 Same outcome mapping, same durable bounds, same session handling as section 3.

## 5. Accounts, presentation and answerability

- [ ] 5.1 Owner: a number per brand, two accounts on each. Record number, brand, messenger
      and account id in the settings of 1.3 — not in prose.
- [ ] 5.2 Record each account's presentation: display name, username, photo, description
      naming the service. Verify by looking at the account as a stranger sees it.
- [ ] 5.3 First-contact message identifies who is writing and why.
- [ ] 5.4 Replies reach the operator by the inbound path; a refusal suppresses messenger
      routes for that number without blacklisting it out of SMS.
- [ ] 5.5 Aggregate alert: N consecutive non-acceptances on a route, or zero acceptance
      share while messages are still offered. Plus the limited/logged-out alert.
- [ ] 5.6 Disclosure records queryable by number, so a person who asks can be answered.

## 6. The reachability door

- [x] 6.1 Owner's decision, taken 13.09.2026: **the answer spans every application's
      traffic.** The narrow alternative would tell an application only what it already
      knows. Normative in `number-reachability`; the legal question it raises is not
      closed by it and goes to the lawyer with the messenger accounts.
- [ ] 6.2 `GET /reachability/{phone}` behind `get_app_id`, the same credential
      `POST /sms/send` demands, with a test that an uncredentialed call is refused. The
      answer: per route, the last reach with its time and its evidence strength, plus
      blacklist state and when it was blocked. No boolean anywhere in the response.
- [ ] 6.3 Test that a number never offered to a route is answered differently from a
      number offered and never accepted. These are the two states with opposite remedies;
      an implementation that returns nothing for both satisfies a careless reading.
- [ ] 6.4 Test that the door contacts no vendor and consumes no rate allowance — assert on
      the route interface being untouched, not on a timing observation.
- [ ] 6.5 Test that the answer carries no `app_id`, no message text and no counts, for a
      number whose only traffic belongs to another application.
- [ ] 6.6 Migration: the append-only record of questions put to the door — asking
      application, number, time. Separate from the disclosure records of 2.8, which account
      for numbers sent to a vendor rather than numbers asked about.
- [ ] 6.7 Answer the reachability question in the admin console too, so the operator
      diagnosing "the customer says nothing arrived" reads it where they already are.

## 7. Verification

- [ ] 7.1 Run the suite and compare the failure list **by name** against the four known
      macOS failures, not by count: a fifth hides inside "four".
- [ ] 7.2 On the production host, prove the ladder to `+79851600019` only: a messenger
      rung carries a code, `GET /sms/{id}` reports the route, and the delivery webhook
      carries it.
- [ ] 7.3 Prove on the production host that a messenger-delivered message is `delivered`
      with delivery inferred and is **still** `delivered` after
      `delivery_timeout_seconds` has passed. This is the expiry defect; it cannot be
      proven by a unit test that does not run the sweep.
- [ ] 7.4 Prove the forced descent: `force_sms` on a number reachable in Telegram is
      carried by the modem.
- [ ] 7.5 On the production host, ask the door about `+79851600019` after 7.2 has run: the
      answer names the route that carried the code, the time, and the evidence strength —
      and asking it a second time changes nothing about the number.
