def run_manager_app():
    import streamlit as st
    import folium

    from util.map_util import add_small_geocoder

    from tabs.traffic_impacts import add_traffic_impact


    # Base overview map
    m = folium.Map(location=[64.2008, -149.4937], zoom_start=4)
    add_small_geocoder(m)

    # Set Page Config
    st.set_page_config(
        page_title="APEX Manager Application",
        page_icon="🛠️",
        layout="centered",
        initial_sidebar_state="collapsed"  # 👈 auto-collapse
    )

    # Header and progress
    st.title("MANAGE APEX PROJECTS 🛠️")
    st.markdown("##### MANAGE AND UPDATE AN EXISTING APEX PROJECT")
    

