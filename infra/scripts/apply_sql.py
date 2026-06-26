#!/usr/bin/env python3
"""Apply one or more arbitrary .sql files to Snowflake as the bootstrap ADMIN.

Reuses ``snowflake_bootstrap.config()`` + ``connect_admin()`` — the SAME key-pair /
PAT auth and the SAME env wiring as ``make snowflake-setup`` — so ad-hoc SQL (e.g.
``snowflake/rls.sql``, ``snowflake/test_user.sql``) runs headlessly with the same
credentials, without touching ``setup.sql`` (which would ``CREATE OR REPLACE TABLE``
and drop attached policies).

Usage:
    python scripts/apply_sql.py snowflake/rls.sql snowflake/test_user.sql

Env: same as snowflake_bootstrap.py (SNOWFLAKE_ACCOUNT / HOST / ADMIN_USER /
ADMIN_AUTH + the key/token), loaded from bedrock-demo/.env by the Makefile.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from snowflake_bootstrap import config, connect_admin


def _statements(sql: str):
    """Yield non-empty SQL statements.

    Strips ``/* */`` block + ``--`` line comments FIRST, then splits on ``;`` — so a
    ``;`` that appears *inside a comment* (the RESET block, an entitlement note) can't
    split a statement. Safe for our controlled DDL: no ``;`` or ``--`` inside string
    literals (string literals like ``'*'`` are left untouched).
    """
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.S)
    sql = re.sub(r"--[^\n]*", "", sql)
    for segment in sql.split(";"):
        stmt = segment.strip()
        if stmt:
            yield stmt


def apply_file(con, path: Path) -> None:
    print(f"--- applying {path} ---")
    cur = con.cursor()
    n = 0
    try:
        for stmt in _statements(path.read_text()):
            n += 1
            cur.execute(stmt)
            print(f"  [{n}] ok: {stmt.splitlines()[0][:72]}")
    finally:
        cur.close()
    print(f"--- done {path} ({n} statements) ---")


def main(argv: list[str]) -> int:
    files = [Path(a) for a in argv[1:]]
    if not files:
        print(__doc__)
        return 2
    for f in files:
        if not f.exists():
            sys.exit(f"error: no such SQL file: {f}")

    c = config()
    if not c["account"] or not c["admin_user"]:
        sys.exit("error: SNOWFLAKE_ACCOUNT and SNOWFLAKE_ADMIN_USER must be set (see ../.env)")

    con = connect_admin(c)
    try:
        for f in files:
            apply_file(con, f)
    finally:
        con.close()
    print("all SQL applied ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
