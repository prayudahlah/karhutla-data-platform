{{ config(tags=['gold']) }}

-- Kunci burn_scar_monthly: (burn_month, province) harus unik.

select burn_month, province, count(*) as baris
from {{ ref('burn_scar_monthly') }}
group by 1, 2
having count(*) > 1
