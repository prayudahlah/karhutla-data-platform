{% set normalized_root = env_var('SILVER_NORMALIZED_ROOT', 'data/silver/_normalized') %}

select
    cast(tile as varchar) as tile,
    cast(period as varchar) as period,
    cast(ulx as double) as ulx,
    cast(uly as double) as uly,
    cast(px as double) as px,
    cast(py as double) as py,
    cast(nx as integer) as nx,
    cast(ny as integer) as ny
from read_parquet(
    '{{ normalized_root }}/mcd64a1/dataset=tiles/date=*/part-*.parquet',
    hive_partitioning = true,
    union_by_name = true
)
