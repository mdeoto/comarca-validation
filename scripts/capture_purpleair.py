#!/usr/bin/env python3

from pathlib import Path
from datetime import datetime
import csv
import os

import cv2
import numpy as np
import pytesseract
import yaml
from playwright.sync_api import sync_playwright


# ============================================================
# Configuración general
# ============================================================

PURPLEAIR_BASE_URL = "https://map.purpleair.com"

PURPLEAIR_OPTIONS = (
    "opt=%2F1%2Flp%2Fa10%2Fp604800%2FcC5"
)

# Traducción entre nuestros productos configurables y
# las rutas utilizadas por el mapa de PurpleAir.
#
# Si mañana aparece, por ejemplo, PM1:
#
#   "raw_pm1": "air-quality-raw-pm1",
#
PRODUCT_PATHS = {
    "raw_pm25": "air-quality-raw-pm25",
    "raw_pm10": "air-quality-raw-pm10",
}

VIEWPORT = {
    "width": 1200,
    "height": 900,
}

CONFIG_FILE = Path("config/sites.yaml")

DEBUG_DIR = Path("data/debug/purpleair")
DATA_DIR = Path("data/observations/purpleair")

MIN_RADIUS = 150
MAX_RADIUS = 230

# Rango admisible para la lectura visual.
# No es QC científico: evita aceptar basura evidente del OCR.
OCR_MIN_VALUE = 0
OCR_MAX_VALUE = 500


# ============================================================
# Configuración de sitios
# ============================================================

def load_sites():
    with CONFIG_FILE.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    return cfg["sites"]


def get_enabled_variables(aq):
    """
    Devuelve las variables habilitadas para este instrumento.

    Ejemplo:
        pm25 -> raw_pm25
        pm10 -> raw_pm10
    """

    variables = aq.get("variables", {})

    enabled = {}

    for variable, config in variables.items():

        if not config.get("enabled", True):
            continue

        map_product = config.get("map_product")

        if not map_product:
            continue

        enabled[variable] = config

    return enabled


def build_url(capture, map_product):

    if map_product not in PRODUCT_PATHS:
        raise ValueError(
            f"Producto PurpleAir desconocido: {map_product}"
        )

    product_path = PRODUCT_PATHS[map_product]

    url = (
        f"{PURPLEAIR_BASE_URL}/{product_path}"
        f"?{PURPLEAIR_OPTIONS}"
    )

    if capture.get("select") is not None:
        url += f"&select={capture['select']}"

    url += (
        f"#{capture['zoom']}/"
        f"{capture['latitude']}/"
        f"{capture['longitude']}"
    )

    return url


# ============================================================
# PurpleAir / navegador
# ============================================================

def close_cookie_banner(page):

    try:

        page.get_by_role(
            "button",
            name="Reject All",
        ).click(timeout=5000)

        page.wait_for_timeout(1000)

    except Exception:
        pass


# ============================================================
# Imagen
# ============================================================

def make_zoom(full_file, zoom_file):

    img = cv2.imread(str(full_file))

    if img is None:
        raise RuntimeError(
            "No se pudo leer la captura"
        )

    h, w = img.shape[:2]

    cx = w // 2
    cy = h // 2

    crop = img[
        cy - 100:cy + 100,
        cx - 100:cx + 100,
    ]

    zoom = cv2.resize(
        crop,
        None,
        fx=8,
        fy=8,
        interpolation=cv2.INTER_CUBIC,
    )

    if not cv2.imwrite(
        str(zoom_file),
        zoom,
    ):
        raise RuntimeError(
            f"No se pudo escribir {zoom_file}"
        )

    return zoom


def detect_marker(img):

    hsv = cv2.cvtColor(
        img,
        cv2.COLOR_BGR2HSV,
    )

    # Hue completo.
    # No dependemos del color del marcador, porque PurpleAir
    # cambia el color según la concentración.
    mask = cv2.inRange(
        hsv,
        np.array([0, 80, 80]),
        np.array([179, 255, 255]),
    )

    contours, _ = cv2.findContours(
        mask,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )

    if not contours:
        return None

    contour = max(
        contours,
        key=cv2.contourArea,
    )

    (x, y), radius = cv2.minEnclosingCircle(
        contour
    )

    return (
        int(x),
        int(y),
        int(radius),
    )


