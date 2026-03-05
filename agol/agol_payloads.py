
"""
===============================================================================
PAYLOAD BUILDERS (STREAMLIT) — APEX / AGOL APPLYEDITS PAYLOAD FACTORIES
===============================================================================

Purpose:
    Provides helper utilities and payload factory functions used to construct
    ArcGIS "applyEdits" payloads for uploading project-related data into APEX
    (AGOL-backed) feature layers.

    This module is called by the upload orchestration layer (e.g., load_project.py)
    to build per-layer payloads based on current st.session_state values.

Key behaviors:
    - Payload normalization and cleaning:
        * clean_payload(): removes attributes that are None, 0, or '' to reduce
          noise and avoid overwriting values with empty defaults.
        * clean_payloads(): removes attributes explicitly marked "REMOVE".
    - Type conversion helpers:
        * to_date_string(): normalizes date/datetime to YYYY-MM-DD string form.
        * str_to_int(): converts currency-like strings into integers.
    - Geometry center helpers:
        * get_point_center(), get_line_center(), get_polygon_center(): compute
          representative (lon, lat) centers for display/point geometry fields.
    - Payload builders (ArcGIS applyEdits schema):
        * project_payload(): main project record with a representative point.
        * geometry_payload(): child geometry records for site/route/boundary.
        * communities_payload(): optional impacted communities child records.
        * contacts_payload(): optional contacts child records.
        * geography_payload(): optional geography overlays (region/borough/senate/
          house/route) sourced by querying reference services.

Session-state dependencies (selected examples; see each builder for details):
    - Geometry selection:
        'selected_point' | 'selected_route' | 'selected_boundary'
    - Project attributes:
        'proj_name', 'proj_desc', 'phase', 'fund_type', etc.
    - Geography selections:
        '{name}_list' keys (e.g., 'region_list', 'borough_list', ...)
    - Communities:
        'impact_comm_ids'
    - Contacts:
        'project_contacts'

Notes:
    - This module intentionally raises/returns None in a few "valid empty" cases:
        * communities_payload(): returns None when nothing exists to add.
        * contacts_payload(): returns None when no contacts exist.
        * geometry_payload(): returns None when no geometry selection exists.
        * geography_payload(): returns None when no payload was assembled.
    - Shapely is used for center computation; payload geometry structures are
      formatted as ArcGIS JSON (wkid 4326).

===============================================================================
"""

import streamlit as st
from shapely.geometry import LineString, Point, Polygon
import datetime
from agol.agol_util import select_record, get_objectids_by_identifier
from util.geospatial_util import center_of_geometry, create_buffers

# =============================================================================
# PAYLOAD CLEANING / NORMALIZATION HELPERS
# =============================================================================
# These helpers standardize outgoing payloads:
# - Remove empty values that should not be written (None/0/"")
# - Remove sentinel values used to indicate explicit removal ("REMOVE")
# =============================================================================
def clean_payload(payload: dict) -> dict:
    """
    Remove any attributes set to None, 0, or ''.

    Why:
        ArcGIS applyEdits payloads are sensitive to "empty" values. Filtering
        these prevents overwriting or storing meaningless defaults.

    Parameters:
        payload: dict
            A standard applyEdits-like payload dict containing 'adds'.

    Returns:
        dict: A cleaned payload with filtered 'attributes' per add entry.
    """
    cleaned = dict(payload)
    new_adds = []
    for add in payload.get("adds", []):
        attrs = add.get("attributes", {})
        filtered_attrs = {
            k: v for k, v in attrs.items()
            if v is not None and v != 0 and v != ""
        }
        new_add = dict(add)
        new_add["attributes"] = filtered_attrs
        new_adds.append(new_add)
    cleaned["adds"] = new_adds
    return cleaned


def to_date_string(value):
    """
    Convert a datetime.date or datetime.datetime to a string.

    Behavior:
        - If value is already a string, return it unchanged.
        - If value is None, return None.
        - If value is a date/datetime, return YYYY-MM-DD.
        - Otherwise return None.

    Rationale:
        ArcGIS services often prefer consistent date string formats when using
        attribute payloads (or when upstream sources produce mixed types).
    """
    if value is None:
        return None
    # If it's already a string, assume it's a date string and return as-is
    if isinstance(value, str):
        return value
    # If it's a date (but not datetime), promote to datetime
    if isinstance(value, datetime.date) and not isinstance(value, datetime.datetime):
        value = datetime.datetime.combine(value, datetime.time())
    # If it's a datetime, format it
    if isinstance(value, datetime.datetime):
        return value.strftime("%Y-%m-%d")
    # Anything else is invalid
    return None


