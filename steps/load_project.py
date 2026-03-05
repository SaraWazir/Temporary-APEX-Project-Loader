"""
===============================================================================
LOAD PROJECT (STREAMLIT) — APEX / AGOL UPLOAD ORCHESTRATION
===============================================================================

Purpose:
    Orchestrates the Streamlit workflow for uploading a project and its related
    datasets into APEX (AGOL-backed) layers using AGOLDataLoader.

    This module:
      - Builds payloads using the payload factory functions (payloads.py)
      - Uploads records to the appropriate AGOL layers in a defined sequence
      - Reports per-step success/failure to the Streamlit UI
      - Aggregates failures and summarizes them (no automatic deletion)

Key behaviors:
    Upload order (and failure semantics):
      1) Project
         - HARD STOP if this fails (st.stop()) because dependent uploads require
           the created GlobalID.
      2) Geometry
         - May upload one or multiple geometry payloads
         - Aggregates per-geometry failures for clear user feedback
      3) Communities (optional)
      4) Contacts (optional)   # (contacts not in this function; reserved)
      5) Geography layers (optional; depends on presence of {name}_list keys)
      6) Traffic impact artifacts (silent; failures summarized at the end)

    Failure handling pattern:
      - Project failure: show error, record failure with step name, and st.stop()
      - Downstream failure(s): record failures with step names; at end, present
        a clear summary of which steps failed. No automatic deletion is performed.

Session-state dependencies (expected at runtime):
    Connection:
      - 'apex_url'

    Layer IDs:
      - 'projects_layer', 'sites_layer', 'routes_layer', 'boundaries_layer'
      - 'impact_comms_layer', 'contacts_layer'  # contacts not used in this file
      - 'region_layer', 'bor_layer', 'house_layer', 'senate_layer'
      - optional: 'impact_routes_layer' (used when route or boundary selected)
      - 'traffic_impacts', 'start_points', 'end_points'

    Geometry selection flags:
      - 'selected_point', 'selected_route', 'selected_boundary'

    Geography presence flags:
      - '{name}_list' keys (e.g., 'region_list', 'borough_list', etc.)
        NOTE: these keys gate whether the corresponding geography layer uploads.

    Results / status:
      - 'apex_globalid' (set after project upload)
      - 'upload_complete' (set True when all steps succeed)

    Error aggregation:
      - 'step_failures' list (accumulated dicts: {'step': str, 'message': str})

Notes:
    - This module is intentionally UI-driven: it uses Streamlit spinners, success/
      error messages, and session_state to communicate status.
    - No automatic cleanup is attempted on error.
===============================================================================
"""

from __future__ import annotations

import streamlit as st

from agol.agol_util import AGOLDataLoader, format_guid, delete_cascade_by_globalid
from agol.agol_payloads import (
    communities_payload,
    geography_payload,
    geometry_payload,
    project_payload,
    traffic_impact_payload,
    traffic_impact_route_payload,
    traffic_impact_start_point_payload,
    traffic_impact_end_point_payload,
    location_payload
)

# -----------------------------------------------------------------------------
# Helper: record a structured failure with step name and message
# -----------------------------------------------------------------------------
def _record_failure(step: str, message: str) -> None:
    st.session_state.setdefault("step_failures", [])
    st.session_state["step_failures"].append({"step": step, "message": str(message)})


