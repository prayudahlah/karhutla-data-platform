select event_id
from {{ ref('hotspot_event_evidence_reason') }}
where is_primary_reason
group by 1
having count(*) > 1
