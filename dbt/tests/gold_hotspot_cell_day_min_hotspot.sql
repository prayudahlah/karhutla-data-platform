-- Sel-hari selalu berasal dari minimal satu deteksi hotspot.
select *
from {{ ref('gold_hotspot_cell_day') }}
where n_hotspot < 1
