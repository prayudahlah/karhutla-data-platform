{{ config(materialized='table') }}

with ranked as (
    select
        *,
        row_number() over (
            partition by province, city, ts_utc
            order by ingestion_timestamp desc nulls last, run_id desc
        ) as row_number
    from {{ ref('stg_open_meteo_air_quality') }}
)

select * exclude (row_number)
from ranked
where row_number = 1
