#!/usr/bin/env python3
"""Build the ranked list of Colorado's unplugged orphan wells from public data.

The script downloads two public datasets, joins them, scores every well, and
writes one CSV row per well:

1. ECMC's Orphaned Well Program shapefile (OWP_SHP.ZIP, refreshed daily).
   Records with OWPStatus "Unplugged" are the unplugged orphan well list.
2. CDPHE's Colorado EnviroScreen 2.0 census block groups, which carry the
   November 2024 Disproportionately Impacted (DI) community designation,
   the EnviroScreen percentile, and block group population.

Each well is placed in its block group by point-in-polygon and given a
priority score out of 100 in three parts: community burden (40), population
exposure (30), and deliverability (30).  The README describes each part.

Downloads are saved in ip/downloads/ and reused on later runs unless
--refresh is given.  A JSON file written next to the output CSV records the
source URLs, retrieval times, and file checksums.

Usage:
    python build_ranked_wells.py [--out PATH] [--refresh] [--contact ADDR]
    python build_ranked_wells.py --owp-zip OWP_SHP.zip --blockgroups bg.geojson
"""

import argparse
import hashlib
import io
import json
import logging
import math
import struct
import sys
import time
import zipfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import requests

from common import (
    BACKOFF_S,
    DELAY_S,
    MAX_ATTEMPTS,
    REPO_ROOT,
    RETRY_STATUSES,
    TIMEOUT_S,
    configure_logging,
    make_session,
    resolve_contact,
    write_csv,
    write_text_atomic,
)

log = logging.getLogger(__name__)

# Sources.  ECMC's ArcGIS map services now require a sign-in token (checked
# November 2026), so the well list comes from the shapefile download, which
# holds the same records.
OWP_URL = "https://ecmc.state.co.us/documents/data/downloads/gis/OWP_SHP.ZIP"
CDPHE_LAYER_URL = (
    "https://services3.arcgis.com/66aUo8zsujfVXRIT/ArcGIS/rest/services/"
    "EJP_Main_English_v1_BlockGroup_20230803/FeatureServer/0"
)
CDPHE_FIELDS = (
    "GEOID",
    "Cnt_N",
    "ES_S_",
    "POCFlag",
    "LIFlag",
    "LEPFlag",
    "HCBFlag",
    "ESFlag",
    "Justice40F",
    "TJ",
    "D_I_C",
    "DIType",
    "Ttl_P",
)
CDPHE_PAGE_SIZE = 2000  # the layer's maxRecordCount
UNPLUGGED = "Unplugged"

DEFAULT_OUT = REPO_ROOT / "ip" / "CO_Orphan_Wells_EJ_Ranked_Wells.csv"
DOWNLOAD_DIR = REPO_ROOT / "ip" / "downloads"
OWP_FILE = "OWP_SHP.zip"
BLOCKGROUP_FILE = "enviroscreen_v2_blockgroups.geojson"

# The seven statutory DI criteria, in the order CDPHE lists them.  A block
# group meeting any of them is a DI community; DIType names the one it meets,
# or "More than one category".
DI_CRITERIA = (
    "POCFlag",  # people of color above 40%
    "LIFlag",  # low income above 40%
    "LEPFlag",  # linguistically isolated above 20%
    "HCBFlag",  # housing cost burdened above 50%
    "ESFlag",  # EnviroScreen percentile above 80
    "Justice40F",  # in a federal Justice40 census tract
    "TJ",  # under tribal jurisdiction
)
NOT_DI = "N/A"

# Scoring.  Community burden, up to 40 points.
DI_POINTS = 20.0
POINTS_PER_CRITERION = 2.0
CRITERIA_POINTS_CAP = 10.0
ES_POINTS = 10.0  # scaled on the EnviroScreen percentile (0 to 100)
NEAR_DI_POINTS = 8.0  # flat score for a non-DI well near a DI block group
# Population exposure, up to 30 points.
DENSITY_POINTS = 20.0
DENSITY_FULL_PER_KM2 = 100.0  # log scale, log10(1 + d) / log10(100)
POPULATION_POINTS = 10.0
POPULATION_FULL = 3000.0
# Deliverability, up to 30 points.
CLUSTER_POINTS = 15.0
CLUSTER_FULL = 50  # same-project wells within CLUSTER_RADIUS_KM, log scale
CLUSTER_RADIUS_KM = 5.0
JURISDICTION_POINTS = 15.0
FED_MINERALS_POINTS = 8.0  # fee or state surface over federal minerals
FED_SURFACE_POINTS = 4.0  # federal surface, whatever the minerals
TRIBAL = frozenset({"Tribal", "Indian"})
# Tiers, by the rounded priority score.
TIER_CUTOFFS = (55.0, 45.0, 30.0)  # tier 1 at 55 and above, ..., tier 4 below 30

