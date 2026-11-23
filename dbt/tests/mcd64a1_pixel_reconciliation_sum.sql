with required as (
    select count(*) as n
    from {{ ref('mcd64a1_pixel_period_required') }}
),
reconciled as (
    select count(*) as n
    from {{ ref('mcd64a1_pixel_period_reconciliation') }}
)
select required.n as required_count, reconciled.n as reconciled_count
from required, reconciled
where required.n != reconciled.n