def str_to_int(value):
    """
    Convert a value to an integer if it's a string.

    Behavior:
        - If value is already an int, return it unchanged.
        - If value is a string, strip $, commas, and decimals, then convert.
        - If conversion fails, return the original value.

    Notes:
        This allows number inputs to come from either numeric widgets or
        pre-formatted strings (e.g., "$12,345.00").
    """
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        cleaned = value.strip()
        cleaned = cleaned.replace("$", "").replace(",", "")
        # Remove decimal portion if present
        if "." in cleaned:
            cleaned = cleaned.split(".")[0]
        try:
            return int(cleaned)
        except ValueError:
            return value
    return value




# =============================================================================
# PAYLOAD BUILDER: PROJECT
# =============================================================================
# project_payload():
# - Determines a representative center based on selected geometry
# - Builds the "projects" layer payload
# - Uses clean_payload() to remove empty attributes before upload
# =============================================================================
def project_payload():
    try:
        
        # Determine center based on selected geometry
        if st.session_state.get("selected_point"):
            proj_type = "Site"
        elif st.session_state.get("selected_route"):
            proj_type = "Route"
        elif st.session_state.get("selected_boundary"):
            proj_type = "Boundary"


        # Create Buffer Version of Geometry for Geospatial Base
        geoms = st.session_state.get("project_geom")
        geom_type = (st.session_state.get("project_geom_type") or "").lower()

        if not geoms or not isinstance(geoms, (list, tuple)):
            raise RuntimeError("No project geometries available in session.")
        
        # Normalize single point -> list of one point (NO ORDER SWAP)
        if (
            isinstance(geoms, (list, tuple))
            and len(geoms) == 2
            and all(isinstance(v, (int, float)) for v in geoms)
        ):
            geoms = [geoms]

        # --- Split by kind (copying the impact_area method) ---
        points, lines, polys = [], [], []

        def _as_lonlat_pair(v):
            return [float(v[0]), float(v[1])]

        for item in geoms:
            # POINT: [lon, lat]
            if isinstance(item, (list, tuple)) and len(item) == 2 and all(isinstance(v, (int, float)) for v in item):
                points.append(_as_lonlat_pair(item))
            # LINE/POLY: [[lon, lat], ...]
            elif (
                isinstance(item, (list, tuple))
                and item
                and isinstance(item[0], (list, tuple))
                and len(item[0]) == 2
                and all(isinstance(v, (int, float)) for v in item[0])
            ):
                coords = [_as_lonlat_pair(p) for p in item]
                is_closed = len(coords) >= 4 and coords[0] == coords[-1]
                if is_closed:
                    polys.append(coords)
                else:
                    lines.append(coords)

        # --- Create buffers (10 m fixed) ---
        buffers = []
    
        # If a single declared type is provided, respect it. Otherwise, rely on split result.
        if geom_type in ("point",):
            if points:
                buffers += create_buffers(geometry_list=points, geom_type="point", distance_m=100)
        elif geom_type in ("line", "linestring"):
            if lines:
                buffers += create_buffers(geometry_list=lines, geom_type="line", distance_m=50)
        elif geom_type in ("polygon",):
            if polys:
                buffers += create_buffers(geometry_list=polys, geom_type="polygon", distance_m=1)
        else:
            # Fallback: make buffers for whatever was detected
            if points:
                buffers += create_buffers(geometry_list=points, geom_type="point", distance_m=100)
            if lines:
                buffers += create_buffers(geometry_list=lines, geom_type="line", distance_m=50)
            if polys:
                buffers += create_buffers(geometry_list=polys, geom_type="polygon", distance_m=1)

        if not buffers:
            raise RuntimeError("Buffering produced no output (check geometry and 10 m distance).")

        # --- ESRI Polygon geometry (multipart via rings) ---
        esri_polygon = {
            "rings": buffers,  # list of rings (each is [[lon, lat], ...])
            "spatialReference": {"wkid": 4326},
        }

        # Build payload with .get() and default None
        payload = {
            "adds": [
                {
                    "attributes": {
                        "Proj_Type": proj_type,
                        "AWP_Proj_Name": st.session_state.get("awp_proj_name", None),
                        "Proj_Name": st.session_state.get("proj_name", None),
                        "Construction_Year": st.session_state.get("construction_year", None),
                        "New_Continuing": st.session_state.get("new_continuing", None),
                        "Phase": st.session_state.get("phase", None),
                        "IRIS": st.session_state.get("iris", None),
                        "STIP": st.session_state.get("stip", None),
                        "Fed_Proj_Num": st.session_state.get("fed_proj_num", None),                     
                        "Fund_Type": st.session_state.get("fund_type", None),
                        "Proj_Prac": st.session_state.get("proj_prac", None),
                        "Anticipated_Start": st.session_state.get("anticipated_start", None),
                        "Anticipated_End": st.session_state.get("anticipated_end", None),
                        "Awarded": "Yes" if st.session_state.get("contractor") else "No",
                        "Award_Date": to_date_string(st.session_state.get("award_date", None)),
                        "Award_Fiscal_Year": st.session_state.get("award_fiscal_year", None),
                        "Contractor": st.session_state.get("contractor", None),
                        "Awarded_Amount": str_to_int(st.session_state.get("awarded_amount", None)),
                        "Current_Contract_Amount": str_to_int(st.session_state.get("current_contract_amount", None)),
                        "Amount_Paid_to_Date": str_to_int(st.session_state.get("amount_paid_to_date", None)),
                        "TenAdd": to_date_string(st.session_state.get("tenadd", None)),
                        "AWP_Proj_Desc": st.session_state.get("awp_proj_desc", None),
                        "Proj_Desc": st.session_state.get("proj_desc", None),
                        "Contact_Name": st.session_state.get("contact_name", None),
                        "Contact_Email": st.session_state.get("contact_email", None),
                        "Contact_Phone": st.session_state.get("contact_phone", None),
                        "Impact_Comm": st.session_state.get("impact_comm_names", None),
                        "AWP_DOT_PF_Region": st.session_state.get("awp_region", None),
                        "AWP_Borough_Census_Area": st.session_state.get("awp_borough", None),
                        "AWP_Senate_District": st.session_state.get("awp_senate", None),
                        "AWP_House_District": st.session_state.get("awp_house", None),
                        "List_DOT_PF_Region": st.session_state.get("region_string", None),
                        "List_Borough_Census_Area": st.session_state.get("borough_string", None),
                        "List_Senate_District": st.session_state.get("senate_string", None),
                        "List_House_District": st.session_state.get("house_string", None),
                        "List_Route_ID": st.session_state.get("route_ids", None),
                        "List_Route_Name": st.session_state.get("route_names", None),
                        "Proj_Web": st.session_state.get("proj_web", None),
                        'Submitted_By': st.session_state.get('submitted_by', None),
                        "Database_Status": "Review: Awaiting Review",
                        "AWP_Contract_ID": st.session_state.get("awp_guid", None),
                        "AWP_Update": st.session_state.get("awp_update", None)
                    },
                    "geometry": esri_polygon
                }
            ]
        }
        return clean_payload(payload)
    except Exception as e:
        # Bubble up error so caller can handle with st.error
        raise RuntimeError(f"Error building project payload: {e}")


