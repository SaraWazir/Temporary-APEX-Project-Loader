# =============================================================================
# INFORMATION MANAGEMENT TAB
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


def _resolve_is_awp(project_attrs: dict) -> bool:
    """
    Match details_form logic: prefer the active source selection from session,
    otherwise fall back to the presence of AWP_Contract_ID on the record.
    """
    details_type = st.session_state.get("details_type") or st.session_state.get("info_option")
    if details_type in ("AASHTOWare Database", "User Input"):
        return details_type == "AASHTOWare Database"
    return bool(project_attrs.get("AWP_Contract_ID"))


# -----------------------------------------------------------------------------
# NEW: default seeding helpers (used ONLY to prefill values in User Input mode)
# -----------------------------------------------------------------------------
def _coerce_to_option(value, options):
    """Return an option entry that equals `value` by direct or string match."""
    if value is None or not options:
        return value
    if value in options:
        return value
    str_val = str(value)
    for opt in options:
        if str(opt) == str_val:
            return opt
    return value


def _seed_default(key: str, project: dict, project_field: str, fmt=None):
    """
    If `key` not set (or blank) in session_state, seed it from project[project_field].
    Optionally run through a formatter that can handle None.
    """
    if key not in st.session_state or st.session_state.get(key) in (None, ""):
        raw = project.get(project_field)
        st.session_state[key] = fmt(raw) if fmt else raw


def _seed_select_default(key: str, project: dict, project_field: str, options_key: str):
    """
    Seed a selectbox's backing session_state value from the project attribute
    and coerce it to an entry found in the select `options`.
    """
    if key not in st.session_state or st.session_state.get(key) in (None, ""):
        options = st.session_state.get(options_key, [])
        raw = project.get(project_field)
        st.session_state[key] = _coerce_to_option(raw, options)


# -----------------------------------------------------------------------------
# Build package for Update
# -----------------------------------------------------------------------------
def _build_information_package() -> dict:
    """
    Build a package of the current values from the
    PROJECT INFORMATION step.
    """
    return {
        # 1. Project Name
        "proj_name": st.session_state.get("proj_name"),
        # 2. Construction Year, Phase, & IDs
        "construction_year": st.session_state.get("construction_year"),
        "phase": st.session_state.get("phase"),
        "iris": st.session_state.get("iris"),
        "stip": st.session_state.get("stip"),
        "fed_proj_num": st.session_state.get("fed_proj_num"),
        # 3. Funding Type & Practice
        "fund_type": st.session_state.get("fund_type"),
        "proj_prac": st.session_state.get("proj_prac"),
        # 4. Start & End Date
        "anticipated_start": st.session_state.get("anticipated_start"),
        "anticipated_end": st.session_state.get("anticipated_end"),
        # 5. Award Information
        "award_date": st.session_state.get("award_date"),
        "award_fiscal_year": st.session_state.get("award_fiscal_year"),
        "contractor": st.session_state.get("contractor"),
        "awarded_amount": st.session_state.get("awarded_amount"),
        "current_contract_amount": st.session_state.get("current_contract_amount"),
        "amount_paid_to_date": st.session_state.get("amount_paid_to_date"),
        "tenadd": st.session_state.get("tenadd"),
        # 6. Description
        "proj_desc": st.session_state.get("proj_desc"),
        # 7. Contact
        "contact_name": st.session_state.get("contact_name"),
        "contact_email": st.session_state.get("contact_email"),
        "contact_phone": st.session_state.get("contact_phone"),
        # 8. Web Link
        "proj_web": st.session_state.get("proj_web"),
    }


# -----------------------------------------------------------------------------
# AWP connect/change helpers
# -----------------------------------------------------------------------------
def _show_awp_selector():
    """
    Flip session flags so the source summary is hidden and the AWP selector shows.
    The actual dropdown is rendered in manage_information().
    """
    st.session_state["info_show_awp_selector"] = True
    # Reset last loaded tracker for this view so we can detect a fresh selection
    st.session_state["info_last_awp_loaded"] = None


