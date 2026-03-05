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
version = st.session_state.get("version")

# ---- Sidebar: Change task button ----
with st.sidebar:
    if st.button("← Change task"):
        st.session_state["version"] = None
        st.session_state["step"] = 1
        st.session_state["upload_clicked"] = False
        st.rerun()

# ---- Home chooser (only if no version chosen) ----
if version not in ("loader", "manager"):
    with st.container():
        st.title("📝 APEX MANAGER APPLICATION")
        st.markdown(
            "Use this application to **load a new project** into APEX or **manage an existing project**. "
            "Choose one of the options below to get started."
        )
        st.divider()
        st.markdown("##### CHOOSE A TASK\n", unsafe_allow_html=True)

        # ---- Stacked (vertical) large buttons ----
        # Wrap each in a small div to add a spacing class between them
        with st.container():
            # First button (LOADER)
            st.markdown('<div class="stacked-btn">', unsafe_allow_html=True)
            if st.button("📦 **LOAD A NEW PROJECT TO APEX**", use_container_width=True, key="btn_loader"):
                st.session_state["version"] = "loader"
                st.rerun()
            
            # Second button (MANAGER)
            st.markdown('<div class="stacked-btn">', unsafe_allow_html=True)
            if st.button("🛠️ **MANAGE AN EXISTING PROJECT IN APEX**", use_container_width=True, key="btn_manager"):
                st.session_state["version"] = "manager"
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

else:
    # ---- Route to selected app ----
    if version == "loader":
        from applications.loader_app import run_loader_app
        run_loader_app()
    elif version == "manager":
         from applications.manager_app import run_manager_app
         run_manager_app()