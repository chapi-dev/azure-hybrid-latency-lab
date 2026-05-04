# Architecture notes

## Why simulate "on-prem" inside Azure?

To run a controlled, repeatable lab of "chatty over WAN" without provisioning
real on-prem infrastructure or paying for ExpressRoute, this lab uses an
ordinary Azure VM that is reshaped to *behave* like an on-prem host:

1. **DNS / hostname**: the VM is renamed to `db-batch-server.corp.local`
   and reaches the DB through a `pg-prod.corp.local` alias added to
   `/etc/hosts` — so application code never sees `.postgres.database.azure.com`.
2. **Azure Arc**: the VM is onboarded to Azure Arc (`MSFT_ARC_TEST=true` is
   used since the host is technically still an Azure VM). This gives the
   "non-Azure machine" representation in Azure (Hybrid Compute resource).
3. **Latency injection**: `tc qdisc add dev eth0 root netem delay 80ms 5ms`
   adds realistic WAN latency on the on-prem VM's egress so every packet
   leaving it pays the WAN tax. We picked 80 ms (≈ the RTT between
   West Europe ↔ East US over Microsoft backbone) — adjust at deploy time.

## Why Virtual WAN?

ExpressRoute is the production answer; vWAN is the right *control plane*
for any hybrid network with multiple branches and is the closest analogue
that we can deploy quickly. Both VNets attach to the hub as
`hubVirtualNetworkConnections`, so traffic from "on-prem" to the spoke
flows through the vWAN hub — the same way a branch behind ExpressRoute
would route through it.

## Why PostgreSQL Flexible Server (and not Azure SQL)?

- Cheapest tier (`Burstable B1ms`) is a few cents per hour.
- VNet-injection (no public endpoint) — clean, real private link.
- `psycopg` provides easy `COPY` for the chunky path.

The same lab works against Azure SQL with minimal changes (swap driver,
use `BULK INSERT` or table-valued parameters for the chunky workload).

## What does "round-trip" mean here?

Every individual statement issued by the Python script is a separate
network request to the DB and is therefore a separate round-trip. The
batch run wraps everything in a single OpenTelemetry span tree, so:

- `requests.duration` = total wall clock of the batch
- `dependencies` = one row per query, each with its own `duration`
- `sum(dependencies.duration)` ≈ time spent in network + server
- `requests.duration - sum(dependencies.duration)` ≈ client/CPU time

The `chatty` script intentionally does not pipeline / batch — that is the
anti-pattern we are demonstrating. The `chunky` script collapses the same
logical work into 1 SELECT + 1 COPY, so the round-trip count drops by
roughly 1000× for 500 items.

## What you should see

With 80 ms injected egress latency and 500 items per run:

- **chatty**: ~1000 round-trips, total ~80 s (≈ items × RTT)
- **chunky**: ~4 round-trips, total ~1 s
- **chunky** is ~80× faster despite same DB, same network, same data.

Connection Monitor will show steady ~80 ms RTT throughout, confirming the
problem is not the network — it's the *number of times we cross it*.
