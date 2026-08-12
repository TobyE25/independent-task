-- Pizza units must be non-negative, and the pizza subset cannot exceed the whole.
--
-- Two invariants in one test because they fail for the same reason — an aggregation or a join
-- that has started double-counting. A negative unit count means bad source data reached the
-- mart; pizza_baskets exceeding baskets means the distinct-count logic broke.
--
-- Worth noting these can actually fail. A `not_null` on a column that is never null is a test
-- that passes forever and proves nothing; both conditions here would fire on realistic bugs.

select
    store_id,
    date_day,
    pizza_units,
    pizza_baskets,
    baskets
from {{ ref('mart_pizza_demand_daily') }}
where pizza_units < 0
   or pizza_baskets > baskets
   or (pizza_units = 0 and pizza_baskets > 0)
