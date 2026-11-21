{{ config(tags=['gold']) }}

-- Kunci cell_daily: (cell_id, date) harus unik.

select cell_id, date, count(*) as baris
from {{ ref('cell_daily') }}
group by 1, 2
having count(*) > 1