# =============================================================================
# PAYLOAD BUILDER: GEOMETRY (SITES / ROUTES / BOUNDARIES)
# =============================================================================
# geometry_payload():
# - Builds one or more child geometry records based on the selected geometry type
# - Normalizes nesting for points, routes (paths), and boundaries (rings)
# - Returns a list of cleaned payloads (one per geometry) or None if no selection
# =============================================================================
def geometry_payload():
    try:
        payloads = []  # final list of cleaned payloads
    
        # ---------------------------------------------------------------------
        # POINT CASE
        # ---------------------------------------------------------------------
        if st.session_state.get("selected_point"):
            points = st.session_state["selected_point"]

            for lon, lat in points:
                payload = {
                    "adds": [
                        {
                            "attributes": {
                                "Site_AWP_Proj_Name": st.session_state.get("awp_proj_name"),
                                "Site_Proj_Name": st.session_state.get("proj_name"),
                                "Site_DOT_PF_Region": st.session_state.get("region_string"),
                                "Site_Borough_Census_Area": st.session_state.get("borough_string"),
                                "Site_Senate_District": st.session_state.get("senate_string"),
                                "Site_House_District": st.session_state.get("house_string"),
                                "parentglobalid": st.session_state.get("apex_globalid", None)
                            },
                            "geometry": {
                                "x": float(lon),
                                "y": float(lat),
                                "spatialReference": {"wkid": 4326}
                            }
                        }
                    ]
                }
                
                payloads.append(clean_payload(payload))
            return payloads

        # ---------------------------------------------------------------------
        # ROUTE CASE (POLYLINES)
        # ---------------------------------------------------------------------
        elif st.session_state.get("selected_route"):
            routes = st.session_state["selected_route"]

            for route in routes:
                payload = {
                    "adds": [
                        {
                            "attributes": {
                                "Route_AWP_Proj_Name": st.session_state.get("awp_proj_name"),
                                "Route_Proj_Name": st.session_state.get("proj_name"),
                                "Route_DOT_PF_Region": st.session_state.get("region_string"),
                                "Route_Borough_Census_Area": st.session_state.get("borough_string"),
                                "Route_Senate_District": st.session_state.get("senate_string"),
                                "Route_House_District": st.session_state.get("house_string"),
                                "parentglobalid": st.session_state.get("apex_globalid", None)
                            },
                            "geometry": {
                                "paths": [route],
                                "spatialReference": {"wkid": 4326}
                            }
                        }
                    ]
                }
                payloads.append(clean_payload(payload))
            return payloads

        # ---------------------------------------------------------------------
        # BOUNDARY CASE (POLYGONS)
        # ---------------------------------------------------------------------
        elif st.session_state.get("selected_boundary"):
            boundaries = st.session_state["selected_boundary"]
            
            for ring in boundaries:
                payload = {
                    "adds": [
                        {
                            "attributes": {
                                "Boundary_AWP_Proj_Name": st.session_state.get("awp_proj_name"),
                                "Boundary_Proj_Name": st.session_state.get("proj_name"),
                                "Boundary_DOT_PF_Region": st.session_state.get("region_string"),
                                "Boundary_Borough_Census_Area": st.session_state.get("borough_string"),
                                "Boundary_Senate_District": st.session_state.get("senate_string"),
                                "Boundary_House_District": st.session_state.get("house_string"),
                                "parentglobalid": st.session_state.get("apex_globalid", None)
                            },
                            "geometry": {
                                "rings": [ring],
                                "spatialReference": {"wkid": 4326}
                            }
                        }
                    ]
                }
                payloads.append(clean_payload(payload))
            return payloads

        # ---------------------------------------------------------------------
        # NOTHING SELECTED
        # ---------------------------------------------------------------------
        else:
            return None
    except Exception as e:
        st.error(f"Error building geometry payload: {e}")
        return None




