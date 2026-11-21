select *
from {{ ref('hotspot_event_evidence') }}
where
    (label_status = 'incomplete' and label is not null)
    or (label_status in ('positive', 'negative') and label is null)
    or (label_status = 'positive' and label != 1)
    or (label_status = 'negative' and label != 0)
