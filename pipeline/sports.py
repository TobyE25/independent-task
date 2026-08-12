"""Sports events ingestion: the source registry and the engine that drives it.

Adding another sports feed is **one registry entry**, not a new script. That is the single property
that stops a pipeline like this becoming a dozen bespoke scripts nobody dares touch.

**Two stages, and the split is the point.** ``fetch_to_bronze`` lands what the API said, byte for byte,
unvalidated. ``bronze_to_records`` reads it back, normalises and validates. So if the normaliser has a
bug or the canonical schema gains a column, we replay bronze instead of re-hitting a rationed API —
which under a restrictive quota may simply not be available today (DECISIONS.md D1).

NOTE ON FORM: the registry and the watchlist are LITERAL — they are the design. Bodies are pseudocode.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Sequence

BRONZE_PREFIX = "bronze/sports_events"
SILVER_PREFIX = "silver/sports_events"

# =================================================================================================
# THE WATCHLIST. Competitions whose fixtures plausibly move UK pizza demand. Every id was verified
# against the live API rather than assumed — a wrong id returns an empty payload, which is
# indistinguishable from "no fixtures", which is the kind of silent hole that is very hard to notice.
#
# In production this belongs in a table Analytics maintains, not in code: deciding the Six Nations
# matters and the Bundesliga does not is a commercial judgement and should not need a deployment.
# =================================================================================================
WATCHLIST_LEAGUES = {
    4328: "English Premier League",
    4329: "English League Championship",
    4480: "UEFA Champions League",
    4482: "FA Cup",
    4391: "NFL",
    4443: "UFC",
}

# Kept narrow by default: each extra sport multiplies the request count across the whole window, and
# we are rationing a quota.
DEFAULT_SPORTS = ("Soccer",)


@dataclass(frozen=True)
class FetchWindow:
    """What to fetch. Dates inclusive, spanning both directions — the brief asks for past *and*
    upcoming events: history trains the model, fixtures drive the forecast.

    ``around(today, days_back=7, days_forward=21)`` is the daily shape, asymmetric on purpose: we only
    re-pull recent history to catch corrections (a postponement, a moved kickoff), but want runway
    ahead for stock-ordering lead time.
    """

    start_date: date
    end_date: date
    sports: Sequence[str] = DEFAULT_SPORTS
    league_ids: Sequence[int] = tuple(WATCHLIST_LEAGUES)
    # Rejects an inverted window at construction.


@dataclass(frozen=True)
class Source:
    """One external dataset, described as DATA rather than code."""

    name: str            # logical name; becomes the bronze folder
    path: str            # endpoint path under the API base url
    items_key: str       # key in the response envelope holding the records
    pagination: str      # "none" | "page" | "offset"
    build_params: Any    # (window) -> list of request parameter sets. This is where fan-out lives.
    label_params: Any    # (params) -> a short label, used in bronze filenames so a landed file traces
                         # back to the exact request that produced it


# =================================================================================================
# THE REGISTRY. Two sources of deliberately DIFFERENT SHAPE — one fans out over a date window, the
# other over a watchlist — which is what proves the registry does real work rather than wrapping a
# single endpoint. The engine below does not know the difference.
# =================================================================================================
REGISTRY: Dict[str, Source] = {
    "events_by_day": Source(
        name="events_by_day",
        path="eventsday.php",
        items_key="events",
        pagination="none",   # the free v1 endpoints return a single payload
        build_params=lambda w: [
            {"d": day.isoformat(), "s": sport} for day in w.dates() for sport in w.sports
        ],
        label_params=lambda p: "{}__{}".format(p["d"], p["s"].lower()),
    ),
    "events_next_by_league": Source(
        name="events_next_by_league",
        path="eventsnextleague.php",
        items_key="events",
        pagination="none",
        build_params=lambda w: [{"id": league_id} for league_id in w.league_ids],
        label_params=lambda p: "league_{}".format(p["id"]),
    ),
    # To add a source: one entry here. No engine changes.
}


# =================================================================================================
# THE SILVER SCHEMA, declared explicitly. Inferred types drift between files, and a column that is
# int64 in one file and string in the next breaks the external table over the partition — failing like
# a query bug rather than an ingestion bug.
# =================================================================================================
SPORTS_SILVER_SCHEMA = {
    "event_id": "string NOT NULL",   "event_name": "string",      "sport": "string",
    "league_id": "string",           "league_name": "string",     "season": "string",
    "home_team": "string",           "away_team": "string",       "venue": "string",
    "city": "string",                "country": "string",
    "event_date": "date32 NOT NULL", "kickoff_utc": "timestamp[us]",
    "status": "string",              "is_postponed": "bool NOT NULL",
    "source_name": "string NOT NULL", "source_file": "string", "run_id": "string",
    "ingested_at": "timestamp[us, tz=UTC] NOT NULL",
}


@dataclass
class SourceIngestResult:
    """What one source's pull did. RETURNED rather than only logged, so the orchestrator can act on it."""

    source_name: str
    requests_made: int = 0
    records_landed: int = 0
    files_written: List[str] = field(default_factory=list)
    empty_responses: int = 0


