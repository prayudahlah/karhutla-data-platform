-- Setiap hotspot wajib muncul tepat sekali di tabel label.
select
    (select count(*) from {{ ref('firms_hotspot') }}) as hotspots,
    (select count(*) from {{ ref('hotspot_scar_label') }}) as labelled
having hotspots != labelled
