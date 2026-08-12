"""The test plan, as executable-shaped specification.

One file rather than seven, because with implementation presented as pseudocode these are a
**specification of what must be true** rather than a running suite. Each stub names the failure it
prevents — which is the whole methodology: a test whose purpose is not obvious is a test that gets
deleted during the next refactor.

The reference implementation (built and run before this was reduced to pseudocode) carries these as 129
real passing tests. See docs/testing.md for the methodology, the layers, and what is deliberately NOT
tested.

Why no mocking framework is needed anywhere below: every external dependency is injected — the clock
and sleep into the rate limiter, the HTTP session into the client, storage behind a protocol, the
BigQuery client into the warehouse.
"""


# =================================================================================================
# THROTTLING — against a FAKE CLOCK, so the suite runs in milliseconds and cannot be flaky on a
# loaded CI runner. Testing a rate limiter by actually waiting would take minutes.
# =================================================================================================

def test_first_request_does_not_wait():
    """The per-minute quota is untouched at the start, so making the first request wait is lost time."""


def test_rate_sets_the_spacing():
    """20/min (the shipped default) means one request every 3 seconds. Assert the sleep sequence."""


def test_idle_time_does_not_grant_unlimited_tokens():
    """GUARDS: without the cap in refill, a job that idled overnight wakes entitled to thousands of
    requests and blows the whole quota in one burst."""


def test_acquiring_more_than_capacity_fails_fast():
    """GUARDS: the loop could never terminate for a request the bucket cannot hold. Must raise, not
    hang a task until its timeout with no useful log."""


# =================================================================================================
# CREDENTIAL HANDLING — the API key is a URL path segment, so every log line is a leak risk.
# =================================================================================================

def test_redact_hides_the_api_key():
    """/json/SECRETKEY/x -> /json/***/x"""


def test_error_messages_never_contain_the_key():
    """GUARDS the realistic regression: someone "improves" an error message by interpolating the raw
    url, and the credential starts appearing on every failure."""


# =================================================================================================
# RETRIES
# =================================================================================================

def test_retries_429_then_succeeds():
    """Two calls, one delay."""


def test_backoff_grows_exponentially():
    """With jitter pinned, delays are base * 2**attempt: 1, 2, 4."""


def test_jitter_is_applied_to_the_whole_interval():
    """Full jitter, not exponential-plus-a-wobble. GUARDS: with many shards retrying at once,
    deterministic backoff synchronises them into a herd."""


def test_server_retry_after_overrides_our_backoff():
    """Honour the server; ignoring it is how a client gets banned."""


def test_an_absurd_retry_after_fails_instead_of_hanging():
    """"Come back in six hours" must fail loudly. GUARDS a task hung until timeout with no signal."""


def test_client_errors_fail_immediately_without_burning_quota():
    """401/404 fail identically every time. Retrying spends rationed requests and delays the error
    reaching whoever can fix the credential. Assert exactly ONE call was made."""


def test_html_served_with_a_200_is_a_hard_failure():
    """GUARDS the worst silent failure available: a maintenance page read as "no events today" would
    zero out a day of the forecast."""


def test_every_attempt_asks_the_limiter_first():
    """Including retries — a retry that skipped the limiter is the request most likely to trip the
    quota, since the server is already unhappy."""


# =================================================================================================
# PAGING — the ONLY thing standing behind this code, since the free API returns a single payload.
# =================================================================================================

def test_null_envelope_yields_no_pages():
    """The API sends {"events": null}, not []. Must yield ZERO pages, not one page of nothing."""


def test_page_and_offset_styles_advance_correctly_and_stop_on_a_short_page():
    """A short page means the last page. Saves one wasted request per pull."""


def test_max_pages_caps_a_runaway_endpoint_and_warns():
    """GUARDS an endpoint that ignores our paging parameters: it would consume the entire quota then
    the task timeout. The warning matters because a silent cap looks identical to "that is all the
    data"."""


def test_pages_are_yielded_lazily():
    """Nothing fetched before the first next(). GUARDS the memory property: the caller writes each page
    before the next is requested."""


# =================================================================================================
# PRIVACY — the enforcement mechanism for the claims in docs/privacy.md. A privacy design in prose is
# an intention; one with tests that fail when it breaks is a control.
# =================================================================================================

def test_refuses_to_operate_without_a_key():
    """GUARDS the worst possible default: predictable, re-identifiable pseudonyms that look correct."""


def test_pseudonyms_are_deterministic():
    """The whole reason for HMAC over dropping the identifier — repeat-purchase analysis needs the same
    customer to map to the same pseudonym across files and days."""


def test_a_different_key_gives_a_different_pseudonym():
    """Proves the key is LOAD-BEARING. If it made no difference we would be doing a plain hash and
    calling it pseudonymisation."""


def test_empty_identifiers_become_none_not_a_pseudonym():
    """GUARDS: hashing "" mints a valid-looking pseudonym that merges every anonymous transaction into
    one very busy fictional customer."""


def test_postcode_reduces_to_district_and_a_full_postcode_never_survives():
    """"N1 9GU" -> "N1". GUARDS a loose pattern letting the whole postcode through as an "outward
    code", silently defeating the generalisation."""


