select event_id, period
from {{ ref('hotspot_event_required_period') }}
group by 1, 2
having count(*) > 1
