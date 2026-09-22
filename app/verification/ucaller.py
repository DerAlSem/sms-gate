"""uCaller's credential, and the one thing its reference settles about the wire.

The `flash_call` rung's adapter is task 4.17 and waits on samples (task 1.3). What does
not wait is how the vendor is authenticated, because that is answered by the reference
alone — read by layers on 22.09.2026 and captured verbatim in the change's
`captures/ucaller-reference-2026-09-22.md`.

The vendor accepts the same two values three interchangeable ways: `?key=&service_id=` on
a GET, both fields in a JSON body, or the header

    Authorization: Bearer <Секретный ключ вашего сервиса>.<Идентификатор сервиса>

so the bearer is a *derived* form of a pair, not a credential of its own. The two halves
live as two settings for a reason written where they are declared: a joined string whose
dot is missing or doubled looks configured on the settings page and arrives as the
vendor's `401` on the first paid call.

⚠️ **Nothing in production calls this yet.** The settings page reads the rows — that is
what an operator configures — but the vendor is not called by anything until 4.17 lands
the adapter, and until its probe is registered the `flash_call` rung is not offered at
all. Said out loud here rather than discovered later.
"""

from __future__ import annotations

from app.settings_store import store


def bearer(key: str | None, service_id: str | None) -> str | None:
    """The vendor's `Authorization: Bearer` value, or `None` if there is no credential.

    Written from the opposite side — nothing is a credential unless both halves say so —
    because the failure it guards is a half-configured estate offering the vendor a
    truncated bearer and reading the refusal as a wrong key.

    Both halves are stripped. A row holding a stray newline is what a paste leaves
    behind, and a bearer built from one is refused as authentication rather than reported
    as an unconfigured rung.
    """
    left = (key or "").strip()
    right = (service_id or "").strip()
    if not left or not right:
        return None
    return f"{left}.{right}"


def configured_bearer() -> str | None:
    """The bearer the estate is configured with, or `None`. What 4.17 will read."""
    return bearer(store.ucaller_key, store.ucaller_service_id)
