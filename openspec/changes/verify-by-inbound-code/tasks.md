The contract with the parking application is settled before anything is built: two teams
implement against it, and changing it later costs both.

## 1. Agree the contract

- [ ] 1.1 Hand the parking developer the integration contract and get the answer to the one question that shapes the build: webhook or polling. If that app cannot receive callbacks, the push half is not worth building first
- [ ] 1.2 Confirm the gateway's own number as the one subscribers text, and that it is safe to publish to end users
- [ ] 1.3 Agree the expiry with the parking developer. Long enough for a person to type an SMS in a car, short enough that a code is not left standing

## 2. Design, with the critic layer run

- [ ] 2.1 Decide where a verification lives: its own table, or a status on an existing one. It is not a message and should probably not be a row in `messages`
- [ ] 2.2 Decide how the operator rule is shared with `route-sends-by-operator` — both changes ask "can this operator be reached", and two answers would drift apart
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
