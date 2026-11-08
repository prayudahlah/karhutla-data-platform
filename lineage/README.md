# Lineage

Setiap job menulis satu baris JSON ke `events.jsonl` atau tabel metadata.

Contoh:

```json
{
  "run_id": "uuid",
  "job": "silver_firms",
  "inputs": ["bronze.firms_raw"],
  "outputs": ["silver.firms_hotspot"],
  "started_at": "2026-11-08T00:00:00Z",
  "finished_at": "2026-11-08T00:01:00Z",
  "status": "success"
}
```
