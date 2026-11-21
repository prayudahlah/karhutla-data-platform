{{ config(materialized='view', tags=['gold']) }}

{#- Scar kumulatif per provinsi per hari, memakai SEMUA piksel scar
    (termasuk sel yang tidak pernah punya hotspot) supaya totalnya tetap
    36.916 piksel dan bisa direkonsiliasi dengan Silver. -#}

with scar_cell as (

    select
        grid.province,
        cast(scar.burn_date as date) as date,
        count(*) as scar_pixels
    from {{ ref('mcd64a1_burn_scar') }} scar
    inner join {{ ref('int_grid_cell') }} grid
        on grid.cell_id = {{ grid_cell_id('scar.latitude', 'scar.longitude') }}
    group by 1, 2

),

provinces as (

    select distinct province
    from {{ ref('int_grid_cell') }}

),

dates as (

    select distinct date
    from {{ ref('int_cell_daily_universe') }}

),

spine as (

    select
        provinces.province,
        dates.date
    from provinces
    cross join dates

),

joined as (

    select
        spine.province,
        spine.date,
        coalesce(scar_cell.scar_pixels, 0) as scar_pixels
    from spine
    left join scar_cell
        on scar_cell.province = spine.province
       and scar_cell.date = spine.date

)

select
    province,
    date,
    cast(sum(scar_pixels) over (
        partition by province
        order by date
        rows between unbounded preceding and current row
    ) as integer) as scar_pixels_cum,
    round(sum(scar_pixels) over (
        partition by province
        order by date
        rows between unbounded preceding and current row
    ) * {{ mcd64a1_pixel_km2() }}, 4) as scar_area_km2_cum
from joined
