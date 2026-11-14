"""Utilitas kecil: daftar objek Bronze FIRMS di Garage.

Dipakai oleh `task bronze-files` / `task bronze-lines`, dijalankan di dalam
container consumer supaya boto3 dan kredensial sudah tersedia.

    python stream/src/ls_bronze.py
    python stream/src/ls_bronze.py --count
    python stream/src/ls_bronze.py --prefix bronze/firms/dataset=hotspot/source=SELFTEST
"""
import argparse
import os

from common.config import GarageSettings
from common.storage import BronzeStore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", default=os.environ.get("BRONZE_PREFIX_FIRMS", "bronze/firms"))
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--count", action="store_true", help="hanya cetak jumlah objek")
    args = parser.parse_args()

    store = BronzeStore(GarageSettings.from_env())
    keys = store.list_keys(args.prefix.strip("/"))

    if args.count:
        print(len(keys))
        return

    for key in keys[: args.limit]:
        print(key)
    print(f"-- {len(keys)} objek di s3://{store.bucket}/{args.prefix.strip('/')}")


if __name__ == "__main__":
    main()
