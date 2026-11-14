select
    cast(sample_id as integer) as sample_id,
    cast(label as varchar) as label
from {{ source('silver_fixtures', 'silver_sample') }}
