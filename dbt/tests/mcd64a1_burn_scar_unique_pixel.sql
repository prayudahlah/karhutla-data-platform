-- Satu piksel tidak boleh muncul dua kali pada tanggal terbakar yang sama.
select
    tile,
    pixel_row,
    pixel_col,
    burn_date,
    count(*) as row_count
from {{ ref('mcd64a1_burn_scar') }}
group by 1, 2, 3, 4
having count(*) > 1
