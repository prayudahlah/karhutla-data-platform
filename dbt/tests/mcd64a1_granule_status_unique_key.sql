select
    tile,
    period
from {{ ref('mcd64a1_granule_status') }}
group by 1, 2
having count(*) > 1
