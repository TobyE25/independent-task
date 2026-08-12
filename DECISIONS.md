# Decision log

Every non-obvious choice in this pipeline, the alternatives it beat, and what would
change my mind. Recorded as I went rather than reconstructed afterwards.

The format is deliberate: a decision without a rejected alternative isn't a decision,
it's a default. And "what would change my mind" is the honest test of whether I
understood the trade-off or just picked something.

---

## D1 — ELT with an immutable raw landing zone, not ETL

**Decision.** Land both sources byte-for-byte first, then transform in the warehouse.
`API/CSV → bronze (immutable) → silver (Parquet) → gold (BigQuery mart)`.

**Alternatives.** Transform in flight and load only the finished table (classic ETL);
or skip the lake and load CSVs straight into BigQuery.

**Why.** Two concrete reasons, both specific to this brief. First, the sports API is
rate-limited — if a transform bug means reprocessing three months of history, replaying
files from the lake costs nothing, whereas re-hitting the API may be impossible inside
the quota. Second, auditability: when the Analytics team asks why a forecast moved, the
raw file that produced the number still exists.

**What would change my mind.** If the raw data carried PII we had no lawful basis to
retain even briefly, "land everything first" becomes a liability rather than an asset.
That's precisely why raw here has a 30-day lifecycle rule (see D6) rather than living
forever.

---

## D2 — TheSportsDB as a concrete stand-in for the unnamed "Sports Events API"

**Decision.** Build against TheSportsDB's free v1 API, with real requests to a real
endpoint.

**Alternatives.** Invent a fictional API and mock it entirely; or use a paid provider
(API-Football, Sportradar) behind a trial key.

**Why.** The brief names two properties — restrictive rate limiting and pagination —
that only mean something against a real server. A fully mocked API would let me *assert*
that I handle 429s without ever having handled one. TheSportsDB's free tier rate-limits
for real (~30 req/min), and the fan-out across leagues × date windows makes it bite.

**Honest limit — stated rather than buried.** TheSportsDB's *free v1 endpoints are not
paginated*, and its free key also **truncates result sets** (a full-season query returns 5
events, not 380). So the paginator handles the two styles that actually occur — page number
and offset — and is covered by unit tests against fake fetchers only. It is **not** exercised
against a live paginated endpoint, and cursor paging is deliberately not implemented because
no source here uses it; building it would be speculation. I would rather say that plainly than
imply coverage I don't have.

The sports side was never the volume problem either: events are thousands of rows a year. The
constraint there is the request quota, which is handled.

**What would change my mind.** For production, licensing and an SLA matter more than
being free. TheSportsDB's free tier is fine for an assessment and wrong for a retailer's
stock forecasting; I'd expect a commercial feed with a support contract.

---

## D3 — Parquet as the columnar format

**Decision.** Snappy-compressed Parquet in the lake, partitioned by date.

**Alternatives.** Avro, ORC, or just leaving it as CSV.

**Why.** The brief asks for a format "well suited to columnar-based storage", and the
access pattern decides it: downstream reads are analytical column scans over date ranges
(`SUM(pizza_units) BY store, date`), not row-level writes or streaming appends. That is
Parquet's case exactly — Avro is row-oriented and suits write-heavy streaming; ORC is
comparable to Parquet but with a Hive-centric ecosystem, whereas BigQuery, BigLake and
Iceberg all treat Parquet as first-class. Snappy over gzip because these files are read
far more often than written, and snappy trades a little size for much cheaper decode.

**What would change my mind.** Nothing about this workload. If we moved to streaming
ingestion with per-record appends, Avro at the edge feeding a Parquet compaction step
would be the shape.

---

## D4 — GCS is the lakehouse; BigQuery is the engine; only the serving mart is native

**Decision.** Bronze and silver live as Parquet on GCS, queried via **BigLake external
tables**. The final `mart_pizza_demand_daily` is a **native BigQuery table**.

**Alternatives.** Load everything into native BigQuery (a plain warehouse, not a
lakehouse); or keep everything external including the mart.

