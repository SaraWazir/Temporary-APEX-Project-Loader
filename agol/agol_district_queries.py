"""
===============================================================================
DISTRICT QUERIES (STREAMLIT) — GEOGRAPHY INTERSECTS (HOUSE / SENATE / BOROUGH / REGION)
===============================================================================
Updated:
  - Adaptive route chunking (polyline point chunks)
  - Adaptive polygon chunking (slice polygon into valid sub-polygons and query)
  - NEW: Optional selective sections execution when calling run_district_queries(sections=[...])
  - Messaging fix: removed info banners; use only proper spinners (context manager)
===============================================================================
"""

import streamlit as st
import re
from agol.agol_util import AGOLQueryIntersect


# =============================================================================
# HELPERS: COMMON
# =============================================================================

def _is_point_pair(x) -> bool:
    """True if x looks like [lat, lon] numeric pair."""
    if not isinstance(x, (list, tuple)) or len(x) != 2:
        return False
    return isinstance(x[0], (int, float)) and isinstance(x[1], (int, float))


def _unique_preserve_order(items):
    seen = set()
    out = []
    for x in items or []:
        if x is None:
            continue
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _split_string_values(s: str):
    """
    AGOLQueryIntersect.string_values is often a single string.
    Split on common delimiters: <br>, newline, semicolon, comma.
    """
    if not s:
        return []
    s = s.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    parts = re.split(r"[\n;]+", s)
    exploded = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        for q in p.split(","):
            q = q.strip()
            if q:
                exploded.append(q)
    return exploded


def _call_intersect(url, layer, geometry, fields, return_geometry, list_values, string_values):
    r = AGOLQueryIntersect(
        url=url,
        layer=layer,
        geometry=geometry,
        fields=fields,
        return_geometry=return_geometry,
        list_values=list_values,
        string_values=string_values
    )
    return (r.list_values or [], r.string_values or "", r.results)


# =============================================================================
# ROUTE (POLYLINE) CHUNKING
# =============================================================================

def _extract_route_paths(geom):
    """
    Normalize route geometry into list of paths (each path=list of [lat,lon]).

    Supports:
      A) [[lat, lon], ...]
      B) [[[lat, lon], ...]]
      C) [[[[lat, lon], ...]], ...] (flatten)
    """
    if not isinstance(geom, list) or not geom:
        return [], False

    # A: single path directly
    if _is_point_pair(geom[0]):
        return [geom], True

    # B: list of paths
    if isinstance(geom[0], list) and geom[0] and _is_point_pair(geom[0][0]):
        return geom, True

    # C: extra nesting, flatten
    if isinstance(geom[0], list) and geom[0]:
        paths = []
        for maybe_route in geom:
            if not isinstance(maybe_route, list) or not maybe_route:
                continue
            if _is_point_pair(maybe_route[0]):
                paths.append(maybe_route)
            elif isinstance(maybe_route[0], list) and maybe_route[0] and _is_point_pair(maybe_route[0][0]):
                paths.extend(maybe_route)
        if paths:
            return paths, True

    return [], False


def _chunk_points(points, max_points: int, overlap: int = 1):
    """Split one path into segments."""
    if not points:
        return []
    if max_points < 2:
        max_points = 2
    if len(points) <= max_points:
        return [points]

    segs = []
    start = 0
    n = len(points)
    while start < n:
        end = min(start + max_points, n)
        seg = points[start:end]
        if len(seg) == 1 and start > 0:
            seg = points[start - 1:end]
        segs.append(seg)
        if end >= n:
            break
        start = end - overlap
    return segs


def _chunk_route_geometry(route_geom, max_points: int):
    """
    Returns list of route geometries each shaped as list-of-paths.
    Example input:  [[[p1..pN]]]
    Output: [ [[seg1]], [[seg2]], ... ]
    """
    paths, is_route = _extract_route_paths(route_geom)
    if not is_route:
        return [route_geom]

    chunks = []
    for path in paths:
        for seg in _chunk_points(path, max_points=max_points, overlap=1):
            chunks.append([seg])  # keep list-of-paths structure

    return chunks or [route_geom]


# =============================================================================
# POLYGON CHUNKING (VALID SUB-POLYGONS)
# =============================================================================

def _extract_polygon_rings(geom):
    """
    Normalize boundary geometry into list of rings:
      rings = [ ring1, ring2, ... ]
      ring = [ [ [lat,lon], ... ] ]

    Returns: (rings, is_polygon_like)
    """
    if not isinstance(geom, list) or not geom:
        return [], False

    # A: ring directly
    if _is_point_pair(geom[0]):
        return [geom], True

    # B/C: list of rings
    if isinstance(geom[0], list) and geom[0] and _is_point_pair(geom[0][0]):
        return geom, True

    return [], False


