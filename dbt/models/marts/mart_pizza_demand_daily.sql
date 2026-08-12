-- ============================================================================================
-- THE COMBINED TABLE. This is the deliverable the brief asks for: one wide, denormalised,
-- model-ready table per store per day, combining transactions with upcoming sporting events.
-- ============================================================================================
--
-- Grain: one row per (store_id, date_day). That is the grain of the decision being made — how
-- many pizzas this store needs on this day (DECISIONS.md D7).
--
-- Built on a full store x date spine rather than on the sales data, and that choice is the
-- important one. A forecasting feature table needs rows for days that have **not happened yet**:
-- future dates carry event features with a null target, which is precisely what the Data Science
-- team predicts into. Driving off sales alone would silently drop every future date and leave
-- them with a training set and nothing to score.
--
-- So `pizza_units` is null for future dates by design, not by accident. `has_sales_data` makes
-- that explicit rather than leaving a modeller to infer it.
--
-- Contains no personal data. The grain guarantees it — see fct_sales_daily.

with spine as (

    -- Every store, every date we hold data for. The cross join is intentional: absent days must
    -- appear as zero-demand rows, because "no sales recorded" and "no row" mean different things
    -- to a model and only one of them is true.
    select
        dim_store.store_id,
        dim_date.date_day
    from {{ ref('dim_store') }} as dim_store
    cross join {{ ref('dim_date') }} as dim_date

),

sales as (

    select * from {{ ref('fct_sales_daily') }}

),

event_features as (

    -- Collapse the bridge to store x day. One row per store-day however many fixtures fall on
    -- it, which is what keeps the join to the spine one-to-one.
    select
        store_id,
        event_date,
        count(*) as relevant_event_count,
        max(weight) as max_event_weight,
        sum(weight) as total_event_weight,
        max(case when scope = 'national' then 1 else 0 end) = 1 as has_national_broadcast_event,
        min(kickoff_hour) as earliest_kickoff_hour,
        max(kickoff_hour) as latest_kickoff_hour
    from {{ ref('event_store_relevance') }}
    group by 1, 2

)

select
    -- --- keys -------------------------------------------------------------------------------
    spine.store_id,
    spine.date_day,

    -- --- store attributes, denormalised in so the DS team needs no joins -------------------
    dim_store.store_name,
    dim_store.city,
    dim_store.region,
    dim_store.nation,

    -- --- calendar features ------------------------------------------------------------------
    dim_date.iso_day_of_week,
    dim_date.is_weekend,
    dim_date.month,

    -- --- event features ---------------------------------------------------------------------
    coalesce(event_features.relevant_event_count, 0) as relevant_event_count,
    coalesce(event_features.max_event_weight, 0) as max_event_weight,
    coalesce(event_features.total_event_weight, 0) as total_event_weight,
    coalesce(event_features.has_national_broadcast_event, false) as has_national_broadcast_event,
    event_features.earliest_kickoff_hour,
    event_features.latest_kickoff_hour,

    -- --- the target and its supporting measures ---------------------------------------------
    -- Null, not zero, where no sales exist: a future date has unknown demand, and coalescing it
    -- to zero would teach a model that every future day sells nothing.
    sales.pizza_units,
    sales.pizza_baskets,
    sales.pizza_revenue_gbp,
    sales.baskets,
    sales.total_revenue_gbp,
    sales.distinct_customers,

    case
        when sales.store_id is not null then true
        else false
    end as has_sales_data

from spine
left join sales
    on spine.store_id = sales.store_id
    and spine.date_day = sales.date_day
left join event_features
    on spine.store_id = event_features.store_id
    and spine.date_day = event_features.event_date
inner join {{ ref('dim_store') }} as dim_store
    on spine.store_id = dim_store.store_id
inner join {{ ref('dim_date') }} as dim_date
    on spine.date_day = dim_date.date_day
