select *
from {{ ref('gold_hotspot_cell_day_labeled') }}
where
    (n_strong > 0 and audit_tier_max != 'strong')
    or (n_strong = 0 and n_medium > 0 and audit_tier_max != 'medium')
    or (n_strong = 0 and n_medium = 0 and n_weak > 0 and audit_tier_max != 'weak')
    or (n_strong = 0 and n_medium = 0 and n_weak = 0 and audit_tier_max != 'candidate')