# =============================================================================
# ENTRYPOINT: PROJECT + RELATED DATASETS UPLOAD
# =============================================================================
def load_project_apex() -> None:
    """
    Upload the current Streamlit session's project and related records into APEX.

    Failure handling:
        - Project upload failure is a hard stop (st.stop()) because the GlobalID
          is required for all dependent payloads.
        - Subsequent failures are collected into st.session_state['step_failures'].
          At the end, a summary of failed steps is displayed. No deletion is attempted.

    Returns:
        None (side effects only: Streamlit UI + st.session_state updates).
    """

    spinner_container = st.empty()

    # -------------------------------------------------------------------------
    # STEP 1: UPLOAD PROJECT (HARD STOP ON FAILURE)
    # -------------------------------------------------------------------------
    with spinner_container, st.spinner("Loading Project to APEX..."):
        try:
            payload_project = project_payload()
            projects_layer = st.session_state["projects_layer"]
            load_project = (
                AGOLDataLoader(
                    url=st.session_state["apex_url"], layer=projects_layer
                ).add_features(payload_project)
                if payload_project
                else {"success": False, "message": "Failed to Load Project to APEX DB"}
            )
        except Exception as e:
            load_project = {"success": False, "message": f"Project payload error: {e}"}
    spinner_container.empty()

    if not load_project.get("success"):
        error_msg = load_project.get("message", "Unknown error")
        st.error(f"LOAD PROJECT: FAILURE ❌ {error_msg}")
        _record_failure("Project", error_msg)
        st.stop()

    # Project success
    st.session_state["apex_globalid"] = format_guid(load_project["globalids"])
    st.success("LOAD PROJECT: SUCCESS ✅")
    

    # -------------------------------------------------------------------------
    # STEP 2: UPLOAD GEOMETRY (MAY BE MULTIPLE GEOMETRIES)
    # -------------------------------------------------------------------------
    with spinner_container, st.spinner("Loading Project Geometry to APEX..."):
        failures = []
        try:
            payload_geometries = geometry_payload()

            # Determine which layer to load based on the selection flags.
            if st.session_state.get("selected_point"):
                geometry_layer = st.session_state["sites_layer"]
                geometry_type = "Point Geometry"
            elif st.session_state.get("selected_route"):
                geometry_layer = st.session_state["routes_layer"]
                geometry_type = "Route Geometry"
            elif st.session_state.get("selected_boundary"):
                geometry_layer = st.session_state["boundaries_layer"]
                geometry_type = "Boundary Geometry"
            else:
                raise ValueError("No geometry type selected.")

            loader = AGOLDataLoader(
                url=st.session_state["apex_url"], layer=geometry_layer
            )

            geometries = (
                payload_geometries
                if isinstance(payload_geometries, list)
                else [payload_geometries]
            )

            for idx, geom in enumerate(geometries, start=1):
                step_name = f"{geometry_type} #{idx}" if len(geometries) > 1 else geometry_type
                if not geom:
                    msg = f"{step_name}: Empty geometry payload."
                    failures.append(msg)
                    _record_failure(step_name, msg)
                    continue
                result = loader.add_features(geom)
                if not result.get("success"):
                    msg = f"{step_name}: {result.get('message', 'Unknown geometry upload failure.')}"
                    failures.append(msg)
                    _record_failure(step_name, msg)
        except Exception as e:
            msg = f"Project Geometry payload error: {e}"
            failures.append(msg)
            _record_failure("Geometry", msg)
    spinner_container.empty()

    if not failures:
        st.success("LOAD GEOMETRY: SUCCESS ✅")
    else:
        st.error("LOAD GEOMETRY: FAILURE ❌")
        for msg in failures:
            st.error(f"• {msg}")

    # -------------------------------------------------------------------------
    # STEP 3: UPLOAD COMMUNITIES (OPTIONAL)
    # -------------------------------------------------------------------------
    if st.session_state.get('impact_comm_ids') != None:
        with spinner_container, st.spinner("Loading Communities to APEX..."):
            try:
                payload_communities = communities_payload()
                communities_layer = st.session_state["impact_comms_layer"]
                if payload_communities is None:
                    load_communities = None
                else:
                    load_communities = AGOLDataLoader(
                        url=st.session_state["apex_url"], layer=communities_layer
                    ).add_features(payload_communities)
            except Exception as e:
                load_communities = {"success": False, "message": f"Communities payload error: {e}"}
        spinner_container.empty()

        if load_communities is not None:
            if load_communities.get("success"):
                st.success("LOAD COMMUNITIES: SUCCESS ✅")
            else:
                msg = load_communities.get("message", "Unknown communities upload error.")
                st.error(f"LOAD COMMUNITIES: FAILURE ❌ {msg}")
                _record_failure("Communities", msg)

    # -------------------------------------------------------------------------
    # STEP 4: UPLOAD GEOGRAPHY (OPTIONAL; GATED BY SESSION_STATE LIST PRESENCE)
    # -------------------------------------------------------------------------
    with spinner_container, st.spinner("Loading Geography to APEX..."):
        geography_layers = {
            "region": st.session_state["region_layer"],
            "borough": st.session_state["bor_layer"],
            "senate": st.session_state["senate_layer"],
            "house": st.session_state["house_layer"],
        }

        load_results = {}
        try:
            for name, layer_id in geography_layers.items():
                if f"{name}_list" in st.session_state:
                    payload = geography_payload(name)
                    if payload is None:
                        load_results[name] = None
                    else:
                        load_results[name] = AGOLDataLoader(
                            url=st.session_state["apex_url"], layer=layer_id
                        ).add_features(payload)
        except Exception as e:
            load_results["__error__"] = {"success": False, "message": f"Geography payload error: {e}"}
    spinner_container.empty()

    failed_layers = []
    fail_messages = []

    for name, result in load_results.items():
        if name == "__error__":
            msg = result.get("message", "Unknown geography error.")
            failed_layers.append("GEOGRAPHY")
            fail_messages.append(msg)
            _record_failure("Geography", msg)
            continue

        if result is not None and not result.get("success", True):
            step_name = f"Geography: {name.upper()}"
            msg = result.get("message", f"{step_name} failed.")
            failed_layers.append(name.upper())
            fail_messages.append(msg)
            _record_failure(step_name, msg)

    if failed_layers:
        st.error(
            "LOAD GEOGRAPHIES: FAILURE ❌\n"
            f"Failed layers: {', '.join(failed_layers)}\n"
            f"Messages: {', '.join(fail_messages)}"
        )
    else:
        st.success("LOAD GEOGRAPHIES: SUCCESS ✅")


    # # -------------------------------------------------------------------------
    # # STEP 5: LOAD TRAFFIC IMPACT CARD
    # # -------------------------------------------------------------------------
    # if st.session_state.get("traffic_impact_answer") == "Yes":
    #     # Use the SAME spinner placeholder defined at the top so it updates in-place
    #     with spinner_container, st.spinner("Loading Traffic Impact Events to APEX..."):
    #         failures = []  # Track all failures in this step

    #         # LOAD TRAFFIC IMPACT EVENT AND GET GLOBALID
    #         try:
    #             payload_traffic_impact = traffic_impact_payload()
    #             traffic_impact_layer = st.session_state["traffic_impacts_layer"]

    #             load_traffic_impact = (
    #                 AGOLDataLoader(
    #                     url=st.session_state["traffic_impact_url"],
    #                     layer=traffic_impact_layer
    #                 ).add_features(payload_traffic_impact)
    #                 if payload_traffic_impact
    #                 else {"success": False, "message": "Failed to Load Traffic Impact to APEX DB"}
    #             )

    #             if not load_traffic_impact.get("success"):
    #                 msg = f"Traffic Impact Event: {load_traffic_impact.get('message', 'Unknown failure.')}"
    #                 failures.append(msg)
    #                 _record_failure("Traffic Impact Event", msg)
    #             else:
    #                 st.session_state["traffic_impact_globalid"] = format_guid(load_traffic_impact["globalids"])

    #         except Exception as e:
    #             msg = f"Traffic Impact payload error: {e}"
    #             failures.append(msg)
    #             _record_failure("Traffic Impact Event", msg)

    #         # Only continue if GlobalID exists
    #         if st.session_state.get("traffic_impact_globalid"):

    #             # -------------------------------------------------------------
    #             # ADD ROUTE
    #             # -------------------------------------------------------------
    #             try:
    #                 payload_route_traffic_impact = traffic_impact_route_payload()
    #                 traffic_impact_route_layer = st.session_state["traffic_impact_routes_layer"]

    #                 route_result = (
    #                     AGOLDataLoader(
    #                         url=st.session_state["traffic_impact_url"],
    #                         layer=traffic_impact_route_layer
    #                     ).add_features(payload_route_traffic_impact)
    #                     if payload_route_traffic_impact
    #                     else {"success": False, "message": "Failed to Load Traffic Impact Route to APEX DB"}
    #                 )

    #                 if not route_result.get("success"):
    #                     msg = f"Traffic Impact Route: {route_result.get('message', 'Unknown failure.')}"
    #                     failures.append(msg)
    #                     _record_failure("Traffic Impact Route", msg)

    #             except Exception as e:
    #                 msg = f"Traffic Impact Route payload error: {e}"
    #                 failures.append(msg)
    #                 _record_failure("Traffic Impact Route", msg)

    #             # -------------------------------------------------------------
    #             # ADD START POINT
    #             # -------------------------------------------------------------
    #             try:
    #                 payload_start_point_traffic_impact = traffic_impact_start_point_payload()
    #                 traffic_impact_start_point_layer = st.session_state["traffic_impact_start_points_layer"]

    #                 start_result = (
    #                     AGOLDataLoader(
    #                         url=st.session_state["traffic_impact_url"],
    #                         layer=traffic_impact_start_point_layer
    #                     ).add_features(payload_start_point_traffic_impact)
    #                     if payload_start_point_traffic_impact
    #                     else {"success": False, "message": "Failed to Load Traffic Impact Start Point to APEX DB"}
    #                 )

    #                 if not start_result.get("success"):
    #                     msg = f"Traffic Impact Start Point: {start_result.get('message', 'Unknown failure.')}"
    #                     failures.append(msg)
    #                     _record_failure("Traffic Impact Start Point", msg)

    #             except Exception as e:
    #                 msg = f"Traffic Impact Start Point payload error: {e}"
    #                 failures.append(msg)
    #                 _record_failure("Traffic Impact Start Point", msg)

    #             # -------------------------------------------------------------
    #             # ADD END POINT
    #             # -------------------------------------------------------------
    #             try:
    #                 payload_end_point_traffic_impact = traffic_impact_end_point_payload()
    #                 traffic_impact_end_point_layer = st.session_state["traffic_impact_end_points_layer"]

    #                 end_result = (
    #                     AGOLDataLoader(
    #                         url=st.session_state["traffic_impact_url"],
    #                         layer=traffic_impact_end_point_layer
    #                     ).add_features(payload_end_point_traffic_impact)
    #                     if payload_end_point_traffic_impact
    #                     else {"success": False, "message": "Failed to Load Traffic Impact End Point to APEX DB"}
    #                 )

    #                 if not end_result.get("success"):
    #                     msg = f"Traffic Impact End Point: {end_result.get('message', 'Unknown failure.')}"
    #                     failures.append(msg)
    #                     _record_failure("Traffic Impact End Point", msg)

    #             except Exception as e:
    #                 msg = f"Traffic Impact End Point payload error: {e}"
    #                 failures.append(msg)
    #                 _record_failure("Traffic Impact End Point", msg)

    #     # Render results OUTSIDE the spinner/container so clearing doesn't remove them
    #     if not failures:
    #         st.success("LOAD TRAFFIC IMPACT EVENTS: SUCCESS ✅")
    #     else:
    #         st.error("LOAD TRAFFIC IMPACT EVENTS: FAILURE ❌")
    #         for msg in failures:
    #             st.error(f"• {msg}")

    #     # Clear ONLY the spinner placeholder now; messages remain visible
    #     spinner_container.empty()


            
    # # -------------------------------------------------------------------------
    # # STEP 6 (SILENT): IMPACT AREA APEX UPDATE
    # # -------------------------------------------------------------------------
    try:
        payload_location = location_payload()
        location_layer = st.session_state.get("locations_layer")  # adjust if needed

        if payload_location is None:
            load_location = None
        else:
            loader = AGOLDataLoader(url=st.session_state['apex_url'], layer=location_layer)
            load_location = loader.add_features(payload_location)

        # Validate loader response shapes (dict or truthy/falsey)
        if load_location is not None:
            if isinstance(load_location, dict):
                if not load_location.get("success", False):
                    _record_failure(
                        "Locations",
                        load_location.get("message", "Unknown error")
                    )
            else:
                # Non-dict responses should be truthy to indicate success
                if not bool(load_location):
                    _record_failure("Locations", "Unknown loader response")

    except Exception as e:
        _record_failure("Location Apex", f"Location payload error: {e}")
        load_location = {"success": False, "message": f"Location payload error: {e}"}

    # (OPTIONAL) record this step in diagnostics
    st.session_state["step6_uploads"] = {
        "location": load_location if "load_location" in locals() else None,
    }



    # -------------------------------------------------------------------------
    # FINALIZATION: CLEANUP ON FAILURE OR MARK COMPLETE
    # -------------------------------------------------------------------------
    if st.session_state.get("step_failures"):
        st.session_state["upload_complete"] = False

        st.error("UPLOAD FAILED ❌ One or more steps failed.")

        # Show detailed failure list
        with st.expander("Failure details", expanded=True):
            for failure in st.session_state["step_failures"]:
                if isinstance(failure, dict):
                    step = failure.get("step", "Unknown step")
                    msg = failure.get("message", "No message provided")
                else:
                    step = "Unknown step"
                    msg = str(failure)
                st.markdown(f"- **{step}**: {msg}")

        # ---------------------------------------------------------
        # Perform cleanup only if project was successfully created
        # ---------------------------------------------------------
        if st.session_state.get("apex_globalid"):
            try:
                cleaned = delete_cascade_by_globalid(
                    url=st.session_state['apex_url'],
                    main_layer=st.session_state['projects_layer'],
                    related_layers=[
                        st.session_state["sites_layer"],
                        st.session_state["routes_layer"],
                        st.session_state["boundaries_layer"],
                        st.session_state["impact_area"],
                        st.session_state["bop_eop_layer"],
                        st.session_state["impact_comms_layer"],
                        st.session_state["region_layer"],
                        st.session_state["bor_layer"],
                        st.session_state["senate_layer"],
                        st.session_state["house_layer"]
                    ],
                    globalid_field='GlobalID',
                    globalid_value=st.session_state['apex_globalid'],
                    parent_field='parentglobalid',
                )


                if cleaned:
                    st.warning(
                        "Partial uploads were cleaned up (placeholder). "
                        "Please address the errors and try again."
                    )
                else:
                    st.warning(
                        "Cleanup attempted but did not complete (placeholder). "
                        "Check logs or try again."
                    )

            except Exception as e:
                st.error(f"Cleanup (placeholder) encountered an error: {e}")

        else:
            st.info(
                "The project record was never created, so no cleanup was required. "
                "Please correct the above issue(s) and try again."
            )

    else:
        st.session_state["upload_complete"] = True
        st.write("")
        st.markdown(
            """
            <h3 style="font-size:20px; font-weight:600;">
                ✅ Upload Finished! Refresh the page to
                <span style="font-weight:700;">add a new project</span>.
            </h3>
            """,
            unsafe_allow_html=True,
        )

    

    
