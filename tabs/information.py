# =============================================================================
# INFORMATION MANAGEMENT TAB
# =============================================================================

import streamlit as st
from agol.agol_util import select_record
from util.read_only_util import ro_widget
from util.input_util import fmt_string, fmt_date, fmt_agol_date


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


# -----------------------------------------------------------------------------
# Helper: fetch AASHTOWare contract record
# -----------------------------------------------------------------------------
def _get_awp_contract_record(awp_id):
    url = st.session_state.get("aashtoware_url")
    layer = st.session_state.get("awp_contracts_layer")

    if not (url and layer is not None and awp_id):
        return None

    recs = select_record(
        url=url,
        layer=layer,
        id_field="AWP_Contract_ID",
        id_value=awp_id,
        fields=["ProjectName", "Last_updated_FME"],
        return_geometry=False,
    )

    return recs[0]["attributes"] if recs else None


# -----------------------------------------------------------------------------
# PROJECT DATA SOURCE CONTAINER
# -----------------------------------------------------------------------------
def _render_project_source_section(project):
    awp_id = project.get("AWP_Contract_ID")

    with st.container(border=True):
        st.markdown("##### PROJECT DATA SOURCE")

        if awp_id:
            st.columns(1)  # spacing consistency
            ro_widget(
                key="proj_data_source",
                label="Source",
                value="AASHTOWare",
            )

            awp_rec = _get_awp_contract_record(awp_id)

            c1, c2 = st.columns(2)
            with c1:
                ro_widget(
                    key="awp_proj_name",
                    label="AWP Project Name",
                    value=fmt_string(awp_rec.get("ProjectName") if awp_rec else ""),
                )
            with c2:
                ro_widget(
                    key="awp_last_updated",
                    label="Last Updated",
                    value=fmt_agol_date(awp_rec.get("Last_updated_FME") if awp_rec else None),
                )

            b1, b2 = st.columns(2)
            with b1:
                st.button(
                    "CHANGE CONNECTION",
                    use_container_width=True,
                    disabled=True,
                )
            with b2:
                st.button(
                    "DELETE CONNECTION",
                    use_container_width=True,
                    disabled=True,
                )

        else:
            c1, c2 = st.columns(2)
            with c1:
                ro_widget(
                    key="proj_data_source",
                    label="Source",
                    value="User Input",
                )
            with c2:
                ro_widget(
                    key="user_last_edit",
                    label="Last Updated",
                    value=fmt_agol_date(project.get("EditDate")),
                )


