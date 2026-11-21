with base as (
    select count(*) as n
    from {{ ref('gold_hotspot_cell_day') }}
),
labeled as (
    select count(*) as n
    from {{ ref('gold_hotspot_cell_day_labeled') }}
)
select base.n as base_count, labeled.n as labeled_count
from base, labeled
where base.n != labeled.n