def estimate_request_count(window: FetchWindow, source_names: Sequence[str] = ()) -> int:
    """How many requests a run would make.

    Logged BEFORE spending anything, so a widened window is an explicit decision rather than a surprise
    against a rationed quota. A 90-day window across four sports is 360 requests — eighteen minutes at
    20/min — and that is worth knowing in advance.
    """
    raise NotImplementedError("pseudocode")


def bronze_path(source_name: str, ingest_date: date, label: str) -> str:
    """``bronze/sports_events/<source>/ingest_date=YYYY-MM-DD/<label>.jsonl.gz``

    Hive-style partitioning, so a query for one day reads one directory instead of scanning the lake.

    A **pure function** of (source, date, request), which is what makes a re-run idempotent: the same
    request writes the same object and replaces it, rather than appending a second copy and
    double-counting.
    """
    raise NotImplementedError("pseudocode")


def fetch_to_bronze(
    settings: Any,
    storage: Any,
    window: FetchWindow,
    run_id: str,
    ingest_date: Optional[date] = None,
    source_names: Sequence[str] = (),
    client: Any = None,
) -> List[SourceIngestResult]:
    """Pull every source and land raw payloads in bronze.

    PSEUDOCODE

        client   = client or HttpClient(limiter=TokenBucket(settings.sports_requests_per_minute))
        base_url = "{base}/{api_key}"
                   # the key is a PATH segment, which is why http_client.redact() exists

        for each source name:
            try:
                for each request params in source.build_params(window):
                    records = flatten(iter_pages(fetch, extract(items_key), source.pagination, params))

                    if not records:
                        result.empty_responses += 1
                        continue
                        # genuinely normal — most sports have no fixtures on most days. Counted so the
                        # ratio stays visible: all-empty across a whole window means a BROKEN QUERY,
                        # not a quiet month.

                    storage.write_bytes(bronze_path(...), to_jsonl_gz(records))
            except anything:
                log the traceback and CONTINUE with the other sources
                # one source failing must not stop the others — a fixture list is still useful without
                # a UFC card. Whether the run is acceptable is the ORCHESTRATOR's judgement, not this
                # function's, so the failure is returned rather than swallowed.

        return one result per source
    """
    raise NotImplementedError("pseudocode")


def bronze_to_records(storage: Any, ingest_date: date, run_id: str) -> Any:
    """Read a day's bronze, normalise and validate. Re-runnable against data already paid for.

    PSEUDOCODE

        for each source, for each bronze object under ingest_date=<date>:
            raw        = from_jsonl_gz(storage.read_bytes(path))
            normalised = [normalise_sports_event(r, source, path, run_id) for r in raw]
            outcome    = validate_records(normalised, ..., raw_records=raw)
                         # raw passed through so quarantine keeps the PROVIDER's payload — the only
                         # version that still shows why a record failed
            accumulate valid + quarantined

        log the combined quarantine rate
    """
    raise NotImplementedError("pseudocode")


def deduplicate_events(records: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Collapse events appearing in more than one source.

    **Load-bearing, not hygiene.** The two sources overlap BY DESIGN: a Premier League fixture arrives
    from both the day sweep and the watchlist. Uncollapsed, every such fixture double-counts in the
    mart — inflating event weight on exactly the days that matter most, where nobody would question a
    high number.

    PSEUDOCODE:  dict keyed on event_id, last write wins; watchlist sources are read second, so the
                 more specific record takes precedence
    """
    raise NotImplementedError("pseudocode")


def sports_silver_path(ingest_date: date) -> str:
    """``silver/sports_events/ingest_date=YYYY-MM-DD/events.parquet``

    Partitioned by **ingest** date, unlike sales which uses transaction date. An events pull is a
    snapshot of what the fixture list looked like that day, and fixtures move — so keeping snapshots
    intact lets staging pick the latest view of each event, rather than scattering one fixture's history
    across partitions as it gets rescheduled.
    """
    raise NotImplementedError("pseudocode")


def write_events_to_silver(storage: Any, records: Sequence[Dict[str, Any]], ingest_date: date):
    """Write canonical events to silver as Parquet, against SPORTS_SILVER_SCHEMA.

    Returns None and writes nothing for an empty batch: no object beats an empty one, which still has
    to be listed and opened by every query touching the partition.
    """
    raise NotImplementedError("pseudocode")
