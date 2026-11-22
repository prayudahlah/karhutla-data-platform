select *
from (describe select * from {{ ref('gold_hotspot_cell_day_labeled') }})
where column_name = 'audit_tier_max_1'
