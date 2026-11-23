{{ config(tags=['gold']) }}

-- Rekonsiliasi: total hotspot dan tier di Gold harus sama dengan Silver.

with gold as (

    select
        sum(hotspot_count) as total,
        sum(hotspot_kuat) as kuat,
        sum(hotspot_sedang) as sedang,
        sum(hotspot_lemah) as lemah,
        sum(hotspot_kandidat) as kandidat
    from {{ ref('cell_daily') }}

),

silver as (

    select
        count(*) as total,
        count(*) filter (where tier = 'kuat') as kuat,
        count(*) filter (where tier = 'sedang') as sedang,
        count(*) filter (where tier = 'lemah') as lemah,
        count(*) filter (where tier = 'kandidat') as kandidat
    from {{ ref('hotspot_scar_label') }}

)

select
    gold.total as gold_total,
    silver.total as silver_total,
    gold.kuat as gold_kuat,
    silver.kuat as silver_kuat,
    gold.sedang as gold_sedang,
    silver.sedang as silver_sedang,
    gold.lemah as gold_lemah,
    silver.lemah as silver_lemah,
    gold.kandidat as gold_kandidat,
    silver.kandidat as silver_kandidat
from gold, silver
where gold.total <> silver.total
   or gold.kuat <> silver.kuat
   or gold.sedang <> silver.sedang
   or gold.lemah <> silver.lemah
   or gold.kandidat <> silver.kandidat
