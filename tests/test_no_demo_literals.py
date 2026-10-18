"""Guard for engineering rule 1: demo records live only in seed/*.yaml.
Collects every ID, username, name and email from the seed files and fails if any appears
in a file under core/, apps/ or templates/ (whole-word, case-insensitive)."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SCANNED = ("core", "apps", "templates")
RECORD_KEYS = {"id", "username", "name", "customer", "email"}


def _collect(node, out: set[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in RECORD_KEYS and isinstance(value, str) and value.strip():
                out.add(value.strip())
            else:
                _collect(value, out)
    elif isinstance(node, list):
        for item in node:
            _collect(item, out)


def demo_literals() -> set[str]:
    found: set[str] = set()
    for path in sorted((ROOT / "seed").glob("*.yaml")):
        _collect(yaml.safe_load(path.read_text()), found)
    return found


def scanned_files() -> list[Path]:
    return [p for d in SCANNED for p in (ROOT / d).rglob("*") if p.is_file() and "__pycache__" not in p.parts]


def test_seed_files_provide_literals():
    literals = demo_literals()
    assert len(literals) >= 10  # the guard is only meaningful if it found the demo records


def test_no_demo_literals_in_code():
    patterns = {lit: re.compile(rf"(?<![\w@.-]){re.escape(lit)}(?![\w@-])", re.IGNORECASE) for lit in demo_literals()}
    offences = []
    for path in scanned_files():
        text = path.read_text(errors="ignore")
        for lit, pattern in patterns.items():
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                offences.append(f"{path.relative_to(ROOT)}:{line}: {lit!r}")
    assert not offences, "Demo records belong in seed/*.yaml only:\n" + "\n".join(offences)