**Why.** This split is the actual meaning of "lakehouse" here: bulk data isn't copied
into the warehouse, so we pay GCS prices for storage and keep one copy with open-format
portability. But the serving table is small (tens of MB) and hit repeatedly by a
dashboard, where native storage gives better performance, clustering, and BI Engine
eligibility. Making everything external would trade real query performance on the hot
path for savings measured in pennies.

**What would change my mind.** If the mart grew to hundreds of GB, or if another engine
(Spark, Trino) needed to read it directly, I'd move it back to open Parquet/Iceberg.

---

## D5 — Pseudonymise with keyed HMAC-SHA256, not a plain hash

**Decision.** `customer_id` and `loyalty_id` → HMAC-SHA256 with a key held in Secret
Manager, key version recorded on every row.

**Alternatives.** Plain `SHA256(value)`; reversible encryption; a third-party
tokenisation service; or dropping the identifiers entirely.

**Why.** Plain hashing of a low-entropy identifier is not pseudonymisation in any
meaningful sense — an email address or a loyalty number has a small enough keyspace that
anyone holding the hash can brute-force or rainbow-table it. The HMAC key is the thing
that makes the mapping infeasible to invert without access to Secret Manager. It stays
*deterministic*, so repeat-purchase and basket analysis still work, which plain dropping
would prevent. Reversible encryption would keep the data personal data — the opposite of
what we want.

**What would change my mind.** If a lawful requirement to re-identify appeared (fraud
investigation, say), HMAC alone can't do it and I'd need a separately-governed crosswalk
table with its own access controls and audit trail.

---

## D6 — Minimise at the boundary, and let the grain finish the job

**Decision.** A declarative field policy marks each source column
`DROP` / `HASH` / `GENERALISE` / `KEEP`, applied at the *first* processing step. Email,
card last-4 and full postcode are dropped there. Raw landing carries a 30-day lifecycle
deletion rule.

**Alternatives.** Carry everything through and restrict access with IAM and column-level
security at the warehouse; or scrub only at the final mart.

**Why.** Access control is a promise; not holding the data is a guarantee. Anything that
never reaches silver cannot leak from silver, cannot appear in a stray query result, and
cannot show up in a support ticket. The policy is *declarative* so the answer to "what
do you do with personal data?" is a table someone can read and audit, not logic spread
across three functions.

**The point that matters most:** because the mart's grain is store × day (D7), the
combined warehouse table contains **no personal data at all**. Aggregation is the
strongest privacy control available and it happens to be exactly what the modelling task
needs — data minimisation by design (GDPR Art. 5(1)(c)) rather than as a bolt-on. The
30-day raw expiry covers storage limitation (Art. 5(1)(e)), and it means an erasure
request touches raw only.

**What would change my mind.** If the DS team needed customer-level features (churn,
personalisation), the mart would need a pseudonymised customer grain, and then
column-level policy tags and authorised views would be doing real work rather than
belt-and-braces.

---

## D7 — The combined table's grain is store × day

**Decision.** One row per `(store_id, date)`, denormalised and ML-ready, with a star
schema behind it.

**Alternatives.** Transaction-level (leave aggregation to the DS team); or hourly.

**Why.** Grain should match the decision being made, and the decision here is "how many
pizzas does this store need tomorrow" — a daily, per-store stocking call. Transaction
grain would push a heavy, repeated aggregation onto every consumer and would drag PII
into the warehouse for no modelling benefit. I provide the star schema too, so anyone
needing more depth isn't blocked by my choice.

**Honest limit.** Kickoff time plausibly matters *within* a day — demand for an 8pm
kickoff concentrates in the late afternoon. Day grain cannot see that. I keep
`earliest_kickoff_hour` as a feature so the signal isn't lost entirely, and name hourly
grain as a real extension rather than pretending the question doesn't exist.

**What would change my mind.** If the dashboard's purpose shifted from stock ordering to
intraday staffing or replenishment, hourly becomes correct.

---

## D8 — Event-to-store relevance lives in a dbt seed, not in SQL

**Decision.** A seed file (`seed_event_relevance_rules.csv`: competition, team, scope
`national|local`, radius_km, weight) drives which events are relevant to which stores.

