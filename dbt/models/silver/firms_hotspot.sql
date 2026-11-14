{{ config(
    materialized='external',
    format='parquet',
    location=var('silver_publish_root') ~ '/firms/hotspot',
    options={'partition_by': 'date'}
) }}

with ranked as (
    select
        *,
        cast(acq_date as date) as date,
        row_number() over (
            partition by event_id
            order by ingested_at desc nulls last, source_file desc
        ) as row_number
    from {{ ref('stg_firms_hotspot') }}
)

select * exclude (row_number)
from ranked
where row_number = 1