def location_payload():
    """
    Build an AGOL-ready 'adds' payload from session-state inputs:
      - st.session_state["projects_geom"]: geometry(ies) in [lon, lat]
      - st.session_state["projects_geom_type"]: 'point' | 'line'/'linestring' | 'polygon'

    Steps:
      1) Split geoms into points/lines/polys (same pattern as impact_area).
      2) Create buffers per kind using create_buffers(...) with fixed 10 m.
      3) Combine rings into a single ESRI Polygon geometry (multipart).
      4) Build and return the applyEdits payload with Impact_Area attributes.
    """
    try:

        # Determine center based on selected geometry
        if st.session_state.get("selected_point"):
            pt = st.session_state["selected_point"]
            st.session_state['center'] = center_of_geometry(pt, "Point")
        elif st.session_state.get("selected_route"):
            route = st.session_state["selected_route"]
            st.session_state['center'] =  center_of_geometry(route, "Line")
        elif st.session_state.get("selected_boundary"):
            boundary = st.session_state["selected_boundary"]
            st.session_state['center'] = center_of_geometry(boundary, "Polygon")


        # --- Build payload with Impact_Area attribute schema ---
        payload = {
            "adds": [
                {
                    "attributes": {
                        "Location_AWP_Proj_Name": st.session_state.get("awp_proj_name", None),
                        "Location_Area_Proj_Name": st.session_state.get("proj_name", None),
                        "Location_Area_DOT_PF_Region": st.session_state.get("region_string", None),
                        "Location_Area_Borough_Census_Area": st.session_state.get("borough_string", None),
                        "Location_Area_Senate_District": st.session_state.get("senate_string", None),
                        "Location_Area_House_District": st.session_state.get("house_string", None),
                        "parentglobalid": st.session_state.get("apex_globalid", None)
                    },
                    "geometry": {
                        "x": st.session_state['center'][0] if st.session_state['center'] else None,  # longitude
                        "y": st.session_state['center'][1] if st.session_state['center'] else None,  # latitude
                        "spatialReference": {"wkid": 4326}
                        
                    }
                }
            ]
        }

        return clean_payload(payload)

    except Exception as e:
        raise RuntimeError(f"Error building buffered project polygon payload: {e}")


