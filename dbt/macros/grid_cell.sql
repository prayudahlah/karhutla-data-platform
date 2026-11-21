{#- Grid 0,25 derajat yang dipakai semua tabel Gold.

    Batas grid dikunci di sini supaya ``cell_id`` tidak berubah antar run.
    ``row`` dan ``col`` adalah indeks sel, bukan koordinat. -#}

{% macro grid_cell_size() %}0.25{% endmacro %}
{% macro grid_lat_min() %}-11.0{% endmacro %}
{% macro grid_lon_min() %}95.0{% endmacro %}
{% macro grid_rows() %}70{% endmacro %}
{% macro grid_cols() %}186{% endmacro %}

{#- Lintang pusat sel dari indeks baris. -#}
{% macro grid_cell_lat(row_expr) %}
    round(cast({{ grid_lat_min() }} as double) + (cast({{ row_expr }} as double) + 0.5) * {{ grid_cell_size() }}, 6)
{% endmacro %}

{#- Bujur pusat sel dari indeks kolom. -#}
{% macro grid_cell_lon(col_expr) %}
    round(cast({{ grid_lon_min() }} as double) + (cast({{ col_expr }} as double) + 0.5) * {{ grid_cell_size() }}, 6)
{% endmacro %}

{#- Indeks sel untuk sebuah titik. Harus konsisten dengan grid_cell_lat/lon.
    Argumen di-cast ke integer karena ``%04d`` pada BIGINT bisa salah format. -#}
{% macro grid_cell_id(lat_expr, lon_expr) %}
    {{ grid_cell_id_from_indices(
        'cast(floor((cast(' ~ lat_expr ~ ' as double) - (' ~ grid_lat_min() ~ ')) / ' ~ grid_cell_size() ~ ') as integer)',
        'cast(floor((cast(' ~ lon_expr ~ ' as double) - (' ~ grid_lon_min() ~ ')) / ' ~ grid_cell_size() ~ ') as integer)'
    ) }}
{% endmacro %}

{#- cell_id dari indeks baris/kolom yang sudah dihitung. -#}
{% macro grid_cell_id_from_indices(row_expr, col_expr) %}
    printf('%04d_%04d', cast({{ row_expr }} as integer), cast({{ col_expr }} as integer))
{% endmacro %}

{#- Jarak great-circle dalam km, cukup akurat untuk pemetaan provinsi. -#}
{% macro haversine_km(lat1, lon1, lat2, lon2) %}
    2 * 6371.0088 * asin(
        sqrt(
            power(sin(radians({{ lat2 }} - {{ lat1 }}) / 2), 2)
            + cos(radians({{ lat1 }})) * cos(radians({{ lat2 }}))
              * power(sin(radians({{ lon2 }} - {{ lon1 }}) / 2), 2)
        )
    )
{% endmacro %}

{#- Satu piksel MCD64A1 kira-kira 463 m x 463 m. -#}
{% macro mcd64a1_pixel_km2() %}0.2146{% endmacro %}

{#- Ambang label risiko: tier kuat dan sedang dianggap positif. -#}
{% macro label_tiers() %}'kuat', 'sedang'{% endmacro %}
