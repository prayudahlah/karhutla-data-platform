-- Label 1 hanya sah bila ada hotspot kuat/sedang di sel-hari itu.
select *
from {{ ref('gold_hotspot_cell_day') }}
where label = 1
  and coalesce(audit_n_confirmed, 0) < 1
