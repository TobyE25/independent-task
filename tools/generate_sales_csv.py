"""Generate synthetic daily sales exports, shaped like the real ecommerce feed.

**Why this exists.** No supermarket transaction data is publicly available, so the sales side of this
brief has to be synthesised. That is inherent to the exercise rather than a shortcut — and it means the
generator's job is to reproduce the *engineering* problem faithfully:

  * **The 10,000-row export cap.** The platform truncates every file at 10,000 rows, so a day arrives
    as MANY files, not one. That single constraint is what makes file count the real scaling pressure
    (DECISIONS.md D10), and it must be reproduced exactly. That is 31 files/day at the brief's current
    100,000 transactions, an estimated ~304 at the 1M forecast.
  * **Realistic PII** — email, loyalty id, full postcode, card last-4 — so the privacy layer has
    something genuine to strip. A generator emitting only clean columns would let the privacy design go
    untested.
  * **Optional malformed rows** (``--dirty-rate``) so the quarantine path is exercised by data rather
    than only by tests.

**On the sports uplift — read this before quoting any correlation.**

The generator can boost pizza demand on days with a relevant fixture. That makes the downstream mart
*show* a sports-driven uplift, which proves nothing whatsoever about the world: the correlation is there
because it was put there. It exists so the Data Science team receives a dataset with signal to model
rather than pure noise.

To keep that honest rather than hidden, every run writes a **ground-truth manifest** recording exactly
which uplift was applied to which date. Two consequences worth stating:

  1. Any lift the mart shows is an INPUT, not a finding. Validating a real relationship needs real
     transaction data, and that is the Data Science team's job, not this pipeline's.
  2. Because the uplift is aligned to the REAL fixture dates, it doubles as a **correctness assertion**:
     the mart should show elevated demand on exactly those dates and no others. If it does, the
     relevance join and the date alignment are right.

NOTE ON FORM: pseudocode, like the rest of `pipeline/`.

    python tools/generate_sales_csv.py --start 2026-08-01 --end 2026-08-14 \
        --transactions-per-day 100000 --out-dir data/landing --uplift-json data/uplift.json
"""

from typing import Dict, List, Optional, Sequence

EXPORT_ROW_CAP = 10_000

# The export's columns, as the ecommerce platform delivers them. This list IS the input contract that
# pipeline/privacy.py's field policy must cover — a test asserts the two agree, because if they drift
# the policy silently drops a column.
CSV_COLUMNS = [
    "transaction_id", "transaction_timestamp", "store_id",
    "customer_id", "customer_email", "loyalty_id", "card_last4", "customer_postcode",
    "product_sku", "product_name", "category",
    "quantity", "unit_price_gbp", "line_total_gbp", "channel",
]

# Twelve fictional stores across the four UK nations, so the national-vs-local relevance rules have
# something to bite on. Mirrors dbt/seeds/seed_stores.csv.
STORES = "STO-001 .. STO-012, spanning London, North West, West Midlands, Yorkshire, North East, " \
         "South West, Scotland, Wales, Northern Ireland — with per-store weights, because a chain's " \
         "stores differ in throughput and a uniform split would produce a suspiciously flat dataset"


def generate(
    start: str,
    end: str,
    transactions_per_day: int = 100_000,
    out_dir: str = "data/landing",
    seed: int = 42,
    row_cap: int = EXPORT_ROW_CAP,
    dirty_rate: float = 0.0,
    uplift_by_date: Optional[Dict[str, float]] = None,
) -> List[str]:
    """PSEUDOCODE

        rng = Random(seed)          # seeded, so "run this exact command and you get my numbers" holds

        for each day in start..end:
            for each of transactions_per_day baskets:

                store    = weighted choice of STORES
                customer = drawn from a FIXED POOL of 50,000
                           # a pool, not a fresh customer per transaction, so repeat purchasers exist —
                           # otherwise deterministic pseudonymisation would have nothing to demonstrate

                pizza_chance = base 0.16
                             + 0.06 if weekend, + 0.04 if Friday      # a real, uncontroversial retail
                                                                      # pattern, so the day-of-week
                                                                      # features are not vacuous
                pizza_chance *= (1 + uplift_by_date.get(day, 0))

                if rng < pizza_chance:  add 1-2 lines from PIZZA_PRODUCTS

                add 1-5 filler lines from OTHER_PRODUCTS
                    # ***NOT from all products.*** Drawing filler from a pool that INCLUDED pizza would
                    # put pizza into ~37% of filler lines — a second path into the basket that the
                    # uplift never touches. That dilutes a 21-54% injected uplift to low single digits
                    # and pushes the attach rate to an implausible 1.5 per basket, while every test
                    # still passes. Only looking at the numbers catches it.

                kickoff-aware purchase hour on event days (people buy before an evening kickoff), so
                the earliest_kickoff_hour feature is not meaningless

                if rng < dirty_rate: corrupt one row — blank store, negative quantity, unparseable
                                     date, non-numeric price, blank transaction id

            write rows to sales_<date>_part-NNN.csv, starting a NEW FILE every row_cap rows

        write _ground_truth.json: seed, uplift_by_date, uplift_source, row counts, and an explicit note
                                  that the uplift is an INPUT and says nothing about real behaviour

        return the file paths
    """
    raise NotImplementedError("pseudocode")
