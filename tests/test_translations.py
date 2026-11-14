"""Custom integrations get no build step: HA never expands [%key:...%] references in their translation files."""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent / "custom_components" / "vafabmiljo"
FILES = [ROOT / "strings.json", *sorted((ROOT / "translations").glob("*.json"))]


def _strings(node):
    if isinstance(node, dict):
        for v in node.values():
            yield from _strings(v)
    elif isinstance(node, str):
        yield node


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_no_unresolved_key_references(path):
    bad = [s for s in _strings(json.loads(path.read_text(encoding="utf-8"))) if "[%key:" in s]
    assert not bad, f"{path.name} has references HA will show verbatim: {bad}"