**Alternatives.** Hardcode the rules in the mart SQL; join purely on venue geography;
or learn the weights from data.

**Why.** This is the least certain part of the whole design and the part with the most
influence on the forecast. A World Cup England match affects every UK store via
broadcast; a mid-table fixture affects the catchment around its venue. That mapping is a
*business judgement*, so the design should make it explicit, reviewable and tunable by
an analyst without a code change or a deployment — rather than burying an assumption
inside a `CASE` statement. Containing uncertainty in a reviewable artefact is the point.

**What would change my mind.** Once there's enough history, the weights should be
*learned* rather than asserted — but that's the DS team's model, and it needs this
pipeline to exist first. The seed is the honest v1.

---

## D9 — Cloud Run Jobs + Workflows + Scheduler as the orchestrator, not Composer

**Decision.** The pipeline runs as Cloud Run Jobs, sequenced by **Cloud Workflows** and triggered by
**Cloud Scheduler** at 08:15 Europe/London (`deploy/workflow.yaml`). The equivalent **Airflow DAG** is given as
pseudocode in DESIGN.md §2 for the environment where Composer already exists.

**Alternatives.** Cloud Composer as the primary (the obvious reading of "i.e. Apache Airflow"); a
plain cron job on a VM; Cloud Scheduler hitting a single Cloud Run service.

**Why.** Two reasons, and the first is that the brief permits it. R1 asks for an orchestration-based
environment *"in the form of a DAG **or collection of functions/tasks run in sequential order**"* —
Workflows sequencing discrete jobs is precisely that second form. So this is the option the brief
offers, not a way around it.

The second reason is cost, which the brief explicitly asks me to consider and underlines with
"Sprouts runs a tight ship":

| Orchestrator, one daily pipeline | Monthly |
|---|---|
| Cloud Composer 2, smallest environment | **~£250–350** |
| Workflows + Cloud Run Jobs + Scheduler | **~£1–5** |

For a single daily DAG, Composer would be roughly **90% of this pipeline's entire running cost** —
it charges for a always-on GKE cluster, Airflow scheduler, web server and database, to run one job a
day that takes minutes. That is a poor trade at this scale and a defensible one at a larger one.

**What Workflows still gives us**, so this is not "cron with extra steps": per-step retries with
exponential backoff, a visible execution graph and run history, parallel branches (the two ingestion
paths are independent and run concurrently), structured error handling, and a scheduled trigger with
a logical date that can be overridden for backfills.

**What Composer would give us that this does not:** backfill and catchup as first-class operations,
a richer sensor ecosystem, task-level UI for reruns, cross-DAG dependencies, and a scheduler the rest
of the data team probably already knows. Every one of those becomes worth £300/month once there are
*many* pipelines — none of them is worth it for one.

**Parallelism without a scheduler.** Airflow's dynamic task mapping is the usual answer to "one task
per file". Cloud Run Jobs give the same thing natively: a job launched with `--tasks 8` runs eight
containers, each receiving `CLOUD_RUN_TASK_INDEX`, and `cli.ingest_sales` shards deterministically by
index. No coordination, no queue, no two containers claiming the same export.

**Honest note on the alternative.** I first wrote the DAG as working code, then removed it. Installing
`apache-airflow` alongside this project pins `typing-extensions` back far enough to break pydantic,
and with it both pytest and dbt-core — so the DAG could not be verified without breaking the thing it
was meant to complement. It is now pseudocode (which the brief explicitly accepts), and the incident is
itself a small argument for the Cloud Run design, where each step is an isolated container with its own
dependency closure.

**What would change my mind.** An existing Composer instance — then the marginal cost is near zero and
Airflow is simply correct. Also: once this is the fifth pipeline rather than the first, or once anyone
needs routine backfills, the platform fee starts paying for itself. **The crossover is roughly "more
than a handful of pipelines, or a team that needs self-service reruns."**

---

## D10 — Shard the exports across parallel workers