# =============================================================================
# PAYLOAD BUILDER: IMPACTED COMMUNITIES (OPTIONAL)
# =============================================================================
def communities_payload():
    """
    Build an ArcGIS applyEdits payload for impacted communities.

    Returns:
        dict | None:
            - dict: cleaned payload containing 'adds' for each resolved community
            - None: when there are no impacted communities, or no usable records

    Notes:
        - Communities are resolved via select_record() against a reference service.
        - Records with missing required fields are skipped rather than failing.
    """
    try:
        comm_list = st.session_state.get("impact_comm_ids", None)
        if not comm_list:
            # Valid case: nothing to add
            return None

        payload = {"adds": []}
        comms_url = st.session_state['communities']

        for comm_id in comm_list:
            comms_data = select_record(
                comms_url,
                7,
                "DCCED_CommunityId",
                str(comm_id),
                fields="OverallName,Latitude,Longitude"
            )
            if not comms_data:
                # Skip silently if no record found
                continue

            attrs = comms_data[0].get("attributes", {})
            name = attrs.get("OverallName")
            y = attrs.get("Latitude")
            x = attrs.get("Longitude")
            if name and y is not None and x is not None:
                payload["adds"].append({
                    "attributes": {
                        "Community_Name": name,
                        "parentglobalid": st.session_state.get("apex_globalid", None)
                    },
                    "geometry": {
                        "x": x,
                        "y": y,
                        "spatialReference": {"wkid": 4326}
                    }
                })
            # If required fields are missing, skip this community instead of raising

        if not payload["adds"]:
            # Valid case: no usable community records
            return None

        return clean_payload(payload)
    except Exception as e:
        st.error(f"Error building communities payload: {e}")
        return




