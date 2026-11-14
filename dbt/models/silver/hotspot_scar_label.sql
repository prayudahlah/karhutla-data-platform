{{ config(
    materialized='external',
    format='parquet',
    location=var('silver_publish_root') ~ '/firms/hotspot_label',
    options={'partition_by': 'date'}
) }}

with located as (
    select
        h.event_id,
        h.source,
        h.satellite,
        h.instrument,
        h.latitude,
        h.longitude,
        h.acq_ts_utc,
        h.acq_ts_local,
        h.acq_date,
        h.acq_time,
        h.confidence,
        h.confidence_score,
        h.frp,
        h.brightness,
        h.brightness_secondary,
        h.scan,
        h.track,
        h.daynight,
        h.version,
        h.ingested_at,
        h.in_bbox,
        h.source_file,
        t.tile,
        cast(floor((t.uly - h.y) / t.py) as integer) as pixel_row,
        cast(floor((h.x - t.ulx) / t.px) as integer) as pixel_col
    from (
        select
            *,
            6371007.181 * cos(radians(latitude)) * radians(longitude) as x,
            6371007.181 * radians(latitude) as y
        from {{ ref('firms_hotspot') }}
    ) h
    left join {{ ref('mcd64a1_tiles') }} t
        on h.x >= t.ulx
       and h.x < t.ulx + t.px * t.nx
       and h.y > t.uly - t.py * t.ny
       and h.y <= t.uly
),
matched as (
    select
        l.*,
        s.burn_date,
        {{ burn_gap_days('l.acq_date', 's.burn_date') }} as gap_days,
        row_number() over (
            partition by l.event_id
            order by {{ burn_gap_days('l.acq_date', 's.burn_date') }} asc nulls last
        ) as row_number
    from located l
    left join {{ ref('mcd64a1_burn_scar') }} s
        on l.tile = s.tile
       and l.pixel_row = s.pixel_row
       and l.pixel_col = s.pixel_col
)

select
    event_id,
    source,
    satellite,
    instrument,
    latitude,
    longitude,
    acq_ts_utc,
    acq_ts_local,
    acq_date,
    cast(acq_date as date) as date,
    acq_time,
    confidence,
    confidence_score,
    frp,
    brightness,
    brightness_secondary,
    scan,
    track,
    daynight,
    version,
    ingested_at,
    in_bbox,
    source_file,
    tile,
    pixel_row,
    pixel_col,
    burn_date,
    gap_days,
    {{ burn_scar_tier('gap_days') }} as tier
from matched
where row_number = 1