BOUNDARY_M = 300.0
DI_EDGE_FLAG = "DI edge <300m"  # DI well within 300 m of a non-DI block group
NEAR_DI_FLAG = "near DI <300m"  # non-DI well within 300 m of a DI block group

EARTH_RADIUS_KM = 6371.0088  # mean radius, for well-to-well distances
AUTHALIC_RADIUS_M = 6371007.2  # equal-area sphere, for block group areas
M_PER_DEG_LAT = 110574.0  # local flat-earth scale for the 300 m boundary test
M_PER_DEG_LON_EQUATOR = 111320.0
SEARCH_MARGIN_DEG = 0.01  # bounding box slack for the boundary search, ~1 km
SQ_M_PER_KM2 = 1e6

# Colorado's extent, with a little slack, for a sanity check on coordinates.
CO_LAT = (36.9, 41.1)
CO_LON = (-109.1, -102.0)

COLUMNS = (
    "Rank",
    "Tier",
    "Priority_Score",
    "API_10",
    "WellName",
    "Project",
    "County",
    "Lat",
    "Lon",
    "Surface",
    "Minerals",
    "DI_Community_Nov2024",
    "DI_Type",
    "DI_Criteria_Count",
    "EnviroScreen2_Pctl",
    "BG_GEOID",
    "BG_Pop",
    "BG_PopDensity_km2",
    "Cluster_Size_5km",
    "Score_Community",
    "Score_Exposure",
    "Score_Deliverability",
    "Boundary_Flag",
)

Ring = list[tuple[float, float]]  # (lon, lat) vertices, first equal to last


HTTP_ERROR = 400  # statuses from here up are failures
DBF_BLOCK = 32  # dBASE header and each field descriptor are 32 bytes
DBF_FIELDS_END = b"\r"  # marks the end of the field descriptors


class GetResponse(Protocol):
    """The parts of requests.Response the downloads use."""

    @property
    def status_code(self) -> int:
        """The HTTP status code."""

    @property
    def content(self) -> bytes:
        """The raw response body."""


class GetSession(Protocol):
    """The part of requests.Session the downloads use."""

    def get(
        self, url: str, *, params: Mapping[str, str] | None = None, timeout: float
    ) -> GetResponse:
        """Send a GET request."""


@dataclass(frozen=True)
class Well:
    """One unplugged orphan well from the ECMC OWP shapefile."""

    api_10: str
    well_name: str
    project: str
    surface: str
    minerals: str
    lat_text: str  # kept as published, for the output
    lon_text: str

    @property
    def lat(self) -> float:
        """Latitude in decimal degrees."""
        return float(self.lat_text)

    @property
    def lon(self) -> float:
        """Longitude in decimal degrees."""
        return float(self.lon_text)

    @property
    def county_fips(self) -> str:
        """The 3 digit county code from the API number."""
        return self.api_10[3:6]


@dataclass
class BlockGroup:
    """One EnviroScreen 2.0 census block group."""

    geoid: str
    county: str
    es_pctl: float
    criteria: int  # number of DI criteria met
    di_type: str
    population: float
    rings: list[Ring]
    area_km2: float = 0.0
    bbox: tuple[float, float, float, float] = field(default=(0.0, 0.0, 0.0, 0.0))

    def __post_init__(self) -> None:
        """Compute the area and bounding box from the rings."""
        self.area_km2 = polygon_area_m2(self.rings) / SQ_M_PER_KM2
        xs = [x for ring in self.rings for x, _ in ring]
        ys = [y for ring in self.rings for _, y in ring]
        self.bbox = (min(xs), min(ys), max(xs), max(ys))

    @property
    def is_di(self) -> bool:
        """True for a November 2024 Disproportionately Impacted community."""
        return self.di_type not in ("", NOT_DI)

    @property
    def density_km2(self) -> float:
        """People per square kilometer."""
        return self.population / self.area_km2 if self.area_km2 > 0 else 0.0


