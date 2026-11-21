{{ config(materialized='view') }}

select *
from read_parquet(
    '{{ env_var("SILVER_NORMALIZED_ROOT", "data/silver/_normalized") }}/mcd64a1/dataset=pixel_period_required/part-*.parquet'
)