def _close_ring(ring):
    """Ensure ring is closed (first==last)."""
    if not ring or len(ring) < 3:
        return ring
    if ring[0] != ring[-1]:
        return ring + [ring[0]]
    return ring


def _polygon_to_shapely(boundary_geom):
    """
    Convert boundary rings [[lat,lon]...] into shapely Polygon (lon,lat).
    Preserves holes if present.
    """
    try:
        from shapely.geometry import Polygon
    except Exception as e:
        raise RuntimeError(
            "Polygon chunking requires the 'shapely' package. "
            "Install it (e.g., pip install shapely) in your environment."
        ) from e

    rings, ok = _extract_polygon_rings(boundary_geom)
    if not ok or not rings:
        raise ValueError("Invalid/empty polygon geometry for chunking")

    outer = _close_ring(rings[0])
    holes = [_close_ring(r) for r in rings[1:]] if len(rings) > 1 else []

    # Convert [lat,lon] -> (lon,lat)
    outer_xy = [(pt[1], pt[0]) for pt in outer]
    holes_xy = [[(pt[1], pt[0]) for pt in h] for h in holes if h and len(h) >= 4]

    poly = Polygon(outer_xy, holes_xy)
    # Clean minor self-intersections
    try:
        poly = poly.buffer(0)
    except Exception:
        pass
    return poly


def _shapely_to_boundary_geom(poly):
    """Convert shapely Polygon -> boundary rings format [ [ [lat,lon]... ], [hole...], ... ]."""
    rings = []

    # Exterior
    ext = list(poly.exterior.coords)
    rings.append([[y, x] for (x, y) in ext])

    # Holes
    for interior in poly.interiors:
        coords = list(interior.coords)
        rings.append([[y, x] for (x, y) in coords])

    return rings


def _slice_polygon_into_equal_parts(boundary_geom, parts: int):
    """
    Slice polygon into 'parts' equal strips along its longest axis,
    returning a list of VALID polygon geometries (rings) for querying.
    """
    try:
        from shapely.geometry import box
        from shapely.prepared import prep
    except Exception as e:
        raise RuntimeError(
            "Polygon chunking requires the 'shapely' package. "
            "Install it (e.g., pip install shapely)."
        ) from e

    poly = _polygon_to_shapely(boundary_geom)
    if poly.is_empty:
        return []

    minx, miny, maxx, maxy = poly.bounds
    width = maxx - minx
    height = maxy - miny
    if parts < 2:
        parts = 2

    prepared = prep(poly)
    pieces = []

    # Choose slicing direction based on longest dimension
    if width >= height:
        # vertical strips
        dx = width / parts if width else 0.0
        for i in range(parts):
            x0 = minx + i * dx
            x1 = minx + (i + 1) * dx if i < parts - 1 else maxx
            strip = box(x0, miny, x1, maxy)
            if not prepared.intersects(strip):
                continue
            piece = poly.intersection(strip)
            if piece.is_empty:
                continue
            if piece.geom_type == "Polygon":
                pieces.append(_shapely_to_boundary_geom(piece))
            elif piece.geom_type == "MultiPolygon":
                for p in piece.geoms:
                    if not p.is_empty:
                        pieces.append(_shapely_to_boundary_geom(p))
    else:
        # horizontal strips
        dy = height / parts if height else 0.0
        for i in range(parts):
            y0 = miny + i * dy
            y1 = miny + (i + 1) * dy if i < parts - 1 else maxy
            strip = box(minx, y0, maxx, y1)
            if not prepared.intersects(strip):
                continue
            piece = poly.intersection(strip)
            if piece.is_empty:
                continue
            if piece.geom_type == "Polygon":
                pieces.append(_shapely_to_boundary_geom(piece))
            elif piece.geom_type == "MultiPolygon":
                for p in piece.geoms:
                    if not p.is_empty:
                        pieces.append(_shapely_to_boundary_geom(p))

    return pieces


# =============================================================================
# ADAPTIVE INTERSECT (ROUTES + POLYGONS)
# =============================================================================