# ---------------------------------------------------------------------------
# Reading the sources


def read_dbf(data: bytes, encoding: str = "cp1252") -> list[dict[str, str]]:
    """Read a dBASE table, the attribute part of a shapefile, as text.

    Every value comes back as a stripped string; callers convert the fields
    they use.  Records marked deleted are skipped.

    Args:
        data: The whole .dbf file.
        encoding: Text encoding.  ECMC's files declare Windows ANSI.

    Returns:
        One dict per record, keyed by field name.
    """
    n_records, header_size, record_size = struct.unpack("<IHH", data[4:12])
    fields: list[tuple[str, int]] = []
    pos = DBF_BLOCK
    while data[pos : pos + 1] != DBF_FIELDS_END:
        descriptor = data[pos : pos + DBF_BLOCK]
        name = descriptor[:11].split(b"\x00")[0].decode("ascii")
        fields.append((name, descriptor[16]))  # byte 16 is the field width
        pos += DBF_BLOCK
    rows = []
    for i in range(n_records):
        start = header_size + i * record_size
        record = data[start : start + record_size]
        if record[:1] == b"*":
            continue
        row, offset = {}, 1  # byte 0 is the deletion flag
        for name, width in fields:
            raw = record[offset : offset + width]
            row[name] = raw.decode(encoding, errors="replace").strip()
            offset += width
        rows.append(row)
    return rows


def read_owp_records(zip_bytes: bytes) -> list[dict[str, str]]:
    """Return the "Unplugged" records from ECMC's OWP_SHP.ZIP, as text.

    The zip also holds plugged wells and orphaned sites; only records with
    OWPStatus "Unplugged" are the unplugged orphan well list.

    Args:
        zip_bytes: The downloaded zip file.

    Returns:
        One dict per unplugged well, keyed by the shapefile's field names,
        in file order.

    Raises:
        ValueError: If the zip doesn't hold exactly one .dbf, or an unplugged
            record has no API number.
    """
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".dbf")]
        if len(names) != 1:
            raise ValueError(f"expected one .dbf in the OWP zip, found {names}")
        rows = read_dbf(zf.read(names[0]))
    records = [row for row in rows if row.get("OWPStatus") == UNPLUGGED]
    for row in records:
        if not row["APInumber"]:
            raise ValueError(f"unplugged record with no API number: {row}")
    return records


def read_owp_zip(zip_bytes: bytes) -> list[Well]:
    """Return the unplugged wells from ECMC's OWP_SHP.ZIP.

    Args:
        zip_bytes: The downloaded zip file.

    Returns:
        One Well per record with OWPStatus "Unplugged", in file order.

    Raises:
        ValueError: If read_owp_records rejects the zip, an API number
            repeats, or coordinates fall outside Colorado.
    """
    wells = [
        Well(
            api_10=f"05-{row['APInumber']}",
            well_name=row["WellName"],
            project=row["ProjName"],
            surface=row["Surface"],
            minerals=row["Minerals"],
            lat_text=row["Latitude"],
            lon_text=row["Longitude"],
        )
        for row in read_owp_records(zip_bytes)
    ]
    check_wells(wells)
    return wells


def check_wells(wells: Sequence[Well]) -> None:
    """Raise ValueError for an empty list, repeated APIs, or stray coordinates."""
    if not wells:
        raise ValueError("no unplugged wells found")
    seen: set[str] = set()
    for w in wells:
        if w.api_10 in seen:
            raise ValueError(f"API number repeats: {w.api_10}")
        seen.add(w.api_10)
        if not (CO_LAT[0] <= w.lat <= CO_LAT[1] and CO_LON[0] <= w.lon <= CO_LON[1]):
            raise ValueError(f"{w.api_10} is outside Colorado: {w.lat}, {w.lon}")


def _number(value: object) -> float:
    """Return a numeric attribute as a float; CDPHE leaves some null."""
    return float(value) if isinstance(value, int | float) else 0.0


