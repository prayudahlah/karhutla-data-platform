-- Kunci Gold: satu baris per sel per tanggal.
select
    cell_id,
    date
from {{ ref('gold_hotspot_cell_day') }}
group by cell_id, date
having count(*) > 1