# ============================================================
# OCR
# ============================================================

def read_value(img, marker):
    """
    Lee el número contenido dentro del marcador.

    Esta función no sabe si está leyendo PM2.5, PM10 o PM1.
    La variable queda determinada por el producto que se
    mostró previamente en el mapa.
    """

    x, y, radius = marker

    if not MIN_RADIUS <= radius <= MAX_RADIUS:
        return None, [], 0, "bad_radius"

    r = int(radius * 0.58)

    y1 = max(0, y - r)
    y2 = min(img.shape[0], y + r)

    x1 = max(0, x - r)
    x2 = min(img.shape[1], x + r)

    number = img[
        y1:y2,
        x1:x2,
    ]

    gray = cv2.cvtColor(
        number,
        cv2.COLOR_BGR2GRAY,
    )

    variants = {
        "gray": gray,

        "thr80": cv2.threshold(
            gray,
            80,
            255,
            cv2.THRESH_BINARY,
        )[1],

        "thr100": cv2.threshold(
            gray,
            100,
            255,
            cv2.THRESH_BINARY,
        )[1],

        "thr120": cv2.threshold(
            gray,
            120,
            255,
            cv2.THRESH_BINARY,
        )[1],

        "otsu": cv2.threshold(
            gray,
            0,
            255,
            cv2.THRESH_BINARY + cv2.THRESH_OTSU,
        )[1],
    }

    candidates = []

    for variant in variants.values():

        test = cv2.resize(
            variant,
            None,
            fx=3,
            fy=3,
            interpolation=cv2.INTER_CUBIC,
        )

        text = pytesseract.image_to_string(
            test,
            config=(
                "--psm 10 "
                "-c tessedit_char_whitelist=0123456789"
            ),
        ).strip()

        if not text.isdigit():
            continue

        value = int(text)

        if OCR_MIN_VALUE <= value <= OCR_MAX_VALUE:
            candidates.append(value)

    if not candidates:
        return None, [], 0, "ocr_fail"

    values, counts = np.unique(
        candidates,
        return_counts=True,
    )

    index = np.argmax(counts)

    best = int(values[index])
    votes = int(counts[index])

    # Requerimos al menos dos variantes coincidentes.
    if votes < 2:
        return (
            None,
            candidates,
            votes,
            "ocr_uncertain",
        )

    return (
        best,
        candidates,
        votes,
        "ok",
    )


# ============================================================
# Captura de una variable
# ============================================================

def capture_variable(
    page,
    site_id,
    variable,
    variable_config,
    capture,
    timestamp_file,
):

    map_product = variable_config["map_product"]

    url = build_url(
        capture,
        map_product,
    )

    full_file = (
        DEBUG_DIR /
        f"{site_id}_{variable}_{timestamp_file}_full.png"
    )

    zoom_file = (
        DEBUG_DIR /
        f"{site_id}_{variable}_{timestamp_file}_zoom.png"
    )

    result = {
        "value": None,
        "status": "capture_fail",
        "radius": None,
        "votes": 0,
        "n_candidates": 0,
    }

    try:

        page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=90000,
        )

        page.wait_for_timeout(15000)

        close_cookie_banner(page)

        page.wait_for_timeout(3000)

        page.screenshot(
            path=str(full_file),
            full_page=False,
        )

        img = make_zoom(
            full_file,
            zoom_file,
        )

        marker = detect_marker(img)

        if marker is None:

            result["status"] = "no_marker"
            return result

        _, _, radius = marker

        (
            value,
            candidates,
            votes,
            status,
        ) = read_value(
            img,
            marker,
        )

        result.update({
            "value": value,
            "status": status,
            "radius": radius,
            "votes": votes,
            "n_candidates": len(candidates),
        })

        return result

    except Exception as exc:

        result["status"] = "capture_fail"
        result["error"] = str(exc)

        return result

    finally:

        # Las imágenes son solamente material intermedio.
        remove_file(full_file)
        remove_file(zoom_file)


# ============================================================
# Dataset
# ============================================================

def build_csv_fields(variables):

    fields = ["timestamp"]

    for variable in variables:

        fields.extend([
            variable,
            f"{variable}_status",
            f"{variable}_radius",
            f"{variable}_votes",
            f"{variable}_n_candidates",
        ])

    return fields


