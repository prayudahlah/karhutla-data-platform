{{ config(tags=['gold']) }}

-- Label harus bisa direkonstruksi dari Silver:
-- label_risk = 1 jika ada hotspot tier kuat/sedang pada D..D+2.
-- Hanya baris label_complete yang diuji, karena dua tanggal terakhir
-- jendelanya belum teramati penuh.

with hotspot as (

    select
        {{ grid_cell_id('latitude', 'longitude') }} as cell_id,
        cast(date as date) as date,
        count(*) filter (where tier in ({{ label_tiers() }})) as positif
    from {{ ref('hotspot_scar_label') }}
    group by 1, 2

),

expected as (

    select
        universe.cell_id,
        universe.date,
        sum(coalesce(hotspot.positif, 0)) over (
            partition by universe.cell_id
            order by universe.date
            rows between current row and 2 following
        ) as positif_3d
    from {{ ref('int_cell_daily_universe') }} universe
    left join hotspot
        on hotspot.cell_id = universe.cell_id
       and hotspot.date = universe.date

)

select
    cell_daily.cell_id,
    cell_daily.date,
    cell_daily.label_risk,
    expected.positif_3d
from {{ ref('cell_daily') }} cell_daily
inner join expected
    on expected.cell_id = cell_daily.cell_id
   and expected.date = cell_daily.date
where cell_daily.label_complete
  and cell_daily.label_risk <> case when expected.positif_3d > 0 then 1 else 0 end
