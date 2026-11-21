{{
    config(
        materialized='view',
        tags=['gold']
    )
}}

{#-
    Satu baris per sel grid 0,25 derajat di bbox Indonesia.
    Provinsi diambil dari centroid provinsi terdekat di resources/.
    Batas yang disepakati: sel yang berada di perbatasan bisa salah provinsi;
    jarak ke centroid disimpan di distance_km supaya bisa diaudit.
-#}

with row_idx as (

    select range as row_idx
    from range(0, {{ grid_rows() }})

),

col_idx as (

    select range as col_idx
    from range(0, {{ grid_cols() }})

),

cells as (

    select
        {{ grid_cell_id_from_indices('r.row_idx', 'c.col_idx') }} as cell_id,
        cast(r.row_idx as integer) as row_idx,
        cast(c.col_idx as integer) as col_idx,
        {{ grid_cell_lat('r.row_idx') }} as cell_lat,
        {{ grid_cell_lon('c.col_idx') }} as cell_lon
    from row_idx r
    cross join col_idx c

),

provinces as (

    select
        cast(p.province as varchar) as province,
        cast(p.latitude as double) as latitude,
        cast(p.longitude as double) as longitude,
        cast(i.island as varchar) as island
    from read_csv_auto('{{ var("provinces_csv") }}') p
    left join read_csv_auto('{{ var("islands_csv") }}') i
        on cast(p.province as varchar) = cast(i.province as varchar)

),

assigned as (

    select
        cells.cell_id,
        cells.row_idx,
        cells.col_idx,
        cells.cell_lat,
        cells.cell_lon,
        provinces.province,
        provinces.island,
        {{ haversine_km('cells.cell_lat', 'cells.cell_lon', 'provinces.latitude', 'provinces.longitude') }}
            as distance_km,
        row_number() over (
            partition by cells.cell_id
            order by
                {{ haversine_km('cells.cell_lat', 'cells.cell_lon', 'provinces.latitude', 'provinces.longitude') }} asc,
                provinces.province asc
        ) as row_number
    from cells
    cross join provinces

)

select
    cell_id,
    row_idx,
    col_idx,
    cell_lat,
    cell_lon,
    province,
    island,
    round(distance_km, 3) as distance_km
from assigned
where row_number = 1