def append_observation(
    site_id,
    timestamp,
    variables,
    results,
):
    """
    Agrega una observación al dataset de una estación mediante
    escritura atómica.

    El CSV original nunca se modifica directamente:

        CSV actual
            -> archivo temporal
            -> flush + fsync
            -> os.replace()

    Si el proceso muere antes de os.replace(), el CSV histórico
    permanece intacto.
    """

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    csv_file = DATA_DIR / f"{site_id}.csv"
    tmp_file = DATA_DIR / f".{site_id}.csv.tmp"

    fields = build_csv_fields(variables)

    row = {
        "timestamp": timestamp,
    }

    for variable in variables:

        result = results[variable]
        value = result["value"]

        row[variable] = (
            "" if value is None else value
        )

        row[f"{variable}_status"] = (
            result["status"]
        )

        row[f"{variable}_radius"] = (
            ""
            if result["radius"] is None
            else result["radius"]
        )

        row[f"{variable}_votes"] = (
            result["votes"]
        )

        row[f"{variable}_n_candidates"] = (
            result["n_candidates"]
        )

    # --------------------------------------------------------
    # Leer histórico existente
    # --------------------------------------------------------

    existing_rows = []

    if csv_file.exists():

        with csv_file.open(
            "r",
            newline="",
            encoding="utf-8",
        ) as f:

            reader = csv.DictReader(f)

            # Evitamos mezclar estructuras diferentes si
            # cambia la configuración de variables.
            if reader.fieldnames != fields:
                raise RuntimeError(
                    f"Header incompatible en {csv_file}: "
                    f"{reader.fieldnames} != {fields}"
                )

            existing_rows = list(reader)

    existing_rows.append(row)

    # --------------------------------------------------------
    # Escribir archivo temporal completo
    # --------------------------------------------------------

    try:

        with tmp_file.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as f:

            writer = csv.DictWriter(
                f,
                fieldnames=fields,
            )

            writer.writeheader()
            writer.writerows(existing_rows)

            f.flush()
            os.fsync(f.fileno())

        # Reemplazo atómico dentro del mismo filesystem.
        os.replace(
            tmp_file,
            csv_file,
        )

    finally:

        # Si algo falló antes del replace, eliminamos solamente
        # el temporal. El CSV histórico permanece intacto.
        try:
            tmp_file.unlink()
        except FileNotFoundError:
            pass

    return csv_file


# ============================================================
# Limpieza
# ============================================================

def remove_file(path):

    try:
        path.unlink()

    except FileNotFoundError:
        pass


# ============================================================
# Main
# ============================================================

def main():

    sites = load_sites()

    DEBUG_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    now = datetime.now().astimezone()

    timestamp_iso = now.isoformat(
        timespec="seconds"
    )

    timestamp_file = now.strftime(
        "%Y%m%d_%H%M%S"
    )

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True
        )

        page = browser.new_page(
            viewport=VIEWPORT,
            device_scale_factor=1,
        )

        for site_id, site in sites.items():

            aq = site.get(
                "instruments",
                {},
            ).get(
                "air_quality"
            )

            if not aq:
                continue

            if aq.get("provider") != "purpleair":
                continue

            variables = get_enabled_variables(aq)

            if not variables:
                continue

            capture = aq["capture"]

            results = {}

            print()
            print("=" * 60)
            print(site["name"])
            print("=" * 60)

            for variable, variable_config in variables.items():

                print()
                print(f"  [{variable}]")

                result = capture_variable(
                    page=page,
                    site_id=site_id,
                    variable=variable,
                    variable_config=variable_config,
                    capture=capture,
                    timestamp_file=timestamp_file,
                )

                results[variable] = result

                print(
                    f"    value:      {result['value']}"
                )
                print(
                    f"    status:     {result['status']}"
                )
                print(
                    f"    votes:      {result['votes']}"
                )
                print(
                    f"    radius:     {result['radius']}"
                )
                print(
                    "    candidates: "
                    f"{result['n_candidates']}"
                )

                if result.get("error"):
                    print(
                        f"    error:      {result['error']}"
                    )

            csv_file = append_observation(
                site_id=site_id,
                timestamp=timestamp_iso,
                variables=list(variables.keys()),
                results=results,
            )

            print()
            print(f"  CSV: {csv_file}")

        browser.close()


if __name__ == "__main__":
    main()
