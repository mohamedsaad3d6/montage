"""Map data: Natural Earth countries (public domain) -> simplified polygons in map coordinates
(x = lon * 10, y = -lat * 10; the scene camera turns them into pixels). For writing map scenes.

    from monteer.montage.maps import polys
    polys(bbox=(lon0, lat0, lon1, lat1), detail="50m"|"10m", tol=0.05, colours={"EGY": "#E0B04A"}, turn={"NGA": ("#E0B04A", 3.2)})
"""
import json
from functools import lru_cache
from pathlib import Path

from ..core.paths import MAPS as DL
LAND, SEA = "#3A3229", "#0E1014"


@lru_cache(maxsize=2)
def _load(detail):
    return json.load(open(DL / f"ne_{detail}_admin_0_countries.geojson"))["features"]


def _simplify(pts, tol):
    """Douglas-Peucker on a closed ring (lon/lat degrees)"""
    if len(pts) < 5:
        return pts

    def rdp(a):
        if len(a) < 3:
            return a
        (x0, y0), (x1, y1) = a[0], a[-1]
        dx, dy = x1 - x0, y1 - y0
        n = (dx * dx + dy * dy) ** 0.5 or 1e-9
        dmax, imax = 0, 0
        for i in range(1, len(a) - 1):
            d = abs(dy * a[i][0] - dx * a[i][1] + x1 * y0 - y1 * x0) / n
            if d > dmax:
                dmax, imax = d, i
        if dmax > tol:
            return rdp(a[:imax + 1])[:-1] + rdp(a[imax:])
        return [a[0], a[-1]]
    h = len(pts) // 2
    return rdp(pts[:h + 1])[:-1] + rdp(pts[h:])


def polys(bbox, detail="50m", tol=0.05, colours=None, turn=None, land=LAND):
    """polygons overlapping bbox; colours: iso3 -> fill; turn: iso3 -> (colour, time) to change colour at that time"""
    colours, turn = colours or {}, turn or {}
    lon0, lat0, lon1, lat1 = bbox
    out = []
    for f in _load(detail):
        iso = f["properties"].get("ADM0_A3") or f["properties"].get("ISO_A3")
        g = f["geometry"]
        rings = [p[0] for p in g["coordinates"]] if g["type"] == "MultiPolygon" else [g["coordinates"][0]]
        for r in rings:
            xs = [p[0] for p in r]
            ys = [p[1] for p in r]
            if max(xs) < lon0 or min(xs) > lon1 or max(ys) < lat0 or min(ys) > lat1:
                continue
            s = _simplify([(p[0], p[1]) for p in r], tol)
            if len(s) < 4:
                continue
            pg = {"pts": [[round(x * 10, 2), round(-y * 10, 2)] for x, y in s], "fill": colours.get(iso, land)}
            if iso in turn:
                pg["fill2"], pg["t0"] = turn[iso]
            out.append(pg)
    return out


def xy(lon, lat):
    return [round(lon * 10, 2), round(-lat * 10, 2)]


def cam(t, lon, lat, scale):
    return [t, lon * 10, -lat * 10, scale]


# ---------------------------------------------------------------------------------------------------- real outlines (22 Oct 2026)
UNITS = "ne_50m_admin_0_map_units.geojson"      # England, Scotland, Wales, Northern Ireland … as their own units (public domain)


@lru_cache(maxsize=1)
def _units():
    f = DL / UNITS
    if not f.exists():
        return []
    out = []
    for ft in json.load(open(f))["features"]:
        g = ft["geometry"]
        rings = [poly[0] for poly in (g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]])]
        out.append((ft["properties"].get("GEOUNIT") or ft["properties"].get("NAME"), rings))
    return out


def _inside(x, y, ring):
    c = False
    for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]):
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / ((y1 - y0) or 1e-12) + x0:
            c = not c
    return c


def unit_at(lon, lat):
    """the map unit (a country, or a nation of the UK) whose land holds this point -> (name, rings) or None"""
    for name, rings in _units():
        if any(_inside(lon, lat, r) for r in rings):
            return name, rings
    return None


def real_outlines(scenes, tol=0.03, pins_by=1.5):
    """owner's note of 22 Oct 2026 (the UK map of «المملكة المتحدة تنهار» v2 looked crude: the brain had typed its outlines,
    about 30 points a country): every hand-made shape of a map scene (map coordinates x = lon*10, y = -lat*10) becomes the
    real outline of the unit its centre sits on (its islands too), in the same colours; a place pin of a map scene shows
    within pins_by s (Northern Ireland's came 3.4 s in) -> (scenes, notes)"""
    import copy
    if not _units():
        return scenes, ["map outlines: no map-units file; the shapes as drawn"]
    out, notes = [], []
    for sc in scenes:
        items = sc.get("items", [])
        if not any(i.get("type") == "map" and i.get("polys") for i in items):
            out.append(sc)
            continue
        sc = copy.deepcopy(sc)
        for it in sc["items"]:
            if it.get("type") == "pin" and float(it.get("t0", 0)) > pins_by:
                it["t0"] = pins_by
            if it.get("type") != "map" or not isinstance(it.get("polys"), list):
                continue
            new = []
            for poly in it["polys"]:
                pts = poly.get("pts") if isinstance(poly, dict) else None
                if not pts or len(pts) < 3:
                    new.append(poly)
                    continue
                lon = sum(p[0] for p in pts) / len(pts) / 10.0
                lat = -sum(p[1] for p in pts) / len(pts) / 10.0
                u = unit_at(lon, lat)
                if u is None:
                    new.append(poly)
                    continue
                name, rings = u
                for r in sorted(rings, key=len, reverse=True)[:6]:
                    simple = _simplify([list(p) for p in r], tol)
                    if len(simple) >= 3:
                        new.append(dict(poly, pts=[[round(x * 10, 2), round(-y * 10, 2)] for x, y in simple]))
                notes.append(f"{sc['name']}: {name} drawn from its real outline")
            it["polys"] = new
        out.append(sc)
    return out, notes
