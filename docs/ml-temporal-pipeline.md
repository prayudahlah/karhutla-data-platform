# Pipeline training temporal (Feast + Prefect + MLflow)

Pipeline ini melatih dua konfigurasi temporal yang sudah dibekukan:

| Config | Model | Fitur | Freeze |
|---|---|---|---|
| `lr-temporal-29` | Logistic Regression, C=10 | 29 fitur setelah VIF | `experiments/lr-baseline.yaml` |
| `lgbm-temporal-29` | LightGBM | 29 fitur setelah VIF | `experiments/lgbm-baseline.yaml` |

Konfigurasi pipeline ada di `experiments/pipeline.yaml`. Flow Prefect tidak
mengevaluasi test: jendela 19-23 September 2026 sudah `seen`, jadi semua
keputusan memakai valid.

## Arsitektur

```
dbt Gold hotspot_cell_day
        │
        ▼
ml.feature_publish
  ├── data/gold/published/ml_feature_cell_day/date=*/     (23 fitur sel + label)
  └── data/gold/published/ml_feature_province_day/date=*/ (15 fitur konteks)
        │
        ▼
Feast (feature_repo/)
  entities : cell, province
  FV       : hotspot_cell_day, hotspot_province_context
  service  : hotspot_training_v1 (39 fitur kandidat)
  offline  : DuckDB membaca parquet Gold
  online   : SQLite
        │
        ▼
flows/ml_training.py (Prefect, manual)
  1. publish fitur Gold
  2. feast apply + materialize
  3. get_historical_features → dataset point-in-time
  4. train LR 29 fitur + LightGBM 29 fitur
  5. compare di valid → rekomendasi champion
        │
        ▼
MLflow: parent run + 2 nested run + registered model
Gold: data/gold/models/temporal/<run_id>/
```

## Mengapa 39 fitur di Feast, 29 di model?

Feast menyimpan **39 fitur kandidat**: 24 fitur sel (termasuk `province`) dan
15 fitur cuaca/AQ. VIF adalah praproses milik model, bukan definisi fitur. Di
setiap training, VIF dijalankan pada train dan hasilnya wajib sama dengan daftar
29 fitur di `experiments/pipeline.yaml`. Kalau daftar bergeser, flow gagal
dengan pesan jelas supaya konfigurasi beku tidak berubah diam-diam.

## Kontrak tabel fitur

### `ml_feature_cell_day`

Grain `cell_id × date`.

- kunci/entity: `cell_id`, `province`, `event_timestamp`
- fitur: `CELL_FEATURE_COLUMNS` (23 kolom, lihat `ml.feature_publish`)
- label: `label`, `label_complete` (hanya untuk entity frame, bukan feature view)
- lineage: `created_timestamp`, `feature_version`

### `ml_feature_province_day`

Grain `province × date`.

- kunci/entity: `province`, `event_timestamp`
- fitur: `CONTEXT_COLUMNS` (15 kolom cuaca/AQ)
- lineage: `created_timestamp`, `feature_version`

`event_timestamp` dan `created_timestamp` dipakai Feast untuk point-in-time
join. Label, tier, burn date, gap days, dan kolom `audit_*` tidak pernah
didaftarkan sebagai fitur.

## Perintah

```bash
# pasang extra Feast
pip install -e ".[dev,ml,feast]"

# 1. bangun tabel fitur Gold
task ml-features

# 2. daftarkan definisi Feast dan isi online store
task feast-apply
task feast-materialize

# 3. latih satu model dari Feast (opsional, untuk debug)
task ml-train-feast -- --model lr --c 10 --no-test \
  --freeze-config experiments/lr-baseline.yaml \
  --out data/gold/models/debug-lr

# 4. jalankan pipeline penuh secara manual lewat Prefect
task ml-pipeline

# 5. daftarkan deployment manual ke Prefect server (tanpa jadwal)
#    rebuild worker dulu karena image perlu paket feast
docker compose -f compose/base.yml -f compose/vps-batch.yml build prefect-worker
task deploy
```

`task ml-pipeline` memakai profil `prefect-profiles.toml` dan Prefect API
ephemeral di lokal. Di server Prefect, jalankan deployment
`ml-temporal-training` lewat UI atau:

```bash
prefect deployment run "ml-temporal-training/default" \
  --param promote=false
```

## MLflow

Tracking URI mengikuti `MLFLOW_TRACKING_URI`. Di Compose, worker memakai
`http://mlflow:5000`; `task ml-pipeline` dari host memakai
`http://127.0.0.1:5000` (port MLflow dipublikasikan). Untuk menulis ke
`mlruns/` lokal, jalankan flow dengan `MLFLOW_TRACKING_URI` kosong. Tanpa
server, flow tetap menulis artefak Gold dan hanya melewati pencatatan MLflow.

Setiap pipeline membuat:

- satu parent run `temporal-pipeline-<run_id>`
- nested run `lr-temporal-29` dan `lgbm-temporal-29`
- registered model `karhutla-hotspot-cell-fire-lr` dan
  `karhutla-hotspot-cell-fire-lgbm`
- alias `candidate` pada versi baru masing-masing model
- tag `feature_source=feast`, `feature_service`, `feast_registry_hash`,
  `feature_table_hash`, `label_fingerprint`, `config_hash`

Alias `champion` hanya di-set bila flow dijalankan dengan `promote=true` dan
perbandingan valid menerima kandidat. Default `promote=false`: flow hanya
menulis rekomendasi ke `data/gold/models/temporal/champion.json`.

## Output Gold

```
data/gold/models/temporal/<run_id>/
  dataset/dataset.parquet
  dataset/dataset.joblib
  dataset/dataset_manifest.json
  lr-temporal-29/{pipeline.joblib, metrics.json, threshold.json, ...}
  lgbm-temporal-29/{model.joblib, metrics.json, threshold.json, ...}
  comparison.json
  pipeline_manifest.json
  registry.yaml

data/gold/models/temporal/runs.jsonl      # lineage tiap run
data/gold/models/temporal/champion.json   # rekomendasi champion
```

`comparison.json` memakai bootstrap blok tanggal (`ml.evaluate.
paired_bootstrap_delta`) dan metrik Brier. Kriteria default:

- delta PR-AUC valid ≥ 0,01
- batas bawah CI 95% > 0
- kandidat lebih baik di ≥ 3 dari 5 tanggal valid
- Brier tidak memburuk lebih dari 0,01

## Guardrail

- `test_policy=none`; tidak ada angka test yang diklaim.
- Feature view menolak label dan kolom audit.
- Baris `label_complete=false` tidak masuk training.
- Daftar 29 fitur setelah VIF dibandingkan dengan konfigurasi beku.
- Registry runtime ditulis ke folder run, bukan `experiments/registry.yaml`.
- MLflow opsional untuk run manual; deployment Prefect memakai
  `mlflow_required=true`.

## Troubleshooting

| Gejala | Perbaikan |
|---|---|
| `Tabel fitur sel tidak lengkap` | jalankan `task ml-features` |
| `Feast belum terpasang` | `pip install -e ".[feast]"` |
| `feature_store.yaml tidak ditemukan` | jalankan dari root repo atau set `FEAST_REPO_PATH` |
| `Konteks cuaca/AQ kosong` | jalankan `task silver-openmeteo` lalu `task dbt-build` |
| MLflow tidak bisa dihubungi | nyalakan service `mlflow` atau set `MLFLOW_TRACKING_URI` ke `mlruns/` |
| Daftar fitur bergeser | periksa data/konfigurasi VIF; perbarui freeze secara sadar, jangan paksa |
