select
    province,
    city,
    ts_utc,
    count(*) as row_count
from {{ ref('open_meteo_weather') }}
group by 1, 2, 3
having count(*) > 1
