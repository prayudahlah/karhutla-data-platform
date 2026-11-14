-- Tier harus konsisten dengan gap_days, bukan sekadar salah satu nilai sah.
select *
from {{ ref('hotspot_scar_label') }}
where tier != case
    when gap_days is null then 'kandidat'
    when gap_days <= 3 then 'kuat'
    when gap_days <= 7 then 'sedang'
    when gap_days <= 14 then 'lemah'
    else 'kandidat'
end
