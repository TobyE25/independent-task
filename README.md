# Pizza Perfect

A pipeline that combines **upcoming sporting events** with **daily sales transactions** into one
warehouse table, so Sprouts can forecast how many pizzas each store needs on a match day.

The deliverable is **`mart_pizza_demand_daily`** — one row per store per day, model-ready.

```
Sports Events API ─┐
                   ├─► GCS lakehouse (Parquet) ─► BigQuery ─► mart_pizza_demand_daily
Daily sales CSVs ──┘
```

---

## What form this submission takes

The brief asks for *"a detailed end-to-end description of your pipeline"*, supported by *"python-based
code, Sudo code, Diagrams, UML"*. So:

|                            | Form                                 | Why                                                                                                                                                                                                                                        |
| -------------------------- | ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **`DESIGN.md`**    | The deliverable                      | The end-to-end description                                                                                                                                                                                                                 |
| `docs/architecture.md`   | Diagrams + UML                       | Containers with trust zones, sequence, classes, ERD                                                                                                                                                                                        |
| `dbt/`                   | **Real, runnable SQL**         | The transformation logic and the data tests*are* the modelling argument — paraphrasing them would lose it                                                                                                                               |
| `pipeline/`              | **Pseudocode in real modules** | Signatures, docstrings and the reasoning, with bodies as specified behaviour. Declarative parts — the field policy, the schemas, the source registry — are literal, because those are design decisions rather than implementation detail |
| `tests/test_pipeline.py` | Specification                        | Each stub names the failure it prevents                                                                                                                                                                                                    |
| `deploy/`                | Real config + commands               | Cloud Workflows definition and the`gcloud` sequence                                                                                                                                                                                      |

**Where the numbers come from.** The figures quoted in `DESIGN.md` are **estimates**, derived from the
data actually loaded — the real fixture feed and a generated sales sample at the brief's current 100,000
transactions/day — then scaled arithmetically to the 1M/day forecast. So ~3.04M rows in ~304 files,
~533 MB of CSV and ~5.8× Parquet compression are grounded in observed row counts and file sizes, but
they are projections rather than benchmark results. Throughput and memory would need a production run to
state, so I don't quote figures for them.

---

## Where to look

|                                                                       |                                                                                                                             |
| --------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| **[DESIGN.md](DESIGN.md)**                                       | **Start here.** Architecture, cost, scale, privacy, assumptions, compromises, what I'd do next, and the weakest parts |
| [DECISIONS.md](DECISIONS.md)                                           | 17 decisions, each with the alternative it beat and what would change my mind                                               |
| [docs/architecture.md](docs/architecture.md)                           | Diagrams and UML                                                                                                            |
| [docs/privacy.md](docs/privacy.md)                                     | PII register, GDPR mapping, erasure runbook                                                                                 |
| [docs/testing.md](docs/testing.md)                                     | Testing methodology, and the specific failure modes the suite is built to catch                                             |
| [docs/requirements_traceability.md](docs/requirements_traceability.md) | Every requirement in the brief mapped to where it's answered                                                                |

## Layout

```
pipeline/          no orchestrator dependency — Workflows calls in, never the reverse
  config.py        the only module that touches os.environ
  http_client.py   throttling, retries, paging against a rate-limited API
  privacy.py       the field policy: drop / hash / generalise, applied before anything else
  validation.py    schema contracts; invalid rows are quarantined, never dropped
  storage.py       the cloud boundary — local filesystem or GCS
  warehouse.py     the warehouse boundary — DuckDB or BigQuery/BigLake
  sports.py        source registry + ingestion engine
  sales.py         CSV -> Parquet, with the privacy policy applied first
  cli.py           entrypoints, called by Cloud Run Jobs

dbt/               staging -> marts -> mart_pizza_demand_daily, plus 50 data tests
deploy/            Cloud Workflows definition and the gcloud commands
tools/             the synthetic sales generator
tests/             the test plan
```

## How it runs

Daily at 08:15 Europe/London — after the 05:00–08:00 export window — as five Cloud Run Jobs sequenced by
Cloud Workflows (`deploy/workflow.yaml`). In order:

```
ingest-sports ─┐                                    # fetch fixtures, validate, land Parquet
               ├─ register ─ dbt build ─ reconcile   # BigLake tables, marts + tests, late arrivals
ingest-sales ──┘  (×8 shards)                       # privacy policy, then Parquet
```

The two ingestion steps run concurrently — the sports API has nothing to do with the CSV drop, and
coupling them would let a slow rate-limited pull delay the sales load for no reason.

The same `pipeline.cli` entrypoints target the filesystem and DuckDB when `TARGET=local`, so the design
carries no hard dependency on a cloud account. See [`deploy/README.md`](deploy/README.md) for the GCP
deployment.

---

## Three things worth knowing up front

**The sports data is real; the sales data is synthetic.** No supermarket transaction data is public, so
`tools/generate_sales_csv.py` produces it — honouring the platform's 10,000-row export cap, with
realistic PII for the privacy layer to strip.

**Any sports/pizza correlation in the demo data was injected, not discovered.** The generator boosts
demand on real fixture dates and writes a ground-truth manifest recording exactly what it injected. Any
lift the mart shows is an *input*, not a finding, and says nothing about consumer behaviour — it exists
as a *correctness assertion* that the features land on exactly the right dates and no others.

**The combined table holds no personal data at all.** Its store × day grain makes that structural rather
than a promise, and `dbt/tests/assert_no_pii_columns_in_marts.sql` fails the build if it ever stops
being true.
