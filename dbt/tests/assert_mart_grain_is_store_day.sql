-- The mart's grain must be exactly one row per store per day.
--
-- The most damaging failure mode this design has: if the event bridge were joined without being
-- collapsed to store x day first, a date with three relevant fixtures would produce three rows
-- for that store, and every sales measure on it would be counted three times. The forecast would
-- be inflated precisely on the days the business cares most about — which is also the day nobody
-- would question a high number.
--
-- This is the same class of bug as a fan-out in any star schema, and it is worth a dedicated test
-- rather than relying on a unique test over a surrogate key that may not exist.

select
    store_id,
    date_day,
    count(*) as row_count
from {{ ref('mart_pizza_demand_daily') }}
group by 1, 2
having count(*) > 1
