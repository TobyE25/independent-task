"""Central configuration: the only module that touches ``os.environ``.

The pipeline should not know whether it is running on a laptop, in a Cloud Run Job or in CI — it asks
``load_settings()`` for an immutable object and gets on with it. One owner also means a
misconfiguration produces one clear error rather than an opaque 401 three modules deep.

Python >= 3.8 per the brief. Note 3.8 is end-of-life; in production I would run 3.11+.

NOTE ON FORM: bodies below are pseudocode. The declarative parts — constants, the Settings fields —
are literal, because those are design decisions rather than implementation detail.
"""

from dataclasses import dataclass
from typing import Optional

# --- Constants that do not vary by environment -------------------------------------------------

# TheSportsDB v1 free tier — a concrete stand-in for the brief's unnamed API (DECISIONS.md D2).
SPORTS_API_BASE_URL = "https://www.thesportsdb.com/api/v1/json"

# Free tier ceiling is ~30 req/min. We sit under it: going slowly costs nothing, a 429 storm costs
# the whole run.
DEFAULT_REQUESTS_PER_MINUTE = 20

# An upstream fact from the brief, not a tuning knob. The loader asserts against it rather than
# assuming it, and it is the constraint that makes in-memory Parquet buffering safe.
ECOMMERCE_EXPORT_ROW_CAP = 10_000

TARGET_LOCAL = "local"
TARGET_GCP = "gcp"


class ConfigError(RuntimeError):
    """Configuration is missing or contradictory. Always means a human must act, never "retry"."""


@dataclass(frozen=True)
class Settings:
    """Immutable snapshot of runtime configuration.

    Frozen: a mid-run change is never intentional, and a mutation in one task would be invisible in
    the next.
    """

    # local filesystem + DuckDB, or GCS + BigQuery. Everything branches on this one value.
    target: str
    data_dir: str

    # --- Sports events API ---
    sports_api_key: str
    sports_api_base_url: str = SPORTS_API_BASE_URL
    sports_requests_per_minute: int = DEFAULT_REQUESTS_PER_MINUTE
    http_timeout_seconds: float = 30.0
    http_max_retries: int = 4

    # --- Google Cloud (required only when target == "gcp") ---
    gcp_project: Optional[str] = None
    gcp_location: str = "europe-west2"      # London: UK retailer, UK data residency
    bucket_landing: Optional[str] = None    # where the ecommerce platform drops CSVs
    bucket_lake: Optional[str] = None       # bronze + silver
    bq_dataset: str = "pizza_perfect"

    # Never defaulted — see load_settings().
    pseudonym_key: str = ""
    # Stamped on every row so a key rotation is explainable rather than looking like the customer
    # base churned overnight.
    pseudonym_key_version: str = "v1"

    @property
    def is_gcp(self) -> bool:
        return self.target == TARGET_GCP


def load_settings(env: Optional[dict] = None) -> Settings:
    """Build Settings from the environment. ``env`` is injectable so tests need no real environment.

    PSEUDOCODE

        env = env or os.environ

        target = lower(env["TARGET"] or "local")
        if target not in ("local", "gcp"):
            raise ConfigError naming the valid values

        # The one secret with NO safe default. A fallback here would mean a misconfigured run
        # emitting predictable, re-identifiable pseudonyms that look entirely correct.
        # Fail closed instead.
        require env["PSEUDONYM_HMAC_KEY"], else raise ConfigError

        settings = Settings(... reading each field, with the defaults above ...)

        # Validate the GCP target EAGERLY. Discovering a missing bucket name after a rate-limited
        # API pull has already run is an expensive way to find out.
        if settings.is_gcp:
            require GCP_PROJECT, BUCKET_LANDING, BUCKET_LAKE

        return settings
    """
    raise NotImplementedError("pseudocode — see docstring")
