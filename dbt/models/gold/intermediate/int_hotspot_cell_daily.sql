{{ config(materialized='view', tags=['gold']) }}

{#- Agregat hotspot Silver per sel 0,25 derajat per hari.
    Sumber: hotpot_scar_label, jadi tier dan gap_days sudah final di Silver. -#}

select
    {{ grid_cell_id('latitude', 'longitude') }} as cell_id,
    cast(date as date) as date,
    count(*) as hotspot_count,
    count(*) filter (where tier = 'kuat') as hotspot_kuat,
    count(*) filter (where tier = 'sedang') as hotspot_sedang,
    count(*) filter (where tier = 'lemah') as hotspot_lemah,
    count(*) filter (where tier = 'kandidat') as hotspot_kandidat,
    count(*) filter (where daynight = 'D') as hotspot_day,
    count(*) filter (where daynight = 'N') as hotspot_night,
    round(sum(cast(frp as decimal(18, 3))), 3) as frp_sum,
    round(sum(cast(frp as decimal(18, 3))) / nullif(count(frp), 0), 3) as frp_mean,
    round(max(frp), 3) as frp_max,
    round(
        sum(cast(confidence_score as decimal(18, 3))) / nullif(count(confidence_score), 0),
        3
    ) as confidence_mean,
    min(gap_days) as gap_days_min,
    max(ingested_at) as hotspot_ingested_at
from {{ ref('hotspot_scar_label') }}
group by 1, 2
