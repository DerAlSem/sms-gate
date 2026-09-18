The contract with the parking application is settled before anything is built: two teams
implement against it, and changing it later costs both.

🔴 **The contract was handed over on 07.09.2026, before this change was frozen, and five
things in it have since diverged from what `route-sends-by-operator` normalises.** They are
carried by tasks 1.1 to 1.5 below. None of them is ours to change: the developer holds a
document the owner sent, and amending it is the owner's letter to write. Recorded here so the
divergence is not discovered during implementation by the team on the other side.

## 1. Agree the contract

- [ ] 1.1 Get the parking developer's answer to the one question that shapes the build: webhook or polling. The contract already handed over answers it for them — it specifies a webhook, body `{"event":"verification.confirmed","id":…}` — so the open half is whether that app can in fact receive callbacks. ⚠️ Settle at the same time that the verification id sits in a field named `id`: the critic round of 11.09.2026 landed the opposite norm, that a verification's id belong to a field distinct from `id` so a receiver cannot read a verification as a message. `event` carries the kind; `id` alone does not
- [ ] 1.2 Confirm the gateway's own number as the one subscribers text, and that it is safe to publish to end users. ⚠️ **There are TWO placeholders in the contract, not one** — `+79001234567` in the JSON example and `+7 900 123-45-67` in the screen text — and both are already at the developer. Replacing one and not the other ships a contract that contradicts itself
- [ ] 1.3 Agree the expiry with the parking developer. Long enough for a person to type an SMS in a car, short enough that a code is not left standing. ⚠️ **No longer a free choice: the contract states 10 minutes to the end user** ("Код действует 10 минут", plus `expires_at`), while `route-sends-by-operator` carries a proposal of 5 minutes. Accept 10 and align the neighbouring change, or amend the contract — but not both, and the owner decides which
- [ ] 1.4 Settle one vocabulary of methods across both changes before either is built. The contract says `method: outbound` / `inbound`; `route-sends-by-operator` names routes `call` and `modem`, and the flash call is a third method the contract does not name at all. The messenger ladder, if it is built, adds more steps still. Two vocabularies on one door means a client branching on words that do not cover its own cases. **A resolution is on the table (proposed 12.09.2026 by the `M·мессенджеры` session, owner's to accept): the two vocabularies are two axes, not one flat list.** `outbound` / `inbound` is a DIRECTION — and it is already at the client, so it does not move. A route is a separate field: `app_bot`, `tg_user`, `max_user`, `modem`, `flash_call`, `tg_gateway`, `inbound`, where `inbound` is the only route of its direction. Flattened into one list, `inbound` and `tg_user` sit side by side as if they were the same kind of thing, and they are not. Two axes also mean a new step extends the contract instead of breaking what was sent. ⚠️ One name is still contested: this ladder calls the vendor call `flash_call`, `route-sends-by-operator` calls it `call` — one side gives it up, and that is exactly what this task exists to decide
- [ ] 1.5 Resolve the endpoint paths, which are not the same on the two sides: the contract at the developer says `POST /verify`, `POST /verify/{id}/check`, `GET /verify/{id}`; `route-sends-by-operator` normalises `POST /verifications`, `POST /verifications/{id}/check`, `GET /verifications/{id}`. Do not change either side unilaterally — this is the owner's decision and the owner's letter to the developer. This change's own spec names no paths, deliberately, and SHALL keep naming none

## 2. Design, with the critic layer run

- [ ] 2.1 Decide where a verification lives: its own table, or a status on an existing one. It is not a message and should probably not be a row in `messages`
- [ ] 2.2 Decide how the operator rule is shared with `route-sends-by-operator` — both changes ask "can this operator be reached", and two answers would drift apart. The neighbouring change has since answered its half normatively: the rule is "a typed setting of its own, validated when it is saved", explicitly NOT the existing dispatch-route setting, which demands a `webhook_url` per entry and would reject it; an unparseable rule raises an alert and is never read as empty. ⚠️ **The drift is already visible and is about the model, not the storage:** that rule maps an operator to a named route (`call`, `modem`), while this change's spec asks whether an operator is "configured as undeliverable" — a boolean. One of the two phrasings has to go, and a boolean cannot express three routes
- [ ] 2.3 Run `system-architect` and `gap-finder`. Not yet run

## 3. Implement

- [ ] 3.1 Test: an inbound message with the right code from the right number confirms
- [ ] 3.2 Test (negative): the right code from a different number confirms nothing
- [ ] 3.3 Test (negative): the wrong code from the right number leaves the verification pending
- [ ] 3.4 Test: replaying the same inbound message confirms once, not twice
- [ ] 3.5 Test: the correct code arriving after expiry does not revive the verification
- [ ] 3.6 Test: two verifications open at once for one number do not share a code
- [ ] 3.7 Test: an inbound message matching nothing is still stored and still visible in the admin console
- [ ] 3.8 Check the SIM inbox under sustained verification load — inbound lands on the SIM and is read-then-deleted, and the SIM holds only a few dozen. Today's inbound is occasional; this is not
- [ ] 3.9 Reject a verification request that supplies its own code
- [ ] 3.10 Implement the endpoints and the matcher
- [ ] 3.11 Document the fallback in `docs/`: what the subscriber sees, what the operator sees when it goes wrong

## 4. Verify against the real thing

- [ ] 4.1 Run one verification end to end against a real МегаФон number — the outbound path to that operator is refusing everything, so this is the only proof the fallback works
- [ ] 4.2 Confirm the parking application saw the confirmation by the mechanism agreed in 1.1
- [ ] 4.3 Confirm an unrelated inbound message during the same window was not swallowed