def blockgroup_from_feature(feature: Mapping[str, Any]) -> BlockGroup:
    """Build a BlockGroup from one GeoJSON feature of the CDPHE layer.

    CDPHE publishes no data for block groups inside the Southern Ute and Ute
    Mountain Ute reservations, so their numbers are null.  Null counts as 0.
    """
    props = feature["properties"]
    geometry = feature["geometry"]
    polygons = (
        [geometry["coordinates"]]
        if geometry["type"] == "Polygon"
        else geometry["coordinates"]
    )
    rings = [[(x, y) for x, y, *_ in ring] for polygon in polygons for ring in polygon]
    return BlockGroup(
        geoid=str(props["GEOID"]),
        county=str(props["Cnt_N"]),
        es_pctl=_number(props["ES_S_"]),
        criteria=sum(1 for c in DI_CRITERIA if _number(props[c]) >= 1),
        di_type=str(props["DIType"] or ""),
        population=_number(props["Ttl_P"]),
        rings=rings,
    )


def read_blockgroups(path: Path) -> list[BlockGroup]:
    """Read the CDPHE block groups from a GeoJSON feature collection."""
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    return [blockgroup_from_feature(feature) for feature in data["features"]]


# ---------------------------------------------------------------------------
# Downloading


def _get(
    session: GetSession,
    url: str,
    params: Mapping[str, str] | None = None,
    *,
    sleep: Callable[[float], object] = time.sleep,
) -> bytes:
    """GET a URL and return the body, pausing DELAY_S after every request.

    Connection errors, timeouts, and HTTP 429 or 5xx responses are retried up
    to MAX_ATTEMPTS times with a growing backoff, the same policy the
    scrapers use.

    Raises:
        requests.RequestException: If the request fails for good.
    """
    problem = "no attempts made"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = session.get(url, params=params, timeout=TIMEOUT_S)
        except (requests.ConnectionError, requests.Timeout) as exc:
            problem, transient = f"{type(exc).__name__}: {exc}", True
        else:
            if response.status_code < HTTP_ERROR:
                sleep(DELAY_S)
                return response.content
            problem = f"HTTP {response.status_code}"
            transient = response.status_code in RETRY_STATUSES
        sleep(DELAY_S)
        if not transient or attempt == MAX_ATTEMPTS:
            break
        log.info("%s: %s, retrying", url, problem)
        sleep(BACKOFF_S * attempt)
    raise requests.RequestException(f"{url}: {problem} after {attempt} attempts")


def download_owp(
    session: GetSession,
    dest: Path,
    *,
    sleep: Callable[[float], object] = time.sleep,
) -> None:
    """Download ECMC's OWP shapefile zip to dest.

    Raises:
        zipfile.BadZipFile: If ECMC sends something other than a zip, such as
            an error page.  Nothing is written in that case.
    """
    log.info("downloading %s", OWP_URL)
    data = _get(session, OWP_URL, sleep=sleep)
    with zipfile.ZipFile(io.BytesIO(data)):  # fail now on an HTML error page
        pass
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)


def download_blockgroups(
    session: GetSession,
    dest: Path,
    *,
    sleep: Callable[[float], object] = time.sleep,
) -> int:
    """Download every CDPHE block group, paging the query, to one GeoJSON file.

    Returns:
        The number of features written.

    Raises:
        ValueError: If the service returns an error instead of features.
    """
    features: list[Any] = []
    while True:
        params = {
            "where": "1=1",
            "outFields": ",".join(CDPHE_FIELDS),
            "orderByFields": "OBJECTID",
            "resultOffset": str(len(features)),
            "resultRecordCount": str(CDPHE_PAGE_SIZE),
            "returnGeometry": "true",
            "outSR": "4269",  # NAD83, the layer's own system and ECMC's
            "f": "geojson",
        }
        log.info("downloading block groups from offset %d", len(features))
        page = json.loads(
            _get(session, f"{CDPHE_LAYER_URL}/query", params, sleep=sleep)
        )
        if "features" not in page:
            raise ValueError(f"CDPHE query failed: {str(page)[:300]}")
        features += page["features"]
        more = page.get("properties", {}).get("exceededTransferLimit", False)
        if not more or not page["features"]:
            break
    collection = {"type": "FeatureCollection", "features": features}
    write_text_atomic(dest, json.dumps(collection))
    return len(features)


# ---------------------------------------------------------------------------
# Geometry


