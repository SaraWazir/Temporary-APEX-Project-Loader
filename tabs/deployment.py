## =============================================================================
## PROJECT DEPLOYMENT TAB
## =============================================================================

import streamlit as st
import json
import hashlib
from typing import Optional, Dict, Any, List
from agol.agol_util import (
    AGOLDataLoader,
    select_record
)

## -----------------------------------------------------------------------------
## Helper: fetch active project record
## -----------------------------------------------------------------------------

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


## -----------------------------------------------------------------------------
## DEPLOY (expects a ready applyEdits payload; no internal payload building)
## -----------------------------------------------------------------------------

def _deploy_to_agol_deployment(
    payload: Dict[str, Any],
    edit_type: str,
    *,
    progress_placeholder: Optional[st.delta_generator.DeltaGenerator] = None,
) -> Dict[str, Any]:

    base_url = st.session_state.get("apex_url")
    lyr_idx = st.session_state.get("projects_layer")

    if base_url is None or lyr_idx is None:
        st.error("AGOL layer is not configured")
        return {"deployment": {"success": False}}

    loader = AGOLDataLoader(base_url)

    if edit_type == "update":
        return loader.apply_edits(lyr_idx, updates=[payload])

    if edit_type == "add":
        return loader.apply_edits(lyr_idx, adds=[payload])

    return {"deployment": {"success": False}}


## -----------------------------------------------------------------------------
## UI: Manage Deployment
## -----------------------------------------------------------------------------

def manage_deployment():

    # ---------------------------------------------------------
    # Pull project record BEFORE building the UI
    # ---------------------------------------------------------
    project_attrs = _get_project_record() or {}

    # ---------------------------------------------------------
    # Deployment Status setup
    # ---------------------------------------------------------
    deployment_status_vals: List[str] = (
        st.session_state.get("deployment_status_vals") or []
    )

    project_deployment_status = project_attrs.get("Database_Status")

    # Insert blank option if no defaults OR no values
    if not deployment_status_vals or not project_deployment_status:
        if "" not in deployment_status_vals:
            deployment_status_vals = [""] + deployment_status_vals
        default_deployment_status = ""
    else:
        default_deployment_status = project_deployment_status

    # ---------------------------------------------------------
    # Target Applications setup (multi-select)
    # ---------------------------------------------------------
    target_app_vals: List[str] = (
        st.session_state.get("target_applications_vals") or []
    )

    raw_project_targets = project_attrs.get("Target_Applications")

    if raw_project_targets:
        default_target_apps = [
            v.strip()
            for v in raw_project_targets.split(",")
            if v.strip()
        ]
    else:
        default_target_apps = []

    # Insert blank option if needed
    if not target_app_vals or not default_target_apps:
        if "" not in target_app_vals:
            target_app_vals = [""] + target_app_vals
        default_target_apps = []

    # ---------------------------------------------------------
    # UI Widgets
    # ---------------------------------------------------------
    st.markdown("##### DEPLOYMENT OF APEX PROJECT")

    deployment_status = st.selectbox(
        "Deployment Status",
        options=deployment_status_vals,
        index=deployment_status_vals.index(default_deployment_status)
        if default_deployment_status in deployment_status_vals
        else 0,
    )

    target_applications = st.multiselect(
        "Target Applications",
        options=target_app_vals,
        default=[v for v in default_target_apps if v in target_app_vals],
    )

    # Store selections back to session state if needed later
    st.session_state["selected_deployment_status"] = deployment_status
    st.session_state["selected_target_applications"] = target_applications