#!/usr/bin/env python3
"""Fail if a public document states a number that CLAIMS.md does not account for.

Every percentage and every decimal in README.md must appear in CLAIMS.md,
where it is tied either to a source (DOI plus location in the paper) or to
the test that proves it. The point is not tidiness. It is that a reader who
doubts any number in the README can find, in one file, exactly where it came
from — and that a number cannot be added to the README without someone having
to say where it came from.

There is deliberately no allowlist here. Structural numbers (version strings,
Python versions, DOI fragments) are justified in CLAIMS.md alongside the
substantive ones, so that all the justification lives in one auditable place
rather than half of it in this script.

Usage:
    python scripts/claims_lint.py            # lint
    python scripts/claims_lint.py --list     # print every token found
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLAIMS = ROOT / "CLAIMS.md"

#: Documents whose numbers must be accounted for.
LINTED = ("README.md",)

#: A percentage, or any number written with a decimal point. Deliberately
#: narrow: this is the shape a quantitative claim takes.
TOKEN = re.compile(r"\d+(?:\.\d+)?%|\d+\.\d+")

#: Attributions this project got wrong once and must not get wrong again.
#: The alerting randomised trial at doi:10.1080/08989621.2022.2082290 is by
#: Avenell, Bolland, Gamble and Grey. An earlier version of the README
#: credited it to a different author entirely. Assembled at runtime so this
#: file does not match its own check.
FORBIDDEN = {
    "Schnei" + "der": (
        "the alerting randomised trial is Avenell A, Bolland MJ, Gamble GD, "
        "Grey A, Account Res, doi:10.1080/08989621.2022.2082290"
    ),
}

#: Files exempt from the attribution check. CLAIMS.md is exempt because it
#: records the correction on purpose: deleting the history of a mistake is
#: not the same as fixing it.
FORBIDDEN_EXEMPT = {"CLAIMS.md", "scripts/claims_lint.py"}


def tokens(text: str) -> list[str]:
    """Every percentage and decimal in `text`, in order of appearance."""
    return TOKEN.findall(text)


def check_attributions() -> list[str]:
    """Find any resurrected misattribution in tracked project text."""
    problems: list[str] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or ".git/" in str(path):
            continue
        if path.suffix not in {".md", ".py", ".json", ".yml", ".toml"}:
            continue
        relative = path.relative_to(ROOT).as_posix()
        if relative in FORBIDDEN_EXEMPT:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for name, correction in FORBIDDEN.items():
            if name.lower() in text.lower():
                problems.append(f"{relative}: {name!r} appears; {correction}")
    return problems


def main(argv: list[str]) -> int:
    if not CLAIMS.exists():
        print(f"claims-lint: {CLAIMS.name} is missing", file=sys.stderr)
        return 1
    claims = CLAIMS.read_text(encoding="utf-8")

    found: dict[str, list[str]] = {}
    for name in LINTED:
        path = ROOT / name
        if not path.exists():
            print(f"claims-lint: {name} is missing", file=sys.stderr)
            return 1
        for token in tokens(path.read_text(encoding="utf-8")):
            found.setdefault(token, []).append(name)

    if "--list" in argv:
        for token in sorted(found, key=lambda s: (len(s), s)):
            mark = "ok " if token in claims else "MISSING"
            print(f"{mark} {token}")
        return 0

    missing = sorted(
        (token for token in found if token not in claims),
        key=lambda s: (len(s), s),
    )
    if missing:
        print(
            "claims-lint: these numbers appear in a public document but have "
            f"no entry in {CLAIMS.name}:",
            file=sys.stderr,
        )
        for token in missing:
            where = ", ".join(sorted(set(found[token])))
            print(f"  {token}   (in {where})", file=sys.stderr)
        print(
            f"\nAdd each one to {CLAIMS.name} with its source (DOI plus "
            "location in the paper) or the test that proves it, then re-run.",
            file=sys.stderr,
        )
        return 1

    attribution_problems = check_attributions()
    if attribution_problems:
        print("claims-lint: a corrected misattribution has come back:", file=sys.stderr)
        for problem in attribution_problems:
            print(f"  {problem}", file=sys.stderr)
        return 1

    print(
        f"claims-lint: {len(found)} distinct numbers, all accounted for in "
        f"{CLAIMS.name}; no misattributions"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
