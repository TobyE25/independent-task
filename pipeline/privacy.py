"""The privacy boundary: what happens to every personal field, applied at the first step.

A **declarative field policy** rather than logic spread through the loader. Same runtime behaviour as
scattered `del row["email"]` calls, but this version is a table someone can read and audit in one
sitting — which is the actual answer to "what do you do with personal data?".

Four actions, in decreasing order of preference: **DROP** (not holding data is the only guarantee;
access control is a promise), **GENERALISE**, **HASH**, **KEEP**.

Why HMAC and not a plain hash (DECISIONS.md D5): hashing a low-entropy identifier is not
pseudonymisation. An email or loyalty number has a small enough keyspace to brute-force, so
`SHA256(value)` is still personal data — the ICO is explicit about this. The **secret key** is what
makes the mapping infeasible to invert, and it lives in Secret Manager.

Everything here reduces risk; the mart's store x day grain eliminates it. This module protects the
intermediate layers where personal data briefly exists.

NOTE ON FORM: the policy below is LITERAL, not pseudocode. It is the data-protection design itself,
and docs/privacy.md generates its PII register from it. Function bodies are pseudocode.
"""

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Sequence, Tuple

DROP = "drop"
GENERALISE = "generalise"
HASH = "hash"
KEEP = "keep"

# 128 bits of a SHA-256 HMAC, hex encoded. A full digest doubles the storage of what becomes the most
# repeated value in the dataset, for no practical gain at retail scale.
PSEUDONYM_LENGTH = 32

# Strict on purpose: a loose pattern would let a full postcode through as an "outward code" and
# silently defeat the generalisation.
UK_POSTCODE_PATTERN = r"^\s*([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})\s*$"


class PrivacyError(RuntimeError):
    """The privacy layer cannot do its job. Always fatal, never retried."""


@dataclass(frozen=True)
class FieldPolicy:
    """What to do with one field, and why. ``note`` is the audit trail, not decoration."""

    field: str
    action: str
    note: str = ""
    generaliser: Optional[Callable[[Any], Any]] = None
    # Pseudonymised columns are renamed so nothing downstream — including a human reading a query
    # result — can mistake a pseudonym for the original identifier.
    rename_to: Optional[str] = None

    # Validated at construction: an unknown action, or GENERALISE with no generaliser, is rejected.
    # The latter matters most — the field would pass through unchanged while the policy table claimed
    # it was generalised, which is the worst possible failure for an audit artefact.


# =================================================================================================
# THIS TUPLE IS THE DATA PROTECTION DESIGN for the sales path: what arrives, what happens to it, why.
# =================================================================================================
SALES_FIELD_POLICY: Tuple[FieldPolicy, ...] = (
    FieldPolicy("transaction_id", KEEP, "Order reference. Not personal on its own."),
    FieldPolicy("transaction_timestamp", KEEP, "Needed for the date grain and kickoff-hour features."),
    FieldPolicy("store_id", KEEP, "Store, not person."),
    FieldPolicy(
        "customer_id", HASH,
        "Deterministic so repeat-purchase analysis survives; not reversible without the Secret "
        "Manager key.",
        rename_to="customer_pseudonym",
    ),
    FieldPolicy(
        "loyalty_id", HASH,
        "Same treatment. Kept separate because the two identifier spaces are distinct and conflating "
        "them would create false joins.",
        rename_to="loyalty_pseudonym",
    ),
    FieldPolicy(
        "customer_email", DROP,
        "Directly identifying and nothing downstream needs it. Exists only in the immutable raw "
        "file, which expires after 30 days.",
    ),
    FieldPolicy(
        "card_last4", DROP,
        "No analytical use, and retaining it would drag the lake towards PCI scope for no benefit.",
    ),
    FieldPolicy(
        "customer_postcode", GENERALISE,
        "Reduced to outward code for catchment analysis. Would be DROP if that work is dropped — "
        "minimisation is a standing review, not a one-off.",
        generaliser=None,  # postcode_to_district
        rename_to="customer_postcode_district",
    ),
    FieldPolicy("product_sku", KEEP, "Product, not person."),
    FieldPolicy("product_name", KEEP, "Product, not person."),
    FieldPolicy("category", KEEP, "Needed to identify pizza lines."),
    FieldPolicy("quantity", KEEP, "Measure."),
    FieldPolicy("unit_price_gbp", KEEP, "Measure."),
    FieldPolicy("line_total_gbp", KEEP, "Measure."),
    FieldPolicy("channel", KEEP, "Online or in-store. Not personal."),
)


