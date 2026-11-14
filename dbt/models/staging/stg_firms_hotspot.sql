{% set normalized_root = env_var('SILVER_NORMALIZED_ROOT', 'data/silver/_normalized') %}

select
    cast(event_id as varchar) as event_id,
    cast(source as varchar) as source,
    cast(satellite as varchar) as satellite,
    cast(instrument as varchar) as instrument,
    cast(latitude as double) as latitude,
    cast(longitude as double) as longitude,
    cast(acq_ts_utc as timestamp) as acq_ts_utc,
    cast(acq_ts_local as timestamp) as acq_ts_local,
    cast(acq_date as date) as acq_date,
    cast(acq_time as varchar) as acq_time,
    cast(confidence as varchar) as confidence,
    cast(confidence_score as smallint) as confidence_score,
    cast(frp as double) as frp,
    cast(brightness as double) as brightness,
    cast(brightness_secondary as double) as brightness_secondary,
    cast(scan as double) as scan,
    cast(track as double) as track,
    cast(daynight as varchar) as daynight,
    cast(version as varchar) as version,
    cast(ingested_at as timestamp) as ingested_at,
    cast(in_bbox as boolean) as in_bbox,
    cast(source_file as varchar) as source_file
from read_parquet(
    '{{ normalized_root }}/firms/dataset=hotspot/date=*/part-*.parquet',
    hive_partitioning = true,
    union_by_name = true
)