# =============================================================================
# PAYLOAD BUILDER: GEOGRAPHY (OPTIONAL OVERLAYS)
# =============================================================================
def geography_payload(name: str):
    """
    Build a payload containing attributes and geometry for a given geography type.

    Parameters:
        globalid: str
            The parent GlobalID to associate with the payload.
        name: str
            The geography type to process. Supported values include:
            'region', 'borough', 'senate', 'house', and 'route'.

    Returns:
        dict | None:
            - dict: cleaned payload with 'adds' entries containing attributes + geometry
            - None: when no payload could be assembled (no IDs or no results)

    Mechanism:
        - IDs are read from st.session_state[f"{name}_list"]
        - Records are fetched from an AGOL reference service via select_record()
        - The returned geometry is passed through directly into the outgoing payload
    """

    payload = {}

    # -------------------------------------------------------------------------
    # REGION
    # -------------------------------------------------------------------------
    if name == 'region':
        id_list = st.session_state.get(f"{name}_list")
    
        payload = {"adds": []}
        for item_id in id_list:
            # Query record from AGOL service
            data = select_record(
                url = st.session_state['region_intersect']['url'],
                layer = st.session_state['region_intersect']['layer'],
                id_field = "GlobalID", 
                id_value = str(item_id), 
                fields="*", 
                return_geometry=True
            )
            if not data:
                continue
            attrs = data[0].get("attributes", {})
            geom = data[0].get("geometry", {})
            region_name = attrs.get("NameAlt")
            payload["adds"].append({
                "attributes": {
                    "Region_Name": region_name,
                    "parentglobalid": st.session_state.get("apex_globalid", None),
                },
                "geometry": geom
            })

    # -------------------------------------------------------------------------
    # BOROUGH
    # -------------------------------------------------------------------------
    if name == 'borough':
        id_list = st.session_state.get(f"{name}_list")

        payload = {"adds": []}
        for item_id in id_list:
            data = select_record(
                url = st.session_state['borough_intersect']['url'],
                layer = st.session_state['borough_intersect']['layer'],
                id_field = "GlobalID", 
                id_value = str(item_id), 
                fields="*", 
                return_geometry=True
            )
            if not data:
                continue
            attrs = data[0].get("attributes", {})
            geom = data[0].get("geometry", {})
            fips = attrs.get('FIPS')
            borough_name = attrs.get("NameAlt")
            payload["adds"].append({
                "attributes": {
                    "Bor_FIPS": fips,
                    "Bor_Name": borough_name,
                    "parentglobalid": st.session_state.get("apex_globalid", None),
                },
                "geometry": geom
            })

    # -------------------------------------------------------------------------
    # SENATE
    # -------------------------------------------------------------------------
    if name == 'senate':
        id_list = st.session_state.get(f"{name}_list")
        if not id_list:
            print(None)

        payload = {"adds": []}
        for item_id in id_list:
            data = select_record(
                url = st.session_state['senate_intersect']['url'],
                layer = st.session_state['senate_intersect']['layer'],
                id_field = "GlobalID", 
                id_value = str(item_id), 
                fields="*", 
                return_geometry=True
            )
            if not data:
                continue
            attrs = data[0].get("attributes", {})
            geom = data[0].get("geometry", {})
            district = attrs.get("DISTRICT")
            payload["adds"].append({
                "attributes": {
                    "Senate_District_Name": district,
                    "parentglobalid": st.session_state.get("apex_globalid", None),
                },
                "geometry": geom
            })


    # -------------------------------------------------------------------------
    # HOUSE
    # -------------------------------------------------------------------------
    if name == 'house':
        id_list = st.session_state.get(f"{name}_list")
        if not id_list:
            print(None)

        payload = {"adds": []}
        for item_id in id_list:
            data = select_record(
                url = st.session_state['house_intersect']['url'],
                layer = st.session_state['house_intersect']['layer'],
                id_field = "GlobalID", 
                id_value = str(item_id), 
                fields="*", 
                return_geometry=True
            )
            if not data:
                continue
            attrs = data[0].get("attributes", {})
            geom = data[0].get("geometry", {})
            house_num = attrs.get("DISTRICT")
            house_name = attrs.get("HOUSE_NAME")
            senate = attrs.get("SENATE_DISTRICT")
            payload["adds"].append({
                "attributes": {
                    "House_District_Num": house_num,
                    "House_District_Name": house_name,
                    "House_Senate_District": senate,
                    "parentglobalid": st.session_state.get("apex_globalid", None),
                },
                "geometry": geom
            })

    return clean_payload(payload)

    


def traffic_impact_payload():
    try:
        if st.session_state.get("project_traffic_impact_area"):
            area = st.session_state["project_traffic_impact_area"]
        else:
            raise ValueError("No traffic impact area geometry selected.")

        payload = {
            "adds": [
                {
                    "attributes": {
                        "Event_Name": f"Traffic Impact @ {st.session_state.get('project_impact_route_name')}",
                        "AWP_Proj_Name": st.session_state.get("awp_proj_name"),
                        "Proj_Name": st.session_state.get("proj_name"),
                        "Route_ID": st.session_state.get("project_impact_route_id"),
                        "Route_Name": st.session_state.get("project_impact_route_name"),
                        "Start_X": st.session_state.get("project_impact_start_point_x"),
                        "Start_Y": st.session_state.get("project_impact_start_point_y"),
                        "End_X": st.session_state.get("project_impact_end_point_x"),
                        "End_Y": st.session_state.get("project_impact_end_point_y"),
                        "Event_Type_COMM": "Roadwork / Maintenance",
                        "Assignee": "Unassigned",
                        "Alaska_511_COMM": "No", 
                        "Alaska_511": "No",
                        "APEX_GUID": st.session_state.get("apex_globalid").strip("{}"),
                        "APEX_Database_Status": "Review: Awaiting Review"
                    },
                    "geometry": {
                        "rings": area,   # Matches Boundary Example
                        "spatialReference": {"wkid": 4326}
                    }
                }
            ]
        }

        return clean_payload(payload)

    except Exception as e:
        raise RuntimeError(f"Error building Traffic Impact Payload: {e}")

    


