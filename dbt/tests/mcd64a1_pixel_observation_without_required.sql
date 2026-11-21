select o.*
from {{ ref('mcd64a1_pixel_observation') }} o
left join {{ ref('mcd64a1_pixel_period_required') }} r
    on o.tile = r.tile
   and o.pixel_row = r.pixel_row
   and o.pixel_col = r.pixel_col
   and o.period = r.period
where r.tile is null
