{{ config(
    materialized='external',
    format='parquet',
    location=var('silver_publish_root') ~ '/mcd64a1/burn_scar',
    options={'partition_by': 'burn_date'}
) }}

select
    tile,
    pixel_row,
    pixel_col,
    latitude,
    longitude,
    burn_date,
    burn_month,
    burn_doy,
    qa,
    uncertainty,
    first_day,
    last_day,
    source_file
from {{ ref('stg_mcd64a1_burn_scar') }}
where in_bbox
