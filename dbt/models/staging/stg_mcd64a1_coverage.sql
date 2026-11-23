{% set normalized_root = env_var('SILVER_NORMALIZED_ROOT', 'data/silver/_normalized') %}

select
    cast(period as varchar) as period,
    cast(tile as varchar) as tile,
    cast(source_file as varchar) as source_file,
    cast(pixels_burned as bigint) as pixels_burned,
    cast(pixels_outside_month as bigint) as pixels_outside_month,
    cast(ingested_at as varchar) as ingested_at,
    cast(date as date) as date
from read_parquet(
    '{{ normalized_root }}/mcd64a1/dataset=coverage/date=*/part-*.parquet',
    hive_partitioning = true,
    union_by_name = true
)
