select
    tile,
    pixel_row,
    pixel_col,
    period
from {{ ref('mcd64a1_pixel_observation') }}
group by 1, 2, 3, 4
having count(*) > 1
