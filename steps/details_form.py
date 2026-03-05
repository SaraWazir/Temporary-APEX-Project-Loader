"""
=============================================================================
PROJECT DETAILS FORM (STREAMLIT)
=============================================================================
Purpose:
Renders a two-mode project details form:
    1) AASHTOWare Database (read-only display of values pulled into session_state)
    2) User Input (editable Streamlit widgets)

Key behaviors:
    - Source-specific widget keys to prevent value bleed between AWP vs UI
    - Read-only “widgets” rendered via HTML/CSS while still persisting values
    - Per-source snapshot persistence for navigation and switching modes
    - Impacted communities selection persisted per source and mirrored for legacy usage
    - ✅ Submit button auto-resets to "SUBMIT FOOTPRINT" when:
        * switching modes (AASHTOWare <-> User Input)
        * choosing a different AASHTOWare project
        * any form field changes
=============================================================================
"""

import streamlit as st
import datetime
from agol.agol_util import get_multiple_fields, select_record, aashtoware_geometry
from util.read_only_util import ro_widget
from util.input_util import (
    fmt_currency, 
    fmt_date, 
    fmt_date_or_none, 
    fmt_int, 
    fmt_int_or_none, 
    fmt_string,
    fmt_agol_date,
    widget_key
)
from util.streamlit_util import (
    session_selectbox,
    impacted_comms_select,
    aashtoware_project
)


# =============================================================================
# SNAPSHOTTING / PERSISTENCE
# =============================================================================
# These utilities allow you to:
# - Switch between sources without losing the other source's values
# - Navigate away and return while maintaining progress
#
# Mechanism:
# - Snapshot persisted keys into st.session_state['saved_awp'] or ['saved_user']
# - Preload values back into st.session_state upon re-entering a mode
# =============================================================================
_PERSISTED_KEYS = [
    # Core fields
    "construction_year",
    "phase",
    "proj_name",
    "iris",
    "stip",
    "fed_proj_num",
    "fund_type",
    "proj_prac",
    "anticipated_start",
    "anticipated_end",

    # Award info
    "award_date",
    "award_fiscal_year",
    "contractor",
    "awarded_amount",
    "current_contract_amount",
    "amount_paid_to_date",
    "tenadd",

    # Descriptions / links
    "proj_desc",
    "proj_web",

    #Route ID/Name
    'route_id',
    'route_name',

    # Contact (new/current)
    "contact_name",
    "contact_role",
    "contact_email",
    "contact_phone",

    # Impacted communities (legacy mirror keys used downstream)
    "impact_comm",
    "impact_comm_ids",
    "impact_comm_names",

    # AWP-specific display fields (read-only widgets)
    "awp_proj_name",
    "awp_proj_desc",

    # identifiers for re-population
    "aashto_id",
    "aashto_label",
    "aashto_selected_project",
]
_SOURCE_SNAPSHOT_KEY = {
    "AASHTOWare Database": "saved_awp",
    "User Input": "saved_user",
}


def _snapshot_form(source: str):
    snap_key = _SOURCE_SNAPSHOT_KEY.get(source)
    if not snap_key:
        return
    st.session_state[snap_key] = {k: st.session_state.get(k, None) for k in _PERSISTED_KEYS}


def _preload_from_snapshot(source: str):
    snap_key = _SOURCE_SNAPSHOT_KEY.get(source)
    if not snap_key:
        return
    snap = st.session_state.get(snap_key, {})
    for k, v in snap.items():
        if v is not None:
            st.session_state[k] = v


# =============================================================================
# CHANGE WATCH / DIRTY-STATE HELPERS
# =============================================================================
_WATCH_KEYS = sorted(set(_PERSISTED_KEYS + [
    "info_option",
    "current_option",
    "awp_id",
    "aashto_selected_project",
    "construction_year",
    "phase",
]))


def _mark_unsaved():
    st.session_state["details_complete"] = False


def _watch_and_reset():
    changed = False
    for k in _WATCH_KEYS:
        v = st.session_state.get(k, None)
        last_k = f"__last__{k}"
        if last_k in st.session_state and st.session_state[last_k] != v:
            changed = True
        st.session_state[last_k] = v

    if changed:
        _mark_unsaved()


