select
    product,
    product_version,
    tile,
    period,
    granule_identity
from {{ ref('mcd64a1_granule_inventory') }}
group by 1, 2, 3, 4, 5
having count(*) > 1
