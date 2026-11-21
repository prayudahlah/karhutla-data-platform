{{
    config(
        materialized='external',
        format='parquet',
        location=var('gold_publish_root') ~ '/province_daily',
        options={'partition_by': 'date', 'overwrite': 'true'}
    )
}}

{#-
    Gold mart: satu baris per provinsi per hari.

    Grain : (province, date)
    Sumber: cell_daily untuk hotspot, int_weather/int_air_quality untuk
            variabel provinsi, int_scar_province_daily untuk scar kumulatif.

    frp_mean dihitung dari frp_sum yang sudah dibulatkan, bukan dari agregasi
    kedua, supaya hasilnya identik setiap kali build diulang.
-#}

with cell as (

    select *
    from {{ ref('cell_daily') }}

),

grid as (

    select cell_id, province
    from {{ ref('int_grid_cell') }}

),

hotspot_freshness as (

    select
        grid.province,
        hotspot.date,
        max(hotspot.hotspot_ingested_at) as freshness_at
    from {{ ref('int_hotspot_cell_daily') }} hotspot
    inner join grid
        on grid.cell_id = hotspot.cell_id
    group by 1, 2

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
    from {{ ref('int_scar_province_daily') }}

),

aggregated as (

    select
        cell.province,
        cell.island,
        cell.date,
        sum(cell.hotspot_count) as hotspot_count,
        sum(cell.hotspot_kuat) as hotspot_kuat,
        sum(cell.hotspot_sedang) as hotspot_sedang,
        sum(cell.hotspot_lemah) as hotspot_lemah,
        sum(cell.hotspot_kandidat) as hotspot_kandidat,
        count(*) filter (where cell.hotspot_count > 0) as active_cells,
        sum(cast(cell.frp_sum as decimal(18, 3))) as frp_sum_raw,
        max(cell.frp_max) as frp_max,
        scar.scar_pixels_cum,
        scar.scar_area_km2_cum,
        weather.temp_max,
        weather.rh_min,
        weather.precip_sum,
        weather.wind_speed_max,
        weather.vpd_max,
        coalesce(weather.weather_hours, 0) as weather_hours,
        air_quality.pm25_mean,
        air_quality.pm25_max,
        hotspot_freshness.freshness_at
    from cell
    left join hotspot_freshness
        on hotspot_freshness.province = cell.province
       and hotspot_freshness.date = cell.date
    left join weather
        on weather.province = cell.province
       and weather.date = cell.date
    left join air_quality
        on air_quality.province = cell.province
       and air_quality.date = cell.date
    left join scar
        on scar.province = cell.province
       and scar.date = cell.date
    group by
        cell.province,
        cell.island,
        cell.date,
        scar.scar_pixels_cum,
        scar.scar_area_km2_cum,
        weather.temp_max,
        weather.rh_min,
        weather.precip_sum,
        weather.wind_speed_max,
        weather.vpd_max,
        weather.weather_hours,
        air_quality.pm25_mean,
        air_quality.pm25_max,
        hotspot_freshness.freshness_at

)

select
    province,
    island,
    date,
    cast(hotspot_count as integer) as hotspot_count,
    cast(hotspot_kuat as integer) as hotspot_kuat,
    cast(hotspot_sedang as integer) as hotspot_sedang,
    cast(hotspot_lemah as integer) as hotspot_lemah,
    cast(hotspot_kandidat as integer) as hotspot_kandidat,
    cast(active_cells as integer) as active_cells,
    round(frp_sum_raw, 3) as frp_sum,
    round(frp_sum_raw / nullif(hotspot_count, 0), 3) as frp_mean,
    round(frp_max, 3) as frp_max,
    scar_pixels_cum,
    scar_area_km2_cum,
    temp_max,
    rh_min,
    precip_sum,
    wind_speed_max,
    vpd_max,
    cast(weather_hours as integer) as weather_hours,
    weather_hours >= 20 as weather_complete,
    pm25_mean,
    pm25_max,
    freshness_at
from aggregated