def ring_signed_area_m2(ring: Ring) -> float:
    """Signed area of a lon/lat ring on the equal-area sphere, in m2."""
    total = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:], strict=False):
        total += math.radians(x2 - x1) * (
            2 + math.sin(math.radians(y1)) + math.sin(math.radians(y2))
        )
    return total * AUTHALIC_RADIUS_M**2 / 2


def polygon_area_m2(rings: Iterable[Ring]) -> float:
    """Area of a polygon or multipolygon given as rings, in m2.

    Holes wind the opposite way from outer rings, so summing signed areas
    subtracts them.
    """
    return abs(sum(ring_signed_area_m2(ring) for ring in rings))


def contains(bg: BlockGroup, lon: float, lat: float) -> bool:
    """Point-in-polygon by ray casting, even-odd over all rings."""
    x0, y0, x1, y1 = bg.bbox
    if not (x0 <= lon <= x1 and y0 <= lat <= y1):
        return False
    inside = False
    for ring in bg.rings:
        for (xa, ya), (xb, yb) in zip(ring, ring[1:], strict=False):
            if (ya > lat) != (yb > lat) and lon < (xb - xa) * (lat - ya) / (
                yb - ya
            ) + xa:
                inside = not inside
    return inside


def distance_to_edge_m(bg: BlockGroup, lon: float, lat: float) -> float:
    """Shortest distance from a point to a block group's boundary, in meters.

    Uses a flat-earth projection centered on the point, which is accurate to
    well under a meter at the 300 m scale of the boundary test.
    """
    kx = M_PER_DEG_LON_EQUATOR * math.cos(math.radians(lat))
    best = math.inf
    for ring in bg.rings:
        pts = [((x - lon) * kx, (y - lat) * M_PER_DEG_LAT) for x, y in ring]
        for (ax, ay), (bx, by) in zip(pts, pts[1:], strict=False):
            dx, dy = bx - ax, by - ay
            length2 = dx * dx + dy * dy
            t = (
                0.0
                if length2 == 0
                else max(0.0, min(1.0, -(ax * dx + ay * dy) / length2))
            )
            best = min(best, math.hypot(ax + t * dx, ay + t * dy))
    return best


def near_bbox(bg: BlockGroup, lon: float, lat: float, margin: float) -> bool:
    """True if a point is within margin degrees of a block group's bounding box."""
    x0, y0, x1, y1 = bg.bbox
    return x0 - margin <= lon <= x1 + margin and y0 - margin <= lat <= y1 + margin


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points, in kilometers."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


# ---------------------------------------------------------------------------
# Joining and scoring


def assign_blockgroups(
    wells: Sequence[Well], blockgroups: Sequence[BlockGroup]
) -> dict[str, BlockGroup | None]:
    """Map each well's API_10 to the block group that contains it, or None."""
    found: dict[str, BlockGroup | None] = {}
    for w in wells:
        hits = [bg for bg in blockgroups if contains(bg, w.lon, w.lat)]
        if len(hits) > 1:
            log.warning(
                "%s falls in %d block groups; using the first", w.api_10, len(hits)
            )
        if not hits:
            log.warning("%s falls in no block group", w.api_10)
        found[w.api_10] = hits[0] if hits else None
    return found


def boundary_flag(
    w: Well, bg: BlockGroup | None, blockgroups: Sequence[BlockGroup]
) -> str:
    """Flag a well within BOUNDARY_M of a block group with the other DI status.

    These wells are worth checking at the parcel level, since a small
    location error could change their DI status.
    """
    if bg is None:
        return ""
    for other in blockgroups:
        if (
            other.is_di != bg.is_di
            and near_bbox(other, w.lon, w.lat, SEARCH_MARGIN_DEG)
            and distance_to_edge_m(other, w.lon, w.lat) < BOUNDARY_M
        ):
            return DI_EDGE_FLAG if bg.is_di else NEAR_DI_FLAG
    return ""


def cluster_sizes(wells: Sequence[Well]) -> dict[str, int]:
    """Count, for each well, the wells in the same project within 5 km.

    The count includes the well itself, so a lone well scores 1.
    """
    by_project: dict[str, list[Well]] = {}
    for w in wells:
        by_project.setdefault(w.project, []).append(w)
    return {
        w.api_10: sum(
            1
            for o in by_project[w.project]
            if haversine_km(w.lat, w.lon, o.lat, o.lon) <= CLUSTER_RADIUS_KM
        )
        for w in wells
    }


