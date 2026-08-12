-- Thin staging over the sales lake: rename, derive the one flag everything downstream needs,
-- and nothing else. Deliberately no filtering — a staging model that quietly drops rows makes
-- every count below it impossible to reconcile against the source.

select
    transaction_id,
    transaction_timestamp,
    transaction_date,
    store_id,

    -- Pseudonyms, never identifiers. Named to make that unmistakable at the call site.
    customer_pseudonym,
    loyalty_pseudonym,
    customer_postcode_district,

    product_sku,
    product_name,
    category,
    quantity,
    unit_price_gbp,
    line_total_gbp,
    channel,

    -- The single derived flag the whole mart turns on. Defined once here rather than repeated
    -- as `category = 'Pizza'` in four downstream models, which is how two of them eventually
    -- disagree.
    case when category = 'Pizza' then true else false end as is_pizza_line,

    -- Lineage carried all the way through, so a suspicious number in the mart can be traced
    -- to the file and run that produced it.
    source_file,
    run_id,
    ingested_at

from {{ source('lake', 'raw_sales') }}