def test_unknown_fields_are_dropped_by_default_and_logged():
    """The allow-list direction. GUARDS: if the platform adds customer_phone next quarter, a deny-list
    would load it silently. The worst case must be a missing column somebody notices."""


def test_generalise_without_a_generaliser_is_rejected_at_construction():
    """GUARDS the worst failure for an audit artefact: the field passes through unchanged while the
    policy table claims it was generalised."""


def test_no_personal_value_survives_the_boundary():
    """**THE HEADLINE TEST.** Given a row with known personal values, none appears anywhere in the
    output — not as a key, a value, or embedded in a string.

    Written as a PROPERTY rather than field-by-field on purpose: a field-by-field assertion passes
    happily when a NEW PII field is added upstream. This fails."""


def test_the_property_test_would_actually_fail_if_the_policy_regressed():
    """A test that cannot fail is worse than no test. Deliberately weakens the policy and asserts the
    leak IS detected."""


# =================================================================================================
# VALIDATION AND QUARANTINE — fail closed, never drop, never fatal.
# =================================================================================================

def test_malformed_rows_are_quarantined_with_a_specific_reason():
    """Parametrised over the mundane failures real upstream systems produce: blank store_id, blank
    transaction_id, negative quantity, unparseable date, non-numeric money, missing SKU. Each must NAME
    the offending field, or triage becomes guesswork."""


def test_one_bad_row_does_not_cost_the_good_ones():
    """3 rows in, 1 bad: 2 loaded, 1 quarantined, rate = 1/3."""


def test_implausible_dates_are_quarantined():
    """GUARDS sentinel dates (0000-00-00, 1970-01-01) arriving as real fixtures and dragging the date
    dimension across centuries."""


def test_quarantine_prefers_the_raw_payload_over_the_normalised_one():
    """**A REAL BUG THIS CAUGHT.** Normalisation is lossy exactly where validation fails — an
    unparseable timestamp becomes None — so quarantining the normalised record kept the SYMPTOM and
    discarded the EVIDENCE. Whoever opened the file saw `kickoff_utc: null` with no hint the provider
    had sent `21/08/2026 19:00`."""


def test_quarantined_sales_rows_contain_no_personal_data():
    """**The subtle inversion.** The sports path quarantines the RAW payload as evidence; the sales path
    must NOT, because the raw sales row is full of PII and a quarantine file is still data at rest.
    GUARDS a refactor "making the two paths consistent" that would start writing emails to disk."""


def test_quarantined_rows_are_still_diagnosable():
    """Removing PII must not remove the ability to work out what went wrong."""


# =================================================================================================
# THE SALES LOADER
# =================================================================================================

def test_output_matches_the_declared_schema():
    """GUARDS inference letting a column be int64 in one file and string in the next, which breaks the
    external table over the partition."""


def test_money_is_decimal_not_float():
    """0.1 + 0.2 != 0.3. Revenue feeding a forecast must not accumulate unexplainable error."""


def test_transaction_date_is_derived_from_the_timestamp():
    """GUARDS a partition key disagreeing with the timestamp, so a query filtered on date silently
    misses rows."""


def test_rows_are_grouped_by_date_not_assumed():
    """A file straddling midnight lands in BOTH partitions rather than whichever date we guessed."""


def test_exceeding_the_export_cap_is_warned_about():
    """The platform promises 10,000 rows. More means the promise changed — and in-memory Parquet
    buffering depends on it."""


def test_reprocessing_the_same_file_is_idempotent():
    """Run three times: one output object, one row. The property that matters for any retried task."""


# =================================================================================================
# THE SPORTS ENGINE
# =================================================================================================

def test_request_count_is_knowable_before_spending_the_quota():
    """5 days x 1 sport + 6 watchlist leagues == 11."""


def test_the_two_sources_fan_out_differently():
    """The point of the registry: one over a date window, one over a watchlist, and the engine does not
    know the difference."""


def test_empty_responses_land_no_file_but_are_counted():
    """Most sports have no fixtures most days — normal. But ALL-empty across a window means a broken
    query, so the count must be visible."""


def test_one_source_failing_does_not_stop_the_others():
    """A fixture list is still useful without a UFC card. The failure is REPORTED, not swallowed."""


def test_duplicate_events_across_sources_are_collapsed():
    """The two sources overlap by design. Uncollapsed, a fixture double-counts and inflates event weight
    on exactly the days that matter most — where nobody would question a high number."""


def test_shards_cover_every_export_exactly_once():
    """paths[i::N] for all i must partition the list. GUARDS silent data loss or double-processing when
    the shard count changes."""


# =================================================================================================
# THE WAREHOUSE BOUNDARY
# =================================================================================================

def test_registration_creates_a_view_not_a_copy():
    """The lakehouse property (D4): one copy of the bytes in an open format. A table would mean a second
    copy, and a re-run of ingestion invisible until reload."""


def test_hive_partition_becomes_a_real_prunable_column():
    """The cheapest performance decision available."""


def test_a_missing_source_degrades_to_empty_rather_than_failing():
    """One missing partition must not block the whole dbt project from parsing and building."""
