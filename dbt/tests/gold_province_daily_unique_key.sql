{{ config(tags=['gold']) }}

-- Kunci province_daily: (province, date) harus unik.

select province, date, count(*) as baris
from {{ ref('province_daily') }}
group by 1, 2
having count(*) > 1