# =============================================================================
# FORM ENTRYPOINT: SOURCE SELECTION + ROUTING
# =============================================================================
def project_details_form():

    st.session_state.setdefault("form_version", 0)
    st.session_state.setdefault("prev_info_option", None)
    st.session_state.setdefault("info_option", None)

    OPTIONS = ["AASHTOWare Database", "User Input"]

    prior_choice = st.session_state.get("details_type")
    if (
        prior_choice in OPTIONS
        and (st.session_state.get("info_option") is None or st.session_state.get("info_option") == "")
    ):
        st.session_state["info_option"] = prior_choice

    st.markdown("###### CHOOSE PROJECT SOURCE\n", unsafe_allow_html=True)

    selection = st.segmented_control(
        "Choose Source Method:",
        OPTIONS,
        key="info_option",
    )
    st.write("")

    current_option = selection
    st.session_state["current_option"] = selection
    previous_option = st.session_state.get("prev_info_option")

    if current_option is not None and current_option != previous_option:
        if current_option == "User Input":
            for k in list(st.session_state.keys()):
                if k.startswith("awp_"):
                    st.session_state[k] = ""
            st.session_state["aashto_id"] = ""
            st.session_state["aashto_label"] = ""
            st.session_state["aashto_selected_project"] = ""

            for k in _PERSISTED_KEYS:
                if not k.startswith("awp_"):
                    st.session_state[k] = ""

        st.session_state["prev_info_option"] = current_option
        st.session_state["details_complete"] = False
        st.session_state["form_version"] += 1

    if current_option:
        _preload_from_snapshot(current_option)

    if current_option == "AASHTOWare Database":
        st.markdown("###### SELECT PROJECT AASHTOWARE PROJECT\n", unsafe_allow_html=True)

        with st.container(border=True):
            aashtoware_project()

            for k in ("awp_id", "aashto_selected_project"):
                curr = st.session_state.get(k)
                prev_k = f"__last__{k}"
                if prev_k in st.session_state and st.session_state[prev_k] != curr:
                    _mark_unsaved()
                st.session_state[prev_k] = curr
        
        st.write('')
        _render_original_form(is_awp=True)

    elif current_option == "User Input":
        _render_original_form(is_awp=False)

    else:
        st.info("Please choose a source method above to begin.")



