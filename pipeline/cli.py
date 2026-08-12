"""Command-line entrypoints for each pipeline step.

One place the steps are wired together, called by two things: the local Makefile and the Cloud Run Jobs
that Cloud Workflows sequences. That is what keeps DECISIONS.md D14 honest — **nothing in this package
imports an orchestrator**, so the same code path runs with or without one, and none of it needs a
scheduler to be testable.

    python -m pipeline.cli ingest-sports --start 2026-08-01 --end 2026-08-31
    python -m pipeline.cli ingest-sales                    # shards via CLOUD_RUN_TASK_INDEX
    python -m pipeline.cli register
    python -m pipeline.cli reconcile

NOTE ON FORM: pseudocode.
"""

from datetime import date
from typing import List, Optional, Sequence


def ingest_sports(start: date, end: date, ingest_date: date, run_id: str) -> int:
    """Fetch fixtures to bronze, then normalise, validate and write silver. Returns events written.

    PSEUDOCODE

        settings, storage = load_settings(), build_storage(settings)
        window = FetchWindow(start, end)

        log estimate_request_count(window) and the expected minutes at the configured rate
            # before spending anything, so a widened window is a visible decision

        fetch_to_bronze(...)
        outcome = bronze_to_records(...)
        write_events_to_silver(storage, deduplicate_events(outcome.valid), ingest_date)
        log the quarantine rate
    """
    raise NotImplementedError("pseudocode")


def ingest_sales_file(path: str, run_id: str) -> int:
    """Process one export. The unit of work one Cloud Run task runs.

    PSEUDOCODE:  load_csv_file(read(path), storage, Pseudonymiser(settings.pseudonym_key),
                               row_cap=ECOMMERCE_EXPORT_ROW_CAP)
    """
    raise NotImplementedError("pseudocode")


def ingest_sales(
    landing_dir: Optional[str] = None,
    run_id: str = "manual",
    shard_index: int = 0,
    shard_count: int = 1,
) -> int:
    """Process the day's exports, optionally only this shard of them.

    **Sharding is how the work parallelises without a scheduler.** A Cloud Run Job launched with
    ``--tasks N`` runs N containers, each receiving ``CLOUD_RUN_TASK_INDEX`` and
    ``CLOUD_RUN_TASK_COUNT``; each takes every Nth export. Same effect as one Airflow mapped task per
    file, and it needs no code change as the count grows from 31 to 304 a day (D10).

    Deterministic **by index** rather than claiming work from a queue, so two containers can never take
    the same file and no coordination is needed. (A queue would balance uneven file sizes better; index
    sharding needs no infrastructure.)

    PSEUDOCODE

        paths = list_export_paths()
        mine  = paths[shard_index::shard_count]

        for path in mine:
            try:    rows += ingest_sales_file(path, run_id)
            except: log the traceback, COLLECT the failure, keep going
                    # one corrupt export must not cost the other 303

        if failures: raise, naming them
                     # the shard still fails VISIBLY — but only after doing all the work it could
    """
    raise NotImplementedError("pseudocode")


def list_export_paths() -> List[str]:
    """The exports available to process — a GCS prefix or a local directory, per the target, so the
    orchestrator does not care which."""
    raise NotImplementedError("pseudocode")


def count_pending_exports() -> int:
    """How many exports have landed. Used by the arrival check, which waits for at least one.

    Deliberately NOT a fixed expected count: volumes change (31 files/day today, ~304 at the forecast),
    so any hardcoded expectation breaks the first day the business grows. An upstream manifest with an
    expected count would turn this heuristic into a contract, and it is the first thing I would ask the
    ecommerce team for (D11).
    """
    raise NotImplementedError("pseudocode")


def reconcile(run_id: str) -> int:
    """Process any export whose silver output is missing. Returns how many were reprocessed.

    The **self-healing half of D11**: the daily run proceeds on whatever landed by the cutoff rather
    than blocking on a straggler; this catches what arrived afterwards. Safe to run always, because
    silver paths are deterministic — reprocessing replaces an object rather than adding a second copy.

    PSEUDOCODE

        already = {stem(obj) for obj in storage.list_paths("silver/sales") if obj.endswith(".parquet")}
        missing = [p for p in list_export_paths() if stem(p) not in already]
                  # NOTE: strip ".parquet" from one side and ".csv" from the other. Getting this wrong
                  # made reconciliation silently reprocess the entire day on every run — idempotent, so
                  # the data stayed correct while doing many times the necessary work.
        for each missing: ingest_sales_file(...)

    Limitation, stated rather than hidden: this detects a MISSING output, not a STALE one. An export
    rewritten upstream under the same name would not be picked up. A manifest carrying a content hash
    would catch that, and is the natural next step if the platform ever rewrites files.
    """
    raise NotImplementedError("pseudocode")


def register() -> None:
    """Expose silver to the warehouse: DuckDB views locally, BigLake external tables on GCP. Cheap and
    idempotent — it creates or replaces table definitions and moves no data."""
    raise NotImplementedError("pseudocode")


def main(argv: Optional[Sequence[str]] = None) -> int:
    """argparse over the five subcommands above.

    ``--shard-index`` / ``--shard-count`` default to ``CLOUD_RUN_TASK_INDEX`` and
    ``CLOUD_RUN_TASK_COUNT``, so a sharded Cloud Run Job needs no arguments at all.
    """
    raise NotImplementedError("pseudocode")
