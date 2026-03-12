from typing import List, Sequence, Tuple, Literal
from math import hypot

from shapely.geometry import (
    Point as ShapelyPoint,
    LineString as ShapelyLineString,
    MultiLineString as ShapelyMultiLineString,
    Polygon as ShapelyPolygon,
    MultiPolygon as ShapelyMultiPolygon,
)
from shapely.ops import transform
import pyproj


def create_buffers(
    geometry_list: List[Sequence],
    geom_type: Literal["Point", "LineString", "Polygon", "point", "line", "linestring", "polygon"],
    distance_m: float,
    *,
    crs_in: str = "EPSG:4326",
    crs_projected: str = "EPSG:3338",
    crs_out: str = "EPSG:4326",
    cap_style: Literal["round", "flat", "square"] = "round",
    join_style: Literal["round", "mitre", "miter", "bevel"] = "round",
    resolution: int = 16,
) -> List[List[List[float]]]:
    """
    Create buffers for input geometries and return list of buffer exterior rings in [lon, lat].

    Parameters
    ----------
    geometry_list : list
        List of geometries. Coordinates must be in [lon, lat] order for EPSG:4326 (or the CRS you pass).
        - Point:      [lon, lat] or [[lon, lat]]
        - LineString: [[lon, lat], [lon, lat], ...]
        - Polygon:    [[lon, lat], ..., [lon, lat]] (closed or open ring)
    geom_type : {"Point","LineString","Polygon"} (case-insensitive; "Line" also allowed)
        The geometry type of items in geometry_list.
    distance_m : float
        Buffer distance in meters (performed in crs_projected).
    crs_in, crs_projected, crs_out : str
        Input CRS, metric CRS for buffering, and output CRS (default 4326).
    cap_style : {"round","flat","square"}
        Line buffer cap style at segment ends (ignored for polygons/points).
    join_style : {"round","mitre","miter","bevel"}
        Line vertex join style (ignored for polygons/points). "miter" is accepted as alias of "mitre".
    resolution : int
        Number of segments to approximate a quarter circle in buffer.

    Returns
    -------
    List[List[List[float]]]
        For each input geometry, returns the exterior ring of its buffer polygon
        as a closed list of [lon, lat] coordinates.
    """

    # Shapely accepts integer codes for cap/join styles:
    # cap_style: round=1, flat=2, square=3
    # join_style: round=1, mitre/miter=2, bevel=3
    cap_lookup = {"round": 1, "flat": 2, "square": 3}
    join_lookup = {"round": 1, "mitre": 2, "miter": 2, "bevel": 3}

    cap_key = cap_style.lower()
    join_key = join_style.lower()
    if cap_key not in cap_lookup:
        raise ValueError("cap_style must be 'round', 'flat', or 'square'")
    if join_key not in join_lookup:
        raise ValueError("join_style must be 'round', 'mitre'/'miter', or 'bevel'")

    # Configure transformers (always_xy=True enforces lon,lat axis order)
    to_proj = pyproj.Transformer.from_crs(crs_in, crs_projected, always_xy=True).transform
    to_out = pyproj.Transformer.from_crs(crs_projected, crs_out, always_xy=True).transform

    # Normalize geom_type
    gt = geom_type.lower()
    if gt in ("line", "linestring"):
        gt = "linestring"
    elif gt in ("point", "polygon"):
        pass
    else:
        raise ValueError("geom_type must be 'Point', 'LineString', or 'Polygon'")

    def _as_lonlat_tuples(seq: Sequence[Sequence[float]]):
        # Ensure an iterable of (lon, lat) tuples with numeric values
        return [(float(lon), float(lat)) for lon, lat in seq]

    def build_geom(item: Sequence):
        if gt == "point":
            # Accept [lon, lat] or [[lon, lat]] (take first)
            if isinstance(item, (ShapelyPoint,)):
                return item
            if isinstance(item[0], (int, float)):
                lon, lat = item  # type: ignore
            else:
                lon, lat = item[0]  # type: ignore
            return ShapelyPoint((float(lon), float(lat)))

        elif gt == "linestring":
            if isinstance(item, (ShapelyLineString, ShapelyMultiLineString)):
                return item
            coords = _as_lonlat_tuples(item)  # type: ignore
            return ShapelyLineString(coords)

        elif gt == "polygon":
            if isinstance(item, (ShapelyPolygon, ShapelyMultiPolygon)):
                return item
            ring = list(item)  # type: ignore
            if len(ring) < 3:
                raise ValueError("Polygon ring must have at least 3 coordinate pairs")
            # Ensure closed ring
            if ring[0] != ring[-1]:
                ring = ring + [ring[0]]
            coords = _as_lonlat_tuples(ring)
            return ShapelyPolygon(coords)

        raise ValueError("Unsupported geometry type")

    buffers_lonlat: List[List[List[float]]] = []

    for item in geometry_list:
        geom_in = build_geom(item)
        geom_proj = transform(to_proj, geom_in)

        buf_proj = geom_proj.buffer(
            distance_m,
            resolution=resolution,
            cap_style=cap_lookup[cap_key],
            join_style=join_lookup[join_key],
        )

        buf_out = transform(to_out, buf_proj)

        # Extract exterior ring only, keep [lon, lat] order
        ext_coords = [[float(x), float(y)] for (x, y) in buf_out.exterior.coords]

        # Ensure closed ring
        if ext_coords[0] != ext_coords[-1]:
            ext_coords.append(ext_coords[0])

        buffers_lonlat.append(ext_coords)

    return buffers_lonlat


