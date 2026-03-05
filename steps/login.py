import time
from typing import Optional, Tuple, List
import requests
import streamlit as st

# Use your existing token function
from agol.agol_util import get_agol_token


def _to_sharing_base(portal_base_url: str) -> str:
    """
    Normalizes a portal base URL to its /sharing/rest base.
      - https://akdot.maps.arcgis.com              -> https://akdot.maps.arcgis.com/sharing/rest
      - https://gis.myorg.com/portal               -> https://gis.myorg.com/portal/sharing/rest
      - https://akdot.maps.arcgis.com/sharing/rest -> unchanged
    """
    url = portal_base_url.rstrip("/")
    if url.endswith("/sharing/rest"):
        return url
    if url.endswith("/portal"):
        return f"{url}/sharing/rest"
    return f"{url}/sharing/rest"


def _fetch_user_groups(
    sharing_base: str,
    username: str,
    token: str
) -> Tuple[Optional[List[str]], Optional[str]]:
    """
    Returns (list_of_group_ids, error_message_if_any).
    """
    endpoint = f"{sharing_base}/community/users/{username}"
    params = {"f": "json", "token": token}
    try:
        r = requests.get(endpoint, params=params, timeout=20)
        r.raise_for_status()
        payload = r.json()
        if "error" in payload:
            return None, payload["error"].get("message", "User lookup error")
        groups = payload.get("groups", []) or []
        group_ids = [g.get("id") for g in groups if g.get("id")]
        return group_ids, None
    except Exception as ex:
        return None, str(ex)


def _token_is_valid(expires_epoch_ms: Optional[int]) -> bool:
    """
    Returns True if a token has not yet expired (with a small safety buffer).
    Your get_agol_token() doesn't return expiry; treat None as 'unknown/assume OK'
    and depend on API checks to fail if it’s actually invalid.
    """
    if not expires_epoch_ms:
        return True
    now_ms = int(time.time() * 1000) + 10_000
    return now_ms < int(expires_epoch_ms)


def login_agol(
    portal_base_url: str = "https://akdot.maps.arcgis.com",
    title: str = "Sign in to ArcGIS Online",
) -> bool:
    """
    Login/authorization gate for AGOL.

    Requirements:
      - st.session_state['apex_group_id'] must be set by init_session (e.g., "c77df3ecf35b4cdc9510e078a290a311")

    Flow:
      1) If a token and username already exist, verify group membership; if OK, allow through.
      2) Otherwise, render a login form (no re-runs while typing).
      3) On submit, save username/password, call get_agol_token(), check group membership.
      4) If authorized, store token & set AGOL_AUTHORIZED=True and rerun.

    Session keys set on success:
      - AGOL_USERNAME
      - AGOL_PASSWORD
      - AGOL_TOKEN
      - AGOL_TOKEN_EXPIRES (optional if you add it later)
      - AGOL_AUTHORIZED = True

    Returns True if authorized; otherwise renders the gate and returns False.
    """
    sharing_base = _to_sharing_base(portal_base_url)

    # Required group from session (set by init_session)
    required_gid = st.session_state.get("apex_group_id")
    if not required_gid:
        st.error("Configuration error: required group id (`apex_group_id`) not set in session.")
        return False

    # Fast-path: already signed in?
    saved_user = st.session_state.get("AGOL_USERNAME")
    token = st.session_state.get("AGOL_TOKEN")
    expires = st.session_state.get("AGOL_TOKEN_EXPIRES")

    if saved_user and token and _token_is_valid(expires):
        user_groups, err = _fetch_user_groups(sharing_base, saved_user, token)
        if user_groups is not None and required_gid in user_groups:
            st.session_state["AGOL_AUTHORIZED"] = True
            with st.container(border=True):
                c1, c2 = st.columns([1, 1])
                c1.success(f"Signed in as **{saved_user}**")
                if c2.button("Sign out", type="secondary"):
                    for k in [
                        "AGOL_USERNAME", "AGOL_PASSWORD", "AGOL_TOKEN",
                        "AGOL_TOKEN_EXPIRES", "AGOL_AUTHORIZED"
                    ]:
                        st.session_state.pop(k, None)
                    st.rerun()
            return True

        # If token invalid or group check failed, clear token-related flags
        for k in ["AGOL_TOKEN", "AGOL_TOKEN_EXPIRES", "AGOL_AUTHORIZED"]:
            st.session_state.pop(k, None)

    # --- Login Gate UI ---
    st.subheader(title)
    st.caption(
        "Access restricted: your account must be a member of the required AKDOT group."
    )

    with st.form("agol_login_form", clear_on_submit=False, border=True):
        username = st.text_input(
            "AGOL Username",
            value=st.session_state.get("AGOL_USERNAME", ""),
            autocomplete="username",
        )
        password = st.text_input(
            "AGOL Password",
            type="password",
            value=st.session_state.get("AGOL_PASSWORD", ""),
            autocomplete="current-password",
        )
        submitted = st.form_submit_button("Sign in")

    if submitted:
        if not username or not password:
            st.error("Please enter both username and password.")
            return False

        # Save creds first (your get_agol_token() expects them in session)
        st.session_state["AGOL_USERNAME"] = username
        st.session_state["AGOL_PASSWORD"] = password

        try:
            token = get_agol_token()
        except Exception as ex:
            # Clear partial state so a failed attempt doesn't linger
            for k in ["AGOL_TOKEN", "AGOL_TOKEN_EXPIRES", "AGOL_AUTHORIZED"]:
                st.session_state.pop(k, None)
            st.error(f"Could not generate token: {ex}")
            return False

        st.session_state["AGOL_TOKEN"] = token
        # If you later augment get_agol_token() to return expiry, set AGOL_TOKEN_EXPIRES here.

        # Verify membership in the required group
        user_groups, err = _fetch_user_groups(sharing_base, username, token)
        if err:
            st.error(f"Authorization check failed: {err}")
            return False

        if required_gid not in (user_groups or []):
            st.error("Access denied: your account is not a member of the required group.")
            return False

        # Success
        st.session_state["AGOL_AUTHORIZED"] = True
        st.success("Signed in successfully.")
        st.rerun()

    st.info("Please sign in to continue.")
    return False