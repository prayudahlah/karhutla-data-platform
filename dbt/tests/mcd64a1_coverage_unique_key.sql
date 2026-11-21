-- Kombinasi periode dan tile harus unik pada tabel cakupan.
select
    period,
    tile
from {{ ref('mcd64a1_coverage') }}
group by period, tile
having count(*) > 1
