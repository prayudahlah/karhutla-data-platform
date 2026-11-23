-- cell_id ML harus memakai grid yang sama dengan cell_daily.
select *
from {{ ref('gold_hotspot_cell_day') }}
where cell_id not similar to '[0-9]{4}_[0-9]{4}'
