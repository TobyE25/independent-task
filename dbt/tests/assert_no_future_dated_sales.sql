-- Sales cannot have happened tomorrow.
--
-- The failure this catches is a timezone or parsing bug pushing transactions into the future,
-- which is invisible in aggregate but poisons a forecast: the model trains on "actuals" for days
-- that have not occurred. Caught here rather than in the ingestion layer because it is a property
-- of the assembled dataset, and because a single mis-parsed file would otherwise pass every
-- row-level check.
--
-- Deliberately tests fct_sales_daily rather than the mart: the mart legitimately holds future
-- dates (event features with a null target), so asserting this on the mart would be wrong.

-- Compared against the pipeline's logical date, not current_date. The DAG passes its data
-- interval end; a manual run falls back to the wall clock. Without this, backfilling historical
-- data would fail a test that has nothing to do with the data's correctness, and CI results
-- would drift with the calendar.

{% set as_of = var('as_of_date') %}

select
    store_id,
    date_day,
    pizza_units
from {{ ref('fct_sales_daily') }}
where date_day > {% if as_of %}date '{{ as_of }}'{% else %}current_date{% endif %}