def _agol_intersect_adaptive(
    url: str,
    layer: int,
    geometry,
    fields: str,
    return_geometry: bool,
    list_values: str,
    string_values: str,
    enable_route_chunking: bool = True,
    enable_polygon_chunking: bool = True,
):
    """
    Robust intersect wrapper:
      1) Try a single full-geometry query.
      2) If it fails:
         - If route chunking enabled and geometry route-like: chunk by points
         - Else if polygon chunking enabled and geometry polygon-like: slice into valid pieces
      3) Merge results as uniques.

    Session-state knobs:
      - agol_max_points_per_query (default 300)
      - agol_min_points_per_query (default 15)
      - agol_polygon_initial_slices (default 4)
      - agol_polygon_max_slices (default 64)
      - agol_debug_chunking (default False)
    """
    debug = bool(st.session_state.get("agol_debug_chunking", False))

    # Determine geometry kinds (best-effort)
    _, is_route = _extract_route_paths(geometry)
    _, is_poly = _extract_polygon_rings(geometry)

    # 1) Single call first
    try:
        ids, labels, result = _call_intersect(url, layer, geometry, fields, return_geometry, list_values, string_values)
        return {"list_values": ids, "string_values": labels, 'result': result}
    except Exception as e:
        if debug:
            st.write(f"[chunking] Full-geometry query failed: {e!r}")
        full_error = e

    # 2a) Route chunking path
    if enable_route_chunking and is_route:
        max_points = int(st.session_state.get("agol_max_points_per_query", 300))
        min_points = int(st.session_state.get("agol_min_points_per_query", 15))
        current = max_points
        last_error = None

        while current >= min_points:
            try:
                geoms = _chunk_route_geometry(geometry, max_points=current)
                if debug:
                    st.write(f"[chunking][route] Trying {len(geoms)} chunks @ {current} pts/chunk")

                merged_ids = []
                merged_labels_list = []

                for g in geoms:
                    ids, labels, result = _call_intersect(url, layer, g, fields, return_geometry, list_values, string_values)
                    merged_ids.extend(ids)
                    merged_labels_list.extend(_split_string_values(labels))

                merged_ids = _unique_preserve_order(merged_ids)
                merged_labels_list = _unique_preserve_order(merged_labels_list)
                return {"list_values": merged_ids, "string_values": ", ".join(merged_labels_list), 'result': result}

            except Exception as e:
                last_error = e
                if debug:
                    st.write(f"[chunking][route] Failed @ {current} pts/chunk: {e!r}")
                current = current // 2

        raise RuntimeError(
            f"AGOL intersect failed for route even after chunking down to {min_points} pts/chunk"
        ) from last_error

    # 2b) Polygon chunking path
    if enable_polygon_chunking and is_poly:
        initial = int(st.session_state.get("agol_polygon_initial_slices", 4))
        max_slices = int(st.session_state.get("agol_polygon_max_slices", 64))

        slices = max(2, initial)
        last_error = None

        while slices <= max_slices:
            try:
                pieces = _slice_polygon_into_equal_parts(geometry, parts=slices)
                if debug:
                    st.write(f"[chunking][polygon] Trying {len(pieces)} polygon pieces @ {slices} slices")

                merged_ids = []
                merged_labels_list = []

                for piece_geom in pieces:
                    ids, labels, result = _call_intersect(url, layer, piece_geom, fields, return_geometry, list_values, string_values)
                    merged_ids.extend(ids)
                    merged_labels_list.extend(_split_string_values(labels))

                merged_ids = _unique_preserve_order(merged_ids)
                merged_labels_list = _unique_preserve_order(merged_labels_list)
                return {"list_values": merged_ids, "string_values": ", ".join(merged_labels_list), "result": result}

            except Exception as e:
                last_error = e
                if debug:
                    st.write(f"[chunking][polygon] Failed @ {slices} slices: {e!r}")
                slices *= 2

        raise RuntimeError(
            f"AGOL intersect failed for polygon even after slicing up to {max_slices} parts"
        ) from last_error

    # If we couldn't chunk, re-raise the original failure
    raise full_error


