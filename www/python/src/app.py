"""
Mix-n-Match place explorer · Flask backend
-----------------------------------------

Reads the 2025-05-01 iNaturalist Mix-n-Match catalog TSV and serves a Leaflet
map.  Markers are:

    blue  – already linked to a Wikidata item (has q-id)
    red   – not yet linked

Query string parameters accepted by /map
----------------------------------------
lat=<float>           centre latitude          (required)
lng=<float>           centre longitude         (required)
dist=<float>          search radius in km      (default 25)
show_matched=yes|no   'yes' → show only blue
                      'no'  → show only red
                      omitted → show all
"""

from __future__ import annotations

import csv
import pathlib
from math import radians, sin, cos, asin
from functools import lru_cache
from typing import List, Dict, Any

from flask import Flask, render_template, request, abort
from SPARQLWrapper import SPARQLWrapper, JSON

# ── configuration ─────────────────────────────────────────────────────────────
INAT_FILE = pathlib.Path(
    "/home/lubianat/Documents/wiki_related/inat-maps-n-match/www/python/src/"
    "inat_mix_n_match_2025_05_01.txt"
)
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
def load_inat_entries() -> List[Dict[str, Any]]:
    """Parse TSV once per process → list[dict]."""
    rows: List[Dict[str, Any]] = []
    with INAT_FILE.open(encoding="utf-8") as fh:
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
                    "q": r["q"].strip() if r.get("q") else None,
                }
            )
    return rows


def nearby_entries(lat: float, lon: float, radius_km: float) -> List[Dict[str, Any]]:
    """Return catalog entries within *radius_km* of (lat, lon)."""
    lat, lon = float(lat), float(lon)
    return [
        e
        for e in load_inat_entries()
        if _haversine(lat, lon, e["lat"], e["lng"]) <= radius_km
    ]


def fetch_images_for_qs(qs: List[str]) -> Dict[str, str]:
    """Return {Q-id: imageURL} for ids that have P18."""
    images: Dict[str, str] = {}
    if not qs:
        return images

    CHUNK = 400
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
    return render_template("index.html")


@app.route("/map")
def map_view():
    # -------------------------------- parameters
    lat = request.args.get("lat")
    lng = request.args.get("lng")
    if lat is None or lng is None:
        abort(400, "lat and lng parameters are required")

    dist = float(request.args.get("dist", 25))
    show = request.args.get("show_matched", "").lower()  # "", "yes", "no"

    # -------------------------------- data slice
    pts = nearby_entries(lat, lng, dist)

    if show == "yes":
        pts = [p for p in pts if p["q"]]  # show only matched
    elif show == "no":
        pts = [p for p in pts if not p["q"]]  # show only unmatched

    # -------------------------------- optional images
    images_by_q = fetch_images_for_qs([p["q"] for p in pts if p["q"]])

    # -------------------------------- payload for template
    data = [
        {
            "locId": p["entry_id"],
            "locName": p["name"],
            "lat": p["lat"],
            "lng": p["lng"],
            "wikidata": f"https://www.wikidata.org/wiki/{p['q']}" if p["q"] else None,
            "image": images_by_q.get(p["q"]) if p["q"] else None,
            "external_url": p["external_url"],
            "external_id": p["external_id"],
            "mnm": f"https://mix-n-match.toolforge.org/#/entry/{p['entry_id']}",
        }
        for p in pts
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
