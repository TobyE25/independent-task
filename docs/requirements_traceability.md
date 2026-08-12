# Requirements traceability

Every requirement stated or implied by the brief, and where this repo answers it. The
point of the table is that a reviewer shouldn't have to hunt, or take my word for it.

Status: ✅ built and exercised · 🟡 built, limits noted · 📄 documented, deliberately not built

| # | Requirement (from the brief) | Status | Where |
|---|---|---|---|
| **Environment** | | | |
| R1 | Orchestration-based environment (i.e. Apache Airflow), as a DAG **or ordered tasks** | ✅ | `deploy/workflow.yaml` — Cloud Workflows + Cloud Run Jobs + Scheduler, the brief's second form, chosen on cost (D9). The Airflow equivalent is pseudocode in DESIGN.md §2 |
| R2 | Python >= 3.8 | ✅ | Package avoids 3.9+ syntax (ruff `target-version = py38`). Note 3.8 is EOL — see `pipeline/config.py` |
| **Data sources** | | | |
| R3 | Sports Events API: past and upcoming events, global | ✅ | `pipeline/sports.py` — registry + engine |
| R4 | Handle restrictive rate limiting | ✅ | `pipeline/http_client.py` — token bucket, `Retry-After` honoured and capped, full-jitter backoff |
| R5 | Handle pagination | 🟡 | `pipeline/http_client.py` — page and offset styles. **Limit:** unit-tested against fake fetchers, not a live paginated endpoint; cursor paging not built (DECISIONS.md D2) |
| R6 | Daily sales CSVs delivered to a cloud storage bucket | ✅ | `pipeline/sales.py`, `BUCKET_LANDING`, `deploy/README.md` §1 |
| R7 | Files arrive 5–8 AM | ✅ | 08:15 schedule + `cli.reconcile` for late arrivals (D11); DESIGN.md §2 |
| R8 | Export files capped at 10,000 rows → many files/day | ✅ | `ECOMMERCE_EXPORT_ROW_CAP`; sharded across Cloud Run tasks (D10). 31 files/day at today's volume, an estimated ~304 at forecast |
| **Output** | | | |
| R9 | Combined table in the Data Warehouse, for DS modelling | ✅ | `dbt/models/marts/mart_pizza_demand_daily.sql`; DESIGN.md §3 |
| R10 | Data Lakehouse architecture | ✅ | GCS Parquet + BigLake external tables → BigQuery gold (D4); `pipeline/warehouse.py` |
| R11 | Output format suited to columnar storage | ✅ | Parquet + snappy, Hive-partitioned by date (D3). ~5.8× smaller than CSV on the loaded sample |
| **Design considerations** | | | |
| R12 | Future growth of the business | ✅ | Source registry (new source = one entry); shard count scales with file count; DESIGN.md §6 |
| R13 | Scale 100k → 1M+ transactions/day | ✅ | DESIGN.md §6 — **estimated** from the loaded sample: ~3.04M rows, ~304 files, ~533MB CSV/day |
| R14 | Running and maintenance costs | ✅ | DESIGN.md §7 — itemised, under £3/month, plus the Composer trade-off (D9) |
| R15 | Information security | 🟡 | DESIGN.md §5 + `deploy/README.md` §3 — per-job service accounts, Secret Manager, no delete, key redaction in logs. **Not built:** Terraform, VPC-SC, CMEK |
| R16 | Data privacy and regulation (PII, GDPR) | ✅ | `docs/privacy.md` + `pipeline/privacy.py` — minimise → pseudonymise → aggregate (D5, D6); PII register; erasure runbook; **enforced by tests** |
| R17 | Modularity and reusability of components | ✅ | `Storage`/`Warehouse` protocols, declarative source registry and field policy (D14, D15, D16) |
| **Delivery** | | | |
| R18 | Detailed end-to-end description of the pipeline | ✅ | `DESIGN.md` — the primary deliverable |
| R19 | Supporting python code / pseudocode | ✅ | `dbt/` and `deploy/` are runnable; `pipeline/` is pseudocode in real modules, with declarative parts literal — see README |
| R20 | Diagrams | ✅ | `docs/architecture.md` §1 — containers with trust zones; §4 ERD |
| R21 | UML | ✅ | `docs/architecture.md` §2 sequence diagram, §3 class diagram |
| R22 | Be prepared to discuss architecture and design decisions | ✅ | `DECISIONS.md` — 17 decisions, each with alternatives and what would change my mind |
| R23 | Be prepared to discuss services chosen | ✅ | DESIGN.md §2 and §7; `deploy/README.md` |
| R24 | Be prepared to discuss libraries used | ✅ | `requirements.txt` — every entry annotated with why it is there |
| **Bonus** | | | |
| B1 | Testing methodology / unit tests | ✅ | `docs/testing.md` (methodology + what is deliberately untested), `tests/test_pipeline.py` (the plan), `dbt/tests/` (runnable). 48 unit-test specifications + 50 dbt data tests |
| B2 | Use of Google Cloud services | 🟡 | GCS, BigQuery, **BigLake**, Cloud Run Jobs, Cloud Workflows, Cloud Scheduler, Secret Manager, Artifact Registry, Cloud Build. **Limit:** written and reviewable, not deployed to a live project |

---

## Requirements I've read into the brief

Worth stating separately, because these are interpretations rather than instructions, and
an interviewer may disagree with any of them:

- **"Combined table" means one wide, denormalised, ML-ready table.** I deliver that *and*
  the star schema behind it, so the choice doesn't constrain anyone (D7).
- **The dashboard is downstream of me, not mine to build.** The brief says the Analytics
  team wants a dashboard and the Data Science team does the modelling. My deliverable ends
  at a trustworthy table.
- **"Sporting events in the calendar" means broadcast-relevant events, not just local
  fixtures.** A World Cup match drives pizza demand in every UK store regardless of where
  it's played — which is the whole reason the relevance rules exist (D8).
- **Batch is appropriate.** Stock decisions are daily and the sources are a daily CSV drop
  and a request/response API. Nothing here argues for streaming.
