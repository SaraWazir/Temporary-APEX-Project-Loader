import streamlit as st
from init_session import init_session_state

# ---- Set page config FIRST (before any st.* calls) ----
st.set_page_config(
    page_title="APEX Manager Application",
    page_icon="🧭",
    layout="centered",
    initial_sidebar_state="collapsed"  # auto-collapse
)

# ---- Session init ----
init_session_state()

# Read the preselected app version, if any
version = st.session_state.get("version")

# ---- If a valid version is already set, immediately route and stop ----
if version in ("loader", "manager"):
    with st.sidebar:
        if st.button("← Change task"):
            st.session_state["version"] = None
            st.session_state["step"] = 1
            st.session_state["upload_clicked"] = False
            st.rerun()

    if version == "loader":
        from applications.loader_app import run_loader_app
        run_loader_app()
        st.stop()

    if version == "manager":
        from applications.manager_app import run_manager_app
        run_manager_app()
        st.stop()

# ---- Home chooser (only if no valid version chosen) ----
with st.container():
    st.title("📝 APEX MANAGER APPLICATION")
    st.markdown(
        "Use this application to **load a new project** into APEX or **manage an existing project**. "
        "Choose one of the options below to get started."
    )
    st.divider()
    st.markdown("##### CHOOSE A TASK\n", unsafe_allow_html=True)

    # Spacing block (kept as in your original)
    st.markdown('<div style="height: 4px;"></div>', unsafe_allow_html=True)

    # First button (LOADER)
    if st.button("📦 **LOAD A NEW PROJECT TO APEX**", use_container_width=True, key="btn_loader"):
        st.session_state["version"] = "loader"
        st.rerun()

    # Spacing block (kept as in your original)
    st.markdown('<div style="height: 8px;"></div>', unsafe_allow_html=True)

    # Second button (MANAGER)
    if st.button("🛠️ **MANAGE AN EXISTING PROJECT IN APEX**", use_container_width=True, key="btn_manager"):
        st.session_state["version"] = "manager"
        st.rerun()

    # Bottom spacer (kept as in your original)
    st.markdown('<div style="height: 8px;"></div>', unsafe_allow_html=True)