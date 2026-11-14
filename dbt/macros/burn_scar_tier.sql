{% macro burn_gap_days(hotspot_date, burn_date) %}
    abs(date_diff('day', {{ hotspot_date }}, {{ burn_date }}))
{% endmacro %}


{% macro burn_scar_tier(gap_days, strong_days=3, medium_days=7, weak_days=14) %}
    case
        when {{ gap_days }} is null then 'kandidat'
        when {{ gap_days }} <= {{ strong_days }} then 'kuat'
        when {{ gap_days }} <= {{ medium_days }} then 'sedang'
        when {{ gap_days }} <= {{ weak_days }} then 'lemah'
        else 'kandidat'
    end
{% endmacro %}