def community_score(bg: BlockGroup | None, flag: str) -> float:
    """Community burden, 0 to 40 points."""
    if bg is not None and bg.is_di:
        criteria = min(CRITERIA_POINTS_CAP, POINTS_PER_CRITERION * bg.criteria)
        return DI_POINTS + criteria + ES_POINTS * bg.es_pctl / 100
    return NEAR_DI_POINTS if flag == NEAR_DI_FLAG else 0.0


def exposure_score(bg: BlockGroup | None) -> float:
    """Population exposure, 0 to 30 points."""
    if bg is None:
        return 0.0
    density = math.log10(1 + bg.density_km2) / math.log10(DENSITY_FULL_PER_KM2)
    population = bg.population / POPULATION_FULL
    return DENSITY_POINTS * min(1.0, density) + POPULATION_POINTS * min(1.0, population)


def jurisdiction_score(surface: str, minerals: str) -> float:
    """Points for who holds the surface and minerals, 0 to 15.

    Federal and tribal wells have their own funding and authority, so the
    state's direct jurisdiction scores highest.
    """
    if surface in TRIBAL or minerals in TRIBAL:
        return 0.0
    if surface == "Federal":
        return FED_SURFACE_POINTS
    if minerals == "Federal":
        return FED_MINERALS_POINTS
    return JURISDICTION_POINTS


def deliverability_score(w: Well, cluster: int) -> float:
    """Deliverability, 0 to 30 points: mobilization economies plus jurisdiction."""
    mobilization = math.log(cluster) / math.log(CLUSTER_FULL)
    return CLUSTER_POINTS * min(1.0, mobilization) + jurisdiction_score(
        w.surface, w.minerals
    )


def tier(score: float) -> int:
    """Tier 1 to 4 for a rounded priority score."""
    for n, cutoff in enumerate(TIER_CUTOFFS, start=1):
        if score >= cutoff:
            return n
    return len(TIER_CUTOFFS) + 1


def rank_wells(
    wells: Sequence[Well], blockgroups: Sequence[BlockGroup]
) -> list[dict[str, object]]:
    """Score every well and return output rows, highest priority first.

    Ties on the rounded score are broken by API number so the order is stable.
    """
    county_names = {bg.geoid[2:5]: bg.county for bg in blockgroups}
    found = assign_blockgroups(wells, blockgroups)
    clusters = cluster_sizes(wells)
    scored: list[tuple[float, str, dict[str, object]]] = []
    mismatched = 0
    for w in wells:
        bg = found[w.api_10]
        flag = boundary_flag(w, bg, blockgroups)
        community = community_score(bg, flag)
        exposure = exposure_score(bg)
        deliverability = deliverability_score(w, clusters[w.api_10])
        score = round(community + exposure + deliverability, 1)
        county = county_names.get(w.county_fips, "")
        if bg is not None and bg.county != county:
            mismatched += 1
        row: dict[str, object] = {
            "Tier": tier(score),
            "Priority_Score": f"{score:.1f}",
            "API_10": w.api_10,
            "WellName": w.well_name,
            "Project": w.project,
            "County": county,
            "Lat": w.lat_text,
            "Lon": w.lon_text,
            "Surface": w.surface,
            "Minerals": w.minerals,
            "DI_Community_Nov2024": "Yes" if bg and bg.is_di else "No",
            "DI_Type": bg.di_type if bg and bg.is_di else "",
            "DI_Criteria_Count": bg.criteria if bg and bg.is_di else "",
            "EnviroScreen2_Pctl": f"{bg.es_pctl:.1f}" if bg else "",
            "BG_GEOID": bg.geoid if bg else "",
            "BG_Pop": int(bg.population) if bg else "",
            "BG_PopDensity_km2": f"{bg.density_km2:.1f}" if bg else "",
            "Cluster_Size_5km": clusters[w.api_10],
            "Score_Community": f"{community:.1f}",
            "Score_Exposure": f"{exposure:.1f}",
            "Score_Deliverability": f"{deliverability:.1f}",
            "Boundary_Flag": flag,
        }
        scored.append((score, w.api_10, row))
    if mismatched:
        log.warning(
            "%d wells sit in a block group outside the county their API names",
            mismatched,
        )
    scored.sort(key=lambda item: (-item[0], item[1]))
    rows = [row for _, _, row in scored]
    for n, row in enumerate(rows, start=1):
        row["Rank"] = n
    return rows


