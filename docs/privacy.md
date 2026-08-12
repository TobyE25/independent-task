# Privacy and GDPR

The PII register, the legal reasoning, and what happens when someone asks to be erased.

The design in one line: **minimise at the boundary, pseudonymise what must survive, and let the grain
finish the job.** By the time data reaches the table the Data Science team queries, there is no
personal data left at all.

---

## 1. PII register

Generated from `pipeline/privacy.py` — the code that enforces it — so this table cannot drift from
what actually runs. Regenerate with:

```bash
python -c "from pipeline.privacy import policy_summary; print(policy_summary())"
```

| Source field | Action | Silver column | Rationale |
|---|---|---|---|
| `transaction_id` | KEEP | `transaction_id` | Order reference. Not personal on its own. |
| `transaction_timestamp` | KEEP | `transaction_timestamp` | Needed for the date grain and kickoff-hour features. |
| `store_id` | KEEP | `store_id` | Store, not person. |
| `customer_id` | HASH | `customer_pseudonym` | Deterministic so repeat-purchase analysis survives; not reversible without the Secret Manager key. |
| `loyalty_id` | HASH | `loyalty_pseudonym` | Same treatment. Kept separate because the two identifier spaces are distinct and conflating them would create false joins. |
| `customer_email` | DROP | — | Directly identifying and nothing downstream needs it. Exists only in the immutable raw file, which expires after 30 days. |
| `card_last4` | DROP | — | No analytical use, and retaining it would drag the lake towards PCI scope for no benefit. |
| `customer_postcode` | GENERALISE | `customer_postcode_district` | Reduced to outward code for catchment analysis. Would be DROP if that work is dropped — minimisation is a standing review, not a one-off. |
| `product_sku` | KEEP | `product_sku` | Product, not person. |
| `product_name` | KEEP | `product_name` | Product, not person. |
| `category` | KEEP | `category` | Needed to identify pizza lines. |
| `quantity` | KEEP | `quantity` | Measure. |
| `unit_price_gbp` | KEEP | `unit_price_gbp` | Measure. |
| `line_total_gbp` | KEEP | `line_total_gbp` | Measure. |
| `channel` | KEEP | `channel` | Online or in-store. Not personal. |

**It is an allow-list, not a deny-list.** Any column not listed above is dropped and logged. If the
ecommerce platform adds `customer_phone` next quarter, the worst case is a missing column somebody
notices — not personal data loaded because nobody thought to forbid it.

---

## 2. Where personal data exists, and for how long

| Zone | Contents | Retention | Access |
|---|---|---|---|
| 🔴 Landing bucket | CSV as delivered: email, card last-4, full postcode | Managed by the ecommerce platform | Pipeline SA: read-only. No delete. |
| 🔴 Bronze | Raw API payloads (no customer PII — events only) | **30 days, lifecycle rule** | Pipeline SA + break-glass group |
| 🟡 Silver | Pseudonyms + postcode district | Indefinite | Pipeline SA, dbt SA |
| 🟢 Marts | Aggregate only. **No personal data.** | Indefinite | Analytics, Data Science |
| Quarantine | Rejected rows, **post-pseudonymisation** | 30 days | Data Engineering |

The 30-day expiry on bronze is a **storage-limitation control** (Art. 5(1)(e)), not housekeeping. It
is also what keeps an erasure request confined to a single zone.

---

## 3. Lawful basis and principles

Not a legal opinion — this is the engineering side of a conversation that needs the DPO. But the
pipeline is built so that conversation is short:

| Principle | How the pipeline satisfies it |
|---|---|
| **Minimisation** — Art. 5(1)(c) | Email, card last-4 and full postcode dropped at the first processing step. The mart is aggregate, so it holds no personal data at all. |
| **Storage limitation** — Art. 5(1)(e) | 30-day lifecycle deletion on raw. Pseudonymised silver and aggregate marts are outside the scope of the retention question. |
| **Integrity and confidentiality** — Art. 5(1)(f) | Per-job service accounts, least privilege, no delete permission, Secret Manager, uniform bucket-level access, public access prevention, in-region storage. |
| **Purpose limitation** — Art. 5(1)(b) | The stated purpose is demand forecasting. The mart's grain makes customer-level use physically impossible rather than merely prohibited. |
| **Accuracy** — Art. 5(1)(d) | Fail-closed validation; invalid records quarantined with the reason rather than silently loaded. |

### Is a pseudonym still personal data?

