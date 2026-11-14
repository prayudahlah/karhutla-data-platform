# Contributing

## Branch

- `feat/F-04-stream-consumer`
- `fix/short-description`
- `docs/short-description`
- `chore/short-description`

## Commit

Gunakan conventional commits:

- `feat:`
- `fix:`
- `docs:`
- `test:`
- `refactor:`
- `chore:`

## Pull request

- Satu PR untuk satu tujuan.
- Isi template PR.
- Minimal satu review.
- CI harus hijau.
- Update `evidence/README.md` kalau menyentuh requirement F-xx.

## Test

```bash
task lint
task test
task coverage
```

## Secret dan data

- Jangan commit `.env`.
- Jangan commit data mentah, model, log, atau video besar.
- Gunakan `.env.example` untuk variabel.
- Data dan model disimpan di MinIO.
