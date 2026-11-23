{{ config(
    materialized='external',
    format='parquet',
    location=var('gold_publish_root') ~ '/hotspot_cell_day_labeled',
    options={'partition_by': 'date', 'overwrite': 'true'}
) }}

with base as (
    select *
    from {{ ref('gold_hotspot_cell_day') }}
),
labels as (
    select *
    from read_parquet(
        '{{ env_var("SILVER_NORMALIZED_ROOT", "data/silver/_normalized") }}/mcd64a1/dataset=hotspot_cell_day_labeled/part-*.parquet'
    )
)
select
    b.* exclude (label, label_complete, audit_tier_max),
    l.label,
    l.label_status,
    l.label_complete,
    l.label_reason,
    l.n_events,
    l.n_positive,
    l.n_negative,
    l.n_incomplete,
    l.n_strong,
    l.n_medium,
    l.n_weak,
    l.n_candidate,
    l.n_no_scar_match,
    l.n_scar_outside_window,
    l.n_valid_evidence,
    l.audit_tier_max,
    l.label_rule_version,
    l.fingerprint
from base b
left join labels l
    on b.cell_id = l.cell_id
   and b.date = l.date
