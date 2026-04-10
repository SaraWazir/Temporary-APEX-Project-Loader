
"""
===============================================================================
SESSION INITIALIZATION (STREAMLIT) — DEFAULTS, LISTS, URLS, CREDENTIALS
===============================================================================

Purpose:
    Defines and initializes Streamlit session_state keys used across the app.
    This module centralizes:
      - Default session values and wizard state
      - Static lookup dictionaries and value lists (years, phases, etc.)
      - AGOL/APEX service URLs and layer indices
      - AGOL credential sourcing (.env or st.secrets)
      - AWP field mapping dictionary used for AASHTOWare integration
      - Uploader list values (for attribution / metadata)

Key behaviors:
    - Idempotent initialization:
        * Uses `setdefault()` and conditional checks so repeated imports/reruns
          do not overwrite active user inputs.
    - Centralized service definitions:
        * Sets APEX base URL + layer indices and derived per-layer URLs.
        * Sets intersect-service URLs for geography/district queries.
    - Credential sourcing:
        * If a .env file exists, loads via python-dotenv
        * Otherwise tries Streamlit secrets
        * Stores into session_state['AGOL_USERNAME'] / ['AGOL_PASSWORD']

Session-state keys created/initialized (high-level):
    - Wizard/navigation:
        'step', 'geo_option', 'info_option', selection flags, duplication flags
    - Geometry selections:
        'selected_point', 'selected_route', 'selected_boundary'
    - Project/contact scaffolding:
        'project_contacts', 'details_complete', etc.
    - Static lists:
        'construction_years', 'phase_list', 'funding_list', 'practice_list', 'years'
    - AGOL/APEX:
        'apex_url', layer IDs, layer URLs, intersect URLs
    - AWP:
        'awp_fields' mapping dictionary
    - Uploaders:
        'uploaders' list

Notes:
    - This module runs init_session_state() automatically at import time.
      That pattern is intentional for Streamlit apps where scripts rerun often.
    - Values are seeded, not enforced: downstream pages may update session_state
      after this initializer runs.

===============================================================================
"""

import os
import streamlit as st

