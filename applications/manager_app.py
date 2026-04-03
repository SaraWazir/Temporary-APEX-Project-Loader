def run_manager_app():
    import streamlit as st
    # Removed: global Folium map creation here (see note below)
    from util.map_util import add_small_geocoder  # kept import in case you use later
    from agol.agol_util import select_record, get_multiple_fields
    from tabs.traffic_impacts import manage_traffic_impacts
    from tabs.communities import manage_impacted_communities
    from tabs.information import manage_information

    # ─────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────
    def get_object_id_from_record(record):
        """Extract objectid from a select_record() response (list of features)."""
        if not record or not isinstance(record, list):
            return None
        feature = record[0]
        if "attributes" not in feature:
            return None
        return feature["attributes"].get("objectid")

    def update_project_record():
        """Fetch and store project record/objectid whenever GUID is set/changed."""
        guid = st.session_state.get("guid")
        url = st.session_state.get("apex_url")
        layer = st.session_state.get("projects_layer")

        if not guid or not url or layer is None:
            st.session_state["project_record"] = None
            st.session_state["objectid"] = None
            return

        try:
            rec = select_record(
                url,
                layer,
                "globalid",
                guid,
                fields="*",
                return_geometry=True
            )
            st.session_state["project_record"] = rec
            st.session_state["objectid"] = get_object_id_from_record(rec)
        except Exception as e:
            st.error(f"Project lookup failed for GUID {guid}: {e}")
            st.session_state["project_record"] = None
            st.session_state["objectid"] = None

    def normalize_qp_value(v):
        """Handle st.query_params values that might be str or list[str]."""
        if v is None:
            return None
        if isinstance(v, (list, tuple)):
            return v[0] if v else None
        return v

    # ⬇️ Normalize any existing GUID in session_state to lowercase
    def normalize_guid_in_state():
        g = st.session_state.get("guid")
        if isinstance(g, str):
            st.session_state["guid"] = g.lower()

    def _reset_per_project_state():
        """
        Clear state tied to the currently selected project.
        Keep this minimal and explicit to avoid nuking unrelated app state.
        """
        # Core linkage
        st.session_state["guid"] = None
        st.session_state["project_record"] = None
        st.session_state["objectid"] = None
        st.session_state["_last_guid"] = None

        # APEX context / per-project cache
        st.session_state.pop("apex_guid", None)
        st.session_state.pop("apex_awp_name", None)
        st.session_state.pop("apex_proj_name", None)
        st.session_state.pop("apex_database_status", None)
        st.session_state.pop("apex_awp_id", None)
        st.session_state.pop("apex_object_id", None)
        st.session_state.pop("apex_proj_type", None)
        st.session_state.pop("apex_proj_area", None)
        st.session_state.pop("apex_ready", None)
        st.session_state.pop("apex_error", None)

        # Geometry related aggregates
        st.session_state.pop("apex_geom", None)
        st.session_state.pop("geom_ready", None)
        st.session_state.pop("geom_error", None)

        # Reset project selector widget so placeholder shows again
        st.session_state.pop("project_selector", None)

    def _remove_guid_from_url():
        """Remove 'guid' from current URL query params, preserving any others."""
        params = {}
        try:
            params = dict(st.query_params)
            if "guid" in params:
                params.pop("guid", None)
            st.query_params.clear()
            for k, v in params.items():
                st.query_params[k] = v
        except Exception:
            try:
                st.experimental_set_query_params(**params)
            except Exception:
                pass

    def change_project():
        """Clear project selection + dependent state and rerun to show dropdown."""
        _reset_per_project_state()
        _remove_guid_from_url()
        st.rerun()

    def _set_apex_context_from_record(rec_list):
        """
        Parse the APEX record list and update session state:
        - apex_guid, apex_awp_id, apex_object_id, apex_proj_type, apex_proj_area
        """
        if not rec_list or not isinstance(rec_list, list):
            raise ValueError("Empty APEX response")

        feature = rec_list[0]
        attrs = feature.get("attributes", {})
        st.session_state["apex_guid"] = attrs.get("globalid")
        st.session_state['apex_awp_name'] = attrs.get('AWP_Proj_Name')
        st.session_state['apex_proj_name'] = attrs.get('Proj_Name')
        st.session_state['apex_database_status'] = attrs.get("Database_Status")
        st.session_state["apex_awp_id"] = attrs.get("AWP_Contract_ID")
        st.session_state["apex_object_id"] = attrs.get("objectid")
        st.session_state["apex_proj_type"] = attrs.get("Proj_Type")

        geom = feature.get("geometry", {}) or {}
        st.session_state["apex_proj_area"] = geom.get("rings")

    def _set_geom_context_from_records(rec_list, proj_type):
        """
        Aggregate related geometry features; preserve Esri [x, y] == [lon, lat].
        """
        if not rec_list or not isinstance(rec_list, list):
            st.session_state["apex_geom"] = {"type": "", "globalids": [], "objectids": [], "geoms": []}
            return

        globalids, objectids, geoms = [], [], []
        for feature in rec_list:
            if not isinstance(feature, dict):
                continue
            attrs = feature.get("attributes", {}) or {}
            globalids.append(attrs.get("globalid"))
            objectids.append(attrs.get("objectid"))
            g = feature.get("geometry", {}) or {}

            if proj_type == "Site":
                if "x" in g and "y" in g:
                    geoms.append([g["x"], g["y"]])
                if isinstance(g.get("points"), list):
                    geoms.extend(g.get("points") or [])
                if isinstance(g.get("rings"), list):
                    geoms.extend(g.get("rings") or [])
                if isinstance(g.get("paths"), list):
                    geoms.extend(g.get("paths") or [])
            elif proj_type == "Route":
                if isinstance(g.get("paths"), list):
                    geoms.extend(g.get("paths") or [])
            elif proj_type == "Boundary":
                if isinstance(g.get("rings"), list):
                    geoms.extend(g.get("rings") or [])
            else:
                if isinstance(g.get("paths"), list):
                    geoms.extend(g.get("paths") or [])
                if isinstance(g.get("rings"), list):
                    geoms.extend(g.get("rings") or [])
                if isinstance(g.get("points"), list):
                    geoms.extend(g.get("points") or [])
                if "x" in g and "y" in g:
                    geoms.append([g["x"], g["y"]])

        st.session_state["apex_geom"] = {
            "type": proj_type,
            "globalids": globalids,
            "objectids": objectids,
            "geoms": geoms,
        }

    def fetch_apex_context():
        """Fetch minimal APEX fields + related geometry for the current GUID."""
        st.session_state["apex_ready"] = False
        st.session_state["apex_error"] = None
        st.session_state["geom_ready"] = False
        st.session_state["geom_error"] = None

        guid = st.session_state.get("guid")
        if not guid:
            return

        url = st.session_state.get("apex_url")
        layer = st.session_state.get("projects_layer")
        if not url or layer is None:
            st.session_state["apex_error"] = "Missing APEX URL or layer for record fetch."
            return

        try:
            apex_rec = select_record(
                url, layer, "globalid", guid,
                fields=[
                    "globalid",
                    "objectid",
                    "AWP_Contract_ID",
                    "Proj_Type",
                    "AWP_Proj_Name",
                    "Proj_Name",
                    "Database_Status"
                ],
                return_geometry=True
            )
            _set_apex_context_from_record(apex_rec)
            st.session_state["apex_ready"] = True
        except Exception as e:
            st.session_state["apex_error"] = f"APEX record fetch failed: {e}"
            st.session_state["apex_guid"] = None
            st.session_state["apex_awp_name"] = None
            st.session_state["apex_proj_name"] = None
            st.session_state['apex_database_status'] = None
            st.session_state["apex_awp_id"] = None
            st.session_state["apex_object_id"] = None
            st.session_state["apex_proj_type"] = None
            st.session_state["apex_proj_area"] = None
            st.session_state["apex_ready"] = False
            return

        try:
            if st.session_state.get("apex_guid") and st.session_state.get("apex_proj_type"):
                proj_type = st.session_state["apex_proj_type"]
                if proj_type == "Site":
                    geom_layer = st.session_state.get("sites_layer")
                elif proj_type == "Route":
                    geom_layer = st.session_state.get("routes_layer")
                elif proj_type == "Boundary":
                    geom_layer = st.session_state.get("boundaries_layer")
                else:
                    geom_layer = None

                if geom_layer is None:
                    raise ValueError(f"Missing related layer in session_state for proj_type '{proj_type}'")

                geom_rec = select_record(
                    url, geom_layer, "parentglobalid", guid,
                    fields=["globalid", "objectid"],
                    return_geometry=True
                )
                _set_geom_context_from_records(geom_rec, proj_type)
                st.session_state["geom_ready"] = True
        except Exception as e:
            st.session_state["geom_error"] = f"APEX Geom record fetch failed: {e}"
            st.session_state["apex_geom"] = {"type": '', "globalids": [], "objectids": [], "geoms": []}
            st.session_state["geom_ready"] = False

    # ─────────────────────────────────────────────────────────────
    # Page config
    # ─────────────────────────────────────────────────────────────
    st.set_page_config(
        page_title="APEX Manager Application",
        page_icon="🛠️",
        layout="centered",
        initial_sidebar_state="collapsed"
    )

    # (Optional) initialize debug counter once; don't reset on every rerun
    st.session_state.setdefault('debug', 0)

    # ⬇️ Normalize any pre-existing GUID in session state
    normalize_guid_in_state()

    # ─────────────────────────────────────────────────────────────
    # Sync GUID from URL (if present) into session_state and refresh record
    # ─────────────────────────────────────────────────────────────
    guid_param = None
    try:
        qp = st.query_params
        if qp and "guid" in qp:
            guid_param = normalize_qp_value(qp.get("guid"))
            if isinstance(guid_param, str):
                guid_param = guid_param.lower()  # ✅ normalize before compare
    except Exception:
        guid_param = None

    if guid_param and guid_param != st.session_state.get("guid"):
        st.session_state["guid"] = guid_param  # already lowercased above
        update_project_record()
        _remove_guid_from_url()  # ✅ consume the param to prevent loop
        st.rerun()

    # ─────────────────────────────────────────────────────────────
    # Determine whether to show the dropdown
    # ─────────────────────────────────────────────────────────────
    show_list = True
    if st.session_state.get("guid"):
        show_list = False

    # ─────────────────────────────────────────────────────────────
    # Header
    # ─────────────────────────────────────────────────────────────
    st.title("MANAGE APEX PROJECTS 🛠️")
    st.markdown("##### MANAGE AND UPDATE AN EXISTING APEX PROJECT")
    st.write('')
    st.write('')

    # ─────────────────────────────────────────────────────────────
    # Load project list (only needed if we'll show the dropdown)
    # ─────────────────────────────────────────────────────────────
    label_to_gid = {}
    labels_with_placeholder = []
    placeholder_label = "— Select a project —"

    projects_url = st.session_state.get("apex_url")
    projects_layer = st.session_state.get('projects_layer')

    if show_list:
        if not projects_url or projects_layer is None:
            st.error("Missing `apex_url` and/or `projects_layer` in session state. Initialize app session before opening Manager.")
            return
        try:
            projects = get_multiple_fields(projects_url, projects_layer, ["Proj_Name", "globalid"])
        except Exception as e:
            st.error(f"Failed to load project list: {e}")
            projects = []

        label_to_gid = {
            p.get("Proj_Name"): p.get("globalid")
            for p in projects
            if p.get("Proj_Name") and p.get("globalid")
        }
        labels = sorted(label_to_gid.keys())
        labels_with_placeholder = [placeholder_label] + labels

    # ─────────────────────────────────────────────────────────────
    # Project selection UI / Current project display
    # ─────────────────────────────────────────────────────────────
    def on_select_project():
        label = st.session_state.get("project_selector")
        if label and label != placeholder_label:
            gid = label_to_gid.get(label)
            st.session_state["guid"] = str(gid).lower() if gid is not None else None  # ensure lowercase
            update_project_record()
        else:
            st.session_state["guid"] = None
            st.session_state["project_record"] = None
            st.session_state["objectid"] = None

    if show_list:
        st.markdown("<h5>SELECT AN APEX PROJECT</h5>", unsafe_allow_html=True)
        st.selectbox(
            "Select a project",
            labels_with_placeholder,
            index=0,
            key="project_selector",
            on_change=on_select_project
        )
        st.info("Select an APEX project to view and edit project information.")
        # Early return: nothing else to show until a project is chosen
        st.stop()
    else:
        # Resolve and show the project name
        current_label = None
        if projects_url and projects_layer is not None:
            try:
                if not label_to_gid:
                    projects = get_multiple_fields(projects_url, projects_layer, ["Proj_Name", "globalid"])
                    label_to_gid = {
                        p.get("Proj_Name"): p.get("globalid")
                        for p in projects
                        if p.get("Proj_Name") and p.get("globalid")
                    }
                guid = st.session_state.get("guid")
                if guid:
                    current_label = next(
                        (label for label, gid in label_to_gid.items() if gid == guid or str(gid).lower() == guid),
                        None
                    )
            except Exception:
                current_label = None

        if current_label:
            # Inner columns: title grows, button stays compact
            col_title, col_btn = st.columns([7, 1], vertical_alignment="center")
            with col_title:
                # ⬅️ UPDATED: force uppercase in the displayed project title
                st.markdown(f"<h3 style='margin:0'>{current_label.upper()}</h3>", unsafe_allow_html=True)  # ⬅️ UPDATED
            with col_btn:
                # ⬅️ UPDATED: make the change-project button primary
                if st.button("↺", key="btn_change_project", help="Change Project", type="primary"):  # ⬅️ UPDATED
                    change_project()
        else:
            st.warning("Selected GUID not found in project list.")
            if st.button("↺ Change Project", key="btn_change_project_nf", use_container_width=False):
                change_project()

    # ─────────────────────────────────────────────────────────────
    # Re-fetch if GUID changed elsewhere in the app
    # Also (re)load APEX context used by the segmented tabs
    # ─────────────────────────────────────────────────────────────
    if st.session_state.get("guid") != st.session_state.get("_last_guid"):
        st.session_state["_last_guid"] = st.session_state.get("guid")
        update_project_record()
        fetch_apex_context()

    # ─────────────────────────────────────────────────────────────
    # Segmented control (tabs) – render ONLY the selected tab content and stop
    # ─────────────────────────────────────────────────────────────
    if st.session_state.get("guid"):
        if st.session_state.get("apex_error"):
            st.error(st.session_state["apex_error"])
            st.stop()
        elif st.session_state.get("apex_ready"):
            tabs_key = f"manager_tabs_{st.session_state.get('guid')}"
            st.write('')
            st.markdown("<h5>CHOOSE A CATEGORY TO MANAGE</h5>", unsafe_allow_html=True)

            # Available tabs (labels) – unchanged
            options = ["INFORMATION", "FOOTPRINT", "TRAFFIC IMPACTS", "COMMUNITIES", "DEPLOYMENT"]

            # ✅ NEW: Preselect from session state's `manager_tab` (if valid).
            # This runs BEFORE rendering the segmented control and only updates
            # the widget value when `manager_tab` changes, so we don't override
            # the user's manual selection on later reruns.
            mt_raw = st.session_state.get("manager_tab")
            if isinstance(mt_raw, str):
                mt = mt_raw.strip().upper()
                if mt in options:
                    if st.session_state.get("_last_manager_tab") != mt:
                        st.session_state["_last_manager_tab"] = mt
                        st.session_state[tabs_key] = mt

            # Keep the same "methodology": on_change only bumps a counter (causes rerun)
            def _on_manager_tab_change():
                st.session_state["manager_tab_change_counter"] = st.session_state.get("manager_tab_change_counter", 0) + 1

            choice = st.segmented_control(
                "Select a Category",
                options=options,
                key=tabs_key,
                width='stretch',
                on_change=_on_manager_tab_change
            )

            # Define tab callables. Only the chosen one will run.
            def _tab_information():
                with st.container(border=True):
                    manage_information()

            def _tab_footprint():
                st.info("Footprint Management Tab Under Development")

            def _tab_traffic_impacts():
                with st.container(border=True):
                    manage_traffic_impacts()

            def _tab_communities():
                with st.container(border=True):
                    manage_impacted_communities()

            def _tab_deployment():
                st.info("Deployment Management Tab Under Development")

            TAB_DISPATCH = {
                "INFORMATION": _tab_information,
                "FOOTPRINT": _tab_footprint,
                "TRAFFIC IMPACTS": _tab_traffic_impacts,
                "COMMUNITIES": _tab_communities,
                "DEPLOYMENT": _tab_deployment,
            }

            # Execute ONLY the chosen tab's function, then STOP the script.
            func = TAB_DISPATCH.get(choice)
            if func is not None:
                func()
                st.stop()
            else:
                # ⬇️ Updated language per request
                st.info("Please choose a category to access the project management options.")
                st.stop()