def center_of_geometry(
    geometry_list: List[Sequence],
    geom_type: Literal["Point", "LineString", "Polygon", "point", "line", "linestring", "polygon"],
) -> Tuple[float, float]:
    """
    Compute a representative center in [lon, lat] for the submitted geometry list, behaving
    like the old GeometryUtil.center(...) pattern:
      - Accepts a list of inputs of the specified type (Point, LineString, Polygon).
      - Each input can be a raw coordinate list OR a Shapely geometry.
      - If multiple geometries are supplied, returns the average of their per-geometry centers.
      - Coordinate order is always (lon, lat).

    Parameters
    ----------
    geometry_list : list
        List of geometries. Coordinates must be [lon, lat].
        - Points:      [lon, lat] OR [[lon, lat]]
        - LineString:  [[lon, lat], [lon, lat], ...] OR list of such lines
        - Polygon:     [[lon, lat], ..., [lon, lat]] OR list of such rings (closed or open)
    geom_type : {"Point","LineString","Polygon"} (case-insensitive; "Line" also allowed)

    Returns
    -------
    (lon, lat) : Tuple[float, float]
        A single center point representing all provided geometries.
    """

    if not geometry_list:
        raise ValueError("geometry_list is empty")

    gt = (geom_type or "").lower()
    if gt in ("line", "linestring"):
        gt = "linestring"
    elif gt in ("point", "polygon"):
        pass
    else:
        raise ValueError("geom_type must be 'Point', 'LineString', or 'Polygon'")

    def _is_lonlat_pair(v) -> bool:
        return isinstance(v, (list, tuple)) and len(v) == 2 and all(isinstance(x, (int, float)) for x in v)

    # -------------------------
    # Point helpers
    # -------------------------
    def _flatten_points_like(points_input) -> List[Tuple[float, float]]:
        flat = []
        # Shapely Point
        if isinstance(points_input, ShapelyPoint):
            flat.append((float(points_input.x), float(points_input.y)))
            return flat

        # [lon, lat]
        if _is_lonlat_pair(points_input):
            lon, lat = points_input  # type: ignore
            flat.append((float(lon), float(lat)))
            return flat

        # [[lon, lat], ...] or nested list
        if isinstance(points_input, (list, tuple)):
            for item in points_input:
                if _is_lonlat_pair(item):
                    lon, lat = item  # type: ignore
                    flat.append((float(lon), float(lat)))
                elif isinstance(item, (list, tuple)):
                    for pt in item:
                        if _is_lonlat_pair(pt):
                            lon, lat = pt  # type: ignore
                            flat.append((float(lon), float(lat)))
        return flat

    def _point_center(points_any) -> Tuple[float, float]:
        pts = _flatten_points_like(points_any)
        if not pts:
            raise ValueError("No valid point data found.")
        if len(pts) == 1:
            return pts[0]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return (sum(xs) / len(xs), sum(ys) / len(ys))

    # -------------------------
    # Line helpers
    # -------------------------
    def _is_shapely_linestring(obj) -> bool:
        return isinstance(obj, ShapelyLineString)

    def _is_shapely_multiline(obj) -> bool:
        return isinstance(obj, ShapelyMultiLineString)

    def _center_single_line_coords(coords: Sequence[Sequence[float]]) -> Tuple[float, float]:
        if not isinstance(coords, (list, tuple)) or len(coords) == 0:
            raise ValueError("Invalid line geometry.")
        if len(coords) == 1:
            lon, lat = coords[0]
            return (float(lon), float(lat))

        total = 0.0
        for i in range(len(coords) - 1):
            a = coords[i]; b = coords[i + 1]
            total += hypot(float(b[0]) - float(a[0]), float(b[1]) - float(a[1]))

        target = total / 2.0
        d = 0.0
        for i in range(len(coords) - 1):
            a = coords[i]; b = coords[i + 1]
            seg = hypot(float(b[0]) - float(a[0]), float(b[1]) - float(a[1]))
            if seg > 0.0 and d + seg >= target:
                t = (target - d) / seg
                lon = float(a[0]) + t * (float(b[0]) - float(a[0]))
                lat = float(a[1]) + t * (float(b[1]) - float(a[1]))
                return (lon, lat)
            d += seg
        lon, lat = coords[-1]
        return (float(lon), float(lat))

    def _line_center(line_any) -> Tuple[float, float]:
        # Shapely MultiLineString -> average of per-line centers
        if _is_shapely_multiline(line_any):
            centers = [_line_center(ls) for ls in line_any.geoms]
            return _average_centers(centers)

        # Shapely LineString
        if _is_shapely_linestring(line_any):
            mid = line_any.interpolate(line_any.length / 2.0)
            return (float(mid.x), float(mid.y))

        # List-like:
        # - Single line: [[lon, lat], ...]
        # - Multi lines: [[[lon,lat],...], [[lon,lat],...], ...]
        if isinstance(line_any, (list, tuple)) and len(line_any) > 0:
            first = line_any[0]
            if _is_lonlat_pair(first):
                return _center_single_line_coords(line_any)  # type: ignore
            if isinstance(first, (list, tuple)) and len(first) > 0 and _is_lonlat_pair(first[0]):
                centers = [_center_single_line_coords(line) for line in line_any]  # type: ignore
                return _average_centers(centers)

        # Fallback attempt
        return _center_single_line_coords(line_any)

    # -------------------------
    # Polygon helpers
    # -------------------------
    def _is_shapely_polygon(obj) -> bool:
        return isinstance(obj, ShapelyPolygon)

    def _is_shapely_multipolygon(obj) -> bool:
        return isinstance(obj, ShapelyMultiPolygon)

    def _center_single_polygon_coords(ring: Sequence[Sequence[float]]) -> Tuple[float, float]:
        if len(ring) < 1:
            raise ValueError("Empty polygon ring")

        if len(ring) < 3:
            # Handle degenerate inputs gracefully (same as previous behavior)
            if len(ring) == 1:
                lon, lat = ring[0]
                return (float(lon), float(lat))
            if len(ring) == 2:
                (lon1, lat1), (lon2, lat2) = ring
                return ((float(lon1) + float(lon2)) / 2.0, (float(lat1) + float(lat2)) / 2.0)

        # Ensure closed
        closed = list(ring)
        if closed[0] != closed[-1]:
            closed = closed + [closed[0]]

        xs = [float(p[0]) for p in closed]
        ys = [float(p[1]) for p in closed]

        # Shoelace centroid
        A = 0.0
        Cx = 0.0
        Cy = 0.0
        for i in range(len(closed) - 1):
            cross = xs[i] * ys[i + 1] - xs[i + 1] * ys[i]
            A += cross
            Cx += (xs[i] + xs[i + 1]) * cross
            Cy += (ys[i] + ys[i + 1]) * cross
        A *= 0.5

        if A == 0.0:
            # Degenerate: average vertices (excluding duplicate last)
            lon_avg = sum(xs[:-1]) / (len(xs) - 1)
            lat_avg = sum(ys[:-1]) / (len(ys) - 1)
            return (lon_avg, lat_avg)

        Cx /= (6.0 * A)
        Cy /= (6.0 * A)
        return (Cx, Cy)

    def _polygon_center(poly_any) -> Tuple[float, float]:
        # Shapely MultiPolygon -> average of per-polygon centroids
        if _is_shapely_multipolygon(poly_any):
            centers = [_polygon_center(pg) for pg in poly_any.geoms]
            return _average_centers(centers)

        # Shapely Polygon
        if _is_shapely_polygon(poly_any):
            c = poly_any.centroid
            return (float(c.x), float(c.y))

        # List-like:
        # - Single polygon ring: [[lon, lat], ...]
        # - Multiple polygons: [[[lon,lat],...], [[lon,lat],...], ...]
        if isinstance(poly_any, (list, tuple)) and len(poly_any) > 0:
            first = poly_any[0]
            if _is_lonlat_pair(first):
                return _center_single_polygon_coords(poly_any)  # type: ignore
            if isinstance(first, (list, tuple)) and len(first) > 0 and _is_lonlat_pair(first[0]):
                centers = [_center_single_polygon_coords(pg) for pg in poly_any]  # type: ignore
                return _average_centers(centers)

        # Fallback attempt
        return _center_single_polygon_coords(poly_any)

    # -------------------------
    # General helpers
    # -------------------------
    def _average_centers(centers: List[Tuple[float, float]]) -> Tuple[float, float]:
        xs = [c[0] for c in centers]
        ys = [c[1] for c in centers]
        return (sum(xs) / len(xs), sum(ys) / len(ys))

    # -------------------------
    # Dispatch over the list
    # -------------------------
    per_item_centers: List[Tuple[float, float]] = []
    if gt == "point":
        # All provided items are considered parts of the same point collection,
        # consistent with prior behavior -> compute one center from ALL points.
        all_points: List[Tuple[float, float]] = []
        for item in geometry_list:
            all_points.extend(_flatten_points_like(item))
        if not all_points:
            raise ValueError("No valid point data found.")
        if len(all_points) == 1:
            return all_points[0]
        return _average_centers(all_points)

    elif gt == "linestring":
        # Compute center per item (line or list-of-lines), then average
        for item in geometry_list:
            per_item_centers.append(_line_center(item))
        return _average_centers(per_item_centers)

    elif gt == "polygon":
        # Compute center per item (polygon or list-of-polygons), then average
        for item in geometry_list:
            per_item_centers.append(_polygon_center(item))
        return _average_centers(per_item_centers)

    # Unreachable
    raise ValueError("Unsupported geometry type")