def traffic_impact_route_payload():
    try:
        # Ensure geometry exists
        if not st.session_state.get("project_impacted_route"):
            raise ValueError("No traffic impact route geometry selected.")

        path = st.session_state.get("project_impacted_route")
        
        payload = {
            "adds": [
                {
                    "attributes": {
                        "parentglobalid": st.session_state.get("traffic_impact_globalid"),
                    },
                    "geometry": {
                        "paths": [path],
                        "spatialReference": {"wkid": 4326}
                    }
                }
            ]
        }
        return clean_payload(payload)

    except Exception as e:
        raise RuntimeError(f"Error building Traffic Impact Route Payload: {e}")




def traffic_impact_start_point_payload():
    try:
        # Ensure geometry exists
        if not st.session_state.get("project_impact_start_point"):
            raise ValueError("No traffic impact start point geometry selected.")
        
        points = st.session_state["project_impact_start_point"]
        
        if not points:
            raise ValueError("No valid start point geometry found.")

        # Build payloads for each point
        for lon, lat in points:
            payload = {
                "adds": [
                    {
                        "attributes": {
                            "parentglobalid": st.session_state.get("traffic_impact_globalid"),
                        },
                        "geometry": {
                            "x": float(lon),   # lon = x
                            "y": float(lat),   # lat = y
                            "spatialReference": {"wkid": 4326}
                        }
                    }
                ]
            }
        return clean_payload(payload)

    except Exception as e:
        raise RuntimeError(f"Error building Traffic Impact Start Point Payload: {e}")




def traffic_impact_end_point_payload():
    try:
        # Ensure geometry exists
        if not st.session_state.get("project_impact_end_point"):
            raise ValueError("No traffic impact end point geometry selected.")

        
        points = st.session_state["project_impact_end_point"]
    

        if not points:
            raise ValueError("No valid end point geometry found.")

        # Build payloads for each point
        for lon, lat in points:
            payload = {
                "adds": [
                    {
                        "attributes": {
                            "parentglobalid": st.session_state.get("traffic_impact_globalid"),
                        },
                        "geometry": {
                            "x": float(lon),   # lon = x
                            "y": float(lat),   # lat = y
                            "spatialReference": {"wkid": 4326}
                        }
                    }
                ]
            }

        return clean_payload(payload)

    except Exception as e:
        raise RuntimeError(f"Error building Traffic Impact End Point Payload: {e}")
    



def awp_apex_cy_payload():
    # Locate OBJECTID
    object_id = get_objectids_by_identifier(
        url=st.session_state['aashtoware_url'],
        layer=0,
        id_field="Id",
        id_value=st.session_state.get("awp_guid")
    )

    # Read session values
    cy_awp = st.session_state.get("awp_selected_construction_years")
    cy_year = st.session_state.get("construction_year")

    # --- Normalize existing AWP years into a list ---
    if isinstance(cy_awp, str):
        cy_list = [v.strip() for v in cy_awp.split(",") if v.strip()]
    elif isinstance(cy_awp, list):
        cy_list = list(cy_awp)
    else:
        cy_list = []

    # --- Add the new selected year if it is not blank and not already included ---
    if cy_year and cy_year not in cy_list:
        cy_list.append(cy_year)

    # Back to comma‑separated string
    cy_list_str = ", ".join(cy_list)

    # --- Build final payload ---
    try:
        payload = {
            "updates": [
                {
                    "attributes": {
                        "OBJECTID": object_id,
                        "ConstructionYears": cy_list_str
                    }
                }
            ]
        }

        return clean_payload(payload)

    except Exception as e:
        raise RuntimeError(f"Error building Construction Years payload: {e}")