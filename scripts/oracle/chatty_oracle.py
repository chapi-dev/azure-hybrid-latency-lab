"""Chatty workload (Oracle) — N+1 pattern over WAN.

Same logic as scripts/chatty.py but talks to Oracle via python-oracledb (thin mode).
Each item = 1 SELECT + 1 INSERT in its own round-trip. With `tc netem 80ms`
on egress, this is the worst-case pattern.
"""
from __future__ import annotations
import argparse
import logging
import os
import time
import uuid
from datetime import datetime, timezone

import oracledb


WORKLOAD = "chatty"


def setup_telemetry(run_id: str) -> object:
    cs = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
    tracer = None
    if cs:
        # opentelemetry-instrumentation-dbapi works with oracledb.
        from azure.monitor.opentelemetry import configure_azure_monitor
        from opentelemetry import trace
        for noisy in ("azure", "azure.monitor", "urllib3", "opentelemetry.exporter"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
        configure_azure_monitor(connection_string=cs, logger_name="latency-lab")
        tracer = trace.get_tracer("latency-lab")
    logging.basicConfig(
        level=logging.INFO,
        format=f"%(asctime)s [{WORKLOAD} {run_id}] %(message)s",
    )
    return tracer


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--items", type=int, default=500)
    parser.add_argument("--run-id", default=str(uuid.uuid4()))
    args = parser.parse_args()

    run_id = args.run_id
    tracer = setup_telemetry(run_id)
    log = logging.getLogger("latency-lab")

    user = os.environ["ORA_USER"]
    password = os.environ["ORA_PASSWORD"]
    dsn = os.environ["ORA_DSN"]

    started = datetime.now(timezone.utc)
    t0 = time.perf_counter()
    select_count = 0
    insert_count = 0

    def run_body() -> tuple[int, int, int]:
        nonlocal select_count, insert_count
        with oracledb.connect(user=user, password=password, dsn=dsn) as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                # Idempotent CREATE TABLE for the working table.
                cur.execute(
                    """
                    BEGIN
                        EXECUTE IMMEDIATE q'[
                            CREATE TABLE work_chatty (
                                id        NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                                run_id    VARCHAR2(64) NOT NULL,
                                item_id   NUMBER       NOT NULL,
                                sku       VARCHAR2(64) NOT NULL,
                                ts        TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL
                            )
                        ]';
                    EXCEPTION WHEN OTHERS THEN
                        IF SQLCODE != -955 THEN RAISE; END IF;
                    END;
                    """
                )

                cur.execute(
                    "SELECT id FROM items ORDER BY id FETCH FIRST :1 ROWS ONLY",
                    (args.items,),
                )
                ids = [r[0] for r in cur.fetchall()]
                select_count += 1

                for item_id in ids:
                    cur.execute("SELECT id, sku FROM items WHERE id = :1", (item_id,))
                    row = cur.fetchone()
                    select_count += 1
                    cur.execute(
                        "INSERT INTO work_chatty (run_id, item_id, sku) VALUES (:1, :2, :3)",
                        (run_id, row[0], row[1]),
                    )
                    insert_count += 1

                duration_ms_local = int((time.perf_counter() - t0) * 1000)
                cur.execute(
                    """
                    MERGE INTO run_log r
                    USING (SELECT :1 AS run_id FROM dual) s ON (r.run_id = s.run_id)
                    WHEN MATCHED THEN UPDATE SET ended_at = SYSTIMESTAMP,
                                                 duration_ms = :2,
                                                 notes = :3
                    WHEN NOT MATCHED THEN INSERT (run_id, workload, started_at, ended_at,
                                                  rows_count, duration_ms, notes)
                                          VALUES (:1, :4, :5, SYSTIMESTAMP, :6, :2, :3)
                    """,
                    (
                        run_id,
                        duration_ms_local,
                        f"selects={select_count} inserts={insert_count}",
                        WORKLOAD,
                        started,
                        args.items,
                    ),
                )
                return select_count, insert_count, duration_ms_local

    if tracer is not None:
        with tracer.start_as_current_span(f"BatchRun-{WORKLOAD}-{run_id}") as root:
            root.set_attribute("workload", WORKLOAD)
            root.set_attribute("run_id", run_id)
            root.set_attribute("items", args.items)
            sc, ic, duration_ms = run_body()
            roundtrips = sc + ic + 2  # +CREATE +run_log MERGE
            root.set_attribute("roundtrips", roundtrips)
            root.set_attribute("duration_ms", duration_ms)
    else:
        sc, ic, duration_ms = run_body()
        roundtrips = sc + ic + 2

    log.info(
        "DONE workload=%s run_id=%s items=%s roundtrips=%s duration_ms=%s",
        WORKLOAD, run_id, args.items, roundtrips, duration_ms,
    )
    print(f"RUN_ID={run_id} ROUNDTRIPS={roundtrips} DURATION_MS={duration_ms}")


if __name__ == "__main__":
    main()