# -----------------------------------------------------------------------------
# MAIN INFORMATION TAB
# -----------------------------------------------------------------------------
def manage_information():
    import streamlit as st
    from util.read_only_util import ro_widget
    from util.input_util import (
        fmt_string, fmt_date, fmt_agol_date,
        fmt_currency, fmt_int,
    )

    project = st.session_state.get("project_record", [{}])[0].get("attributes", {})
    is_awp = bool(project.get("AWP_Contract_ID"))

    # ------------------------------------------------------------------
    st.markdown("##### PROJECT DATA SOURCE")
    with st.container(border=True):
        if is_awp:
            ro_widget("info_source", "Source", "AASHTOWare")
            ro_widget("awp_name", "AWP Project", project.get("AWP_Proj_Name"))
            ro_widget("awp_updated", "Last Updated", fmt_agol_date(project.get("Last_updated_FME")))
            st.columns(2)[0].button("CHANGE CONNECTION", use_container_width=True, disabled=True)
            st.columns(2)[1].button("DELETE CONNECTION", use_container_width=True, disabled=True)
        else:
            ro_widget("info_source", "Source", "User Input")
            ro_widget("user_updated", "Last Updated", fmt_agol_date(project.get("EditDate")))

    # ------------------------------------------------------------------
    with st.container(border=True):
        st.markdown("<h5>1. PROJECT NAME</h5>", unsafe_allow_html=True)
        if is_awp:
            ro_widget("awp_proj_name", "AASHTOWare Project Name", project.get("AWP_Proj_Name"))
        ro_widget("proj_name", "Public Project Name", project.get("Proj_Name"))

        st.markdown("<h5>2. CONSTRUCTION YEAR, PHASE, & IDS</h5>", unsafe_allow_html=True)
        ro_widget("construction_year", "Construction Year", project.get("Construction_Year"))
        ro_widget("phase", "Phase", project.get("Phase"))
        ro_widget("iris", "IRIS", project.get("IRIS"))
        ro_widget("stip", "STIP", project.get("STIP"))
        ro_widget("fed_proj_num", "Federal Project Number", project.get("Fed_Proj_Num"))

        st.markdown("<h5>3. FUNDING TYPE & PRACTICE</h5>", unsafe_allow_html=True)
        ro_widget("fund_type", "Funding Type", project.get("Fund_Type"))
        ro_widget("proj_prac", "Project Practice", project.get("Proj_Prac"))

        st.markdown("<h5>4. START & END DATE</h5>", unsafe_allow_html=True)
        ro_widget("anticipated_start", "Anticipated Start", fmt_date(project.get("Anticipated_Start")))
        ro_widget("anticipated_end", "Anticipated End", fmt_date(project.get("Anticipated_End")))

        st.markdown("<h5>5. AWARD INFORMATION</h5>", unsafe_allow_html=True)
        ro_widget("award_date", "Award Date", fmt_agol_date(project.get("Award_Date")))
        ro_widget("award_fiscal_year", "Awarded Fiscal Year", fmt_int(project.get("Award_Fiscal_Year"), year=True))
        ro_widget("contractor", "Awarded Contractor", project.get("Contractor"))
        ro_widget("awarded_amount", "Awarded Amount", fmt_currency(project.get("Awarded_Amount")))
        ro_widget("current_contract_amount", "Current Contract Amount", fmt_currency(project.get("Current_Contract_Amount")))
        ro_widget("amount_paid_to_date", "Amount Paid to Date", fmt_currency(project.get("Amount_Paid_To_Date")))
        ro_widget("tenadd", "Tentative Advertise Date", fmt_date(project.get("TenAdd")))

        st.markdown("<h5>6. DESCRIPTION</h5>", unsafe_allow_html=True)
        if is_awp:
            ro_widget("awp_proj_desc", "AASHTOWare Description", project.get("AWP_Proj_Desc"), textarea=True)
        ro_widget("proj_desc", "Public Description", project.get("Proj_Desc"), textarea=True)

        st.markdown("<h5>7. CONTACT</h5>", unsafe_allow_html=True)
        ro_widget("contact_name", "Contact Name", project.get("Contact_Name"))
        ro_widget("contact_role", "Role", project.get("Contact_Role"))
        ro_widget("contact_email", "Email", project.get("Contact_Email"))
        ro_widget("contact_phone", "Phone", project.get("Contact_Phone"))

        st.markdown("<h5>8. ROUTE INFORMATION</h5>", unsafe_allow_html=True)
        ro_widget("route_id", "Route ID", project.get("Route_ID"))
        ro_widget("route_name", "Route Name", project.get("Route_Name"))

        st.markdown("<h5>9. IMPACTED COMMUNITIES</h5>", unsafe_allow_html=True)
        ro_widget("impact_comm", "Impacted Communities", project.get("Impact_Comm"))
        ro_widget("impact_comm_names", "Community Names", project.get("Impact_Comm_Names"))

        st.markdown("<h5>10. PROJECT LINKS / IDS</h5>", unsafe_allow_html=True)
        ro_widget("proj_web", "Project Website", project.get("Proj_Web"))
        ro_widget("aashto_id", "AASHTO ID", project.get("aashto_id"))
        ro_widget("aashto_selected_project", "AASHTOWare Selection", project.get("aashto_selected_project"))


# -----------------------------------------------------------------------------
# DEPLOYMENT STUB (FOR CONSISTENCY WITH MANAGER)
# -----------------------------------------------------------------------------
def deploy_information_to_agol():
    """
    Placeholder for future INFORMATION deployment logic.
    Included to match Manager tab structure.
    """
    return {"success": False, "message": "Information deployment not implemented yet."}