**Decision.** The sales load is sharded by index: N workers, each taking every Nth export. On Cloud
Run Jobs that is `--tasks N` plus `CLOUD_RUN_TASK_INDEX` (implemented in `cli.ingest_sales`); the
Airflow equivalent would be dynamic task mapping (`.expand()`).

**Alternatives.** One process looping over all files; a single BigQuery load job with a wildcard URI;
a work queue that containers claim from.

**Why.** The file count is unknown at authoring time and grows with the business — **measured: 31
files/day today, 304 at the 1M-transaction forecast**. Sharding by index handles that with no code
change, gives per-shard retries so one corrupt export does not cost the other 303, and parallelises
for free. A work queue would also work and would balance load better, but it needs coordination and
at-least-once handling; index sharding is deterministic and needs neither.

A single wildcard BigQuery load job would genuinely be cheaper still — batch loads are free — but it
would skip the privacy layer entirely, which is not a trade available here.

**What would change my mind.** Thousands of files a day, where per-container startup begins to
dominate: then group files into batches per shard. Or wildly uneven file sizes, where index sharding
leaves one worker with all the big files and a queue would balance better.

---

## D11 — Completeness: cutoff, plus a manifest, plus reconciliation

**Decision.** A deferrable sensor waits to an 08:15 cutoff, every processed file is
recorded in an ingestion manifest, and a reconciliation task reprocesses the affected
date partition if files arrive late.

**Alternatives.** Wait for a fixed expected file count; require an upstream `_MANIFEST`
control file; or just run at 08:15 and hope.

**Why.** "Files typically arrive between 5–8 AM" is a soft guarantee, and the brief gives
no completeness signal. Waiting for a fixed count breaks the first day volumes change.
An upstream control file is genuinely the best answer — and the one I'd ask the
ecommerce team for — but I can't assume cooperation I haven't been promised. So:
fail-open then self-heal. The daily table is never blocked by one straggler, and a late
file triggers an idempotent partition rebuild rather than a silent undercount.

**What would change my mind.** If the ecommerce platform will emit a manifest with an
expected row/file count, use it — that turns a heuristic into a contract, and I'd raise
it in the first sprint.

---

## D12 — No Spark, no Dataflow

**Decision.** Plain Python with pyarrow streaming, plus BigQuery SQL. No distributed
compute anywhere.

**Alternatives.** Dataflow (Beam) for the CSV→Parquet step; Dataproc/Spark for
transforms.

**Why.** The numbers don't justify it, and I'd rather say so than reach for something
impressive. These are measured on this pipeline, not estimated:

| At the 1M transactions/day forecast peak | Measured |
|---|---|
| Line-item rows per day | 3,037,800 |
| Raw CSV per day | 533 MB |
| Parquet per day (snappy) | 92.7 MB — 5.8× compression |
| Full day ingested, single process, serial | **45.0 seconds** (67,575 rows/sec) |
| Peak memory across all 304 files | **93 MB, flat** |
| Parquet per year | ~34 GB |

One process ingests the entire forecast peak day in under a minute in 93MB of RAM.
Dataflow would add a per-job cost, a Beam dependency and an entire runtime to operate and
debug, in exchange for parallelism that would save forty seconds. Choosing the boring
option *is* the cost-consciousness the brief asks for.

Worth being precise about what my first estimate got wrong: I initially assumed ~120MB/day,
because I was implicitly treating a transaction as one row. A transaction is a *basket* of
several line items, so the real figure is roughly 4× higher. The conclusion doesn't change,
but the file count does — and that turned out to be the pressure that actually matters
(D10).

**What would change my mind.** A stated threshold, not a vibe: above roughly 50GB/day —
about 100× current volume — or if a single file stopped fitting comfortably in a Cloud Run
job's memory and time budget, Dataflow becomes the right tool. Sub-hour freshness
requirements would change the shape entirely.

---

## D13 — pyarrow streaming, no pandas

**Decision.** Read CSV in batches with `pyarrow.csv` and write with `ParquetWriter`.

**Alternatives.** pandas `read_csv(chunksize=...)`; or Polars.