def _seed_awp_default_from_project(project: dict):
    """
    Seed the default selection of the AWP dropdown from the current project
    when available. We use the project's AWP_Contract_ID as the dropdown's default.
    """
    awp_contract_id = project.get("AWP_Contract_ID")
    if awp_contract_id:
        # These keys are honored by util.streamlit_util.aashtoware_project()
        # to seed the dropdown selection.
        st.session_state["awp_id"] = awp_contract_id
        st.session_state["awp_guid"] = awp_contract_id
        st.session_state["aashto_id"] = awp_contract_id


def _apply_awp_attrs_to_state(attrs: dict):
    """
    Mirror the same mapping logic used in util.streamlit_util.aashtoware_project()
    so the AWP-backed form fields fill correctly. This writes both raw awp_* keys
    and friendly keys expected by the AWP_FIELDS mapping.
    """
    # Raw attributes -> awp_* keys
    for k, v in attrs.items():
        st.session_state[f"awp_{k}".lower()] = v

    # Friendly mirrors used by the AWP form (kept in sync with streamlit_util)
    _awp_to_friendly = {
        "ProjectName": "awp_proj_name",
        "Description": "awp_proj_desc",
        "Phase": "awp_phase",
        "FundingType": "awp_fund_type",
        "ProjectPractice": "awp_proj_prac",
        "IRIS": "awp_iris",
        "STIP": "awp_stip",
        "FederalProjectNumber": "awp_fed_proj_num",
        "AnticipatedStart": "awp_anticipated_start",
        "AnticipatedEnd": "awp_anticipated_end",
        "AwardDate": "awp_award_date",
        "AwardFiscalYear": "awp_award_fiscal_year",
        "TentativeAdvertiseDate": "awp_tenadd",
        "AwardedAmount": "awp_awarded_amount",
        "CurrentContractAmount": "awp_current_contract_amount",
        "AmountPaidToDate": "awp_amount_paid_to_date",
        "ContactName": "awp_contact_name",
        "ContactRole": "awp_contact_role",
        "ContactEmail": "awp_contact_email",
        "ContactPhone": "awp_contact_phone",
        "ProjectWebsite": "awp_proj_web",
        "RouteId": "awp_route_id",
        "RouteName": "awp_route_name",
    }
    for awp_attr, friendly_key in _awp_to_friendly.items():
        if awp_attr in attrs:
            st.session_state[friendly_key] = attrs[awp_attr]


def _load_awp_by_contract_id_and_switch():
    """
    When a selection is made in the AWP dropdown, load the record from the
    AASHTOWare connection table (by CONTRACT_Id) and switch the form below to
    AASHTOWare mode so fields are populated via AWP_FIELDS.
    """
    selected_id = (
        st.session_state.get("apex_awp_id")
        or st.session_state.get("awp_guid")
        or st.session_state.get("aashto_id")
        or None
    )
    if not selected_id:
        return

    # Avoid duplicate loads within the same selection
    if st.session_state.get("info_last_awp_loaded") == selected_id:
        return

    awp_url = st.session_state.get("aashtoware_url")
    awp_layer = st.session_state.get("awp_contracts_layer")
    if awp_url is None or awp_layer is None:
        # If not configured, we can't proceed.
        st.warning("AASHTOWare source is not configured (missing aashtoware_url or awp_contracts_layer).")
        return

    # Per your instruction: query by CONTRACT_Id and use the selected Id as the value.
    recs = select_record(
        url=st.session_state["aashtoware_url"],
        layer=st.session_state["awp_contracts_layer"],
        id_field="Id",
        id_value=selected_id,
        return_geometry=False
    )
    if recs and "attributes" in recs[0]:
        attrs = recs[0]["attributes"]
        _apply_awp_attrs_to_state(attrs)

        # Flip the form below into AWP mode; this mirrors details_form behavior
        st.session_state["info_option"] = "AASHTOWare Database"
        st.session_state["details_type"] = "AASHTOWare Database"
        st.session_state["is_awp"] = True

        # Mark what we just loaded so we don't re-query unnecessarily
        st.session_state["info_last_awp_loaded"] = selected_id


