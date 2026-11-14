select
    province,
    city,
    cast(ts_local as date) as local_date,
    count(*) as row_count
from {{ ref('open_meteo_air_quality') }}
group by 1, 2, 3
having count(*) <> 24