def postcode_to_district(value: Optional[str]) -> Optional[str]:
    """Reduce a UK postcode to its outward code: "N1 9GU" -> "N1".

    A full postcode identifies roughly 15 households. The district is tens of thousands of people,
    which is what catchment analysis needs.

    PSEUDOCODE

        match UK_POSTCODE_PATTERN against value
        return group(1).upper() if it matches, else None
            # None rather than a best guess: a value that does not parse is more likely a
            # data-quality problem than a postcode worth salvaging, and guessing risks passing
            # something identifying straight through
    """
    raise NotImplementedError("pseudocode")


class Pseudonymiser:
    """Turns identifiers into stable, non-reversible pseudonyms."""

    def __init__(self, key: str, key_version: str = "v1") -> None:
        """PSEUDOCODE

            if not key: raise PrivacyError
                # Second line of defence after config.py. A default key would be WORSE than a crash:
                # the output would look entirely correct and be re-identifiable by anyone who guessed
                # the default.
        """
        raise NotImplementedError("pseudocode")

    def pseudonymise(self, value: Any) -> Optional[str]:
        """PSEUDOCODE

            if value is None or blank after stripping:
                return None
                # NOT a hash of "". That would mint a valid-looking pseudonym and silently merge
                # every anonymous transaction into one very busy fictional customer.

            return HMAC-SHA256(key, str(value).strip()).hexdigest()[:PSEUDONYM_LENGTH]
                # strip() so " CUST-1 " and "CUST-1" are the same customer
                # str() so an int from one source and a string from another do not diverge
        """
        raise NotImplementedError("pseudocode")


def apply_policy(
    row: Dict[str, Any],
    pseudonymiser: Pseudonymiser,
    policy: Sequence[FieldPolicy] = SALES_FIELD_POLICY,
    strict: bool = True,
) -> Dict[str, Any]:
    """Apply the field policy to one row, returning the row that may enter silver.

    ``strict`` (the default) means **unknown fields are dropped**. That direction is the whole point:
    if the platform adds `customer_phone` next quarter, an allow-list drops it silently while a
    deny-list would load it silently. The worst case of an upstream schema change should be a missing
    column somebody notices, not a breach nobody does.

    PSEUDOCODE

        unexpected = set(row) - {policy fields}
        if unexpected and strict:
            log WARNING naming them
            # dropping is already safe, but invisible dropping means a genuinely needed new column
            # goes missing without explanation

        for each policy entry:
            DROP        -> skip entirely
            field absent -> emit output_name = None
                            # emit the KEY anyway so the Parquet schema stays stable across files;
                            # a schema that varies per file breaks the external table
            KEEP        -> copy through
            HASH        -> pseudonymiser.pseudonymise(value), under the renamed column
            GENERALISE  -> generaliser(value), under the renamed column

        return the new row
    """
    raise NotImplementedError("pseudocode")


def policy_summary(policy: Sequence[FieldPolicy] = SALES_FIELD_POLICY) -> str:
    """Render the policy as a markdown table.

    Generated rather than hand-maintained, so the PII register in docs/privacy.md cannot drift from
    the code that enforces it. A privacy document that disagrees with the pipeline is worse than none.
    """
    raise NotImplementedError("pseudocode")
