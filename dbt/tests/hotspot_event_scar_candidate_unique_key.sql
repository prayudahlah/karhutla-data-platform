select event_id, burn_scar_key
from {{ ref('hotspot_event_scar_candidate') }}
group by 1, 2
having count(*) > 1