# =============================================================================
# ENTRYPOINT: SESSION STATE INITIALIZATION
# =============================================================================
# init_session_state():
#   - Creates baseline session_state keys if missing
#   - Populates lookup dictionaries and static lists
#   - Populates AGOL/APEX URLs and layer IDs
#   - Loads credentials from .env or st.secrets and stores them in session_state
#   - Sets AWP field mapping and uploader list
# =============================================================================
def init_session_state():
    """Initialize all session state values."""

    # -------------------------------------------------------------------------
    # Session scaffolding: widget prefix registry (used by other modules)
    # -------------------------------------------------------------------------
    if "all_widget_prefixes" not in st.session_state:
        st.session_state["all_widget_prefixes"] = set()

    # ======================================================
    # DEFAULT & QUERY PARAMS
    # ======================================================

    # Defaults
    defaults = {
        'version': None,
        'guid': None,
        'set_year': None,
        'init_run': True,
        "loader_step": 1,
        "manager_tab": None,
        "is_awp": False,
        "apex_guid": None,
        "apex_awp_id": None,
        "apex_object_id": None,
        "ti_guid": None,
    }

    # Read query params (new + old API)
    if hasattr(st, "query_params"):
        params = {k: str(v) for k, v in st.query_params.items()}
    else:
        raw = st.experimental_get_query_params()
        params = {k: v[0] for k, v in raw.items() if v}

    # Keys that should be ints
    int_keys = {"loader_step", "manager_step"}

    def coerce(key, value):
        """Coerce known numeric keys to int; otherwise return as-is."""
        if value is None or value == "":
            return None
        if key in int_keys:
            try:
                return int(value)
            except Exception:
                # If parsing fails, fall back to default later
                return None
        return value

    # Seed: priority = query param (with coercion) → default
    for key, default in defaults.items():
        if key not in st.session_state:
            from_query = coerce(key, params.get(key))
            st.session_state[key] = from_query if from_query is not None else default

    # -------------------------------------------------------------------------
    # DICTIONARIES
    # -------------------------------------------------------------------------
    # Lookup dictionaries and code->label mappings used across form fields.
    dicts = {
        'project_phases': {
            49: "Project Definition",
            50: "Project Design & Review",
            51: "Assigned to Letting",
            52: "Advertising",
            91: "Import Xtab File from BidX",
            53: "Award Processing",
            54: "Add Alt Analysis",
            55: "Awarded",
            56: "Active Contract"
        }
    }
    for key, value in dicts.items():
        st.session_state.setdefault(key, value)

    # -------------------------------------------------------------------------
    # VALUES
    # -------------------------------------------------------------------------
    # Predefined selectbox lists (construction years, funding types, etc.)
    value_lists = {
        'construction_years': [
            "",
            "CY2026",
            "CY2027",
            "CY2028",
            "CY2029",
            "CY2030"
        ],
        'phase_list': [
            "",
            "Active Contract",
            "Add Alt Analysis",
            "Advertising",
            "Assigned to Letting",
            "Award Processing",
            "Awarded",
            "Import Xtab File from BidX",
            "Project Definition",
            "Project Design &amp; Review"
        ],
        'funding_list': [
            "",
            "AMHS",
            "DRER",
            "FAA",
            "FAPT",
            "FHWA",
            "FHWY",
            "FTA",
            "GRNT",
            "HARB",
            "MULT",
            "OTHER",
            "PFAC",
            "PLRS",
            "RMBS",
            "SAPT",
            "SHWY",
            "STATE"
        ],
        'practice_list': [
            "",
            'AMHS',
            "AVI",
            "CMGC",
            "CSB",
            "CSP",
            "DB",
            "DFS",
            "ER",
            "HWY",
            "JOCC",
            "M&O",
            "PSA",
            "SP",
            "SSP"
        ],
        'years': [
            "",
            "2020",
            "2021",
            "2022",
            "2023",
            "2024",
            "2025",
            "2026",
            "2027",
            "2028",
            "2029",
            "2030"
        ],
        'database_status_vals' : [
            "",
            'Review: Awaiting Review',
            'Review: Review in Progress',
            'Review: Returned for Edits',
            'Published',
            'Marked for Deletion',
            'Archived',
        ],
        'target_applications_vals' : [
            "",
            'Traffic Impacts',
            'Dashboard',
            'Infosheet'
        ]
    }

    for key, value in value_lists.items():
        st.session_state.setdefault(key, value)



    # -------------------------------------------------------------------------
    # AGOL URLS
    # -------------------------------------------------------------------------
    agol_urls = {
        'apex_url': "https://services.arcgis.com/r4A0V7UzH9fcLVvv/arcgis/rest/services/APEX_PROJECTS_LOADER_APPLICATION/FeatureServer",
        'traffic_impact_url': "https://services.arcgis.com/r4A0V7UzH9fcLVvv/arcgis/rest/services/TRAFFIC_IMPACT_EVENTS_LOADER_APPLICATION/FeatureServer",
        "aashtoware_url": "https://services.arcgis.com/r4A0V7UzH9fcLVvv/arcgis/rest/services/AWP_to_APEX_TRAFFIC_IMPACTS_LOADER/FeatureServer",
        "milepoints_url": "https://services.arcgis.com/r4A0V7UzH9fcLVvv/arcgis/rest/services/Pavement_Condition_Data_Tenth_Mile_2024/FeatureServer",
        "mileposts_url": "https://services.arcgis.com/r4A0V7UzH9fcLVvv/arcgis/rest/services/AKDOTPF_Route_Data/FeatureServer",
        'communities_url': "https://services.arcgis.com/r4A0V7UzH9fcLVvv/arcgis/rest/services/""All_Alaska_Communities_Baker/FeatureServer",
        'apex_contacts_url': "https://services.arcgis.com/r4A0V7UzH9fcLVvv/arcgis/rest/services/Traffic_Impact_Assignees/FeatureServer"
    }

    aashtoware_layers = {
        'awp_contracts_layer': 3,
        'awp_geometry_layer': 0,
        'awp_routes_layer': 1
    }

    traffic_impact_layers = {
        'traffic_impacts_layer': 0,
        'traffic_impact_routes_layer': 1,
        'traffic_impact_start_points_layer': 2,
        'traffic_impact_end_points_layer': 3
    }

    # Layer indices used by loaders and query helpers
    apex_layers = {
        "projects_layer": 0,
        "locations_layer": 1,
        "sites_layer": 2,
        "routes_layer": 3,
        "boundaries_layer": 4,
        "impact_comms_layer": 5,
        "region_layer": 6,
        "bor_layer": 7,
        "senate_layer": 8,
        "house_layer": 9
        }
    
    assigness_layers = {
        'apex_contacts_layer': 0
    }

    # Geography intersect services (used by district_queries / geography payloads)
    geography_intersects = {
        "region_intersect": {
            "url": "https://services.arcgis.com/r4A0V7UzH9fcLVvv/arcgis/rest/services/APEX_DOTPF_Regions/FeatureServer",
            "layer": 0
        },
        "borough_intersect": {
            "url": "https://services.arcgis.com/r4A0V7UzH9fcLVvv/arcgis/rest/services/APEX_BoroughCensus/FeatureServer",
            "layer": 0
        },
        "senate_intersect": {
            "url": "https://services.arcgis.com/r4A0V7UzH9fcLVvv/arcgis/rest/services/APEX_SenateDistricts/FeatureServer",
            "layer": 0
        },
        "house_intersect": {
            "url": "https://services.arcgis.com/r4A0V7UzH9fcLVvv/arcgis/rest/services/APEX_HouseDistricts/FeatureServer",
            "layer": 0
        },
        "route_intersect": {
            "url": "https://services.arcgis.com/r4A0V7UzH9fcLVvv/arcgis/rest/services/Roads_AKDOT/FeatureServer",
            "layer": 0
        },
        "mileposts_intersect": {
            'url':"https://services.arcgis.com/r4A0V7UzH9fcLVvv/arcgis/rest/services/Mileposts_AKDOT/FeatureServer",
            'layer': 0
        }
    }

    # Seed layer indices and URLs into session_state
    for key, value in agol_urls.items():
        st.session_state.setdefault(key, value)
    for key, value in apex_layers.items():
        st.session_state.setdefault(key, value)
    for key, value in traffic_impact_layers.items():
        st.session_state.setdefault(key, value)
    for key, value in aashtoware_layers.items():
        st.session_state.setdefault(key, value)
    for key, value in geography_intersects.items():
        st.session_state.setdefault(key, value)
    for key, value in assigness_layers.items():
        st.session_state.setdefault(key, value)

    # -------------------------------------------------------------------------
    # AGOL CREDENTIALS
    # -------------------------------------------------------------------------
    # Credential sourcing precedence:
    #   1) .env file (python-dotenv)
    #   2) Streamlit secrets
    # The resolved credentials are then stored into session_state.
    #
    # NOTE: Variables env_user/env_pass are present but unused; preserved as-is.
    # -------------------------------------------------------------------------
    # 1. Check if a .env file exists
    env_file_exists = os.path.exists(".env")
    env_user = None
    env_pass = None

    if env_file_exists:
        from dotenv import load_dotenv
        load_dotenv()
        agol_username = os.getenv("AGOL_USERNAME")
        agol_password = os.getenv("AGOL_PASSWORD")
    else:
        # 2. Check secrets (may or may not exist)
        agol_username = st.secrets.get("AGOL_USERNAME") if hasattr(st, "secrets") else None
        agol_password = st.secrets.get("AGOL_PASSWORD") if hasattr(st, "secrets") else None

    # 4. Store in session_state safely
    st.session_state.setdefault("AGOL_USERNAME", agol_username)
    st.session_state.setdefault("AGOL_PASSWORD", agol_password)

    # ======================================================
    # NEW: Central dictionary for AWP mappings
    # ======================================================
    # AWP_FIELDS provides a single place to map UI/session keys to the
    # AASHTOWare-provided session keys.
    AWP_FIELDS = {
        'awp_guid' : "Id",
        "awp_proj_name": "ProjectName",
        "proj_name": "awp_PublicProjectName",
        "phase": "awp_ProjectPhase",
        "iris": "IRIS",
        "stip": "STIP_ID",
        "fed_proj_num": "FederalProjectNumber",
        "fund_type": "FundingType",
        "proj_prac": "ProjectPractice",
        "anticipated_start": "StartDate",
        "anticipated_end": "EndDate",
        "award_date": "AwardDate",
        "award_fiscal_year": "AwardFederalFiscalYear",
        "contractor": "AwardedContractor",
        "awarded_amount": "AwardedContractAmount",
        "current_contract_amount": "CurrentContractAmount",
        "amount_paid_to_date": "AmountPaidToDate",
        "tenadd": "TentativeAdvertisingDate",
        "awp_proj_desc": "AASTOWARE_Description",
        "contact_name":"ContactName",
        "contact_email":"ContactEmail",
        "contact_phone":"ContactPhone",
        "proj_desc": "PublicDescription",
        "proj_web": "ProjectURL",
    }

   # Build transformed dict in session_state
    st.session_state["awp_fields"] = {}

    for key, value in AWP_FIELDS.items():
        if not value:
            # keep blanks as blank
            st.session_state["awp_fields"][key] = ""
        else:
            v = value.strip().lower()
            if not v.startswith("awp_"):
                v = "awp_" + v
            st.session_state["awp_fields"][key] = v


    
    
# -----------------------------------------------------------------------------
# RUN AUTOMATICALLY WHEN IMPORTED
# -----------------------------------------------------------------------------
# Streamlit reruns scripts frequently; importing this module should ensure
# session_state is always seeded with required defaults.
# -----------------------------------------------------------------------------
init_session_state()