# =============================================================================
# ENTRYPOINT: RUN ALL / SELECTED DISTRICT/GEOGRAPHY QUERIES
# =============================================================================
# Optional alias for convenience (matches the name you mentioned)
# Optional alias for convenience (matches the name you mentioned)
def run_district_queries(sections=None, message=None):
    """
    Progress-bar version of district queries.
    Uses a borderless container inside a placeholder and clears it when done.
    """
    import streamlit as st

    valid_sections = {'house', 'senate', 'borough', 'region', 'routes'}
    if sections is None:
        sections_set = valid_sections.copy()
    else:
        sections_set = {str(s).lower().strip() for s in sections if isinstance(s, str)}
        sections_set = {s for s in sections_set if s in valid_sections}
        if not sections_set:
            sections_set = valid_sections.copy()

    # Geometry precedence
    if st.session_state.get('selected_point'):
        st.session_state['project_geometry'] = st.session_state['selected_point']
        st.session_state['project_geometry_type'] = 'point'
    elif st.session_state.get('selected_route'):
        st.session_state['project_geometry'] = st.session_state['selected_route']
        st.session_state['project_geometry_type'] = 'line'
    elif st.session_state.get('selected_boundary'):
        st.session_state['project_geometry'] = st.session_state['selected_boundary']
        st.session_state['project_geometry_type'] = 'polygon'
    else:
        st.session_state['project_geometry'] = None

    # Initialize defaults for selected sections
    if 'house' in sections_set:
        st.session_state['house_list'] = []
        st.session_state['house_string'] = ""
    if 'senate' in sections_set:
        st.session_state['senate_list'] = []
        st.session_state['senate_string'] = ""
    if 'borough' in sections_set:
        st.session_state['borough_list'] = []
        st.session_state['borough_string'] = ""
    if 'region' in sections_set:
        st.session_state['region_list'] = []
        st.session_state['region_string'] = ""
    if 'routes' in sections_set:
        st.session_state['route_id'] = ""
        st.session_state['route_name'] = ""
        st.session_state.setdefault('route_list', [])
        st.session_state.setdefault('route_ids', "")
        st.session_state.setdefault('route_names', "")

    if st.session_state['project_geometry'] is None:
        return

    geom = st.session_state['project_geometry']

    enable_route_chunking = bool(st.session_state.get("selected_route"))
    enable_polygon_chunking = bool(st.session_state.get("selected_boundary"))

    ordered_sections = [s for s in ['house', 'senate', 'borough', 'region'] if s in sections_set]
    total = max(1, len(ordered_sections))

    # --------------------------------------------------------------
    # Use a *placeholder* that owns the render, then put a container inside it.
    # Empty the placeholder at the end to ensure complete removal.
    # --------------------------------------------------------------
    progress_block = st.empty()  # <-- the owner we can definitely clear
    try:
        with progress_block.container():  # borderless by default
            st.write('')
            status_ph = st.empty()
            bar_ph = st.empty()
            progress_bar = bar_ph.progress(0)

            def _set_status(txt: str):
                status_ph.write(txt)

            completed = 0

            # --- House ---
            if 'house' in ordered_sections:
                _set_status("Finding House district(s)…")
                house_res = _agol_intersect_adaptive(
                    url=st.session_state['house_intersect']['url'],
                    layer=st.session_state['house_intersect']['layer'],
                    geometry=geom,
                    fields="GlobalID,DISTRICT",
                    return_geometry=False,
                    list_values="GlobalID",
                    string_values="DISTRICT",
                    enable_route_chunking=enable_route_chunking,
                    enable_polygon_chunking=enable_polygon_chunking,
                )
                st.session_state['house_list'] = house_res["list_values"] or []
                st.session_state['house_string'] = house_res["string_values"] or ""
                completed += 1
                progress_bar.progress(int(completed * 100 / total))

            # --- Senate ---
            if 'senate' in ordered_sections:
                _set_status("Finding Senate district(s)…")
                senate_res = _agol_intersect_adaptive(
                    url=st.session_state['senate_intersect']['url'],
                    layer=st.session_state['senate_intersect']['layer'],
                    geometry=geom,
                    fields="GlobalID,DISTRICT",
                    return_geometry=False,
                    list_values="GlobalID",
                    string_values="DISTRICT",
                    enable_route_chunking=enable_route_chunking,
                    enable_polygon_chunking=enable_polygon_chunking,
                )
                st.session_state['senate_list'] = senate_res["list_values"] or []
                st.session_state['senate_string'] = senate_res["string_values"] or ""
                completed += 1
                progress_bar.progress(int(completed * 100 / total))

            # --- Borough ---
            if 'borough' in ordered_sections:
                _set_status("Finding Borough/Census Area(s)…")
                borough_res = _agol_intersect_adaptive(
                    url=st.session_state['borough_intersect']['url'],
                    layer=st.session_state['borough_intersect']['layer'],
                    geometry=geom,
                    fields="GlobalID,NameAlt",
                    return_geometry=False,
                    list_values="GlobalID",
                    string_values="NameAlt",
                    enable_route_chunking=enable_route_chunking,
                    enable_polygon_chunking=enable_polygon_chunking,
                )
                st.session_state['borough_list'] = borough_res["list_values"] or []
                st.session_state['borough_string'] = borough_res["string_values"] or ""
                completed += 1
                progress_bar.progress(int(completed * 100 / total))

            # --- Region ---
            if 'region' in ordered_sections:
                _set_status("Finding DOT&PF Region(s)…")
                region_res = _agol_intersect_adaptive(
                    url=st.session_state['region_intersect']['url'],
                    layer=st.session_state['region_intersect']['layer'],
                    geometry=geom,
                    fields="GlobalID,NameAlt",
                    return_geometry=False,
                    list_values="GlobalID",
                    string_values="NameAlt",
                    enable_route_chunking=enable_route_chunking,
                    enable_polygon_chunking=enable_polygon_chunking,
                )
                st.session_state['region_list'] = region_res["list_values"] or []
                st.session_state['region_string'] = region_res["string_values"] or ""
                completed += 1
                progress_bar.progress(int(completed * 100 / total))

            # Optional final tick/status (still inside the container)
            progress_bar.progress(100)
            _set_status("Geography queries complete.")

    finally:
        # Clear the ENTIRE block (headline + status + bar) at the very end.
        progress_block.empty()