**Why.** We need CSV in and Parquet out with bounded memory — pyarrow does exactly that
natively, and it's already a dependency because Parquet requires it. Adding pandas would
mean a second large dependency, a second type system to reconcile, and a materialised
DataFrame per chunk for no gain. Fewer dependencies is also fewer things to patch.

**What would change my mind.** If the transform needed real dataframe ergonomics, Polars
over pandas — lazy, Arrow-native, no index concept.

---

## D14 — The DAG file contains no business logic

**Decision.** All logic lives in the `pipeline/` package, exposed through `cli.py`. The orchestrator
calls in; nothing in the package calls back out. `pipeline/` has **no orchestrator dependency at
all**.

**Alternatives.** Write the logic directly into PythonOperator callables or Workflows steps, as most
tutorials do.

**Why.** This is the single most load-bearing structural choice for testability: the whole suite runs
in seconds with no scheduler and no metadata database, and the same code runs under Workflows, in a
Cloud Run Job, or invoked directly on a laptop — which is what makes D9's recommendation credible
rather than aspirational.

It also turned out to matter concretely. When I tried to verify an Airflow DAG, installing
`apache-airflow` pinned `typing-extensions` back far enough to break pydantic, and with it pytest and
dbt-core. A package that *imports* its orchestrator inherits that orchestrator's dependency conflicts;
this one doesn't, which is why removing the DAG cost nothing but the file.

**What would change my mind.** Nothing. This one I'd defend anywhere.

---

## D15 — Dual-target: the same code runs locally and on GCP

**Decision.** A `Storage` protocol (local filesystem / GCS) and a `Warehouse` protocol
(DuckDB / BigQuery), selected by one config value.

**Alternatives.** GCP-only, requiring a project and credentials to run anything.

**Why.** A reviewer can clone this and run it end to end with no cloud account and no
spend, which is worth a great deal for an assessment. It also keeps the cloud boundary
honest and visible in one place — the only genuinely cloud-specific concern is where
bytes go and which SQL dialect runs.

**Honest limit.** The GCP path is **written but not deployed.** DuckDB and BigQuery are not the same
engine, and SQL that passes locally can still fail on BigQuery — dbt's adapter absorbs most of that
difference, not all of it. So "one config change" is the design intent, not a demonstrated fact. The
GCS and BigLake code is reviewable; it has not been run against a live project.

---

## D16 — Keep the package small, and say what was left out

**Decision.** Nine modules, one concern each. Throttling, retries and paging live together in
`http_client.py` because they are only ever used together; the source registry lives with the
engine that reads it.

**Alternatives.** A module per concern (which is where this started — twelve of them), or one large
`pipeline.py`.

**Why.** The brief asks for modularity *and* for a pipeline that is cheap to maintain, and those
pull in opposite directions past a certain point. Twelve modules for two data sources reads as
structure for its own sake, and every extra file is another import to follow when debugging.
Nine is the point where each file still has an obvious single answer to "what is this for?".

Deliberately not built, and named here rather than left as gaps: cursor pagination (no source needs
it), streaming ingestion, incremental dbt models (the volumes don't justify the complexity yet — see
D12), a shipped Airflow DAG (D9), and an ML model, which is the Data Science team's job.

**What would change my mind.** A third and fourth data source would justify splitting the
registry back out, because at that point the registry becomes the thing people edit most.

---

## D17 — Fail closed, with quarantine

**Decision.** Pydantic validates every record at the ingestion boundary. Invalid records
are written aside with the reason attached; they are never silently dropped and never
loaded.

**Alternatives.** Drop bad rows and log a count; or fail the entire run on the first bad
record.

**Why.** Silent drops are how a forecast quietly becomes wrong — nobody notices 3% of
transactions vanishing. Failing the whole run on one malformed row is the opposite
failure: a single upstream typo takes out the daily table. Quarantine keeps both the good
data and the evidence, and the quarantine *rate* becomes a monitorable metric — a spike
means the upstream schema changed, surfaced as an alert rather than as corrupted marts
three weeks later.

**What would change my mind.** For financial reconciliation, where partial data is worse
than none, fail-the-run is correct. For demand forecasting it isn't.
