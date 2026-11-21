{{ config(tags=['gold']) }}

-- cell_id harus bisa direkonstruksi dari indeks baris dan kolom.
-- Uji ini menangkap kesalahan format seperti tanda minus pada printf.

select cell_id, row_idx, col_idx
from {{ ref('int_grid_cell') }}
where cell_id <> printf('%04d_%04d', row_idx, col_idx)
