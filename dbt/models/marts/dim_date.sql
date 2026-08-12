-- The date spine, built from the dates we actually hold data for: sales dates union event dates.
--
-- A production warehouse would use a full generated calendar (dbt_utils.date_spine, or a
-- GENERATE_DATE_ARRAY in BigQuery) so that dates with neither sales nor fixtures still appear.
-- Deriving it from the data instead is a deliberate simplification with one real benefit — it is
-- portable across DuckDB and BigQuery without dialect branching — and one real cost, noted here
-- rather than hidden: a day with no sales and no events is absent from the mart entirely.

with all_dates as (

    select distinct transaction_date as date_day from {{ ref('stg_sales') }}
    union
    select distinct event_date as date_day from {{ ref('stg_sports_events') }}

)

select
    date_day,
    extract(year from date_day) as year,
    extract(month from date_day) as month,
    extract(day from date_day) as day_of_month,

    -- ISO day of week: 1 = Monday .. 7 = Sunday. Spelled out because dow numbering is one of
    -- the great silent inconsistencies between SQL engines, and a mart column that means
    -- something different on BigQuery than on DuckDB is a bug waiting to happen.
    extract(isodow from date_day) as iso_day_of_week,
    case when extract(isodow from date_day) in (6, 7) then true else false end as is_weekend

from all_dates
