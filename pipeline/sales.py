"""The sales ingestion job: capped CSV exports in, partitioned Parquet out.

    read CSV -> apply privacy policy -> validate -> write Parquet

**Privacy comes first, before validation — the opposite of the sports path.** There, quarantine
deliberately keeps the raw payload as evidence. Here the raw payload holds email addresses, card
last-4 and full postcodes, and a quarantine file is still data at rest — so sales rows are quarantined
*post-pseudonymisation*: still diagnosable (you can see the malformed quantity), with nothing
identifying in them. A refactor "making the two paths consistent" would silently start writing email
addresses to disk, which is why there is an explicit test for it.

pyarrow rather than pandas (D13): CSV in, Parquet out, bounded memory, and it is already required for
Parquet. Adding pandas would mean a second large dependency and a second type system to reconcile.

NOTE ON FORM: the silver schema is LITERAL — it is the contract dbt and BigLake depend on. Bodies are
pseudocode.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

SILVER_PREFIX = "silver/sales"

# =================================================================================================
# THE SILVER SCHEMA, declared once. Every Parquet file this module writes has exactly this shape.
#
# Letting pyarrow infer types per file is how a column becomes int64 in one file and string in the
# next, at which point the BigLake external table over the partition stops working and the failure
# looks like a query bug rather than an ingestion bug.
# =================================================================================================
SILVER_SCHEMA = {
    "transaction_id":             "string NOT NULL",
    "transaction_timestamp":      "timestamp[us] NOT NULL",
    "transaction_date":           "date32 NOT NULL",         # DERIVED from the timestamp, not trusted
    "store_id":                   "string NOT NULL",

    # Pseudonyms, never the originals. Nullable: not every basket has a known customer, and not every
    # customer is a loyalty member.
    "customer_pseudonym":         "string",
    "loyalty_pseudonym":          "string",
    "customer_postcode_district": "string",

    "product_sku":                "string NOT NULL",
    "product_name":               "string",
    "category":                   "string",
    "quantity":                   "int32 NOT NULL",

    # Money as DECIMAL, not float: 0.1 + 0.2 != 0.3 in binary floating point, and revenue feeding a
    # forecast should not accumulate error nobody can explain. Maps onto BigQuery NUMERIC.
    "unit_price_gbp":             "decimal128(12, 2)",
    "line_total_gbp":             "decimal128(12, 2)",

    "channel":                    "string",

    # Lineage, on every row.
    "source_file":                "string NOT NULL",
    "run_id":                     "string",
    "ingested_at":                "timestamp[us, tz=UTC] NOT NULL",
}


class SalesRowError(ValueError):
    """One row could not be made fit for silver. Becomes a quarantine entry, never a dropped row."""


@dataclass
class SalesFileResult:
    """What processing one CSV export did."""

    source_file: str
    rows_read: int = 0
    rows_written: int = 0
    quarantined: List[Dict[str, Any]] = field(default_factory=list)
    parquet_paths: List[str] = field(default_factory=list)
    dates_seen: List[date] = field(default_factory=list)


def prepare_row(safe_row: Dict[str, Any], source_file: str, run_id: Optional[str]) -> Dict[str, Any]:
    """Coerce one ALREADY-PSEUDONYMISED row into the silver schema.

    Raises SalesRowError, which the caller turns into a quarantine entry.

    PSEUDOCODE — each rule exists because of a specific failure

        transaction_timestamp: required, ISO-8601. Unparseable -> reject.
        transaction_date:      DERIVED from that timestamp.
                               # never trusted from a separate column: the partition key must agree
                               # with the timestamp, or a query filtered on date silently misses rows

        transaction_id, store_id, product_sku: required and NON-BLANK
                               # blank, not absent. A blank store_id passes a naive not-null check and
                               # then joins to nothing, silently dropping a store's entire day

        quantity:              int, strictly > 0
                               # returns and refunds are real but arrive through a different feed. A
                               # negative here is a data error, and letting it through UNDERSTATES
                               # demand — the exact direction that causes a stockout.

        unit_price_gbp, line_total_gbp: Decimal, >= 0, optional
    """
    raise NotImplementedError("pseudocode")


def transform_csv(
    csv_bytes: bytes,
    source_file: str,
    pseudonymiser: Any,
    run_id: Optional[str] = None,
    row_cap: Optional[int] = None,
) -> Tuple[Dict[date, Any], SalesFileResult]:
    """Turn one CSV export into Parquet-ready tables, keyed by transaction date.

    PSEUDOCODE

        reader = pyarrow.csv.open_csv(bytes, block_size=1MB,
                                      column_types = ALL STRING)
                 # all strings, coerced explicitly in prepare_row: inference would make a column's
                 # type depend on THIS file's contents, which is the drift SILVER_SCHEMA prevents

        for each record batch:              # batched, so memory stays flat regardless of file size
            for each row:
                safe_row = apply_policy(row, pseudonymiser)      # PRIVACY FIRST
                try:
                    prepared = prepare_row(safe_row, ...)
                except SalesRowError as why:
                    quarantine {reason: why, source_file, run_id, row: safe_row}
                    # the PSEUDONYMISED row, never the raw one
                    continue
                group prepared by its transaction_date

        if rows_read > row_cap:
            log WARNING
            # the platform promises at most 10,000 rows. More means the promise changed, and
            # assumptions downstream (in-memory Parquet buffering) depend on it.

        return {date: Arrow table against SILVER_SCHEMA}, result

    Normally one date — exports are daily — but GROUPING rather than assuming means a file straddling
    midnight lands in the right partitions instead of whichever date we guessed.
    """
    raise NotImplementedError("pseudocode")


def silver_path(transaction_date: date, source_file: str) -> str:
    """``silver/sales/transaction_date=YYYY-MM-DD/<source stem>.parquet``

    Partitioned by **transaction** date, not ingest date: every downstream query asks "what happened on
    the 8th", so late-arriving data lands in the partition it belongs to and reconciliation (D11) is a
    simple partition rebuild.

    The source stem in the object name keeps a silver row traceable to the export that produced it, and
    makes re-processing REPLACE rather than duplicate.
    """
    raise NotImplementedError("pseudocode")


def quarantine_path(source_file: str, run_id: Optional[str]) -> str:
    """``quarantine/sales/run_id=<run>/<source stem>.jsonl`` — partitioned by run, so a bad run is easy
    to isolate. Uses the same stem logic as silver_path: when the two disagreed, tracing a quarantined
    row back to its partition meant guessing."""
    raise NotImplementedError("pseudocode")


def load_csv_file(
    csv_bytes: bytes,
    source_file: str,
    storage: Any,
    pseudonymiser: Any,
    run_id: Optional[str] = None,
    row_cap: Optional[int] = None,
) -> SalesFileResult:
    """Process one export end to end, writing Parquet and quarantine output.

    **The unit of work one shard runs** (D10): one file, its own retry, so a corrupt export fails alone
    rather than taking the other 303 with it.

    PSEUDOCODE

        tables, result = transform_csv(...)
        for date, table in tables:  storage.write_bytes(silver_path(...), to_parquet(table))
        if any quarantined:         storage.write_bytes(quarantine_path(...), jsonl)
                                    # only if there ARE any — an empty quarantine file every day is
                                    # noise that trains people to ignore the directory
        log rows in / rows out / quarantined
    """
    raise NotImplementedError("pseudocode")
