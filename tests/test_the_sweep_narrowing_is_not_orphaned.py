"""The narrowing of the open-verification sweep lives in a *neighbour's* delta, and this
guards it against being lost there.

Задача 7.2. The code shipped with `route-sends-by-operator`; the requirement it narrows —
"A verification whose route stops working ends with a named reason" — is an ADDED
requirement of the sibling change `verify-by-inbound-contact`, which is where it was
authored and the only place it exists. It is not in the live spec and will not be until
that sibling archives.

That is a gap with a silent failure mode, and `openspec validate` is blind to all of it: it
does not read the prose of a requirement, does not notice a renamed heading, and says
nothing about a `MODIFIED` block for a requirement the live spec does not have. So a rename
or a rewrite of that requirement in the sibling — or an archiving that carries the old
generic wording — would leave production narrower than every written norm, with nothing
red anywhere.

**This guard is written to survive the archiving rather than to fire on it.** It looks for
the requirement in the live spec *and* in the open changes, and asserts the narrowing
travels with it wherever it currently lives. The moment `verify-by-inbound-contact`
archives, the same assertions apply to the live spec — which is the moment that matters,
because that is when the live spec starts being read as the truth.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / "openspec" / "specs"
CHANGES = ROOT / "openspec" / "changes"

HEADING = ("### Requirement: A verification whose route stops working ends with a named "
           "reason, and a call that arrived during an outage is gone")

# What the narrowing *is*, as the smallest phrases that cannot survive the old reading.
# Deliberately not a whole paragraph: a guard keyed on wording fails on every edit and gets
# fixed by being deleted.
NARROWING = (
    "SHALL NOT be re-proved",          # the norm itself
    "placement.PLACED_HERE",           # the boundary, named rather than listed
    "`call_in` and\n`sms_in`",         # who it still applies to
)


def _requirement_blocks() -> dict[Path, str]:
    """Every copy of that requirement outside the archive, by the file holding it.

    `changes/archive/` is excluded on purpose: an archived change keeps its delta for ever,
    so counting it would make this guard pass on a stale copy after the live spec had moved
    on.
    """
    found = {}
    candidates = list(LIVE.rglob("*.md"))
    candidates += [p for p in CHANGES.rglob("specs/**/*.md")
                   if "archive" not in p.relative_to(CHANGES).parts]
    for path in candidates:
        text = path.read_text(encoding="utf-8")
        if HEADING not in text:
            continue
        start = text.index(HEADING)
        # To the next requirement heading, or to the end of the file.
        nxt = re.search(r"^### Requirement: ", text[start + len(HEADING):], re.M)
        end = start + len(HEADING) + (nxt.start() if nxt else len(text))
        found[path] = text[start:end]
    return found


def test_the_narrowed_requirement_exists_exactly_once_and_is_findable():
    """A rename or a removal in the sibling is what this catches — the failure that leaves
    the code narrower than anything written down, with `openspec validate` green."""
    blocks = _requirement_blocks()
    assert blocks, (
        f"no live spec and no open change carries the requirement this sweep implements.\n"
        f"Looked for the heading, verbatim:\n  {HEADING}\n"
        f"If it was renamed, this guard and `openspec/changes/route-sends-by-operator/"
        f"tasks.md` task 7.2 have to follow it. If it was dropped, then "
        f"`_end_verifications_whose_route_died` is implementing a norm nobody holds.")
    assert len(blocks) == 1, (
        "two open deltas carry the same requirement; whichever archives second wins, "
        f"silently: {sorted(str(p.relative_to(ROOT)) for p in blocks)}")


@pytest.mark.parametrize("phrase", NARROWING)
def test_the_narrowing_travelled_with_it(phrase):
    """The owner's decision of 23.09.2026, asserted where it is written rather than where
    it was written."""
    blocks = _requirement_blocks()
    if not blocks:
        pytest.skip("covered by the guard above; nothing to read the narrowing out of")
    path, block = next(iter(blocks.items()))
    assert phrase in block, (
        f"{path.relative_to(ROOT)} holds that requirement without the 23.09.2026 "
        f"narrowing: {phrase!r} is gone. Read whole, the requirement is back to ending "
        f"*any* verification whose rung stops proving itself — which on a placed rung "
        f"means ending a call that has already been placed and billed.")


def test_the_code_reads_the_boundary_the_requirement_names():
    """The two halves, joined. The bite script proves the filter has teeth; this proves it
    is the *named* boundary and not a second list that happens to agree today."""
    sweep = (ROOT / "app" / "modem" / "manager.py").read_text(encoding="utf-8")
    body = sweep[sweep.index("async def _end_verifications_whose_route_died"):]
    body = body[:body.index("\n    def _verification_registry")]
    assert "placement.places_here" in body, (
        "the sweep no longer asks `placement` which rungs this gateway places, so the "
        "requirement's boundary and the code's have stopped being the same thing")
