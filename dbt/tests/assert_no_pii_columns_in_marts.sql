-- THE PII GUARD.
--
-- The submission claims the warehouse contains no personal data. This test is what makes that a
-- control rather than a sentence: it interrogates the warehouse's own catalogue and fails if any
-- column in any mart is one of the identifiers the privacy policy is supposed to remove.
--
-- It defends against the realistic failure, which is not someone deciding to load email
-- addresses. It is someone adding `select *` to a staging model, or relaxing one FieldPolicy
-- entry to KEEP, and nobody noticing for six months. Prose cannot catch that; CI can.
--
-- information_schema.columns is available on both DuckDB and BigQuery, so the same test runs
-- against both targets.

-- Note the parentheses. Without them, AND binds tighter than OR and the column filter would
-- apply only to the last table pattern — so the test would return every column of every mart and
-- fail permanently. A test that always fails gets disabled, which is how a guard quietly stops
-- guarding. Worth the two brackets and this comment.

select
    table_name,
    column_name
from information_schema.columns
where (
        lower(table_name) like 'mart%'
        or lower(table_name) like 'dim%'
        or lower(table_name) like 'fct%'
    )
    and lower(column_name) in (
        'customer_id',
        'customer_email',
        'email',
        'loyalty_id',
        'card_last4',
        'customer_postcode',
        'postcode',
        'customer_name',
        'customer_phone',
        'date_of_birth'
    )
