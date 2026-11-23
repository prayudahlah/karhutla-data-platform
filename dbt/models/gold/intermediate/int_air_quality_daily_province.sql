{{ config(materialized='view', tags=['gold']) }}

{#- Kualitas udara harian per provinsi dari Silver. -#}

select
    cast(province as varchar) as province,
    cast(date as date) as date,
    round(avg(pm2_5), 3) as pm25_mean,
    round(max(pm2_5), 3) as pm25_max,
    round(avg(pm10), 3) as pm10_mean,
    round(avg(carbon_monoxide), 3) as co_mean,
    round(avg(nitrogen_dioxide), 3) as no2_mean,
    round(avg(sulphur_dioxide), 3) as so2_mean,
    round(avg(ozone), 3) as o3_mean,
    round(avg(aerosol_optical_depth), 3) as aod_mean,
    count(*) as aq_hours
from {{ ref('open_meteo_air_quality') }}
group by 1, 2
