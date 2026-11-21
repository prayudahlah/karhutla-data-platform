select cell_id, date
from {{ ref('gold_hotspot_cell_day_labeled') }}
group by 1, 2
having count(*) > 1
