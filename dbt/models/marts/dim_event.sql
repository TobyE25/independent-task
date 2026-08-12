-- Event dimension. Postponed fixtures are kept, not filtered: they are real events that were
-- scheduled, and the fact that one was called off is information the Data Science team may want.
-- The relevance bridge is where they get excluded from driving demand, because that is a
-- modelling decision rather than a data-quality one.

select
    event_id,
    event_name,
    sport,
    league_id,
    league_name,
    season,
    home_team,
    away_team,
    venue,
    city,
    country,
    event_date,
    kickoff_utc,
    kickoff_hour,
    status,
    is_postponed
from {{ ref('stg_sports_events') }}
