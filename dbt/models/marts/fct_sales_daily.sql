-- Sales aggregated to store x day: the grain the stocking decision is made at (DECISIONS.md D7).
--
-- This is also where the last trace of personal data disappears. Line items carry a customer
-- pseudonym; this model aggregates them away, so nothing downstream — including the combined
-- table the Data Science team queries — contains personal data of any kind. Aggregation is the
-- strongest privacy control available, and here it is also exactly what the modelling task
-- needs.

select
    store_id,
    transaction_date as date_day,

    count(distinct transaction_id) as baskets,
    count(*) as line_items,

    sum(case when is_pizza_line then quantity else 0 end) as pizza_units,
    count(distinct case when is_pizza_line then transaction_id end) as pizza_baskets,
    sum(case when is_pizza_line then line_total_gbp else 0 end) as pizza_revenue_gbp,
    sum(line_total_gbp) as total_revenue_gbp,

    -- Distinct customers, from pseudonyms. Countable precisely because pseudonymisation is
    -- deterministic (DECISIONS.md D5) — a random token per row would make this meaningless,
    -- and dropping the identifier would make it impossible.
    count(distinct customer_pseudonym) as distinct_customers

from {{ ref('stg_sales') }}
group by 1, 2