# -----------------------------------------------------------------------------
# Placeholder action handlers wired to buttons
# (now updated to show the AWP picker and seed defaults)
# -----------------------------------------------------------------------------
def _on_update_aashtoware_information():
    """Placeholder action for 'UPDATE AASHTOWARE INFORMATION' button."""
    package = _build_information_package()
    # Include OBJECTID for updates when available
    if "apex_object_id" in st.session_state:
        package["objectid"] = st.session_state.apex_object_id
    # Build the AGOL applyEdits payload (updates)
    payload = manage_information_payload(package, 'updates')

    # --- Progress placeholder is stored by the UI section right under the buttons ---
    progress_ph = st.session_state.get("info_progress_placeholder")

    # === actually deploy to AGOL with in-place progress updates ===
    result = deploy_to_agol_information(payload, "updates", progress_placeholder=progress_ph)

    # Clear the progress bar after completion (success or failure)
    try:
        if progress_ph is not None:
            progress_ph.empty()
    except Exception:
        # If Streamlit already cleared/invalidated the placeholder on rerun, ignore
        pass


def _on_change_aashtoware_connection():
    """Action for 'CHANGE AASHTOWARE CONNECTION' button."""
    project = _get_project_record() or {}
    _show_awp_selector()
    _seed_awp_default_from_project(project)


def _on_connect_to_aashtoware_project():
    """Action for 'CONNECT TO AASHTOWARE PROJECT' button."""
    project = _get_project_record() or {}
    _show_awp_selector()
    _seed_awp_default_from_project(project)


def _on_update_information():
    """
    Action for 'UPDATE INFORMATION' button.
    Shows progress during AGOL deployment and clears it on completion.
    """
    package = _build_information_package()
    # Include OBJECTID for updates when available
    if "apex_object_id" in st.session_state:
        package["objectid"] = st.session_state.apex_object_id
    # Build the AGOL applyEdits payload (updates)
    payload = manage_information_payload(package, 'updates')

    # --- Progress placeholder is stored by the UI section right under the buttons ---
    progress_ph = st.session_state.get("info_progress_placeholder")

    # === actually deploy to AGOL with in-place progress updates ===
    result = deploy_to_agol_information(payload, "updates", progress_placeholder=progress_ph)

    # Clear the progress bar after completion (success or failure)
    try:
        if progress_ph is not None:
            progress_ph.empty()
    except Exception:
        # If Streamlit already cleared/invalidated the placeholder on rerun, ignore
        pass


def deploy_to_agol_information(
    payload: Dict[str, Any],
    edit_type: str,
    *,
    progress_placeholder: Optional[st.delta_generator.DeltaGenerator] = None,
) -> Dict[str, Any]:
    """
    Submit the Project Information applyEdits payload to AGOL.
    - Uses st.session_state['apex_url'] and st.session_state['projects_layer'].
    - Supports ONLY 'adds' and 'updates'. 'deletes' is explicitly rejected.
    - Normalizes OBJECTID key casing for updates if needed.
    """
    base_url = st.session_state.get("apex_url")
    layer_idx = st.session_state.get("projects_layer")
    if base_url is None or layer_idx is None:
        st.error("AGOL Projects layer is not configured (missing apex_url or projects_layer).")
        return {"success": False, "message": "Layer not configured"}

    if edit_type not in ("adds", "updates"):
        st.warning("manage_information does not support deletes. Skipping request.")
        return {"success": False, "message": f"Unsupported edit_type '{edit_type}'"}

    loader = AGOLDataLoader(base_url, layer_idx)

    def _progress(frac: float, text: str):
        if progress_placeholder is not None:
            progress_placeholder.progress(frac, text=text)
        else:
            st.progress(frac, text=text)

    # Show initial state
    _progress(0.0, f"Submitting {edit_type} to AGOL…")

    try:
        if edit_type == "adds":
            # payload should be {"adds":[{ "attributes": {...} }]}
            result = loader.add_features(payload)
        elif edit_type == "updates":
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


