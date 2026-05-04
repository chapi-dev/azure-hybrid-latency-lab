"""Chatty workload — N+1 pattern over WAN.

For each of `--items` ids:
  - issue 1 SELECT
  - issue 1 INSERT into a working table

Each query is a separate round-trip. Total round-trips ~= 2 * items.

Telemetry sent to Azure Application Insights (set
APPLICATIONINSIGHTS_CONNECTION_STRING). Each run is wrapped in a single
operation_id so you can join app traces with PG logs by application_name.
"""
from __future__ import annotations
import os
import time
import uuid
import argparse
import logging
from datetime import datetime, timezone

import psycopg

from azure.monitor.opentelemetry import configure_azure_monitor
from opentelemetry import trace


WORKLOAD = "chatty"


def setup_telemetry(run_id: str) -> trace.Tracer:
    cs = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if cs:
        configure_azure_monitor(
            connection_string=cs,
            logger_name="latency-lab",
        )
    logging.basicConfig(
        level=logging.INFO,
        format=f"%(asctime)s [{WORKLOAD} {run_id}] %(message)s",
    )
    return trace.get_tracer("latency-lab")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--items", type=int, default=500, help="number of items to process")
    parser.add_argument("--run-id", default=str(uuid.uuid4()))
    args = parser.parse_args()

    run_id = args.run_id
    tracer = setup_telemetry(run_id)
    log = logging.getLogger("latency-lab")

    conninfo = os.environ["PG_CONNINFO"]
    app_name = f"chatty-{run_id}"
    started = datetime.now(timezone.utc)
    t0 = time.perf_counter()

    select_count = 0
    insert_count = 0

    with tracer.start_as_current_span(f"BatchRun-{WORKLOAD}-{run_id}") as root:
        root.set_attribute("workload", WORKLOAD)
        root.set_attribute("run_id", run_id)
        root.set_attribute("items", args.items)
        with psycopg.connect(conninfo, application_name=app_name) as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS work_chatty (
                        id BIGSERIAL PRIMARY KEY,
                        run_id TEXT NOT NULL,
                        item_id BIGINT NOT NULL,
                        sku TEXT NOT NULL,
                        ts TIMESTAMPTZ NOT NULL DEFAULT now()
                    );
                    """
                )

                cur.execute("SELECT id FROM items ORDER BY id LIMIT %s;", (args.items,))
                ids = [r[0] for r in cur.fetchall()]
                select_count += 1

                for item_id in ids:
                    with tracer.start_as_current_span("select_one") as s:
                        s.set_attribute("db.statement", "SELECT id, sku FROM items WHERE id=%s")
                        cur.execute("SELECT id, sku FROM items WHERE id = %s;", (item_id,))
                        row = cur.fetchone()
                    select_count += 1
                    with tracer.start_as_current_span("insert_one"):
                        cur.execute(
                            "INSERT INTO work_chatty (run_id, item_id, sku) VALUES (%s, %s, %s);",
                            (run_id, row[0], row[1]),
                        )
                    insert_count += 1

                duration_ms = int((time.perf_counter() - t0) * 1000)
                cur.execute(
                    """
                    INSERT INTO run_log (run_id, workload, started_at, ended_at, rows, duration_ms, notes)
                    VALUES (%s, %s, %s, now(), %s, %s, %s)
                    ON CONFLICT (run_id) DO UPDATE
                      SET ended_at = EXCLUDED.ended_at,
                          duration_ms = EXCLUDED.duration_ms,
                          notes = EXCLUDED.notes;
                    """,
                    (run_id, WORKLOAD, started, args.items, duration_ms,
                     f"selects={select_count} inserts={insert_count}"),
                )

        roundtrips = select_count + insert_count + 2  # +CREATE +INSERT run_log
        root.set_attribute("roundtrips", roundtrips)
        root.set_attribute("duration_ms", duration_ms)
        log.info(
            "DONE workload=%s run_id=%s items=%s roundtrips=%s duration_ms=%s",
            WORKLOAD, run_id, args.items, roundtrips, duration_ms,
        )

    print(f"RUN_ID={run_id} ROUNDTRIPS={roundtrips} DURATION_MS={duration_ms}")


if __name__ == "__main__":
    main()
