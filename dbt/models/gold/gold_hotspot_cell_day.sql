{{ config(
    materialized='external',
    format='parquet',
    location=var('gold_publish_root') ~ '/hotspot_cell_day',
    options={'partition_by': 'date'}
) }}

-- Satu baris per sel 0,25° per hari. Label biner: 1 bila ada hotspot
-- kuat/sedang, 0 bila hanya lemah/kandidat. Kolom audit_* hanya untuk laporan.
-- Jendela kelengkapan label 7 hari: hanya scar 0..7 hari yang bisa membalik
-- label (lemah, 8..14 hari, tetap negatif), jadi scar di luar itu tidak perlu.

with labeled as (
    select *
    from {{ ref('hotspot_scar_label') }}
    where in_bbox
),

coverage as (
    select period, tile
    from {{ ref('mcd64a1_coverage') }}
),

needed_periods as (
    select
        event_id,
        tile,
        unnest(list_distinct(list_value(
            strftime(date - 7, '%Y-%m'),
            strftime(date, '%Y-%m'),
            strftime(date + 7, '%Y-%m')
        ))) as period
    from labeled
),

event_completeness as (
    select
        n.event_id,
        count(*) as n_period_needed,
        count(c.period) as n_period_covered
    from needed_periods n
    left join coverage c
        on c.period = n.period
       and c.tile = n.tile
    group by n.event_id
),

hotspots as (
    select
        l.event_id,
        l.date,
        l.tier,
        l.frp,
        l.brightness,
        l.brightness_secondary,
        l.confidence_score,
        l.confidence,
        case
            when l.confidence_score is not null then cast(l.confidence_score as double)
            when lower(trim(l.confidence)) = 'h' then 90.0
            when lower(trim(l.confidence)) = 'n' then 60.0
            when lower(trim(l.confidence)) = 'l' then 30.0
            else try_cast(l.confidence as double)
        end as confidence_norm,
        l.scan,
        l.track,
        l.daynight,
        l.instrument,
        l.satellite,
        l.tile,
        l.acq_ts_utc,
        cast(floor((cast(l.latitude as double) - ({{ grid_lat_min() }})) / {{ grid_cell_size() }}) as integer)
            as cell_y,
        cast(floor((cast(l.longitude as double) - ({{ grid_lon_min() }})) / {{ grid_cell_size() }}) as integer)
            as cell_x,
        {{ grid_cell_id('l.latitude', 'l.longitude') }} as cell_id,
        (c.n_period_needed is not null
            and c.n_period_covered = c.n_period_needed) as label_complete
    from labeled l
    left join event_completeness c
        on c.event_id = l.event_id
),

ranked as (
    select
        *,
        row_number() over (
            partition by cell_id, date
            order by frp desc nulls last, acq_ts_utc asc, event_id asc
        ) as frp_rank
    from hotspots
)

select
    cell_id,
    cell_y,
    cell_x,
    round(cast({{ grid_lat_min() }} as double)
        + (cast(cell_y as double) + 0.5) * {{ grid_cell_size() }}, 6) as center_lat,
    round(cast({{ grid_lon_min() }} as double)
        + (cast(cell_x as double) + 0.5) * {{ grid_cell_size() }}, 6) as center_lon,
    date,
    count(*) as n_hotspot,
    count(*) filter (where daynight = 'N') as n_night,
    count(distinct satellite) as n_satellite,
    count(*) filter (where instrument = 'VIIRS') as n_viirs,
    max(frp) as frp_max,
    avg(frp) as frp_mean,
    quantile_cont(frp, 0.95) as frp_p95,
    max(brightness) as brightness_max,
    avg(brightness) as brightness_mean,
    max(brightness - brightness_secondary) as brightness_diff_max,
    max(confidence_norm) as confidence_max,
    avg(confidence_norm) as confidence_mean,
    max(scan) as scan_max,
    max(track) as track_max,
    max(case when frp_rank = 1 then extract('hour' from acq_ts_utc) end) as hour_of_max_frp,
    avg(sin(2 * pi() * extract('hour' from acq_ts_utc) / 24.0)) as hour_sin_mean,
    avg(cos(2 * pi() * extract('hour' from acq_ts_utc) / 24.0)) as hour_cos_mean,
    max(case when tier in ('kuat', 'sedang') then 1 else 0 end) as label,
    bool_and(label_complete) as label_complete,
    max(tier) as audit_tier_max,
    count(*) filter (where tier in ('kuat', 'sedang')) as audit_n_confirmed,
    count(*) filter (where tier = 'lemah') as audit_n_weak,
    count(*) filter (where tier = 'kandidat') as audit_n_candidate,
    count(distinct tile) as audit_n_tile
from ranked
group by cell_id, cell_y, cell_x, date
