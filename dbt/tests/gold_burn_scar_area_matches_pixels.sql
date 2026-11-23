{{ config(tags=['gold']) }}

-- scar_area_km2 harus konsisten dengan jumlah piksel (1 piksel = 0,2146 km2).

select burn_month, province, scar_pixels, scar_area_km2
from {{ ref('burn_scar_monthly') }}
where abs(scar_area_km2 - scar_pixels * {{ mcd64a1_pixel_km2() }}) > 0.01
