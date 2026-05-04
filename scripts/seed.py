"""Idempotent schema + data seed for the latency lab.

Creates `items` table with N rows (default 5000), each carrying a small payload.
Run once from any machine that has network access to the PG server.
"""
from __future__ import annotations
import os
import argparse
import psycopg
from psycopg import sql


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=int(os.getenv("SEED_ROWS", "5000")))
    args = parser.parse_args()

    conninfo = os.environ["PG_CONNINFO"]  # e.g. host=... dbname=... user=... password=... sslmode=require
    with psycopg.connect(conninfo, application_name="latency-lab-seed", autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS items (
                    id        BIGSERIAL PRIMARY KEY,
                    sku       TEXT       NOT NULL,
                    payload   TEXT       NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE TABLE IF NOT EXISTS run_log (
                    run_id     UUID       PRIMARY KEY,
                    workload   TEXT       NOT NULL,
                    started_at TIMESTAMPTZ NOT NULL,
                    ended_at   TIMESTAMPTZ,
                    rows       INT,
                    duration_ms BIGINT,
                    notes      TEXT
                );
                """
            )
            cur.execute("SELECT count(*) FROM items;")
            existing = cur.fetchone()[0]
            if existing >= args.rows:
                print(f"items already has {existing} rows >= {args.rows}; nothing to do")
                return
            to_insert = args.rows - existing
            print(f"inserting {to_insert} rows…")
            with cur.copy("COPY items (sku, payload) FROM STDIN") as cp:
                for i in range(to_insert):
                    sku = f"SKU-{existing + i:08d}"
                    payload = "x" * 256
                    cp.write_row((sku, payload))
            cur.execute("SELECT count(*) FROM items;")
            print(f"done. items count={cur.fetchone()[0]}")


if __name__ == "__main__":
    main()
