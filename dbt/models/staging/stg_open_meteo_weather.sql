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
    cast(temperature_2m as double) as temperature_2m,
    cast(relative_humidity_2m as double) as relative_humidity_2m,
    cast(precipitation as double) as precipitation,
    cast(wind_speed_10m as double) as wind_speed_10m,
    cast(wind_direction_10m as double) as wind_direction_10m,
    cast(soil_moisture_0_to_7cm as double) as soil_moisture_0_to_7cm,
    cast(vapour_pressure_deficit as double) as vapour_pressure_deficit,
    cast(et0_fao_evapotranspiration as double) as et0_fao_evapotranspiration,
    cast(date as date) as date
from read_parquet(
    '{{ normalized_root }}/open_meteo/dataset=weather/date=*/part-*.parquet',
    hive_partitioning = true,
    union_by_name = true
)
