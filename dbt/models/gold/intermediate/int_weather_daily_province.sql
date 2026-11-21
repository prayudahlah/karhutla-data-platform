{{ config(materialized='view', tags=['gold']) }}

{#- Cuaca harian per provinsi dari Silver (grain Silver: provinsi x kota x jam).
    weather_hours dipakai sebagai penanda kelengkapan: satu hari idealnya 24 jam. -#}

select
    cast(province as varchar) as province,
    cast(date as date) as date,
    round(avg(temperature_2m), 3) as temp_mean,
    round(max(temperature_2m), 3) as temp_max,
    round(avg(relative_humidity_2m), 3) as rh_mean,
    round(min(relative_humidity_2m), 3) as rh_min,
    round(sum(cast(precipitation as decimal(18, 3))), 3) as precip_sum,
    round(max(wind_speed_10m), 3) as wind_speed_max,
    round(max(vapour_pressure_deficit), 3) as vpd_max,
    round(avg(soil_moisture_0_to_7cm), 3) as soil_moisture_mean,
    round(sum(cast(et0_fao_evapotranspiration as decimal(18, 3))), 3) as et0_sum,
    count(*) as weather_hours
from {{ ref('open_meteo_weather') }}
group by 1, 2
