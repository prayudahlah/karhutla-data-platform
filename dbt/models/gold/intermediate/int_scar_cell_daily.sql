{{ config(materialized='view', tags=['gold']) }}

{#- Scar kumulatif per sel per hari, dihitung di atas spine yang padat
    (semua sel x semua tanggal) supaya jendela 30 hari tidak bolong.
    Satu piksel MCD64A1 = 0,2146 km2. -#}

with scar_daily as (

    select
        {{ grid_cell_id('latitude', 'longitude') }} as cell_id,
        cast(burn_date as date) as date,
        count(*) as scar_pixels
    from {{ ref('mcd64a1_burn_scar') }}
    group by 1, 2

),

spine as (

    select cell_id, date
    from {{ ref('int_cell_daily_universe') }}

    union

    -- Tanggal scar yang tidak punya hotspot tetap masuk spine supaya
    -- kumulatif di tanggal hotspot berikutnya tidak kehilangan piksel.
    select cell_id, date
    from scar_daily

),

joined as (

    select
        spine.cell_id,
        spine.date,
        coalesce(scar_daily.scar_pixels, 0) as scar_pixels
    from spine
    left join scar_daily
        on scar_daily.cell_id = spine.cell_id
       and scar_daily.date = spine.date

),

windowed as (

    select
        cell_id,
        date,
        sum(scar_pixels) over (
            partition by cell_id
            order by date
            rows between unbounded preceding and current row
        ) as scar_pixels_cum,
        sum(scar_pixels) over (
            partition by cell_id
            order by date
            rows between 29 preceding and current row
        ) as scar_pixels_30d,
        max(case when scar_pixels > 0 then date end) over (
            partition by cell_id
            order by date
            rows between unbounded preceding and current row
        ) as last_scar_date
    from joined

)

select
    cell_id,
    date,
    cast(scar_pixels_cum as integer) as scar_pixels_cum,
    round(scar_pixels_cum * {{ mcd64a1_pixel_km2() }}, 4) as scar_area_km2_cum,
    cast(scar_pixels_30d as integer) as scar_pixels_30d,
    round(scar_pixels_30d * {{ mcd64a1_pixel_km2() }}, 4) as scar_area_km2_30d,
    cast(date_diff('day', last_scar_date, date) as integer) as days_since_last_scar
from windowed
