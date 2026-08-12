"""Schema contracts at the boundary, and the quarantine that makes them safe.

Policy, stated once (DECISIONS.md D17): **fail closed, quarantine, never drop silently.** The two
alternatives are both worse — dropping and logging a count means nobody notices 3% of records
vanishing, and failing the whole run means one upstream typo takes out the daily table for every
store. Quarantine keeps the data *and* the evidence, and makes the quarantine rate a monitorable
number: a steady 0.1% is upstream noise, a jump to 40% is a schema change that should page someone.

Raw payloads land in bronze unconditionally (D1). Validation gates bronze -> silver, where data enters
our model and our guarantees begin.

NOTE ON FORM: the canonical schema is LITERAL — it is the contract every dbt model depends on. Bodies
are pseudocode.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Sequence

# =================================================================================================
# THE CANONICAL EVENT. Provider-neutral on purpose: swapping sports feeds changes the normaliser below
# and nothing else, because every dbt model, test and mart column depends on THIS shape rather than on
# TheSportsDB's `strHomeTeam` spelling.
#
# This is specified as a pydantic BaseModel; the field list and the constraints are
# what matter to the design.
# =================================================================================================
SPORTS_EVENT_SCHEMA = {
    # required — the two things the forecast cannot do without
    "event_id":        "str, required, non-blank after stripping",
    "event_date":      "date, required, year between 1990 and 2100",

    # optional — permissive enough for the patchy metadata that is normal in sports data
    "event_name":      "Optional[str]",
    "sport":           "Optional[str]",
    "league_id":       "Optional[str]",
    "league_name":     "Optional[str]",   # joins the relevance rules
    "season":          "Optional[str]",
    "home_team":       "Optional[str]",
    "away_team":       "Optional[str]",
    "venue":           "Optional[str]",
    "city":            "Optional[str]",
    "country":         "Optional[str]",   # the VENUE, not the audience — see DECISIONS.md D8
    "kickoff_utc":     "Optional[datetime]",
    "status":          "Optional[str]",
    "is_postponed":    "bool, default False",

    # lineage, on every row from the start rather than added when something goes wrong. Turns
    # "this number looks off" into "it came from that file, in that run" — five minutes, not an
    # afternoon.
    "source_name":     "str, required",
    "source_file":     "Optional[str]",
    "run_id":          "Optional[str]",
    "ingested_at":     "datetime, default now(UTC)",
}

# Why event_id and event_date are the only required fields: a blank id passes a naive not-null check
# and then silently breaks every join it enters; a sentinel date like 0000-00-00 or 1970-01-01 would
# drag the date dimension across centuries and wreck any date-partitioned query. Everything else can
# be absent without poisoning anything.


@dataclass
class QuarantinedRecord:
    """A rejected record, with enough context to diagnose it."""

    reason: str
    source_name: str
    source_file: Optional[str] = None
    run_id: Optional[str] = None
    quarantined_at: Optional[datetime] = None
    record: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationOutcome:
    """What passed, what did not, and how bad that is."""

    valid: List[Dict[str, Any]] = field(default_factory=list)
    quarantined: List[QuarantinedRecord] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.valid) + len(self.quarantined)

    @property
    def quarantine_rate(self) -> float:
        """The number worth alerting on. Zero for an empty batch — a quiet day must not divide by 0."""
        raise NotImplementedError("pseudocode")


def normalise_sports_event(
    raw: Dict[str, Any],
    source_name: str,
    source_file: Optional[str] = None,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Map one provider event onto the canonical shape.

    **All provider-specific knowledge in the pipeline is concentrated here** — this is the single seam
    a different sports feed would be swapped at.

    PSEUDOCODE

        clean(value):
            None, "", whitespace, "null", "none", "n/a", "-"  ->  None
            # the API says "nothing" in six different ways; left alone those become six distinct
            # values in a GROUP BY, so "Emirates Stadium", "" and "null" report as three venues

        kickoff    = parse_iso(raw["strTimestamp"])          # tolerate a trailing Z
        event_date = parse_date(raw["dateEvent"]) or kickoff.date()
                     # the two fields are not always both populated, and losing the date loses the row

        is_postponed = clean(raw["strPostponed"]) == "yes"
                     # anything not explicitly "yes" counts as NOT postponed: assuming a fixture is
                     # off is the more damaging error, because it removes demand the stores will see

        return {canonical field: clean(provider field) for each mapping} + lineage
    """
    raise NotImplementedError("pseudocode")


def validate_records(
    records: Sequence[Dict[str, Any]],
    source_name: str = "unknown",
    source_file: Optional[str] = None,
    run_id: Optional[str] = None,
    raw_records: Optional[Sequence[Dict[str, Any]]] = None,
) -> ValidationOutcome:
    """Validate a batch, splitting it into loadable rows and quarantined ones.

    ``raw_records`` is the pre-normalisation payload, positionally aligned. When supplied **that** is
    what gets quarantined, because normalisation is lossy in exactly the cases that fail validation: an
    unparseable timestamp becomes None on the way through, so quarantining the normalised record keeps
    the *symptom* and discards the *evidence*. Whoever opens the file needs to see what the provider
    actually sent.

    (This was a real bug in the first version — the quarantine file showed `kickoff_utc: null` with no
    hint that the provider had sent `21/08/2026 19:00` in the wrong format.)

    PSEUDOCODE

        for each record:
            try validate against SPORTS_EVENT_SCHEMA
            on failure:
                evidence = raw_records[i] if aligned else the normalised record
                    # if the two lists ever drift out of step, attach NOTHING rather than the wrong
                    # evidence — sending someone to debug the wrong row is worse than no context
                append QuarantinedRecord(reason = the offending fields, record = stringify(evidence))
                    # stringify because the reason a record failed is often a value JSON cannot
                    # encode, and the quarantine write itself must not be able to fail
                continue
            append to valid

        if any quarantined: log WARNING with the rate
        return outcome
    """
    raise NotImplementedError("pseudocode")
