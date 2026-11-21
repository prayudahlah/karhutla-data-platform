{{
    config(
        materialized='external',
        format='parquet',
        location=var('gold_publish_root') ~ '/burn_scar_monthly',
        options={'partition_by': 'burn_month', 'overwrite': 'true'}
    )
}}

{#-
    Gold mart: luas terbakar per provinsi per bulan.

    Grain : (burn_month, province)
    Sumber: mcd64a1_burn_scar dipetakan ke provinsi lewat int_grid_cell.
    Total piksel harus tetap 36.916 untuk September 2026.
    -#}

with scar as (

    select
        grid.province,
        cast(scar.burn_month as varchar) as burn_month,
        cast(scar.burn_date as date) as burn_date,
        scar.tile,
        scar.qa,
        scar.uncertainty
    from {{ ref('mcd64a1_burn_scar') }} scar
    inner join {{ ref('int_grid_cell') }} grid
        on grid.cell_id = {{ grid_cell_id('scar.latitude', 'scar.longitude') }}

)

select
    burn_month,
    province,
    count(*) as scar_pixels,
    round(count(*) * {{ mcd64a1_pixel_km2() }}, 4) as scar_area_km2,
    count(distinct tile) as tile_count,
    round(avg(qa), 3) as qa_mean,
    round(avg(uncertainty), 3) as uncertainty_mean,
    min(burn_date) as first_burn_date,
    max(burn_date) as last_burn_date
from scar
group by 1, 2
