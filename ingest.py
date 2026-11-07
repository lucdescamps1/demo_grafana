"""Ingestion du jeu de données NASA IMS Bearing dans InfluxDB 2.x.

Usage :
    python ingest.py --data-dir data/2nd_test
    python ingest.py --data-dir data/2nd_test --dry-run   # sans InfluxDB
"""
import argparse
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import kurtosis

FILENAME_FORMAT = "%Y.%m.%d.%H.%M.%S"


def parse_timestamp(name: str):
    try:
        return datetime.strptime(name, FILENAME_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def compute_features(signal: np.ndarray) -> dict:
    rms = float(np.sqrt(np.mean(signal ** 2)))
    peak = float(np.max(np.abs(signal)))
    return {
        "rms": rms,
        "kurtosis": float(kurtosis(signal, fisher=False)),
        "peak": peak,
        "crest_factor": peak / rms if rms > 0 else 0.0,
    }


def tags_for_channel(i: int, n_cols: int) -> dict:
    # 2nd/3rd test : 4 colonnes = 4 roulements.
    # 1st test : 8 colonnes = 2 axes (x, y) par roulement.
    if n_cols == 8:
        return {"bearing": f"bearing_{i // 2 + 1}", "axis": "x" if i % 2 == 0 else "y"}
    return {"bearing": f"bearing_{i + 1}", "axis": "x"}


def iter_points(data_dir: Path):
    files = sorted(p for p in data_dir.iterdir() if p.is_file() and parse_timestamp(p.name))
    if not files:
        raise SystemExit(f"Aucun fichier de mesure trouvé dans {data_dir}")
    for n, path in enumerate(files, 1):
        ts = parse_timestamp(path.name)
        df = pd.read_csv(path, sep=r"\s+", header=None, engine="c")
        values = df.to_numpy(dtype=float)
        for i in range(values.shape[1]):
            yield {
                "measurement": "vibration",
                "tags": tags_for_channel(i, values.shape[1]),
                "fields": compute_features(values[:, i]),
                "time": ts,
            }
        if n % 100 == 0:
            print(f"  {n}/{len(files)} fichiers traités")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True, type=Path)
    ap.add_argument("--dry-run", action="store_true", help="affiche quelques points sans écrire")
    ap.add_argument("--batch-size", type=int, default=500)
    args = ap.parse_args()

    if args.dry_run:
        for k, point in enumerate(iter_points(args.data_dir)):
            print(point)
            if k >= 7:
                break
        return

    from influxdb_client import InfluxDBClient, WritePrecision
    from influxdb_client.client.write_api import SYNCHRONOUS

    url = os.getenv("INFLUX_URL", "http://localhost:8086")
    token = os.getenv("INFLUX_TOKEN", "my-super-token")
    org = os.getenv("INFLUX_ORG", "demo")
    bucket = os.getenv("INFLUX_BUCKET", "bearings")

    total = 0
    with InfluxDBClient(url=url, token=token, org=org) as client:
        write_api = client.write_api(write_options=SYNCHRONOUS)
        batch = []
        for point in iter_points(args.data_dir):
            batch.append(point)
            if len(batch) >= args.batch_size:
                write_api.write(bucket=bucket, record=batch, write_precision=WritePrecision.S)
                total += len(batch)
                batch = []
        if batch:
            write_api.write(bucket=bucket, record=batch, write_precision=WritePrecision.S)
            total += len(batch)
    print(f"Terminé : {total} points écrits dans le bucket '{bucket}'.")


if __name__ == "__main__":
    main()
