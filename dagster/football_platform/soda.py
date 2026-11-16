"""The verdict of a Soda result file (soda/run_checks.py writes data/soda/<layer>.json). Pure."""


def failed_checks(summary: dict, table: str | None = None) -> list[str]:
    """Names of the checks that failed or could not run, for one table or all of them."""
    return [c["name"] for c in summary["checks"]
            if c["outcome"] not in ("pass", "warn") and (table is None or c["table"] == table)]


def passed(summary: dict, table: str | None = None) -> bool:
    """True when no check failed. A check that could not run (Soda error) fails the whole layer: an error has no table
    we could trust."""
    return summary["errors"] == 0 and not failed_checks(summary, table)
