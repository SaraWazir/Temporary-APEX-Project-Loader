# =============================================================================
# FOOTPRINT MANAGEMENT TAB
# =============================================================================
import streamlit as st
import json
from agol.agol_util import (
    select_record,
    AGOLDataLoader
)
from agol.agol_payloads import (
    manage_information_payload
)
from util.read_only_util import ro_widget
from util.input_util import (
    fmt_string,
    fmt_date,
    fmt_agol_date,
    fmt_currency,
    fmt_int,
    fmt_int_or_none,
    fmt_date_or_none,
    widget_key,
)
# ⬇️ also import aashtoware_project so we can render the selector
from util.streamlit_util import session_selectbox, aashtoware_project
from typing import Optional, Dict, Any

from util.geometry_util import (
    point_shapefile,
    polyline_shapefile,
    polygon_shapefile,
    enter_latlng,
    draw_point,
    draw_line,
    draw_boundary,
    aashtoware_point,
    aashtoware_path,
)
from util.streamlit_util import (
    segmented_with_safe_default,
    handle_project_type_change,
    handle_upload_method_change,
    run_queries_if_geometry_changed,
    render_geographies_expander,
)
from agol.agol_util import aashtoware_geometry  # (kept for side effects elsewhere if needed)
from agol.agol_district_queries import run_district_queries  # noqa: F401 (referenced in utilities)



# -----------------------------------------------------------------------------
# Helper: fetch active project record
# -----------------------------------------------------------------------------
def _get_project_record():
    apex_guid = st.session_state.get("apex_guid")
    url = st.session_state.get("apex_url")
    layer = st.session_state.get("projects_layer")
    if not (apex_guid and url and layer is not None):
        return None
    recs = select_record(
        url=url,
        layer=layer,
        id_field="globalid",
        id_value=apex_guid,
        fields="*",
        return_geometry=False,
    )
    return recs[0]["attributes"] if recs else None


def deploy_to_agol_footprint(
    payload: Dict[str, Any],
    edit_type: str,
    geom_type: str,
    *,
    progress_placeholder: Optional[st.delta_generator.DeltaGenerator] = None,
) -> Dict[str, Any]:
    """
    Submit the Project Information applyEdits payload to AGOL.
    - Uses st.session_state['apex_url'] and st.session_state['projects_layer'].
    - Supports ONLY 'adds' and 'updates'. 'deletes' is explicitly rejected.
    - Normalizes OBJECTID key casing for updates if needed.
    """
    # APEX URL
    base_url = st.session_state.get("apex_url")

    # Projects Layer
    projects_layer = st.session_state.get('projects_layer')

    # Footprint Layers
    sites_layer = st.session_state.get("sites_layer")
    routes_layer = st.session_state.get("routes_layer")
    boundaries_layer = st.session_state.get("boundaries_layer")

    # Geography Layers
    region_layer = st.session_state.get("region_layer")
    bor_layer = st.session_state.get("bor_layer")
    senate_layer = st.session_state.get("senate_layer")
    house_layer = st.session_state.get("house_layer")
    
    if base_url is None or projects_layer is None:
        st.error("AGOL Projects layer is not configured (missing apex_url or projects_layer).")
        return {"success": False, "message": "Layer not configured"}
    
    if sites_layer is None or routes_layer is None or boundaries_layer is None:
        st.error("AGOL Footprints layers are not configured (UPDATE THIS).")
        return {"success": False, "message": "Layer not configured"}
    
    if region_layer is None or bor_layer is None or senate_layer is None or house_layer is None:
        st.error("AGOL Geospatial layers are not configured (UPDATE THIS).")
        return {"success": False, "message": "Layer not configured"}

    if edit_type not in ("adds", "updates"):
        st.warning("manage_information does not support deletes. Skipping request.")
        return {"success": False, "message": f"Unsupported edit_type '{edit_type}'"}

    #ENTER CHECK BA
    if geom_type == 'point':
        loader = AGOLDataLoader(base_url, sites_layer)
    elif geom_type == 'line':
        loader = AGOLDataLoader(base_url, routes_layer)
    elif geom_type == 'polygon':
        loader = AGOLDataLoader(base_url, boundaries_layer)
    

    def _progress(frac: float, text: str):
        if progress_placeholder is not None:
            progress_placeholder.progress(frac, text=text)
        else:
            st.progress(frac, text=text)

    # Show initial state
    _progress(0.0, f"Submitting Footprint {edit_type} to AGOL…")

    try:
        if edit_type == "updates":
            # Normalize OBJECTID casing if caller supplied "objectId"
            if isinstance(payload, dict) and "updates" in payload:
                for rec in payload.get("updates") or []:
                    attrs = rec.get("attributes", {})
                    if "OBJECTID" not in attrs and "objectId" in attrs:
                        attrs["OBJECTID"] = attrs.pop("objectId")
            result = loader.update_features(payload)
        else:
            # Should never hit given the earlier check; keep for safety.
            return {"success": False, "message": f"Unsupported edit_type '{edit_type}'"}
        _progress(1.0, "Done")
        return result or {"success": True}
    except Exception as e:
        return {"success": False, "message": str(e)}





def manage_footprint():

    # APEX URL
    base_url = st.session_state.get("apex_url")

    # Projects Layer
    projects_layer = st.session_state.get('projects_layer')

    # Footprint Layers
    sites_layer = st.session_state.get("sites_layer")
    routes_layer = st.session_state.get("routes_layer")
    boundaries_layer = st.session_state.get("boundaries_layer")

    # Geography Layers
    region_layer = st.session_state.get("region_layer")
    bor_layer = st.session_state.get("bor_layer")
    senate_layer = st.session_state.get("senate_layer")
    house_layer = st.session_state.get("house_layer")
    
    if base_url is None or projects_layer is None:
        st.error("AGOL Projects layer is not configured (missing apex_url or projects_layer).")
    
    if sites_layer is None or routes_layer is None or boundaries_layer is None:
        st.error("AGOL Footprints layers are not configured (UPDATE THIS).")
        
    if region_layer is None or bor_layer is None or senate_layer is None or house_layer is None:
        st.error("AGOL Geospatial layers are not configured (UPDATE THIS).")
        

    # Pull Footprint Information from Project Record
    rec = _get_project_record()
    proj_type = rec.get("Proj_Type")

    # Pull Footprint Information
    footprint_rec = None
    if proj_type == "Site":
        footprint_rec = select_record(
            url = base_url,
            layer = sites_layer,
            id_field = 'parentglobalid',
            id_value = st.session_state['apex_guid'],
            fields = '*',
            return_geometry=True
        )
    elif proj_type == 'Route':
        footprint_rec = select_record(
            url = base_url,
            layer = routes_layer,
            id_field = 'parentglobalid',
            id_value = st.session_state['apex_guid'],
            fields = '*',
            return_geometry=True
        )
    elif proj_type == 'Boundary':
        footprint_rec = select_record(
            url = base_url,
            layer = boundaries_layer,
            id_field = 'parentglobalid',
            id_value = st.session_state['apex_guid'],
            fields = '*',
            return_geometry=True
        )

    
    st.markdown(footprint_rec)