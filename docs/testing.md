# Testing methodology

**129 unit tests in under a second, plus 50 dbt data tests.** No network, no cloud credentials, no
scheduler.

Those counts are from the working version, which was built and run before implementation was reduced to
pseudocode. `tests/test_pipeline.py` presents the same suite as a **specification** — one stub per test,
each naming the failure it prevents. The dbt tests in `dbt/tests/` and `dbt/models/**/*.yml` are real and
runnable.

---

## The structural choice that makes this possible

`pipeline/` **has no orchestrator dependency at all** (DECISIONS.md D14). Cloud Workflows and Cloud Run
call into `cli.py`; nothing in the package calls back out. So the suite needs no scheduler, no metadata
database and no cloud project, and the same code path runs unchanged in a Cloud Run Job.

That this matters is not hypothetical: an earlier version shipped an Airflow DAG, and installing
`apache-airflow` to verify it pinned `typing-extensions` back far enough to break pydantic — taking
pytest and dbt-core with it. A package that depends on an orchestrator inherits its dependency
conflicts.

Similarly, every external dependency is injected: the clock and `sleep` into the rate limiter, the
HTTP session into the client, the storage backend behind a protocol, the BigQuery client into the
warehouse. So the tests need **no mocking framework** — just the local implementations.

---

## The layers, and what each is for

### 1. Unit tests — behaviour, not coverage

Each test names the failure it prevents. A test whose purpose isn't obvious is a test that gets
deleted during the next refactor.

| Area | What is actually asserted |
|---|---|
| Rate limiter | Scheduling arithmetic against a **fake clock** — no real waiting, no flakiness on a loaded CI runner. Also: idle time cannot grant unlimited tokens, and asking for more than capacity fails fast rather than looping forever |
| HTTP client | Retries 429/5xx, honours `Retry-After`, **caps** it so a hostile header can't hang a job, fails fast on 4xx without spending quota, treats HTML-with-200 as a hard failure, and **never logs the API key** |
| Pagination | Every style and every termination path — the only thing standing behind this code, since the live API doesn't paginate |
| Validation | Malformed records are **quarantined with a specific reason**, never dropped, never fatal; the batch survives one bad row |
| Privacy | Determinism, key sensitivity, postcode generalisation, and the property test below |
| Sales loader | The 10,000-row cap, ragged rows, money as `Decimal`, date derived from the timestamp, schema stability |
| Sports engine | Fan-out, per-source isolation, idempotency, deduplication, shard coverage |
| Warehouse | Registration creates a **view, not a copy**; a missing partition degrades to empty rather than failing the build |

### 2. Data tests (dbt) — invariants of the assembled dataset

Row-level checks can't catch a property that only exists once everything is joined.

- `unique` / `not_null` on every key
- `relationships` fact → dimension, so a store appearing in sales but not in the estate fails loudly
  instead of silently vanishing from the mart via an inner join
- `accepted_values` on `scope`, `nation`, `iso_day_of_week`
- **Grain guard** — one row per store per day. This is the fan-out that would triple every sales
  measure on precisely the days the business cares most about, and where nobody would question a high
  number
- **No future-dated sales** — compared against the **logical date**, not the wall clock
- **Plausibility** — non-negative units, and the pizza subset can't exceed the whole basket count
- **The PII guard** — see below

### 3. The end-to-end check

A verification step runs after the dbt build and reports whether the combined table actually *does
anything*: how many rows have both a sales target and a relevant event, and how demand on fixture days
compares to quiet ones.

It exists because the most damaging possible outcome is a mart that is **structurally perfect and
analytically empty** — every event feature zero on every row with a target, so the join runs, all 50
tests pass, and the table is worthless. That failure is invisible unless something explicitly looks for
it, and it **is what happened** on the first build: the sales window did not overlap any UK-relevant
fixture, so the join produced nothing while every test stayed green.

This is a sanity check on the dataset, not a data test. The dbt tests assert invariants that must always
hold; this reports numbers a human should look at.

