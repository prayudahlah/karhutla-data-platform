{{ config(severity='warn') }}

-- Confidence seharusnya hampir selalu terisi setelah confidence_norm dipakai.
-- Baris tanpa confidence tetap diizinkan, tetapi jumlahnya harus kecil.
select *
from {{ ref('gold_hotspot_cell_day') }}
where confidence_max is null
