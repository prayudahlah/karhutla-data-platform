{{ config(tags=['gold']) }}

-- Setiap sel harus punya pulau, dan hanya 7 pulau yang diizinkan.
-- Uji ini menangkap provinsi baru yang belum masuk mapping.

select cell_id, province, island
from {{ ref('int_grid_cell') }}
where island is null
   or island not in (
       'Sumatera',
       'Jawa',
       'Kalimantan',
       'Sulawesi',
       'Bali & Nusa Tenggara',
       'Maluku',
       'Papua'
   )