Yes, while the key exists — and treating it otherwise is the mistake worth avoiding. HMAC-SHA256 with
a Secret Manager key means the mapping is infeasible to invert *without the key*, so silver is
pseudonymised data under Art. 4(5) rather than anonymous data. It stays in scope, it is access
controlled, and it is covered by the DSAR process below.

The **marts** are different: aggregated to store × day across thousands of customers, with no
identifier and no realistic route to singling anyone out. That is where the data stops being personal.

### Why not a plain hash?

Because `SHA256(email)` is not pseudonymisation in any meaningful sense. Email addresses and loyalty
numbers have a small enough keyspace that anyone holding the digest can recover the input by brute
force or a rainbow table — the ICO is explicit that such a hash remains personal data. The **secret
key** is the control; the hash function is just plumbing.

---

## 4. Erasure and subject access — the runbook

The design makes this cheap, which is the practical payoff of minimising early.

**A subject access request (Art. 15):**

1. Compute the pseudonym: `HMAC-SHA256(customer_id, key)` using the current key version.
2. Query silver for rows carrying that pseudonym. This returns their purchase history at line-item
   level.
3. Note that identifying *which* customer a pseudonym belongs to requires the original `customer_id`
   from the ecommerce platform — the pipeline holds no route from pseudonym back to person.

**An erasure request (Art. 17):**

1. **The marts need no action.** They are aggregate; there is nothing to erase and nothing that
   identifies the individual.
2. **Landing and bronze** are handled by retention: whatever has not already expired does so within
   30 days. If immediate deletion is required, delete the objects for the relevant dates — they are
   replayable from the platform if genuinely needed.
3. **Silver** rows for that pseudonym are deleted, and the affected date partitions rebuilt. Silver
   paths are deterministic, so a rebuild is idempotent.
4. **Aggregates are not recomputed.** A store-day pizza count that included one erased customer's
   basket is not personal data, and rewriting history to remove a single unit would corrupt the
   forecast for no privacy gain. This is a defensible position, but it is a position — worth
   confirming with the DPO rather than assuming.

**Key rotation.** Rotating the HMAC key changes every pseudonym, so history stops joining to new
data. That is the accepted cost, which is why `pseudonym_key_version` is stamped on every row: a
rotation is then explainable rather than looking like the entire customer base churned overnight. A
rotation needs a planned re-pseudonymisation of retained silver, or an accepted discontinuity.

---

## 5. The controls that are tested, not just described

This is the part that matters. A privacy design in prose is an intention; one with tests that fail
when it breaks is a control.

| Control | Test |
|---|---|
| No PII column in any mart | `dbt/tests/assert_no_pii_columns_in_marts.sql` — queries `information_schema`, fails on any known identifier |
| No personal **value** anywhere in output | `tests/test_privacy.py::test_no_personal_value_survives_the_boundary` — a property test, so a *new* PII field still fails |
| That test can actually fail | `test_the_property_test_would_actually_fail_if_the_policy_regressed` — deliberately weakens the policy and asserts the leak is caught |
| Pseudonyms are not reversible by guessing | `test_a_different_key_gives_a_different_pseudonym` — proves the key is load-bearing, not decorative |
| Pseudonyms are stable across files and runs | `test_pseudonymisation_is_stable_across_separate_runs` |
| A full postcode never survives | `test_a_full_postcode_never_survives_generalisation` |
| Quarantine holds no PII | `tests/test_sales.py::test_quarantined_sales_rows_contain_no_personal_data` |
| Unknown columns are dropped | `test_unknown_fields_are_dropped_by_default` |
| The pipeline refuses to run unkeyed | `test_refuses_to_operate_without_a_key` |

The quarantine test guards a subtle inversion: the **sports** path deliberately quarantines the raw
payload as evidence, while the **sales** path must not, because the raw sales row is full of PII and a
quarantine file is still data at rest. A well-intentioned refactor "making the two paths consistent"
would silently start writing email addresses to disk.

---

## 6. Open questions for the DPO

Flagged rather than guessed:

1. **Retaining aggregates that included erased customers** (§4 step 4) — my position is that it is
   not personal data and rewriting it would damage the forecast for no benefit. Needs confirming.
2. **Whether the postcode district is needed at all.** It is retained for catchment analysis. If
   nothing uses it, it should be `DROP` — minimisation is a standing review, not a one-off.
3. **Whether 30 days is the right raw retention.** Long enough to replay and debug, short enough to
   limit exposure. The number is a judgement.
4. **Lawful basis for the ecommerce feed itself** — legitimate interest for demand forecasting seems
   straightforward, but it is the platform's privacy notice that has to cover it, not mine.
