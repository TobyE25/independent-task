-- Staging over the events lake. Two jobs: deduplicate, and derive the kickoff hour.
--
-- Deduplication is load-bearing, not hygiene. The by-day sweep and the by-league watchlist
-- overlap by design, so a Premier League fixture can arrive twice. Counted twice, it would
-- double that date's event weight — inflating the forecast on exactly the days that matter
-- most. Keeping the most recently ingested copy also means a rescheduled fixture resolves to
-- its latest known date rather than both.

with ranked as (

    select
        *,
        row_number() over (
            partition by event_id
            order by ingested_at desc, source_name
        ) as recency_rank
    from {{ source('lake', 'raw_sports_events') }}

)

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

    -- Kept even though the mart is day-grain: it is the one intraday signal available, and
    -- an evening kickoff concentrates demand in the afternoon. Named as a known limitation in
    -- DECISIONS.md D7 rather than pretending day grain sees everything.
    extract(hour from kickoff_utc) as kickoff_hour,

    status,
    is_postponed,
    source_name,
    source_file,
    run_id,
    ingested_at

from ranked
where recency_rank = 1
