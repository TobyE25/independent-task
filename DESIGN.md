# Pizza Perfect — pipeline design

End-to-end description of the pipeline: what it does, the architecture and why, what it costs, how it
scales, how personal data is handled, and what I deliberately left out.

Diagrams and UML are in [`docs/architecture.md`](docs/architecture.md). Every non-obvious choice, with
the alternative it beat, is in [`DECISIONS.md`](DECISIONS.md) — 17 of them, referenced as **D1**…**D17**
below. A requirement-by-requirement map is in
[`docs/requirements_traceability.md`](docs/requirements_traceability.md).

**On form and on the numbers.** `dbt/` and `deploy/` are real, runnable artefacts; `pipeline/` presents
implementation as pseudocode inside real modules, with the declarative parts (field policy, schemas,
source registry) literal. The brief permits this — *"python-based code, Sudo code, Diagrams, UML"* — and
it keeps the submission readable.

Every figure quoted below is a **measurement, not an estimate**: I built and ran the pipeline end to end
before reducing it to this form. So "45.0 seconds" and "93 MB peak" are numbers I observed, not numbers
I expect. Happy to walk through the working version.

---

## 1. What it does

Sprouts wants to forecast pizza demand per store around major sporting events. This pipeline
assembles the dataset that makes that possible:

```
Sports Events API ─┐
                   ├─► GCS lakehouse (Parquet) ─► BigQuery ─► mart_pizza_demand_daily
Daily sales CSVs ──┘
```

The deliverable is **`mart_pizza_demand_daily`**: one row per store per day, combining sales
measures with the sporting events relevant to that store, ready for the Data Science team to model
and the Analytics team to chart.

It runs daily at 08:15 Europe/London — after the 05:00–08:00 export window — as five Cloud Run Jobs
sequenced by Cloud Workflows.

---

## 2. Architecture, and why

### ELT with an immutable raw zone, not ETL (D1)

`API/CSV → bronze (immutable) → silver (Parquet) → gold (BigQuery)`.

Land raw first, transform later. Two concrete reasons, both specific to this brief. The sports API is
**rate-limited**, so if a transform bug means reprocessing three months of history, replaying files
from the lake costs nothing while re-hitting the API may be impossible inside the quota. And
auditability: when Analytics asks why a forecast moved, the exact bytes that produced the number
still exist.

### Lakehouse: GCS holds the data, BigQuery queries it (D4)

The brief asks for a lakehouse and a columnar format. What that means in practice here:

| Layer | Where | Format | Why |
|---|---|---|---|
| Bronze | GCS | JSONL + gzip | Immutable audit trail. Replayable. 30-day expiry. |
| Silver | GCS, Hive-partitioned | **Parquet + snappy** | Columnar, queried in place via BigLake |
| Gold | BigQuery, native | Native table | Small and hit constantly by a dashboard |

Only the serving mart is copied into the warehouse. Bulk data stays as Parquet on object storage —
one copy, open format, readable tomorrow by Spark or Trino without an export. Making *everything*
external would trade real query performance on the hot path for savings measured in pennies.

**Parquet over Avro or ORC** (D3) because the access pattern decides it: downstream reads are
analytical column scans over date ranges, not row-level writes. Avro is row-oriented and suits
write-heavy streaming; ORC is comparable but Hive-centric, while BigQuery, BigLake and Iceberg all
treat Parquet as first-class. Snappy over gzip because these files are read far more often than
written.

### Two ingestion paths, deliberately different

**Sports events.** A declarative source registry (`pipeline/sports.py`) — adding a feed is one entry,
not a new script (D2). The client throttles proactively with a token bucket, honours `Retry-After`
(capped at 60s, so a hostile header cannot hang a job), and backs off with **full jitter** rather than
plain exponential, because many shards retrying in lockstep is a herd.

**Sales exports.** The platform caps files at 10,000 rows, so a day arrives as many files — measured
**31 today, 304 at the 1M-transaction forecast**. Each is processed independently and idempotently.

### Orchestration: Cloud Run Jobs + Workflows + Scheduler (D9)

The brief asks for an orchestration environment *"in the form of a DAG **or collection of
functions/tasks run in sequential order**"*. This is the second form, chosen on cost:

| Orchestrator, one daily pipeline | Monthly |
|---|---|
| Cloud Composer 2, smallest environment | **~£250–350** |
| Workflows + Cloud Run Jobs + Scheduler | **~£1–5** |

For a single daily pipeline, Composer would be roughly **90% of total running cost** — an always-on
GKE cluster, scheduler, web server and database, to run one job a day that takes minutes. The brief
asks me to consider running costs and says Sprouts runs a tight ship; this is the answer.

