{{ config(
    materialized='external',
    format='parquet',
    location=var('silver_publish_root') ~ '/mcd64a1/tiles/tiles.parquet'
) }}

-- Grid tile tidak berubah antar periode, jadi ambil periode terbaru saja.
select
    tile,
    period,
    ulx,
    uly,
    px,
    py,
    nx,
    ny
from {{ ref('stg_mcd64a1_tiles') }}
qualify row_number() over (partition by tile order by period desc) = 1
