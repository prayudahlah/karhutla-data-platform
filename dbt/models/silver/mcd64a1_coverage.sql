-- Satu baris per tile dan periode, dipakai untuk membedakan "tidak terbakar"
-- dari "belum diunduh" saat menilai kelengkapan label.
with ranked as (
    select
        period,
        tile,
        source_file,
        pixels_burned,
        pixels_outside_month,
        date,
        row_number() over (
            partition by period, tile
            order by date desc, ingested_at desc
        ) as row_number
    from {{ ref('stg_mcd64a1_coverage') }}
)

select
    period,
    tile,
    source_file,
    pixels_burned,
    pixels_outside_month,
    date
from ranked
where row_number = 1