# -----------------------------------------------------------------------------
# MAIN ENTRYPOINT
# -----------------------------------------------------------------------------
def manage_information():
    st.markdown("##### MANAGE PROJECT INFORMATION")
    st.caption(
        "View or update project information. "
        "AASHTOWare projects are read-only except for Construction Year. "
        "User-entered projects allow full editing."
    )
    st.write("")

    project = _get_project_record()
    if not project:
        st.warning("No project loaded.")
        return

    # Match details_form mode and key behavior
    version = st.session_state.get("form_version", 0)
    is_awp = _resolve_is_awp(project)

    # ✅ Always seed Construction Year so session_selectbox can resolve default
    _seed_select_default(
        "construction_year",
        project,
        "Construction_Year",
        "construction_years",
    )

    # -------------------------------------------------------------------------
    # NEW: Seed defaults for User Input mode so widgets pick correct values
    # -------------------------------------------------------------------------
    if not is_awp:
        # 1. Project Name
        _seed_default("proj_name", project, "Proj_Name", fmt=fmt_string)
        # 2. Construction Year, Phase, & IDs
        _seed_select_default("construction_year", project, "Construction_Year", "construction_years")
        _seed_select_default("phase", project, "Phase", "phase_list")
        _seed_default("iris", project, "IRIS", fmt=fmt_string)
        _seed_default("stip", project, "STIP", fmt=fmt_string)
        _seed_default("fed_proj_num", project, "Fed_Proj_Num", fmt=fmt_string)
        # 3. Funding Type & Practice
        _seed_select_default("fund_type", project, "Fund_Type", "funding_list")
        _seed_select_default("proj_prac", project, "Proj_Prac", "practice_list")
        # 4. Start & End Date (store date objects or None)
        _seed_default("anticipated_start", project, "Anticipated_Start", fmt=fmt_date_or_none)
        _seed_default("anticipated_end", project, "Anticipated_End", fmt=fmt_date_or_none)
        # 5. Award Information
        _seed_default("award_date", project, "Award_Date", fmt=fmt_date_or_none)
        _seed_select_default("award_fiscal_year", project, "Award_Fiscal_Year", "years")
        _seed_default("contractor", project, "Contractor", fmt=fmt_string)
        # Numerics — keep raw numeric in state; widgets will render it
        if "awarded_amount" not in st.session_state or st.session_state.get("awarded_amount") in (None, ""):
            st.session_state["awarded_amount"] = fmt_int_or_none(project.get("Awarded_Amount"))
        if "current_contract_amount" not in st.session_state or st.session_state.get("current_contract_amount") in (None, ""):
            st.session_state["current_contract_amount"] = fmt_int_or_none(project.get("Current_Contract_Amount"))
        if "amount_paid_to_date" not in st.session_state or st.session_state.get("amount_paid_to_date") in (None, ""):
            st.session_state["amount_paid_to_date"] = fmt_int_or_none(project.get("Amount_Paid_To_Date"))
        _seed_default("tenadd", project, "TenAdd", fmt=fmt_date_or_none)
        # 6. Description
        _seed_default("proj_desc", project, "Proj_Desc", fmt=fmt_string)
        # 7. Contact
        _seed_default("contact_name", project, "Contact_Name", fmt=fmt_string)
        _seed_default("contact_email", project, "Contact_Email", fmt=fmt_string)
        _seed_default("contact_phone", project, "Contact_Phone", fmt=fmt_string)
        # 8. Web Link
        _seed_default("proj_web", project, "Proj_Web", fmt=fmt_string)

    # =========================================================================
    # PROJECT DATA SOURCE (mirrors summary shown elsewhere)
    # =========================================================================
    st.markdown("###### PROJECT DATA SOURCE")
    with st.container(border=True):
        # If the user pressed CONNECT/CHANGE: hide the summary, show the AWP selector
        if st.session_state.get("info_show_awp_selector", False):
            st.markdown("###### SELECT AASHTOWARE PROJECT", unsafe_allow_html=True)
            # Seed default selection if not present yet (e.g., from project->AWP_Contract_ID)
            if not any(st.session_state.get(k) for k in ("awp_id", "awp_guid", "aashto_id")):
                _seed_awp_default_from_project(project)

            # Render the dropdown (this will also populate awp_* keys on selection)
            aashtoware_project()

            # After render, if a selection exists, load via CONTRACT_Id and flip form to AWP view
            _load_awp_by_contract_id_and_switch()
        else:
            if is_awp:
                c1, c2, c3 = st.columns(3)
                with c1:
                    ro_widget(
                        "info_source",
                        "Source",
                        "AASHTOWare",
                    )
                with c2:
                    ro_widget(
                        "id_source",
                        "Contract ID",
                        project.get("AWP_Contract_ID"),
                    )
                with c3:
                    ro_widget(
                        "info_last_updated",
                        "Last Updated",
                        fmt_agol_date(project.get("EditDate")),
                    )
            else:
                c1, c2 = st.columns(2)
                with c1:
                    ro_widget(
                        "info_source",
                        "Source",
                        "User Input",
                    )
                with c2:
                    ro_widget(
                        "info_last_updated",
                        "Last Updated",
                        fmt_agol_date(project.get("EditDate")),
                    )

            # The two source buttons (pressing either flips to the AWP selector view)
            source_buttons = st.container(border=False)
            with source_buttons:
                if is_awp:
                    st.button(
                        "CHANGE AASHTOWARE CONNECTION",
                        use_container_width=True,
                        on_click=_on_change_aashtoware_connection,
                    )
                else:
                    st.button(
                        "CONNECT TO AASHTOWARE PROJECT",
                        use_container_width=True,
                        on_click=_on_connect_to_aashtoware_project,
                    )

    st.write("")

    # =========================================================================
    # PROJECT INFORMATION
    # =========================================================================
    # Re-evaluate AWP mode after potential selection
    is_awp = _resolve_is_awp(project)

    st.markdown("###### PROJECT INFORMATION")
    with st.container(border=True):
        # ---------------------------------------------------------------------
        # 1. PROJECT NAME
        # ---------------------------------------------------------------------
        st.markdown("<h6>1. PROJECT NAME</h6>", unsafe_allow_html=True)
        if is_awp:
            c1, c2 = st.columns(2)
            with c1:
                ro_widget(
                    "awp_proj_name",
                    "AASHTOWare Project Name",
                    fmt_string(project.get("AWP_Proj_Name")),
                )
            with c2:
                ro_widget(
                    "proj_name",
                    "Public Project Name",
                    fmt_string(project.get("Proj_Name")),
                )
        else:
            st.session_state["proj_name"] = st.text_input(
                "Public Project Name ⮜",
                value=st.session_state.get("proj_name", project.get("Proj_Name", "")),
                key=widget_key("proj_name", version, is_awp),
                help="Provide the project name that will be displayed publicly.",
            )

        st.write("")

        # ---------------------------------------------------------------------
        # 2. CONSTRUCTION YEAR, PHASE, & IDS
        # ---------------------------------------------------------------------
        st.markdown("<h6>2. CONSTRUCTION YEAR, PHASE, & IDS</h6>", unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        # --- Construction Year (exact logic from details_form) ---
        with col1:
            if is_awp:
                st.session_state["construction_year"] = session_selectbox(
                    key="construction_year",
                    label="Construction Year",
                    help="The planned construction year for this project.",
                    options=(st.session_state.get("construction_years", [])),
                    is_awp=True,
                )
            else:
                st.session_state["construction_year"] = session_selectbox(
                    key="construction_year",
                    label="Construction Year",
                    help="The planned construction year for this project.",
                    options=(st.session_state.get("construction_years", [])),
                    is_awp=False,
                )

        # Phase
        with col2:
            if is_awp:
                ro_widget("phase", "Phase", fmt_string(project.get("Phase")))
            else:
                st.session_state["phase"] = session_selectbox(
                    key="phase",
                    label="Phase",
                    help="Indicates the construction phase scheduled for this project in the current year.",
                    options=(st.session_state.get("phase_list", [])),
                    is_awp=False,
                )

        col3, col4, col5 = st.columns(3)
        # IRIS
        with col3:
            if is_awp:
                ro_widget("iris", "IRIS", fmt_string(project.get("IRIS")))
            else:
                st.session_state["iris"] = st.text_input(
                    label="IRIS",
                    key=widget_key("awp_iris", version, is_awp),
                    value=st.session_state.get("iris", project.get("IRIS", "")),
                )
        # STIP
        with col4:
            if is_awp:
                ro_widget("stip", "STIP", fmt_string(project.get("STIP")))
            else:
                st.session_state["stip"] = st.text_input(
                    label="STIP",
                    key=widget_key("awp_stip", version, is_awp),
                    value=st.session_state.get("stip", project.get("STIP", "")),
                )
        # Federal Project Number
        with col5:
            if is_awp:
                ro_widget("fed_proj_num", "Federal Project Number", fmt_string(project.get("Fed_Proj_Num")))
            else:
                st.session_state["fed_proj_num"] = st.text_input(
                    label="Federal Project Number",
                    key=widget_key("awp_fed_proj_num", version, is_awp),
                    value=st.session_state.get("fed_proj_num", project.get("Fed_Proj_Num", "")),
                )

        st.write("")
        st.write("")

        # ---------------------------------------------------------------------
        # 3. FUNDING TYPE & PRACTICE
        # ---------------------------------------------------------------------
        st.markdown("<h6>3. FUNDING TYPE & PRACTICE</h6>", unsafe_allow_html=True)
        col13, col14 = st.columns(2)
        if is_awp:
            with col13:
                ro_widget("fund_type", "Funding Type", fmt_string(project.get("Fund_Type")))
            with col14:
                ro_widget("proj_prac", "Project Practice", fmt_string(project.get("Proj_Prac")))
        else:
            with col13:
                st.session_state["fund_type"] = session_selectbox(
                    key="fund_type",
                    label="Funding Type",
                    help="",
                    options=(st.session_state.get("funding_list", [])),
                    is_awp=False,
                )
            with col14:
                st.session_state["proj_prac"] = session_selectbox(
                    key="proj_prac",
                    label="Project Practice",
                    help="",
                    options=st.session_state.get("practice_list", []),
                    is_awp=False,
                )

        st.write("")
        st.write("")

        # ---------------------------------------------------------------------
        # 4. START & END DATE
        # ---------------------------------------------------------------------
        st.markdown("<h6>4. START & END DATE</h6>", unsafe_allow_html=True)
        col10, col11 = st.columns(2)
        if is_awp:
            with col10:
                ro_widget("anticipated_start", "Anticipated Start", fmt_date(project.get("Anticipated_Start")))
            with col11:
                ro_widget("anticipated_end", "Anticipated End", fmt_date(project.get("Anticipated_End")))
        else:
            with col10:
                st.session_state["anticipated_start"] = st.date_input(
                    label="Anticpated Start",
                    format="MM/DD/YYYY",
                    value=st.session_state.get(
                        "anticipated_start",
                        fmt_date_or_none(project.get("Anticipated_Start")),
                    ),
                    key=widget_key("anticipated_start", version, is_awp),
                )
            with col11:
                st.session_state["anticipated_end"] = st.date_input(
                    label="Anticpated End",
                    format="MM/DD/YYYY",
                    value=st.session_state.get(
                        "anticipated_end",
                        fmt_date_or_none(project.get("Anticipated_End")),
                    ),
                    key=widget_key("anticipated_end", version, is_awp),
                )

        st.write("")
        st.write("")

        # ---------------------------------------------------------------------
        # 5. AWARD INFORMATION
        # ---------------------------------------------------------------------
        st.markdown("<h6>5. AWARD INFORMATION</h6>", unsafe_allow_html=True)
        if is_awp:
            col12, col13 = st.columns(2)
            with col12:
                ro_widget("award_date", "Award Date", fmt_agol_date(project.get("Award_Date")))
            with col13:
                ro_widget(
                    "award_fiscal_year",
                    "Awarded Fiscal Year",
                    fmt_int(project.get("Award_Fiscal_Year"), year=True),
                )
            ro_widget("contractor", "Awarded Contractor", fmt_string(project.get("Contractor")))
            col15, col16, col17 = st.columns(3)
            with col15:
                ro_widget("awarded_amount", "Awarded Amount", fmt_currency(project.get("Awarded_Amount")))
            with col16:
                ro_widget(
                    "current_contract_amount",
                    "Current Contract Amount",
                    fmt_currency(project.get("Current_Contract_Amount")),
                )
            with col17:
                ro_widget(
                    "amount_paid_to_date",
                    "Amount Paid to Date",
                    fmt_currency(project.get("Amount_Paid_To_Date")),
                )
            ro_widget("tenadd", "Tentative Advertise Date", fmt_date(project.get("TenAdd")))
        else:
            col12, col13 = st.columns(2)
            with col12:
                st.session_state["award_date"] = st.date_input(
                    label="Award Date",
                    format="MM/DD/YYYY",
                    value=st.session_state.get(
                        "award_date",
                        fmt_date_or_none(project.get("Award_Date")),
                    ),
                    key=widget_key("award_date", version, is_awp),
                )
            with col13:
                st.session_state["award_fiscal_year"] = session_selectbox(
                    key="award_fiscal_year",
                    label="Awarded Fiscal Year",
                    options=st.session_state.get("years", []),
                    force_str=is_awp,  # keep original behavior
                    is_awp=False,
                    help="The fiscal year for the award date",
                )

            st.session_state["contractor"] = st.text_input(
                label="Awarded Contractor",
                key=widget_key("contractor", version, is_awp),
                value=st.session_state.get("contractor", project.get("Contractor", "")),
            )

            col15, col16, col17 = st.columns(3)
            with col15:
                _val_awarded = st.session_state.get("awarded_amount")
                if _val_awarded is None:
                    _val_awarded = fmt_int_or_none(project.get("Awarded_Amount"))
                if _val_awarded is None:
                    _val_awarded = 0
                st.session_state["awarded_amount"] = st.number_input(
                    label="Awarded Amount",
                    key=widget_key("awarded_amount", version, is_awp),
                    value=_val_awarded,
                )
            with col16:
                _val_current = st.session_state.get("current_contract_amount")
                if _val_current is None:
                    _val_current = fmt_int_or_none(project.get("Current_Contract_Amount"))
                if _val_current is None:
                    _val_current = 0
                st.session_state["current_contract_amount"] = st.number_input(
                    label="Current Contract Amount",
                    key=widget_key("current_contract_amount", version, is_awp),
                    value=_val_current,
                )
            with col17:
                _val_paid = st.session_state.get("amount_paid_to_date")
                if _val_paid is None:
                    _val_paid = fmt_int_or_none(project.get("Amount_Paid_To_Date"))
                if _val_paid is None:
                    _val_paid = 0
                st.session_state["amount_paid_to_date"] = st.number_input(
                    label="Amount Paid to Date",
                    key=widget_key("amount_paid_to_date", version, is_awp),
                    value=_val_paid,
                )

            st.session_state["tenadd"] = st.date_input(
                label="Tentative Advertise Date",
                format="MM/DD/YYYY",
                value=st.session_state.get(
                    "tenadd",
                    fmt_date_or_none(project.get("TenAdd")),
                ),
                key=widget_key("tenadd", version, is_awp),
            )

        st.write("")
        st.write("")

        # ---------------------------------------------------------------------
        # 6. DESCRIPTION
        # ---------------------------------------------------------------------
        st.markdown("<h6>6. DESCRIPTION</h6>", unsafe_allow_html=True)
        if is_awp:
            ro_widget(
                "awp_proj_desc",
                "AASHTOWare Description",
                fmt_string(project.get("AWP_Proj_Desc")),
                textarea=True,
            )
            ro_widget(
                "proj_desc",
                "Public Description",
                fmt_string(project.get("Proj_Desc")),
                textarea=True,
            )
        else:
            st.session_state["proj_desc"] = st.text_area(
                "Public Description ⮜",
                height=200,
                max_chars=8000,
                value=st.session_state.get("proj_desc", project.get("Proj_Desc", "")),
                key=widget_key("proj_desc", version, is_awp),
            )

        st.write("")
        st.write("")

        # ---------------------------------------------------------------------
        # 7. CONTACT
        # ---------------------------------------------------------------------
        st.markdown("<h6>7. CONTACT</h6>", unsafe_allow_html=True)
        if is_awp:
            ro_widget("contact_name", "Contact", fmt_string(project.get("Contact_Name")))
            col18, col19 = st.columns(2)
            with col18:
                ro_widget("contact_email", "Email", fmt_string(project.get("Contact_Email")))
            with col19:
                ro_widget("contact_phone", "Phone", fmt_string(project.get("Contact_Phone")))
        else:
            st.session_state["contact_name"] = st.text_input(
                label="Name",
                key=widget_key("contact_name", version, is_awp),
                value=st.session_state.get("contact_name", project.get("Contact_Name", "")),
            )
            col18, col19 = st.columns(2)
            with col18:
                st.session_state["contact_email"] = st.text_input(
                    label="Email",
                    key=widget_key("awp_contact_email", version, is_awp),
                    value=st.session_state.get("contact_email", project.get("Contact_Email", "")),
                )
            with col19:
                st.session_state["contact_phone"] = st.text_input(
                    label="Phone",
                    key=widget_key("contact_phone", version, is_awp),
                    value=st.session_state.get("contact_phone", project.get("Contact_Phone", "")),
                )

        st.write("")
        st.write("")

        # ---------------------------------------------------------------------
        # 8. WEB LINK
        # ---------------------------------------------------------------------
        st.markdown("<h6>8. WEB LINK</h6>", unsafe_allow_html=True)
        if is_awp:
            ro_widget("proj_web", "Project Website", fmt_string(project.get("Proj_Web")))
        else:
            st.session_state["proj_web"] = st.text_input(
                label="Project Website",
                key=widget_key("proj_web", version, is_awp),
                value=st.session_state.get("proj_web", project.get("Proj_Web", "")),
            )

    information_buttons = st.container(border=False)
    with information_buttons:
        # Update Button
        st.button(
            "UPDATE INFORMATION",
            type='primary',
            use_container_width=True,
            on_click=_on_update_information,
        )

        # --- Progress bar placeholder ---
        # Placed directly BELOW the buttons and spans the width of this container.
        progress_placeholder = st.empty()
        # Store a handle in session_state so the callback can update and then clear it.
        st.session_state["info_progress_placeholder"] = progress_placeholder