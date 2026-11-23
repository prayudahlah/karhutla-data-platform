{{ config(materialized='view', tags=['gold']) }}

{#- Semesta contoh ML: setiap sel yang pernah punya hotspot x setiap tanggal,
    plus label risiko dari hotspot tier kuat/sedang pada D..D+2.

    label_complete = false untuk dua tanggal terakhir karena jendela label
    belum teramati penuh; baris seperti ini harus dibuang saat latih/uji. -#}

with hotspot_daily as (

    select
        cell_id,
        date,
        hotspot_count,
        hotspot_kuat + hotspot_sedang as hotspot_positif
    from {{ ref('int_hotspot_cell_daily') }}

),

cells as (

    select distinct cell_id
    from hotspot_daily

),

dates as (

    select distinct date
    from hotspot_daily

),

spine as (

    select
        cells.cell_id,
        dates.date
    from cells
    cross join dates

),

joined as (

    select
        spine.cell_id,
        spine.date,
        coalesce(hotspot_daily.hotspot_positif, 0) as hotspot_positif,
        coalesce(hotspot_daily.hotspot_count, 0) as hotspot_count,
        max(spine.date) over () as max_date
    from spine
    left join hotspot_daily
        on hotspot_daily.cell_id = spine.cell_id
       and hotspot_daily.date = spine.date

),

windowed as (

    select
        cell_id,
        date,
        sum(hotspot_positif) over (
            partition by cell_id
            order by date
            rows between current row and 2 following
        ) as positif_3d,
        sum(hotspot_count) over (
            partition by cell_id
            order by date
            rows between current row and 2 following
        ) as hotspot_3d,
        max_date
    from joined

)

select
    cell_id,
    date,
    cast(case when positif_3d > 0 then 1 else 0 end as integer) as label_risk,
    cast(hotspot_3d as integer) as label_hotspot_count,
    cast(date + interval 2 day as date) as label_window_end,
    date <= max_date - interval 2 day as label_complete
from windowed
