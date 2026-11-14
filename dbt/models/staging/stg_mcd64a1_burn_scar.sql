{% set normalized_root = env_var('SILVER_NORMALIZED_ROOT', 'data/silver/_normalized') %}

select
    cast(tile as varchar) as tile,
    cast(row as integer) as pixel_row,
    cast(col as integer) as pixel_col,
    cast(latitude as double) as latitude,
    cast(longitude as double) as longitude,
    cast(burn_date as date) as burn_date,
    cast(burn_month as varchar) as burn_month,
    cast(burn_doy as smallint) as burn_doy,
    cast(qa as smallint) as qa,
    cast(uncertainty as smallint) as uncertainty,
    cast(first_day as smallint) as first_day,
    cast(last_day as smallint) as last_day,
    cast(in_bbox as boolean) as in_bbox,
    cast(source_file as varchar) as source_file
from read_parquet(
    '{{ normalized_root }}/mcd64a1/dataset=burn_scar/date=*/part-*.parquet',
    hive_partitioning = true,
    union_by_name = true
)
