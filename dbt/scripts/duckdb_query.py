"""duckdb_query.py: run SQL on the Gold DuckDB file (read-only) and print the result.

    make gold-sql Q="select * from gold_shots limit 5"
    make gold-sql                       # no query: lists the Gold tables with their row counts

Runs in the `duckdb` service (same image as dbt), or locally: python dbt/scripts/duckdb_query.py "select 1".
The file is written by `make gold` (dbt build); it is opened read-only so it can never be damaged from here.
"""

import os
import sys
from pathlib import Path

import duckdb

DEFAULT_QUERY = """
select table_name, estimated_size as rows
from duckdb_tables()
where table_name like 'gold_%'
order by table_name
"""


def main() -> None:
    path = Path(os.getenv("GOLD_DUCKDB_PATH", "data/football.duckdb"))
    if not path.exists():
        sys.exit(f"{path} does not exist: run `make gold` first (dbt build writes it)")
    sql = " ".join(sys.argv[1:]).strip() or DEFAULT_QUERY
    con = duckdb.connect(str(path), read_only=True)
    result = con.sql(sql)
    if result is not None:
        result.show(max_rows=60, max_width=220)


if __name__ == "__main__":
    main()
