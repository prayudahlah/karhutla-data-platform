{{ config(tags=['gold']) }}

-- Rekonsiliasi scar: total piksel di burn_scar_monthly dan scar kumulatif
-- province_daily harus sama dengan Silver (36.916 untuk September 2026).

with silver as (

    select count(*) as scar_pixels
    from {{ ref('mcd64a1_burn_scar') }}

),

monthly as (

    select sum(scar_pixels) as scar_pixels
    from {{ ref('burn_scar_monthly') }}

),

province_cum as (

    select sum(max_pixels) as scar_pixels
    from (
        select province, max(scar_pixels_cum) as max_pixels
        from {{ ref('int_scar_province_daily') }}
        group by 1
    )

)

select
    silver.scar_pixels as silver_pixels,
    monthly.scar_pixels as monthly_pixels,
    province_cum.scar_pixels as province_pixels
from silver, monthly, province_cum
where silver.scar_pixels <> monthly.scar_pixels
   or silver.scar_pixels <> province_cum.scar_pixels