# ---------------------------------------------------------------------------
# Running


def sha256(path: Path) -> str:
    """Hex SHA-256 of a file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_time(path: Path) -> str:
    """A file's modification time as a UTC ISO 8601 string."""
    stamp = datetime.fromtimestamp(path.stat().st_mtime, UTC)
    return stamp.isoformat(timespec="seconds")


def build(
    owp_zip: Path, blockgroup_path: Path, out: Path, sources: Mapping[str, str]
) -> list[dict[str, object]]:
    """Read the two inputs, rank the wells, and write the CSV and its manifest.

    Args:
        owp_zip: ECMC's OWP_SHP.ZIP.
        blockgroup_path: The CDPHE block groups as GeoJSON.
        out: The CSV to write.  The manifest goes beside it as .sources.json.
        sources: Where each input came from, keyed "owp" and "blockgroups".

    Returns:
        The rows written, highest priority first.
    """
    wells = read_owp_zip(owp_zip.read_bytes())
    blockgroups = read_blockgroups(blockgroup_path)
    log.info("%d unplugged wells, %d block groups", len(wells), len(blockgroups))
    rows = rank_wells(wells, blockgroups)
    write_csv(out, COLUMNS, rows)
    manifest = {
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "output": out.name,
        "wells": len(rows),
        "sources": {
            "ecmc_owp_shapefile": {
                "url": sources["owp"],
                "retrieved_at": file_time(owp_zip),
                "sha256": sha256(owp_zip),
                "unplugged_wells": len(wells),
            },
            "cdphe_enviroscreen_v2_blockgroups": {
                "url": sources["blockgroups"],
                "retrieved_at": file_time(blockgroup_path),
                "sha256": sha256(blockgroup_path),
                "block_groups": len(blockgroups),
            },
        },
    }
    write_text_atomic(
        out.with_suffix(".sources.json"), json.dumps(manifest, indent=2) + "\n"
    )
    return rows


def main(argv: list[str] | None = None) -> int:
    """Download the inputs if needed, build the ranked list, and return 0."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help="CSV to write (default: ip/CO_Orphan_Wells_EJ_Ranked_Wells.csv)",
    )
    parser.add_argument(
        "--download-dir",
        type=Path,
        default=DOWNLOAD_DIR,
        help="where downloads are kept between runs (default: ip/downloads/)",
    )
    parser.add_argument(
        "--refresh", action="store_true", help="download again even if files exist"
    )
    parser.add_argument(
        "--owp-zip", type=Path, help="use this OWP_SHP.ZIP, no download"
    )
    parser.add_argument(
        "--blockgroups", type=Path, help="use this block group GeoJSON, no download"
    )
    parser.add_argument("--contact", help="contact address for the User-Agent header")
    parser.add_argument("-v", "--verbose", action="store_true", help="log more detail")
    args = parser.parse_args(argv)
    configure_logging(args.verbose)

    owp_zip = args.owp_zip or args.download_dir / OWP_FILE
    blockgroup_path = args.blockgroups or args.download_dir / BLOCKGROUP_FILE
    need_owp = args.owp_zip is None and (args.refresh or not owp_zip.exists())
    need_bg = args.blockgroups is None and (
        args.refresh or not blockgroup_path.exists()
    )
    if need_owp or need_bg:
        session = make_session(resolve_contact(args.contact))
        if need_owp:
            download_owp(session, owp_zip)
        if need_bg:
            count = download_blockgroups(session, blockgroup_path)
            log.info("%d block groups saved to %s", count, blockgroup_path)

    out = args.out
    sources = {
        "owp": str(args.owp_zip) if args.owp_zip else OWP_URL,
        "blockgroups": str(args.blockgroups) if args.blockgroups else CDPHE_LAYER_URL,
    }
    rows = build(owp_zip, blockgroup_path, out, sources)
    di = sum(1 for r in rows if r["DI_Community_Nov2024"] == "Yes")
    tiers = [sum(1 for r in rows if r["Tier"] == t) for t in (1, 2, 3, 4)]
    log.info("%d wells written to %s (%d in DI communities)", len(rows), out, di)
    log.info("tier counts 1-4: %s", ", ".join(map(str, tiers)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
