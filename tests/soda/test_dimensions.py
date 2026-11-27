"""soda/dimensions.yml gives every Soda check one data-quality dimension and a plain-English name (Data quality
page). Read from the check files, not from a run: a new check without a dimension fails here, before any run."""

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

SODA = Path(__file__).resolve().parents[2] / "soda"
DIMENSIONS = {"completeness", "uniqueness", "validity", "consistency", "accuracy"}


def checks_in_files() -> set[tuple[str, str]]:
    """(table, name) of every check, named as Soda reports it: its `name`, else the check itself."""
    out = set()
    for layer in ("silver", "gold"):
        doc = yaml.safe_load((SODA / "checks" / f"{layer}.yml").read_text(encoding="utf-8"))
        for block, items in doc.items():
            table = block.removeprefix("checks for ")
            for item in items:
                if isinstance(item, str):
                    out.add((table, item))
                else:
                    ((check, config),) = item.items()
                    out.add((table, (config or {}).get("name", check)))
    return out


def test_every_check_has_exactly_one_dimension_and_a_plain_name():
    mapping = yaml.safe_load((SODA / "dimensions.yml").read_text(encoding="utf-8"))
    mapped = {(table, name) for table, checks in mapping.items() for name in checks}
    files = checks_in_files()
    assert files - mapped == set(), "checks without a dimension"
    assert mapped - files == set(), "dimensions of checks that no longer exist"
    for table, checks in mapping.items():
        for name, entry in checks.items():
            assert entry["dimension"] in DIMENSIONS, (table, name)
            assert entry["plain"] and "_count(" not in entry["plain"], (table, name)
    assert len(files) == 215
