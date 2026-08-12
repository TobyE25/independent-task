-- The bridge: which events matter to which stores, and how much.
--
-- This model is where the design's central judgement lives, so it is worth being explicit about
-- what it does and does not claim.
--
-- The naive approach — join events to stores on geography — gets this backwards. The live data
-- makes the point better than an argument could: the Champions League tie in the sample is played
-- in Kazakhstan and the NFL game in Cincinnati, and both are broadcast to large UK audiences at
-- exactly the hours people buy pizza. Meanwhile a third-tier Argentinian fixture is
-- geographically irrelevant and commercially irrelevant. **Relevance follows broadcast reach,
-- not venue location.** That cannot be derived from the event feed; it is a business judgement,
-- which is why it comes from a reviewable seed (DECISIONS.md D8).
--
-- Two scopes:
--   national -- broadcast across the UK, so every store is affected. Optionally narrowed to one
--               nation, for competitions with a strong regional draw.
--   local    -- only stores in the matching nation.
--
-- Postponed fixtures are excluded here: a called-off match drives no demand, but it is still a
-- real event and stays in dim_event.

with events as (

    select * from {{ ref('stg_sports_events') }}
    where not is_postponed

),

rules as (

    select * from {{ ref('seed_event_relevance_rules') }}

),

stores as (

    select * from {{ ref('dim_store') }}

)

select
    events.event_id,
    events.event_date,
    events.league_name,
    events.event_name,
    events.kickoff_hour,
    stores.store_id,
    rules.scope,
    rules.weight,
    rules.rationale

from events
inner join rules
    on events.league_name = rules.league_name

-- The relevance rule itself. A national rule with no nation applies everywhere; a national rule
-- naming a nation, or a local rule, applies only to stores in that nation.
inner join stores
    on (
        (rules.scope = 'national' and (rules.applies_to_nation is null or rules.applies_to_nation = ''))
        or rules.applies_to_nation = stores.nation
    )