# =============================================================================
# FORM BODY RENDERER
# =============================================================================
def _render_original_form(is_awp: bool):

    version = st.session_state.get("form_version", 0)
    form_key = f"project_details_form_{version}"

    def val(key_user: str, key_awp: str = None, coerce_float: bool = False):
        if is_awp and key_awp:
            v = st.session_state.get(key_awp, "")
        else:
            v = st.session_state.get(key_user, "")
        if coerce_float:
            try:
                return float(v or 0)
            except Exception:
                return 0.0
        return v

    st.markdown("###### COMPLETE PROJECT FORM\n", unsafe_allow_html=True)

    with st.container(border=True):
        AWP_FIELDS = st.session_state['awp_fields']

        # ---------------------------------------------------------------------
        # SECTION 1
        # ---------------------------------------------------------------------
        st.markdown("<h5>1. PROJECT NAME</h5>", unsafe_allow_html=True)

        if is_awp:
            c1, c2 = st.columns(2)
            with c1:
                ro_widget(
                    key="awp_proj_name",
                    label="AASHTOWare Project Name",
                    value=fmt_string(val(AWP_FIELDS['awp_proj_name'])),
                )
            with c2:
                ro_widget(
                    key="proj_name",
                    label="Public Project Name",
                    value=fmt_string(val(AWP_FIELDS['proj_name'])),
                )
        else:
            st.session_state["proj_name"] = st.text_input(
                "Public Project Name ⮜",
                value=st.session_state.get("proj_name", ""),
                key=widget_key("proj_name", version, is_awp),
                help="Provide the project name that will be displayed publicly.",
            )

        st.write("")

        # ---------------------------------------------------------------------
        # SECTION 2
        # ---------------------------------------------------------------------
        st.markdown("<h5>2. CONSTRUCTION YEAR, PHASE, & IDS</h5>", unsafe_allow_html=True)

        col1, col2 = st.columns(2)
        with col1:
            options = [str(o) if o is not None else "" for o in st.session_state["construction_years"]]
            saved = st.session_state.get("construction_year", "")
            saved_str = str(saved) if saved is not None else ""

            existing_raw = st.session_state.get("awp_selected_construction_years", "")
            if isinstance(existing_raw, str):
                existing = {v.strip() for v in existing_raw.split(",") if v.strip()}
            elif isinstance(existing_raw, (list, tuple, set)):
                existing = {str(v).strip() for v in existing_raw}
            else:
                existing = set()

            filtered_options = [opt for opt in options if opt not in existing]
            if not filtered_options:
                filtered_options = [""]

            if saved_str in filtered_options:
                idx = filtered_options.index(saved_str)
            elif "" in filtered_options:
                idx = filtered_options.index("")
            else:
                idx = 0

            st.session_state["construction_year"] = st.selectbox(
                "Construction Year ⮜",
                filtered_options,
                index=idx,
                key=widget_key("construction_year", version, is_awp),
                help="The project’s assigned year. Continuing projects must also receive a new year.",
            )
        if is_awp:
            with col2:
                ro_widget(
                    key="phase",
                    label="Phase",
                    value=fmt_string(val(AWP_FIELDS['phase'])),
                )
        else:
            with col2:
                st.session_state["phase"] = session_selectbox(
                    key="phase",
                    label="Phase",
                    help="Indicates the construction phase scheduled for this project in the current year.",
                    options=(st.session_state['phase_list']),
                    is_awp=is_awp,
                )

        # ---------------------------------------------------------------------
        # SECTION 3
        # ---------------------------------------------------------------------
        st.markdown("<h5>3. FUNDING TYPE & PRACTICE</h5>", unsafe_allow_html=True)

        if is_awp:
            col13, col14 = st.columns(2)
            with col13:
                ro_widget(
                    key="fund_type",
                    label="Funding Type",
                    value=fmt_string(val(AWP_FIELDS['fund_type'])),
                )
            with col14:
                ro_widget(
                    key="proj_prac",
                    label="Project Practice",
                    value=fmt_string(val(AWP_FIELDS['proj_prac'])),
                )
        else:
            col13, col14 = st.columns(2)
            with col13:
                st.session_state["fund_type"] = session_selectbox(
                    key="fund_type",
                    label="Funding Type",
                    help="",
                    options=(st.session_state['funding_list']),
                    is_awp=is_awp,
                )
            with col14:
                st.session_state["proj_prac"] = session_selectbox(
                    key="proj_prac",
                    label="Project Practice",
                    help="",
                    options=st.session_state['practice_list'],
                    is_awp=is_awp,
                )

        st.write("")
        st.write("")

        # ---------------------------------------------------------------------
        # SECTION 4
        # ---------------------------------------------------------------------
        st.markdown("<h5>4. START & END DATE</h5>", unsafe_allow_html=True)

        if is_awp:
            col10, col11 = st.columns(2)
            with col10:
                ro_widget(
                    key="anticipated_start",
                    label="Anticipated Start",
                    value=fmt_date(val(AWP_FIELDS['anticipated_start'])),
                )
            with col11:
                ro_widget(
                    key="anticipated_end",
                    label="Anticipated End",
                    value=fmt_date(val(AWP_FIELDS['anticipated_end'])),
                )
        else:
            col10, col11 = st.columns(2)
            with col10:
                st.session_state["anticipated_start"] = st.date_input(
                    label="Anticpated Start",
                    format="MM/DD/YYYY",
                    value=fmt_date_or_none(st.session_state.get("anticipated_start", None)),
                    key=widget_key("anticipated_start", version, is_awp),
                )
            with col11:
                st.session_state["anticipated_end"] = st.date_input(
                    label="Anticpated End",
                    format="MM/DD/YYYY",
                    value=fmt_date_or_none(st.session_state.get("anticipated_end", None)),
                    key=widget_key("anticipated_end", version, is_awp),
                )

        st.write("")
        st.write("")

        # ---------------------------------------------------------------------
        # SECTION 5
        # ---------------------------------------------------------------------
        st.markdown("<h5>5. AWARD INFORMATION</h5>", unsafe_allow_html=True)

        if is_awp:
            col12, col13 = st.columns(2)
            with col12:
                ro_widget(
                    key="award_date",
                    label="Award Date",
                    value=fmt_agol_date(val(AWP_FIELDS['award_date'])),
                )
            with col13:
                ro_widget(
                    key="award_fiscal_year",
                    label="Awarded Fiscal Year",
                    value=fmt_int(val(AWP_FIELDS['award_fiscal_year']), year=True),
                )
        else:
            col12, col13 = st.columns(2)
            with col12:
                st.session_state["award_date"] = st.date_input(
                    label="Award Date",
                    format="MM/DD/YYYY",
                    value=fmt_date_or_none(st.session_state.get("award_date", None)),
                    key=widget_key("award_date", version, is_awp),
                )
            with col13:
                st.session_state["award_fiscal_year"] = session_selectbox(
                    key="award_fiscal_year",
                    label="Awarded Fiscal Year",
                    options=st.session_state['years'],
                    force_str=is_awp,
                    is_awp=is_awp,
                    help="The fiscal year for the award date"
                )

        if is_awp:
            ro_widget(
                key="contractor",
                label="Awarded Contractor",
                value=fmt_string(val(AWP_FIELDS['contractor'])),
            )
        else:
            st.session_state["contractor"] = st.text_input(
                label="Awarded Contractor",
                key=widget_key("contractor", version, is_awp),
                value=st.session_state.get("contractor", ''),
            )

        if is_awp:
            col15, col16, col17 = st.columns(3)
            with col15:
                ro_widget(
                    key="awarded_amount",
                    label="Awarded Amount",
                    value=fmt_currency(val(AWP_FIELDS['awarded_amount'])),
                )
            with col16:
                ro_widget(
                    key="current_contract_amount",
                    label="Current Contract Amount",
                    value=fmt_currency(val(AWP_FIELDS['current_contract_amount'])),
                )
            with col17:
                ro_widget(
                    key="amount_paid_to_date",
                    label="Amount Paid to Date",
                    value=fmt_currency(val(AWP_FIELDS['amount_paid_to_date'])),
                )
        else:
            col15, col16, col17 = st.columns(3)
            with col15:
                st.session_state["awarded_amount"] = st.number_input(
                    label="Awarded Amount",
                    key=widget_key("awarded_amount", version, is_awp),
                    value=fmt_int_or_none(st.session_state.get("awarded_amount", None)),
                )
            with col16:
                st.session_state["current_contract_amount"] = st.number_input(
                    label="Current Contract Amount",
                    key=widget_key("current_contract_amount", version, is_awp),
                    value=fmt_int_or_none(st.session_state.get("current_contract_amount", None)),
                )
            with col17:
                st.session_state["amount_paid_to_date"] = st.number_input(
                    label="Amount Paid to Date",
                    key=widget_key("amount_paid_to_date", version, is_awp),
                    value=fmt_int_or_none(st.session_state.get("amount_paid_to_date", None)),
                )

        if is_awp:
            ro_widget(
                key="tenadd",
                label="Tentative Advertise Date",
                value=fmt_date(val(AWP_FIELDS['tenadd'])),
            )
        else:
            st.session_state["tenadd"] = st.date_input(
                label="Tentative Advertise Date",
                format="MM/DD/YYYY",
                value=fmt_date_or_none(st.session_state.get("tenadd", None)),
                key=widget_key("tenadd", version, is_awp),
            )

        st.write("")
        st.write("")

        # ---------------------------------------------------------------------
        # SECTION 6
        # ---------------------------------------------------------------------
        st.markdown("<h5>6. DESCRIPTION</h5>", unsafe_allow_html=True)

        if is_awp:
            ro_widget(
                key="awp_proj_desc",
                label="AASHTOWare Description",
                value=fmt_string(val(AWP_FIELDS['awp_proj_desc'])),
                textarea=True
            )
            ro_widget(
                key="proj_desc",
                label="Public Description",
                value=fmt_string(val(AWP_FIELDS['proj_desc'])),
                textarea=True
            )
        else:
            st.session_state["proj_desc"] = st.text_area(
                "Public Description ⮜",
                height=200,
                max_chars=8000,
                value=st.session_state.get("proj_desc", ""),
                key=widget_key("proj_desc", version, is_awp),
            )

        st.write("")
        st.write("")

        # ---------------------------------------------------------------------
        # SECTION 7
        # ---------------------------------------------------------------------
        st.markdown("<h5>7. CONTACT</h5>", unsafe_allow_html=True)

        if is_awp:
            ro_widget(
                key="contact_name",
                label="Contact",
                value=fmt_string(val(AWP_FIELDS['contact_name']))
            )
            col18, col19 = st.columns(2)
            with col18:
                ro_widget(
                    key="contact_email",
                    label="Email",
                    value=fmt_string(val(AWP_FIELDS['contact_email']))
                )
            with col19:
                ro_widget(
                    key="contact_phone",
                    label="Phone",
                    value=fmt_string(val(AWP_FIELDS['contact_phone']))
                )
        else:
            st.session_state["contact_name"] = st.text_input(
                label="Name",
                key=widget_key("contact_name", version, is_awp),
                value=st.session_state.get("contact_name", ''),
            )
            col18, col19 = st.columns(2)
            with col18:
                st.session_state["contact_email"] = st.text_input(
                    label="Email",
                    key=widget_key("awp_contact_email", version, is_awp),
                    value=st.session_state.get("contact_email", ''),
                )
            with col19:
                st.session_state["contact_phone"] = st.text_input(
                    label="Phone",
                    key=widget_key("contact_phone", version, is_awp),
                    value=st.session_state.get("contact_phone", ''),
                )

        st.write("")
        st.write("")

        # ---------------------------------------------------------------------
        # SECTION 8
        # ---------------------------------------------------------------------
        st.markdown("<h5>8. WEB LINK</h5>", unsafe_allow_html=True)

        if is_awp:
            ro_widget(
                key="proj_web",
                label="Project Website",
                value=fmt_string(val(AWP_FIELDS['proj_web']))
            )
        else:
            st.session_state["proj_web"] = st.text_input(
                label="Project Website",
                key=widget_key("proj_web", version, is_awp),
                value=st.session_state.get("proj_web", ''),
            )

        st.write("")
        st.write("")

        # ---------------------------------------------------------------------
        # SECTION 9
        # ---------------------------------------------------------------------
        st.markdown("<h5>9. IMPACTED COMMUNITIES</h5>", unsafe_allow_html=True)
        st.session_state["impact_comm"] = impacted_comms_select(is_awp=is_awp)

        st.write("")

        # ---------------------------------------------------------------------
        # SUBMIT
        # ---------------------------------------------------------------------

        _watch_and_reset()

        submitted = bool(st.session_state.get("details_complete", False))
        btn_ph = st.empty()

        def _render_submit_button(is_done: bool):
            label = "SUBMIT INFORMATION ✅" if is_done else "SUBMIT INFORMATION"
            done_suffix = "done" if is_done else "live"
            return btn_ph.button(
                label,
                use_container_width=True,
                key=f"details_submit_{version}_{done_suffix}",
                disabled=is_done,
            )

        clicked = _render_submit_button(submitted)

        if clicked and not submitted:

            if is_awp:
                required_fields = {
                    "Construction Year": st.session_state.get("construction_year"),
                    "Public Project Name": st.session_state.get("proj_name"),
                    "Public Description": st.session_state.get("proj_desc"),
                }
            else:
                required_fields = {
                    "Construction Year": st.session_state.get("construction_year"),
                    "Public Project Name": st.session_state.get("proj_name"),
                    "Public Description": st.session_state.get("proj_desc"),
                }

            missing_fields = [f for f,v in required_fields.items() if not v]

            if missing_fields:
                st.session_state["details_complete"] = False
                for field in missing_fields:
                    if is_awp and field in ["Public Project Name", "Public Description"]:
                        st.warning(f"Missing {field}. Please update the information in AASHTOWare before continuing.")
                    else:
                        st.error(f"{field} Required")

            else:
                st.session_state["details_complete"] = True
                st.session_state["project_details"] = required_fields
                st.session_state["details_type"] = st.session_state.get("current_option")

                if not is_awp:
                    UI_TRANSFORM_MAP = {
                        'anticipated_start': fmt_date,
                        'anticipated_end': fmt_date,
                        'award_date': fmt_date,
                        'tenadd': fmt_date,
                    }
                    for key, func in UI_TRANSFORM_MAP.items():
                        if key in st.session_state:
                            try:
                                st.session_state[key] = func(st.session_state.get(key))
                            except Exception:
                                pass

                # Select Geometry Points if AASHTOWARE Project
                if is_awp:
                    st.session_state['is_awp'] = True
                    awp_id = st.session_state.get("awp_id")
                    if not awp_id:
                        st.error(f"AWP ID is missing in session_state['awp_id'].")
                    else:
                        # Fetch geometry points once and store
                        st.session_state["awp_geometry_points"] = aashtoware_geometry(awp_id)

                _snapshot_form(st.session_state.get("info_option"))

                btn_ph.button(
                    "SUBMIT INFORMATION ✅",
                    use_container_width=True,
                    key=f"details_submit_{version}_done",
                    disabled=True,
                )

