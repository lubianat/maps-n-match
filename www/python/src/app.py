"""
Mix-n-Match place explorer · Flask backend
"""

from __future__ import annotations

import csv
import pathlib
from math import radians, sin, cos, asin
from functools import lru_cache
from typing import List, Dict, Any

from flask import Flask, render_template, request, abort
from SPARQLWrapper import SPARQLWrapper, JSON
from wdcuration import lookup_multiple_ids

import yaml

# ── configuration ─────────────────────────────────────────────────────────────

HERE = pathlib.Path(__file__).parent
DATA = HERE / "data"
INAT_FILE = DATA / "catalog_3900.tsv"
# Load catalog info from YAML file
CATALOG_INFO_FILE = DATA / "catalog_info.yml"
CATALOG_INFO = {}
with open(CATALOG_INFO_FILE, "r", encoding="utf-8") as f:
    CATALOG_INFO = yaml.safe_load(f)

EARTH_R_KM = 6371.0088  # mean Earth radius (km)

sparql = SPARQLWrapper("https://query.wikidata.org/sparql")
sparql.addCustomHttpHeader(
    "User-Agent",
    "mixnmatch-places/0.1 (+https://github.com/your-repo; email@example.com)",
)

app = Flask(__name__, template_folder="templates", static_folder="static")


# ── helpers ──────────────────────────────────────────────────────────────────
def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance (km)."""
    φ1, φ2 = radians(lat1), radians(lat2)
    Δφ, Δλ = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(Δφ / 2) ** 2 + cos(φ1) * cos(φ2) * sin(Δλ / 2) ** 2
    return 2 * EARTH_R_KM * asin(a**0.5)


@lru_cache(maxsize=1)
def load_catalog_entries(catalog_number) -> List[Dict[str, Any]]:
    """Parse TSV once per process → list[dict]."""
    rows: List[Dict[str, Any]] = []
    catalog_file = DATA / f"catalog_{catalog_number}.tsv"
    with catalog_file.open(encoding="utf-8") as fh:
        reader = csv.DictReader(
            (ln.lstrip("#") for ln in fh),
            delimiter="\t",
            quoting=csv.QUOTE_NONE,
        )
        for r in reader:
            try:
                lat, lon = float(r["lat"]), float(r["lon"])
            except (KeyError, ValueError):
                continue  # skip rows without coords

            rows.append(
                {
                    "entry_id": r["entry_id"],
                    "external_id": r["external_id"],
                    "external_url": r["external_url"],
                    "name": (r["name"] or r["description"]).strip('" ') or "Unnamed",
                    "lat": lat,
                    "lng": lon,
                }
            )
    return rows


def nearby_entries(
    lat: float, lon: float, radius_km: float, catalog_number
) -> List[Dict[str, Any]]:
    """Return catalog entries within *radius_km* of (lat, lon)."""
    lat, lon = float(lat), float(lon)
    return [
        e
        for e in load_catalog_entries(catalog_number)
        if _haversine(lat, lon, e["lat"], e["lng"]) <= radius_km
    ]


def fetch_images_for_qs(qs: List[str]) -> Dict[str, str]:
    """Return {Q-id: imageURL} for ids that have P18."""
    images: Dict[str, str] = {}
    if not qs:
        return images

    CHUNK = 400
    # TODO -- Refactor this to use wdcuration
    for i in range(0, len(qs), CHUNK):
        batch = qs[i : i + CHUNK]
        sparql.setQuery(
            f"""
            SELECT ?item ?image WHERE {{
              VALUES ?item {{ {' '.join('wd:' + q for q in batch)} }}
              OPTIONAL {{ ?item wdt:P18 ?image }}
            }}
            """
        )
        sparql.setReturnFormat(JSON)
        res = sparql.query().convert()["results"]["bindings"]
        for row in res:
            if "image" in row:
                qid = row["item"]["value"].split("/")[-1]
                images[qid] = row["image"]["value"]
    return images


# ── routes ───────────────────────────────────────────────────────────────────
@app.route("/")
def home():
    catalogs = CATALOG_INFO
    print(CATALOG_INFO)
    return render_template("index.html", catalogs=catalogs)


@app.route("/map")
def map_view():
    """Return a map page showing nearby catalogue entries,
    optionally filtered by Wikidata-matching status."""
    # ------------- Parse & validate query parameters -------------
    try:
        lat = float(request.args["lat"])
        lng = float(request.args["lng"])
    except (KeyError, ValueError):
        abort(400, "lat and lng parameters are required and must be numeric")

    catalog_key = request.args.get("catalog", "inat")
    print(CATALOG_INFO)
    catalog_meta = CATALOG_INFO.get(catalog_key)
    if catalog_meta is None:
        abort(400, f"Unknown catalog '{catalog_key}'")

    max_distance_km = float(request.args.get("dist", 25))
    show_filter = request.args.get("show_matched", "").lower()  # "", "yes", "no"

    # ------------- Pull nearby entries -------------
    entries = nearby_entries(
        lat, lng, max_distance_km, catalog_number=catalog_meta["id"]
    )

    # Optional filtering: matched-only or unmatched-only
    if show_filter == "yes":
        entries = [e for e in entries if e.get("q")]
    elif show_filter == "no":
        entries = [e for e in entries if not e.get("q")]

    # ------------- Enrich with Wikidata Q-IDs -------------
    property_id = catalog_meta["property"]
    id_to_qid = lookup_multiple_ids(
        list_of_ids=[e["external_id"] for e in entries],
        wikidata_property=property_id,
    )
    for e in entries:
        e["q"] = id_to_qid.get(e["external_id"], "")

    # ------------- Grab images where we now have Q-IDs -------------
    images_by_qid = fetch_images_for_qs([e["q"] for e in entries if e["q"]])

    # ------------- Build payload for the template -------------
    data = [
        {
            "locId": e["entry_id"],
            "locName": e["name"],
            "lat": e["lat"],
            "lng": e["lng"],
            "wikidata": f"https://www.wikidata.org/wiki/{e['q']}" if e["q"] else None,
            "image": images_by_qid.get(e["q"]) if e["q"] else None,
            "external_url": e["external_url"],
            "external_id": e["external_id"],
            "mnm": f"https://mix-n-match.toolforge.org/#/entry/{e['entry_id']}",
        }
        for e in entries
    ]

    return render_template("map.html", data=data, lat=lat, lng=lng)


@app.route("/about")
def about():
    return render_template("about.html")


# ── error pages ──────────────────────────────────────────────────────────────
@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


@app.errorhandler(500)
def internal(e):
    return render_template("500.html"), 500


# ── dev entry point ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
