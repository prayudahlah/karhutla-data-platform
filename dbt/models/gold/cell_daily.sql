{{
    config(
        materialized='external',
        format='parquet',
        location=var('gold_publish_root') ~ '/cell_daily',
        options={'partition_by': 'date', 'overwrite': 'true'}
    )
}}

{#-
    Gold: satu baris per sel 0,25 derajat per hari.

    Grain   : (cell_id, date)
    Kunci   : cell_id + date
    Fitur   : agregat hotspot, scar, cuaca, dan kualitas udara HARI ITU.
    Label   : label_risk dari hotspot tier kuat/sedang pada D..D+2.
    Catatan : fitur model di src/ml/features.py memakai jendela D-7..D-1,
              sehingga tidak ada kolom di sini yang bocor dari masa depan.
-#}

with universe as (

    select *
    from {{ ref('int_cell_daily_universe') }}

),

grid as (

    select *
    from {{ ref('int_grid_cell') }}

),

hotspot as (

    select *
    from {{ ref('int_hotspot_cell_daily') }}

),

weather as (

    select *
    from {{ ref('int_weather_daily_province') }}

),

air_quality as (

    select *
    from {{ ref('int_air_quality_daily_province') }}

),

scar as (

    select *
    from {{ ref('int_scar_cell_daily') }}

)

select
    universe.cell_id,
    universe.date,
    grid.cell_lat,
    grid.cell_lon,
    grid.province,
    grid.island,
    grid.distance_km,

    cast(coalesce(hotspot.hotspot_count, 0) as integer) as hotspot_count,
    cast(coalesce(hotspot.hotspot_kuat, 0) as integer) as hotspot_kuat,
    cast(coalesce(hotspot.hotspot_sedang, 0) as integer) as hotspot_sedang,
    cast(coalesce(hotspot.hotspot_lemah, 0) as integer) as hotspot_lemah,
    cast(coalesce(hotspot.hotspot_kandidat, 0) as integer) as hotspot_kandidat,
    cast(coalesce(hotspot.hotspot_day, 0) as integer) as hotspot_day,
    cast(coalesce(hotspot.hotspot_night, 0) as integer) as hotspot_night,
    coalesce(hotspot.frp_sum, 0) as frp_sum,
    hotspot.frp_mean,
    hotspot.frp_max,
    hotspot.confidence_mean,
    cast(hotspot.gap_days_min as integer) as gap_days_min,

    scar.scar_pixels_cum,
    scar.scar_area_km2_cum,
    scar.scar_pixels_30d,
    scar.scar_area_km2_30d,
    scar.days_since_last_scar,

    weather.temp_mean,
    weather.temp_max,
    weather.rh_mean,
    weather.rh_min,
    weather.precip_sum,
    weather.wind_speed_max,
    weather.vpd_max,
    weather.soil_moisture_mean,
    weather.et0_sum,
    cast(coalesce(weather.weather_hours, 0) as integer) as weather_hours,
    coalesce(weather.weather_hours, 0) >= 20 as weather_complete,

    air_quality.pm25_mean,
    air_quality.pm25_max,
    air_quality.pm10_mean,
    air_quality.co_mean,
    air_quality.no2_mean,
    air_quality.so2_mean,
    air_quality.o3_mean,
    air_quality.aod_mean,
    cast(coalesce(air_quality.aq_hours, 0) as integer) as aq_hours,

    universe.label_risk,
    universe.label_hotspot_count,
    universe.label_window_end,
    universe.label_complete
from universe
inner join grid
    on grid.cell_id = universe.cell_id
left join hotspot
    on hotspot.cell_id = universe.cell_id
   and hotspot.date = universe.date
left join weather
    on weather.province = grid.province
   and weather.date = universe.date
left join air_quality
    on air_quality.province = grid.province
   and air_quality.date = universe.date
left join scar
    on scar.cell_id = universe.cell_id
   and scar.date = universe.date
