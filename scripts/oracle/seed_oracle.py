"""Seed Oracle equivalent of seed.py.

Idempotent: creates `items` and `run_log` tables if they don't exist and
inserts up to `--rows` items.

Connection: uses python-oracledb in **thin mode** (no Instant Client needed).
Reads ORA_USER, ORA_PASSWORD and ORA_DSN from the environment.
ORA_DSN can be either:
   - EZConnect:    "host:1521/service_name"
   - tnsnames key: "PROD_DB"    (then set TNS_ADMIN to the wallet dir)
   - Easy Connect+: "host:port/service?wallet_location=/path"

For Autonomous DB with mTLS wallet:
    export TNS_ADMIN=/opt/wallet
    export ORA_DSN=mydb_high
"""
from __future__ import annotations
import argparse
import os

import oracledb


DDL_ITEMS = """
BEGIN
    EXECUTE IMMEDIATE q'[
        CREATE TABLE items (
            id          NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            sku         VARCHAR2(64)  NOT NULL,
            payload     VARCHAR2(4000) NOT NULL,
            created_at  TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL
        )
    ]';
EXCEPTION WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;  -- ORA-00955: name already used
END;
"""

DDL_RUN_LOG = """
BEGIN
    EXECUTE IMMEDIATE q'[
        CREATE TABLE run_log (
            run_id       VARCHAR2(64) PRIMARY KEY,
            workload     VARCHAR2(32) NOT NULL,
            started_at   TIMESTAMP WITH TIME ZONE NOT NULL,
            ended_at     TIMESTAMP WITH TIME ZONE,
            rows_count   NUMBER,
            duration_ms  NUMBER,
            notes        VARCHAR2(4000)
        )
    ]';
EXCEPTION WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;
END;
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=int(os.getenv("SEED_ROWS", "5000")))
    parser.add_argument("--batch", type=int, default=1000, help="executemany batch size")
    args = parser.parse_args()

    user = os.environ["ORA_USER"]
    password = os.environ["ORA_PASSWORD"]
    dsn = os.environ["ORA_DSN"]

    with oracledb.connect(user=user, password=password, dsn=dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(DDL_ITEMS)
            cur.execute(DDL_RUN_LOG)
            conn.commit()

            cur.execute("SELECT count(*) FROM items")
            existing = cur.fetchone()[0]
            if existing >= args.rows:
                print(f"items already has {existing} rows >= {args.rows}; nothing to do")
                return

            to_insert = args.rows - existing
            print(f"inserting {to_insert} rows...")

            sql = "INSERT INTO items (sku, payload) VALUES (:1, :2)"
            payload = "x" * 256
            buf: list[tuple[str, str]] = []
            for i in range(to_insert):
                buf.append((f"SKU-{existing + i:08d}", payload))
                if len(buf) >= args.batch:
                    cur.executemany(sql, buf)
                    buf.clear()
            if buf:
                cur.executemany(sql, buf)
            conn.commit()

            cur.execute("SELECT count(*) FROM items")
            print(f"done. items count={cur.fetchone()[0]}")


if __name__ == "__main__":
    main()
