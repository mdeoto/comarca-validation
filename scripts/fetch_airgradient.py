#!/usr/bin/env python3

from pathlib import Path
from datetime import datetime
import csv
import json
import os
import sys
import tempfile
import urllib.parse
import urllib.request

import yaml


# ============================================================
# Configuración
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

CONFIG_FILE = BASE_DIR / "config/sites.yaml"
DATA_DIR = BASE_DIR / "data/observations/airgradient"

API_BASE = (
    "https://api.airgradient.com/public/api/v1/"
    "locations/{location_id}/measures/current"
)

CSV_FIELDS = [
    "timestamp",
    "fetch_timestamp",

    "pm01",
    "pm02",
    "pm10",

    "pm01_corrected",
    "pm02_corrected",
    "pm10_corrected",

    "pm003_count",

    "temperature",
    "temperature_corrected",

    "relative_humidity",
    "relative_humidity_corrected",

    "co2",
    "co2_corrected",

    "tvoc",
    "tvoc_index",
    "nox_index",

    "wifi",

    "battery_voltage",
    "panel_voltage",
]


# ============================================================
# Configuración de sitios
# ============================================================

def load_airgradient_sites():

    with CONFIG_FILE.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    result = {}

    for site_id, site in cfg["sites"].items():

        aq = (
            site.get("instruments", {})
            .get("air_quality")
        )

        if not aq:
            continue

        if aq.get("provider") != "airgradient":
            continue

        result[site_id] = site

    return result


# ============================================================
# API
# ============================================================

def fetch_current(location_id, token):

    endpoint = API_BASE.format(
        location_id=location_id
    )

    query = urllib.parse.urlencode({
        "token": token,
    })

    url = f"{endpoint}?{query}"

    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "comarca-validation/1.0",
        },
    )

    with urllib.request.urlopen(
        request,
        timeout=30,
    ) as response:

        payload = response.read()

    data = json.loads(
        payload.decode("utf-8")
    )

    if "errors" in data:
        raise RuntimeError(
            f"AirGradient API error: {data['errors']}"
        )

    return data


# ============================================================
# Conversión API -> dataset
# ============================================================

def make_row(data):

    fetch_timestamp = (
        datetime.now()
        .astimezone()
        .isoformat(timespec="seconds")
    )

    return {
        "timestamp":
            data.get("timestamp"),

        "fetch_timestamp":
            fetch_timestamp,

        "pm01":
            data.get("pm01"),

        "pm02":
            data.get("pm02"),

        "pm10":
            data.get("pm10"),

        "pm01_corrected":
            data.get("pm01_corrected"),

        "pm02_corrected":
            data.get("pm02_corrected"),

        "pm10_corrected":
            data.get("pm10_corrected"),

        "pm003_count":
            data.get("pm003Count"),

        "temperature":
            data.get("atmp"),

        "temperature_corrected":
            data.get("atmp_corrected"),

        "relative_humidity":
            data.get("rhum"),

        "relative_humidity_corrected":
            data.get("rhum_corrected"),

        "co2":
            data.get("rco2"),

        "co2_corrected":
            data.get("rco2_corrected"),

        "tvoc":
            data.get("tvoc"),

        "tvoc_index":
            data.get("tvocIndex"),

        "nox_index":
            data.get("noxIndex"),

        "wifi":
            data.get("wifi"),

        "battery_voltage":
            data.get("batteryVoltage"),

        "panel_voltage":
            data.get("panelVoltage"),
    }


# ============================================================
# Escritura segura
# ============================================================

def write_observation(csv_file, row):

    csv_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    existing_rows = []

    if csv_file.exists():

        with csv_file.open(
            newline="",
            encoding="utf-8",
        ) as f:

            reader = csv.DictReader(f)

            if reader.fieldnames != CSV_FIELDS:
                raise RuntimeError(
                    f"Esquema inesperado en {csv_file}"
                )

            existing_rows = list(reader)

        # Evitar duplicar exactamente la misma observación
        # si AirGradient todavía no publicó una nueva medida.
        if existing_rows:

            last_timestamp = (
                existing_rows[-1].get("timestamp")
            )

            if last_timestamp == row["timestamp"]:
                return False

    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{csv_file.name}.",
        suffix=".tmp",
        dir=csv_file.parent,
        text=True,
    )

    tmp_file = Path(tmp_name)

    try:

        with os.fdopen(
            fd,
            "w",
            newline="",
            encoding="utf-8",
        ) as f:

            writer = csv.DictWriter(
                f,
                fieldnames=CSV_FIELDS,
            )

            writer.writeheader()

            for old_row in existing_rows:
                writer.writerow(old_row)

            writer.writerow(row)

            f.flush()
            os.fsync(f.fileno())

        os.replace(
            tmp_file,
            csv_file,
        )

    except Exception:

        try:
            tmp_file.unlink()
        except FileNotFoundError:
            pass

        raise

    return True


# ============================================================
# Main
# ============================================================

def main():

    token = os.environ.get(
        "AIRGRADIENT_API_TOKEN"
    )

    if not token:
        print(
            "ERROR: AIRGRADIENT_API_TOKEN no definido",
            file=sys.stderr,
        )
        return 1

    sites = load_airgradient_sites()

    if not sites:
        print(
            "ERROR: no hay sitios AirGradient configurados",
            file=sys.stderr,
        )
        return 1

    failed = False

    for site_id, site in sites.items():

        aq = site["instruments"]["air_quality"]

        location_id = aq.get("location_id")

        print()
        print("=" * 60)
        print(site["name"])
        print("=" * 60)

        try:

            data = fetch_current(
                location_id=location_id,
                token=token,
            )

            # Protección básica contra mezclar locations.
            returned_id = data.get("locationId")

            if returned_id != location_id:
                raise RuntimeError(
                    "Location ID devuelto por API "
                    f"({returned_id}) != configurado "
                    f"({location_id})"
                )

            row = make_row(data)

            csv_file = (
                DATA_DIR /
                f"{site_id}.csv"
            )

            written = write_observation(
                csv_file,
                row,
            )

            print(
                f"  timestamp: {row['timestamp']}"
            )

            print(
                f"  PM2.5:     {row['pm02_corrected']}"
            )

            print(
                f"  PM10:      {row['pm10_corrected']}"
            )

            print(
                "  Temp.:     "
                f"{row['temperature_corrected']}"
            )

            print(
                "  RH:        "
                f"{row['relative_humidity_corrected']}"
            )

            print(
                f"  CO2:       {row['co2_corrected']}"
            )

            print(
                f"  CSV:       {csv_file}"
            )

            if written:
                print("  status:    written")
            else:
                print("  status:    duplicate_skipped")

        except Exception as exc:

            failed = True

            print(
                f"  ERROR: {exc}",
                file=sys.stderr,
            )

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
