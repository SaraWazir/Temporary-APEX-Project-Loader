import streamlit as st
import json
from util.geometry_util import (
    select_route_and_points,
)
from util.geospatial_util import create_buffers


def add_traffic_impact():
    """
    Traffic Impact Event workflow (Option B + Top Add Button)
    - Segmented control for event navigation with an inline "Add" button at the top.
    - No tabs; no auto-create after LOAD.
    - Loaded Traffic Impact Events displayed as:
         "1. Traffic Impact @ RouteName" (or A/B/C suffix for duplicates)
    - Each row has a Delete button.
    - Deleting a loaded package un-submits any matching event and removes the event tab.
    - All geometry remains canonical [lon, lat].
    """

    # ------------------------------
    # Global persistent state
    # ------------------------------
    st.session_state.setdefault("traffic_impact_answer", None)
    st.session_state.setdefault("tie_events", [])
    st.session_state.setdefault("tie_next_id", 1)
    st.session_state.setdefault("traffic_impacts_list", [])
    st.session_state.setdefault("tie_active_event_id", None)

    # ------------------------------
    # Header: Yes/No
    # ------------------------------
    st.markdown("###### WILL THIS PROJECT HAVE A TRAFFIC IMPACT EVENT?\n")
    answer = st.segmented_control(
        "Select **Yes** to create a Traffic Impact Event, **No** to continue",
        options=["Yes", "No"],
        default=st.session_state.get("traffic_impact_answer"),
    )
    st.session_state["traffic_impact_answer"] = answer

    if answer != "Yes":
        return

    st.write("")
    st.markdown("###### CREATE TRAFFIC IMPACT EVENTS\n")

    # ------------------------------
    # Build buffers from project geometry
    # ------------------------------
    geoms = st.session_state.get("project_geom")
    geom_type = (st.session_state.get("project_geom_type") or "").lower()

    if not geoms or not isinstance(geoms, (list, tuple)):
        raise RuntimeError("No project geometries available in session.")

    # If user provided a single point
    if (
        isinstance(geoms, (list, tuple))
        and len(geoms) == 2
        and all(isinstance(v, (int, float)) for v in geoms)
    ):
        geoms = [geoms]

    def _as_lonlat_pair(v):
        return [float(v[0]), float(v[1])]

    points, lines, polys = [], [], []
    for item in geoms:
        if (
            isinstance(item, (list, tuple))
            and len(item) == 2
            and all(isinstance(v, (int, float)) for v in item)
        ):
            points.append(_as_lonlat_pair(item))

        elif (
            isinstance(item, (list, tuple))
            and item
            and isinstance(item[0], (list, tuple))
        ):
            coords = [_as_lonlat_pair(p) for p in item]
            if len(coords) >= 4 and coords[0] == coords[-1]:
                polys.append(coords)
            else:
                lines.append(coords)

    st.session_state.setdefault("impact_area", None)

    buffers = []
    if geom_type == "point" and points:
        buffers += create_buffers(points, "point", 50)
    elif geom_type in ("line", "linestring") and lines:
        buffers += create_buffers(lines, "line", 50)
    elif geom_type == "polygon" and polys:
        buffers += create_buffers(polys, "polygon", 1)
    else:
        if points:
            buffers += create_buffers(points, "point", 100)
        if lines:
            buffers += create_buffers(lines, "line", 50)
        if polys:
            buffers += create_buffers(polys, "polygon", 1)

    if not buffers:
        raise RuntimeError("Buffering produced no output.")

    st.session_state["impact_area"] = buffers

    # ------------------------------
    # Create new event helper
    # ------------------------------
    def _new_event():
        eid = st.session_state["tie_next_id"]
        st.session_state["tie_next_id"] += 1
        return {
            "event_id": eid,
            "label": "New Event",
            "selected_impact_area": None,
            "selected_route_geom": None,
            "selected_route_id": None,
            "selected_route_name": None,
            "selected_start_point": None,
            "selected_end_point": None,
            "submitted": False,
            "submitted_sig": None,
            "fit_next_mount": True,
        }

    # If no events, create the first one
    if not st.session_state["tie_events"]:
        st.session_state["tie_events"] = [_new_event()]

    # Ensure active event exists
    if st.session_state["tie_active_event_id"] is None:
        st.session_state["tie_active_event_id"] = st.session_state["tie_events"][0]["event_id"]

    # ------------------------------
    # Utility functions
    # ------------------------------
    def _signature(ev):
        def _pack(x):
            return json.dumps(x) if x is not None else "null"
        return "|".join([
            _pack(ev.get("selected_impact_area")),
            _pack(ev.get("selected_route_geom")),
            _pack(ev.get("selected_start_point")),
            _pack(ev.get("selected_end_point")),
        ])

    def _find_loaded_match(candidate):
        if not candidate:
            return None, None
        rid = candidate.get("route_id")
        sp = candidate.get("start_point")
        ep = candidate.get("end_point")
        if rid is None or sp is None or ep is None:
            return None, None

        impacts = st.session_state["traffic_impacts_list"]
        for idx in range(len(impacts) - 1, -1, -1):
            pkg = impacts[idx]
            if (
                pkg.get("route_id") == rid
                and pkg.get("start_point") == sp
                and pkg.get("end_point") == ep
            ):
                return idx, pkg
        return None, None

    def _event_matches_pkg(ev, pkg):
        return (
            ev.get("selected_route_id") == pkg.get("route_id")
            and ev.get("selected_start_point") == pkg.get("start_point")
            and ev.get("selected_end_point") == pkg.get("end_point")
        )

    def _unset_submitted_if_pkg_removed(pkg):
        for ev in st.session_state["tie_events"]:
            if ev.get("submitted") and _event_matches_pkg(ev, pkg):
                ev["submitted"] = False
                ev["submitted_sig"] = None

    # >>> NEW <<< full reset helper
    def _reset_all_submissions():
        for ev in st.session_state["tie_events"]:
            ev["submitted"] = False
            ev["submitted_sig"] = None

    # NEW: Remove any event(s) that correspond to the removed package
    def _remove_events_for_pkg(pkg):
        events = st.session_state["tie_events"]
        if not events:
            return

        to_delete = [i for i, ev in enumerate(events) if _event_matches_pkg(ev, pkg)]
        if not to_delete:
            return

        active_id = st.session_state.get("tie_active_event_id")

        for i in reversed(to_delete):
            del_event = events.pop(i)
            if del_event["event_id"] == active_id:
                active_id = None

        if not events:
            new_ev = _new_event()
            st.session_state["tie_events"] = [new_ev]
            st.session_state["tie_active_event_id"] = new_ev["event_id"]
            return

        if active_id is None or not any(ev["event_id"] == active_id for ev in events):
            st.session_state["tie_active_event_id"] = events[0]["event_id"]

    # ------------------------------
    # One-time label normalization
    # ------------------------------
    for ev in st.session_state["tie_events"]:
        if isinstance(ev.get("label"), str) and ev["label"].startswith("Event "):
            ev["label"] = "New Event"

    # ------------------------------
    # Segmented Control + Inline Add Button
    # ------------------------------
    labels = []
    id_by_label = {}
    label_by_id = {}
    for ev in st.session_state["tie_events"]:
        label = f"{ev['label']}"
        labels.append(label)
        id_by_label[label] = ev["event_id"]
        label_by_id[ev["event_id"]] = label

    active_id = st.session_state["tie_active_event_id"]
    current_label = label_by_id.get(active_id, labels[0])

    left, right = st.columns([5, 2], vertical_alignment="center")
    with left:
        selected_label = st.segmented_control(
            "Select Impact Event",
            options=labels,
            default=current_label,
        )

    with right:
        if st.button("➕ Add Event", key="btn_add_event_top", use_container_width=True):
            # >>> NEW <<< Reset all submit buttons
            _reset_all_submissions()

            new_ev = _new_event()
            st.session_state["tie_events"].append(new_ev)
            st.session_state["tie_active_event_id"] = new_ev["event_id"]
            st.rerun()

    new_active_id = id_by_label[selected_label]
    if new_active_id != active_id:
        st.session_state["tie_active_event_id"] = new_active_id
        st.rerun()

    # ------------------------------
    # Render active event
    # ------------------------------
    active_ev = next(ev for ev in st.session_state["tie_events"] if ev["event_id"] == new_active_id)

    container = st.container(border=True)
    with container:
        if active_ev["selected_impact_area"] is None:
            active_ev["selected_impact_area"] = st.session_state["impact_area"]

        key_prefix = f"ev{active_ev['event_id']}_"

        if active_ev["fit_next_mount"] and active_ev["selected_impact_area"]:
            st.session_state[f"{key_prefix}fit_bounds_geom"] = active_ev["selected_impact_area"]
            st.session_state[f"{key_prefix}fit_bounds_request"] = True
            active_ev["fit_next_mount"] = False

        # Draw map + route/point workflow
        select_route_and_points(container, key_prefix=key_prefix)

        st.write("")

        # ------------------------------------------------------------
        #  Loaded Traffic Impact Events
        # ------------------------------------------------------------
        with st.expander("**TRAFFIC IMPACT EVENTS**", expanded=True):

            impacts = st.session_state["traffic_impacts_list"]

            if impacts:
                route_counts = {}
                for pkg in impacts:
                    name = pkg.get("route_name") or "—"
                    route_counts[name] = route_counts.get(name, 0) + 1

                seen = {k: 0 for k in route_counts}

                for idx, pkg in enumerate(impacts, start=1):
                    route_name = pkg.get("route_name") or "—"

                    suffix = ""
                    if route_counts[route_name] > 1:
                        suffix = f" {chr(65 + seen[route_name])}"
                        seen[route_name] += 1

                    title = f"{idx}. Traffic Impact @ {route_name}{suffix}"

                    row = st.container()
                    with row:
                        left_row, right_row = st.columns([10, 2])
                        with left_row:
                            st.markdown(f"**{title}**")
                        with right_row:
                            if st.button("🗑️ Delete", key=f"del_pkg_{idx}", use_container_width=True):
                                removed = st.session_state["traffic_impacts_list"].pop(idx - 1)

                                _unset_submitted_if_pkg_removed(removed)
                                _remove_events_for_pkg(removed)

                                # >>> NEW <<< Reset all submit buttons on delete
                                _reset_all_submissions()

                                st.rerun()

            else:
                st.caption("No loaded traffic impacts yet. Click **Load** above to add one.")

        st.write("")

        # ------------------------------------------------------------
        #  Store selection into event record
        # ------------------------------------------------------------
        ti = st.session_state.get(f"{key_prefix}traffic_impact") or {}
        active_ev["selected_route_geom"] = ti.get("route_geom")
        active_ev["selected_start_point"] = ti.get("start_point")
        active_ev["selected_end_point"] = ti.get("end_point")
        active_ev["selected_route_id"] = ti.get("route_id")
        active_ev["selected_route_name"] = ti.get("route_name")

        # ------------------------------------------------------------
        #  Submit Logic
        # ------------------------------------------------------------
        cur_sig = _signature(active_ev)

        # Auto-reset if geometry changed
        if active_ev.get("submitted") and active_ev["submitted_sig"] != cur_sig:
            active_ev["submitted"] = False
            active_ev["submitted_sig"] = None

        _, match_pkg = _find_loaded_match(ti)

        # Rename segmented label after load
        if match_pkg:
            pkg_name = match_pkg.get("name") or match_pkg.get("display_name")
            route_name = match_pkg.get("route_name") or "—"
            new_label_text = pkg_name or f"Traffic Impact @ {route_name}"

            new_label = new_label_text

            if active_ev["label"] != new_label:
                active_ev["label"] = new_label
                st.rerun()

        # ------------------------------------------------------------
        #  SUBMIT BUTTON (Placeholder-swap like footprint)
        # ------------------------------------------------------------
        submitted = bool(active_ev.get("submitted", False))
        btn_ph = st.empty()

        def _render_submit_button(is_done: bool):
            label = "SUBMIT TRAFFIC IMPACT EVENT(S) ✅" if is_done else "SUBMIT TRAFFIC IMPACT EVENT"
            suffix = "done" if is_done else "live"
            return btn_ph.button(
                label,
                use_container_width=True,
                key=f"submit_tie_{active_ev['event_id']}_{suffix}",
                disabled=is_done,
            )

        if match_pkg:
            clicked = _render_submit_button(submitted)

            if clicked and not submitted:
                # === CHANGED: Build a list of { "<Event Label>": <pkg_dict> } for ALL events ===
                named_impacts = []
                impacts = st.session_state.get("traffic_impacts_list", [])

                # Build quick index for exact matching by (route_id, start_point, end_point)
                def _key_from(ev_or_pkg):
                    return (
                        ev_or_pkg.get("selected_route_id") if "selected_route_id" in ev_or_pkg else ev_or_pkg.get("route_id"),
                        tuple(ev_or_pkg.get("selected_start_point") or []),
                        tuple(ev_or_pkg.get("selected_end_point") or []),
                    )

                # Use each event's label as the key and attach its matched loaded package
                for ev in st.session_state.get("tie_events", []):
                    rid = ev.get("selected_route_id")
                    sp = ev.get("selected_start_point")
                    ep = ev.get("selected_end_point")
                    if rid is None or sp is None or ep is None:
                        continue

                    # find matching loaded package
                    pkg_match = None
                    for pkg in impacts:
                        if (
                            pkg.get("route_id") == rid
                            and pkg.get("start_point") == sp
                            and pkg.get("end_point") == ep
                        ):
                            pkg_match = pkg
                            break

                    if not pkg_match:
                        continue

                    # Prefer the user's segmented-control label; otherwise fall back
                    label_text = ev.get("label")
                    if not label_text or not isinstance(label_text, str):
                        label_text = f"Traffic Impact @ {pkg_match.get('route_name') or '—'}"

                    named_impacts.append({label_text: pkg_match})

                # Commit the named list (does NOT mutate traffic_impacts_list)
                st.session_state["project_traffic_impacts"] = named_impacts

                # Mark active event submitted (placeholder swap)
                active_ev["submitted"] = True
                active_ev["submitted_sig"] = cur_sig
                st.session_state["traffic_impact_submitted"] = True

                btn_ph.button(
                    "SUBMIT TRAFFIC IMPACT EVENT ✅",
                    use_container_width=True,
                    key=f"submit_tie_{active_ev['event_id']}_done",
                    disabled=True,
                )

                # (Optional) Debug preview
                # st.json(st.session_state["project_traffic_impacts"])

        else:
            # Reset if package no longer matches
            active_ev["submitted"] = False
            active_ev["submitted_sig"] = None

            st.caption(
                "After selecting the route and both points, click **Load** above to add this impact."
            )