def slice_and_buffer_route(route_geom: list, start_point: list, end_point: list, distance_m: int = 50) -> list:
    """
    Slices a route between a start and end point and returns a buffered polygon
    as a list of rings suitable for an ESRI polygon geometry.

    Parameters
    ----------
    route_geom  : list of [lon, lat] pairs representing the full route
    start_point : [lon, lat] snapped to the route line
    end_point   : [lon, lat] snapped to the route line
    distance_m  : buffer distance in meters (default 50)

    Returns
    -------
    list of rings ([[lon, lat], ...]) for use in {"rings": ..., "spatialReference": {"wkid": 4326}}
    """
    from shapely.geometry import LineString, Point
    from shapely.ops import substring

    route_line = LineString(route_geom)

    sp_point = Point(start_point[0], start_point[1])
    ep_point = Point(end_point[0], end_point[1])

    sp_dist = route_line.project(sp_point)
    ep_dist = route_line.project(ep_point)

    start_dist = min(sp_dist, ep_dist)
    end_dist   = max(sp_dist, ep_dist)

    sliced_segment = substring(route_line, start_dist, end_dist)
    sliced_coords  = list(sliced_segment.coords)

    buffer_rings = create_buffers(geometry_list=[sliced_coords], geom_type="line", distance_m=distance_m)
    if not buffer_rings:
        raise RuntimeError("create_buffers produced no output for sliced segment.")

    return buffer_rings