---

## The tests worth arguing about

### The PII guard

```sql
select table_name, column_name
from information_schema.columns
where (lower(table_name) like 'mart%' or ... )
  and lower(column_name) in ('customer_email', 'card_last4', ...)
```

This turns "the warehouse contains no personal data" from a sentence in a document into something CI
enforces. It defends against the realistic failure — not somebody deciding to load email addresses,
but somebody adding `select *` to a staging model and nobody noticing for six months.

It also carries a comment about its own operator precedence, because the first version had
`A or B or (C and D)` and matched every mart column. **A test that always fails gets disabled, which
is how a guard quietly stops guarding.**

### The property test, and the test that tests it

Rather than asserting specific columns are absent, `test_no_personal_value_survives_the_boundary`
asserts that no known personal *value* appears anywhere in the output — as a key, a value, or embedded
in a string. Field-by-field assertions pass happily when a *new* PII field is added upstream; this
fails.

And because a test that cannot fail is worse than no test,
`test_the_property_test_would_actually_fail_if_the_policy_regressed` deliberately weakens the policy
and asserts the leak is detected.

### Every test should be able to go red

The question applied to each one: *what change would make this fail?* If nothing, it was rewritten or
deleted. A previous project shipped a `not_null` test on a column that was never null and a bounds
test that couldn't fire — both passed forever and proved nothing.

---

## Deliberately not tested

Named, because an unexplained gap looks like an oversight:

| Not tested | Why | Covered by |
|---|---|---|
| Live GCS / BigQuery calls | Mocking a cloud client verifies I can write a mock, not that the SQL is right | A real cloud run |
| `BigQueryWarehouse` SQL | Same reasoning. The external-table DDL is dialect-specific and only a real BigQuery will tell the truth | A real cloud run |
| The Airflow alternative | Not shipped as code — it is pseudocode in DESIGN.md §2, because installing Airflow breaks this project's dependency closure (D9) | Nothing. It is a described mapping, not an artefact |
| `deploy/workflow.yaml` execution | Workflows has no local emulator | YAML structure validated; a real deployment |
| End-to-end volume beyond one day | A 14-day demo and a measured 1M-transaction single day were enough to characterise it | The measurements in DESIGN.md §6 |

---

## Continuous integration

Ruff, then pytest, then `dbt build` against DuckDB — the same three commands as locally, so CI cannot
pass something a developer can't reproduce.

One rule worth copying: pytest is configured to turn any `DeprecationWarning` raised from the `pipeline`
package into a **failure**, rather than filtering warnings off wholesale. Third-party noise is left
alone. That rule is what caught `datetime.utcnow()` before it became a runtime error on a future
Python.

---

## What the tests actually caught

The honest answer to "did any of this find a real bug?" — four, all found by running the thing rather
than reading it:

1. **Quarantine stored the wrong version of the record.** It kept the *normalised* row, but
   normalisation is lossy exactly where validation fails: an unparseable timestamp becomes `None`, so
   the quarantine file preserved the symptom and discarded the evidence. Whoever opened it would see
   `kickoff_utc: null` and never know the provider sent `21/08/2026 19:00`.
2. **The PII guard's operator precedence** — would have failed permanently, then been disabled.
3. **A future-date test compared against wall-clock time**, so backfilling last year's data would fail
   a test unrelated to the data's correctness.
4. **Reconciliation reprocessed every export on every run.** `file_stem` strips `.csv` but not
   `.parquet`, so nothing looked processed. Idempotent, so the output was always correct — it just
   silently redid the entire day's work every time.

And one the tests *didn't* catch, which the verification step did: the synthetic uplift was diluted from
21–54% down to an observed 2.8%, because filler basket lines were drawn from a product pool that included
pizza — a second path into the basket that the uplift never touched. Every test passed. Only looking at
the numbers found it.

Which is the argument for having a step that reports numbers rather than only asserting invariants.
