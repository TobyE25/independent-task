-- The store estate, from the seed. A dimension with no surrogate key: store_id is a stable
-- business key the source system already guarantees, and inventing a surrogate for it would add
-- a join for no benefit.

select
    store_id,
    store_name,
    city,
    region,
    nation,
    postcode_district
from {{ ref('seed_stores') }}
