{% set normalized_root = env_var('SILVER_NORMALIZED_ROOT', 'data/silver/_normalized') %}

select
    cast(province as varchar) as province,
    cast(city as varchar) as city,
    cast(latitude as double) as latitude,
    cast(longitude as double) as longitude,
    cast(ts_utc as timestamp) as ts_utc,
    cast(ts_local as timestamp) as ts_local,
    cast(run_id as varchar) as run_id,
    cast(ingestion_timestamp as timestamp) as ingestion_timestamp,
    cast(units_json as varchar) as units_json,
    cast(pm2_5 as double) as pm2_5,
    cast(pm10 as double) as pm10,
    cast(carbon_monoxide as double) as carbon_monoxide,
    cast(nitrogen_dioxide as double) as nitrogen_dioxide,
    cast(sulphur_dioxide as double) as sulphur_dioxide,
    cast(ozone as double) as ozone,
    cast(aerosol_optical_depth as double) as aerosol_optical_depth,
    cast(date as date) as date
from read_parquet(
    '{{ normalized_root }}/open_meteo/dataset=air_quality/date=*/part-*.parquet',
    hive_partitioning = true,
    union_by_name = true
)