Workflows still provides what this pipeline actually uses from an orchestrator: per-step retries with
backoff, a visible execution graph and history, parallel branches, structured error handling, and a
logical date overridable for backfills.

**The trade-off reverses the moment Composer already exists** — then the platform fee is paid,
marginal cost is near zero, and Airflow is the better tool. **Crossover: more than a handful of
pipelines, or a team needing self-service reruns.** The same five steps map onto a DAG directly,
because `pipeline/cli.py` is the interface either orchestrator calls:

```python
# Sketch, not shipped code — the equivalent Airflow DAG.
# Every task is a thin call into pipeline.cli, exactly as the Workflows definition is.

with DAG("pizza_perfect_daily", schedule="15 8 * * *",
         start_date=..., catchup=False, max_active_runs=1,
         default_args={"retries": 2, "retry_exponential_backoff": True}) as dag:

    sports = PythonOperator(task_id="ingest_sports",
                            python_callable=cli.ingest_sports)      # -7d .. +21d window

    wait = GCSObjectsWithPrefixExistenceSensor(                     # 45-min cutoff
        task_id="wait_for_exports", prefix="sales_",
        mode="reschedule",       # release the worker slot between pokes
        soft_fail=True)          # the cutoff is a cutoff, not a failure

    # Dynamic task mapping is Airflow's equivalent of Cloud Run's --tasks N:
    # one task per export, so a corrupt file fails alone.
    load = PythonOperator.partial(task_id="ingest_sales_file",
                                  python_callable=cli.ingest_sales_file
                       ).expand(op_args=cli.list_export_paths())

    register = PythonOperator(task_id="register_silver", python_callable=cli.register)
    build    = BashOperator(task_id="dbt_build",
                            bash_command="dbt build --vars '{as_of_date: {{ ds }}}'")
    fix_late = PythonOperator(task_id="reconcile", python_callable=cli.reconcile,
                              trigger_rule="all_done")   # runs even if upstream failed

    [sports, wait >> load] >> register >> build >> fix_late
```

