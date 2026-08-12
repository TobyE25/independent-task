"""Pizza Perfect — sports-event-driven demand pipeline for Sprouts.

Each module owns one concern, and **nothing here imports an orchestrator**: Cloud Workflows and Cloud
Run call into `cli.py`, never the reverse (DECISIONS.md D14). That is what lets the suite run in seconds
with no scheduler, and what makes Cloud Run Jobs a real alternative to Composer.

Implementation is presented as pseudocode; the declarative parts — the field policy, the schemas, the
source registry — are literal, because those are design decisions rather than implementation detail.

    config.py       reads the environment; the only module touching os.environ
    http_client.py  throttling, retries, and paging against a rate-limited API
    validation.py   schema contracts at the boundary; invalid rows are quarantined
    privacy.py      the field policy: drop / hash / generalise, applied before silver
    storage.py      the cloud boundary: local filesystem or GCS
    warehouse.py    the warehouse boundary: DuckDB or BigQuery/BigLake
    sports.py       the sports source registry and its ingestion engine
    sales.py        the CSV -> Parquet ingestion job
    cli.py          entrypoints, called by the Cloud Run Jobs that Workflows sequences
"""

__version__ = "0.1.0"