Presented as pseudocode rather than shipped because the brief accepts it ("*python-based code, Sudo
code, Diagrams, UML*") and because shipping it has a real cost: installing `apache-airflow` alongside
this project pins `typing-extensions` back far enough to break pydantic, and with it both pytest and
dbt-core. Carrying an unverifiable second orchestrator at the price of a broken toolchain would be a
poor trade — and it is itself a small argument for the Cloud Run design, where each step is an
isolated container with its own dependency closure.

### Parallelism without a scheduler (D10)

Airflow's dynamic task mapping is the usual answer to "one task per file". Cloud Run Jobs give the
same natively: `--tasks 8` runs eight containers, each reading `CLOUD_RUN_TASK_INDEX`, and
`cli.ingest_sales` shards deterministically by index. No queue, no coordination, and no two
containers can claim the same export. Per-shard retries mean one corrupt export does not cost the
other 303.

### Completeness: cutoff, then self-heal (D11)

"Files typically arrive between 5–8 AM" is a soft guarantee, and the brief gives no completeness
signal. So: proceed at the cutoff on whatever landed, then a **reconciliation step** reprocesses any
export whose silver output is missing. Fail open, then self-heal — one straggler must not block the
daily table for every store.

Waiting for a fixed file count would break the first day volumes change. An upstream `_MANIFEST` with
an expected count is genuinely the better answer and the first thing I would ask the ecommerce team
for; I can't assume cooperation I haven't been promised.

### Data quality: fail closed, quarantine (D17)

Pydantic contracts at the boundary. Invalid records are written aside **with the reason attached** —
never dropped silently, never fatal to the run. Dropping means nobody notices 3% of records
vanishing; failing the run means one upstream typo takes out the daily table. Quarantine keeps the
data *and* the evidence, and makes the **quarantine rate** a monitorable metric: a spike means the
upstream schema changed.

Plus 50 dbt tests, including referential integrity, a grain guard, and the PII guard below.

---

## 3. The combined table

**Grain: one row per (store_id, date_day)** (D7) — the grain of the actual decision, which is how
many pizzas this store needs on this day.

Built on a full store × date spine rather than off the sales data, and that choice matters: a
forecasting feature table needs rows for days that **haven't happened yet**. Future dates carry event
features with a null target, which is exactly what a model scores into. Driving off sales alone would
silently drop every future date and leave the Data Science team with a training set and nothing to
predict on. `has_sales_data` makes that explicit rather than leaving it to be inferred.

Measured on the demo dataset: **372 rows = 12 stores × 31 dates; 168 with sales, 204 future.**

### The one modelling decision worth arguing about (D8)

Which events affect which stores? The obvious approach — join on geography — is wrong, and the live
data proves it:

| Fixture in the sample | Venue | UK relevance |
|---|---|---|
| Kairat Almaty vs Levski Sofia (Champions League) | Kazakhstan | **High** — midweek UK broadcast |
| Cincinnati Bengals vs Detroit Lions (NFL) | United States | **Moderate** — UK broadcast |
| Wolverhampton vs Blackburn (Championship) | England | **Moderate** |
| Argentinian Primera C fixture | Argentina | **None** |

A geographic join gets three of four wrong. **Relevance follows broadcast reach, not venue
location** — a commercial judgement, not something derivable from the feed. So it lives in a dbt
**seed** an analyst can tune without a code change or a deployment, with `scope` (national or local)
and a `weight` per competition. Containing the uncertainty in a reviewable artefact is the point;
burying it in a `CASE` statement would hide the least certain and most influential part of the design.

Honest limit: those weights are informed judgement, not fitted values. Once there's enough history
the Data Science team should *learn* them — and this seed becomes the baseline they beat.

**Also honest:** kickoff time plausibly matters intraday — demand for an 8pm kickoff concentrates in
the late afternoon. Day grain cannot see that. `earliest_kickoff_hour` preserves the signal, and
hourly grain is a named extension rather than a pretence that the question doesn't exist.

---

## 4. Privacy and GDPR

Three moves, in order, at the earliest possible boundary — see
[`docs/privacy.md`](docs/privacy.md) for the full PII register and the erasure runbook.

**1. Minimise (D6).** A declarative field policy marks every column `DROP` / `HASH` / `GENERALISE` /
`KEEP`. Email, card last-4 and full postcode are dropped at the first processing step. They exist only
in the immutable raw file, which expires after 30 days. Declarative on purpose: the answer to "what do
you do with personal data?" is a table someone can audit, not logic across three functions.

It's an **allow-list** — unknown columns are dropped and logged. If the platform adds
`customer_phone` next quarter, the worst case is a missing column someone notices, not a breach
nobody does.

**2. Pseudonymise (D5).** `customer_id` and `loyalty_id` → **HMAC-SHA256** with a key in Secret
Manager. Not a plain hash: an email or loyalty number has a small enough keyspace to brute-force, so
`SHA256(value)` is still personal data. The secret key is what makes the mapping infeasible to
invert. Deterministic, so repeat-purchase analysis survives — which dropping the identifier would
prevent.

**3. Aggregate it away.** Because the mart's grain is store × day, **the combined warehouse table
contains no personal data at all.** Aggregation is the strongest privacy control available, and here
it's also exactly what the modelling task needs — minimisation by design (Art. 5(1)(c)) rather than a
bolt-on.

**The claim is enforced, not asserted.** `dbt/tests/assert_no_pii_columns_in_marts.sql` interrogates
`information_schema` and fails if any mart column is a known identifier. It defends against the
realistic failure — someone adding `select *` to a staging model — which prose cannot catch and CI
can. There is also a property test asserting no known personal *value* appears anywhere in silver
output, plus a test proving that test can fail.

One detail worth stating: **quarantined sales rows are pseudonymised first.** The sports path
deliberately quarantines the *raw* payload as evidence; the sales path must not, because a quarantine
file is still data at rest. There's an explicit test for it, since a refactor "making the two paths
consistent" would silently start writing email addresses to disk.

---

## 5. Information security

| Control | Implementation |
|---|---|
| Identity | One service account per job, least privilege. Sales ingestion gets `objectViewer` on landing, `objectCreator` on the lake — **no delete anywhere** |
| Secrets | Secret Manager, mounted at runtime. No service-account key files: a key that doesn't exist cannot leak or expire |
| Credential hygiene | The API key travels in the URL *path*, so the client **redacts it before logging** — otherwise every log line publishes it. Tested. |
| Buckets | Uniform bucket-level access (IAM only, no per-object ACLs), public access prevention |
| Data residency | europe-west2. Set at creation, because it cannot be changed later |
| Retention | 30-day lifecycle deletion on bronze |
| Logs | No PII in logs; error bodies truncated to 200 chars so a log line cannot carry a payload |
| Images | One image, non-root user, no secrets baked in; `config.py` refuses to start without the key |

Deliberately not built, and named rather than left as gaps: Terraform (these `gcloud` commands should
be IaC before anyone relies on them — first thing I'd convert), VPC Service Controls, CMEK, and
monitoring/alerting. The pipeline emits the numbers; nothing yet watches them.

---

## 6. Scale — lead with the measured number

My first estimate was **4× too low**. I'd assumed ~120MB/day at 1M transactions; measured it's 533MB,
because a transaction is a *basket* of ~3 line items, not one row. Corrected:

| | 100k txn/day (today) | 1M txn/day (12–18mo forecast) |
|---|---|---|
| Line-item rows | 304,187 | **3,037,800** |
| Files (10k-row cap) | 31 | **304** |
| Raw CSV | 52 MB/day | **533 MB/day** |
| Parquet + snappy | — | **92.7 MB/day** (5.8× smaller) |
| Annual Parquet | — | ~34 GB |
| Annual file count | — | **~111,000** |
| Full day, one process, serial | — | **45.0s** (67,575 rows/sec) |
| Peak memory, all 304 files | — | **93 MB, flat** |

**This is not big data.** One process ingests the entire forecast peak day in 45 seconds using 93MB
of RAM. Saying so is the mature answer; reaching for Spark here would be a red flag.

What *actually* breaks at 10× is **file count**, not volume:

| Pressure | Fix |
|---|---|
| 304 files/day → ~111k/year | Compact to 128–512MB daily Parquet; partition pruning |
| Serial parse grows linearly | Shard across Cloud Run tasks — already implemented, no code change |
| Warehouse cost | Partition by date, cluster by `store_id`, require partition filter |
| The API | Doesn't scale with transaction volume at all — it's independent |

**Escalation thresholds, stated rather than implied** (D12): Dataflow above ~50GB/day — about 100×
current volume; streaming only if freshness requirements drop below an hour; Spark/Dataproc not
warranted at any volume this business plausibly reaches. Choosing the boring option *is* the
cost-consciousness the brief asks for.

---

## 7. Cost

At the 1M transactions/day forecast:

| Component | Monthly |
|---|---|
| GCS (~34GB/yr growth, standard) | ~£0.60 |
| BigQuery storage (mart only, tens of MB) | free tier |
| BigQuery batch loads | **free** |
| BigQuery queries (mart is MBs) | free tier |
| Cloud Run Jobs (~5 min/day across 5 jobs) | ~£0.50 |
| Cloud Workflows + Scheduler | ~£0.10 |
| Secret Manager | ~£0.05 |
| **Total** | **under £3/month** |
| *Cloud Composer 2, if used instead* | *+£250–350* |

The whole pipeline costs less than a round of coffees, and the single largest cost decision was
declining to pay for a managed Airflow control plane to run one daily job.

---

## 8. Testing

**129 unit tests in under a second, no network and no cloud, plus 50 dbt data tests** — measured on the
working version. `tests/test_pipeline.py` presents them as a specification: each stub names the failure it
prevents. Full methodology in [`docs/testing.md`](docs/testing.md).

The structural choice that makes this possible: **`pipeline/` has no orchestrator dependency at all**
(D14). Workflows and Cloud Run call into `cli.py`; nothing in the package calls back out. So the suite
needs no scheduler, no metadata database and no cloud credentials — and the same code path runs
unchanged in a Cloud Run Job, which is what makes D9's recommendation credible rather than
aspirational.

Tests worth pointing at, because each catches a specific realistic failure:

- **The PII guard** — queries `information_schema`, fails if any mart column is a known identifier
- **The property test** — no known personal *value* appears anywhere in output, so a new PII field
  added upstream still fails; plus a test proving that test can fail
- **Fake clock** for the rate limiter, so scheduling arithmetic is asserted without really waiting
- **Idempotency** — run three times, one output object, one row
- **Grain guard** — the fan-out that would triple every sales measure on the days that matter most
- **Shard coverage** — every export taken exactly once, no gaps or duplicates

Deliberately untested: live GCS/BigQuery calls, and `BigQueryWarehouse`. Mocking the BigQuery client
would verify I can write a mock, not that the SQL is right; that's covered by a real cloud run
instead.

### Tests that caught real bugs

Worth listing, because "did your tests catch anything?" deserves a concrete answer:

1. **Quarantine stored the wrong record.** It kept the *normalised* row, but normalisation is lossy
   exactly where validation fails — an unparseable timestamp becomes `None`, so the quarantine file
   preserved the symptom and discarded the evidence.
2. **The PII guard had an operator-precedence bug.** `A or B or (C and D)` meant it matched every
   mart column and would have failed permanently — and a test that always fails gets disabled, which
   is how a guard quietly stops guarding.
3. **A future-date test compared against wall-clock time**, so a backfill of last year's data would
   fail a test that has nothing to do with the data's correctness. Now compares against the logical
   date.
4. **Reconciliation reprocessed every export on every run.** `file_stem` strips `.csv` but not
   `.parquet`, so nothing looked processed. Idempotent, so the data was always right — it just
   silently redid the whole day.

---

## 9. Assumptions

- **"Transactions" are baskets**, so a day's export is line items — measured ~3.04 lines per basket.
  The brief's 100,000/day therefore means ~304,000 rows/day.
- **The combined table means one wide, denormalised, ML-ready table.** I deliver that *and* the star
  schema behind it, so the choice constrains nobody.
- **The dashboard and the model are downstream of me.** My deliverable ends at a trustworthy table.
- **Batch is appropriate.** Stock decisions are daily; the sources are a daily CSV drop and a
  request/response API. Nothing here argues for streaming.
- **Store reference data comes from the business**, not the sales feed — the export carries only a
  `store_id`, so `seed_stores.csv` stands in for a master-data system.
- **TheSportsDB stands in for the brief's unnamed API** (D2). Its free key **truncates result sets**
  (a full-season query returns 5 events, not 380) and its free endpoints aren't paginated. The shape,
  the rate limiting and the client behaviour are real; the volume is not. For production I'd expect a
  commercial feed with an SLA.

---

## 10. Compromises

- **Synthetic sales data.** No supermarket transaction data is public. Inherent to the brief rather
  than a shortcut — and the generator reproduces the *engineering* problem faithfully: the 10,000-row
  cap, realistic PII to strip, and optional malformed rows.
- **The uplift in the demo data is injected, not discovered.** `tools/generate_sales_csv.py` boosts
  pizza demand on real fixture dates and writes a **ground-truth manifest** recording exactly what it
  injected. The observed +19% lift says nothing about consumer behaviour. It's here as an *end-to-end
  assertion*: the features landed on precisely the right dates, so the relevance join and date
  alignment are demonstrably correct. Validating a real relationship needs real transaction data —
  the Data Science team's job.
- **DuckDB stands in locally for BigQuery, and the GCP path is undeployed.** Same dbt models, same
  SQL, zero cloud setup so a reviewer can run it instantly. But the adapters absorb most dialect
  difference, not all, and I have not run this against a live BigQuery — so "one config change" is
  the design intent rather than a demonstrated fact.
- **Pagination is unit-tested, not live-exercised.** The free endpoints don't paginate; cursor paging
  isn't built because no source needs it.
- **Full rebuild, not incremental.** Simple and idempotent at these volumes. Incremental models are
  described below rather than built.
- **`gcloud` commands, not Terraform.**

---

## 11. What I'd do next, in priority order

1. **Terraform the infrastructure.** The deploy commands demonstrate the shape; they shouldn't manage
   it.
2. **Monitoring and alerting** — freshness SLO on the mart, an alert on the quarantine rate (the
   metric that catches an upstream schema change), row-count anomaly detection. The pipeline already
   emits the numbers.
3. **Ask the ecommerce team for a manifest** with an expected file and row count. Turns the
   completeness heuristic into a contract (D11).
4. **Incremental dbt models** keyed on transaction date, once a full rebuild stops being trivially
   cheap.
5. **Compaction** of small Parquet files into daily 128–512MB objects, before ~111k files/year makes
   listing a cost.
6. **Learn the relevance weights** from history instead of asserting them (D8) — the pipeline has to
   exist first, which is the point.
7. **A commercial sports feed** with an SLA and full result sets.
8. **Hourly grain**, if the use case shifts from stock ordering to intraday replenishment.

---

## 12. The weakest parts of this design

Stated plainly, because pretending otherwise is worse:

- **The relevance weights are guesses.** Informed, documented, tunable — but guesses. They're the
  most influential thing in the whole pipeline, which is why they're a reviewable seed rather than
  code.
- **The demo dataset's correlation is manufactured.** Disclosed, manifested, and reframed as a
  correctness assertion — but it is not evidence about pizza and football.
- **Day grain can't see intraday demand shifts**, which is probably where real forecasting value sits.
- **The sports feed is a free tier** that truncates results, so the events side has never been
  exercised at realistic breadth.
- **The GCP path is written but not deployed.** The pipeline runs end to end locally against DuckDB;
  GCS, BigLake and BigQuery are implemented and reviewable but have not been executed against a live
  project. "One config change" is the design intent, not a demonstrated fact.
- **The Airflow alternative is pseudocode.** Cloud Workflows is the orchestrator I would run and the
  one that is actually written; the DAG sketch shows the mapping, not a tested artefact.
