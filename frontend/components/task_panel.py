"""
Task Panel Component:
Displays filtered task views (Today, Upcoming, Completed) with quick action controls.
"""

from datetime import datetime, timezone
import streamlit as st
from frontend.utils.api_client import APIClient, APIError


def _render_task_card(task: dict) -> None:
    task_id = task["id"]
    title = task["title"]
    priority = task.get("priority", "medium")
    due_at = task.get("due_at")
    status = task.get("status")

    badge_colors = {
        "high": "🔴",
        "medium": "🟡",
        "low": "🔵",
    }
    badge = badge_colors.get(priority, "⚪")

    due_str = "No deadline"
    if due_at:
        try:
            dt = datetime.fromisoformat(due_at.replace("Z", "+00:00"))
            due_str = dt.strftime("%b %d, %H:%M")
        except ValueError:
            due_str = due_at[:16]

    with st.container(border=True):
        col_text, col_action = st.columns([4, 1])

        with col_text:
            st.markdown(f"**{title}**")
            st.caption(f"{badge} {priority.capitalize()} · 🕒 {due_str}")

        with col_action:
            if status != "completed":
                if st.button("✓", key=f"done_{task_id}", help="Mark Complete"):
                    try:
                        APIClient.complete_task(task_id)
                        st.toast(f"Completed '{title}'!")
                        st.session_state["refresh_tasks"] = True
                        st.rerun()
                    except APIError as e:
                        st.error(e.message)
            else:
                st.caption("✅ Done")


def render_task_panel() -> None:
    st.subheader("📋 Task Workspace")

    # Force re-fetching if requested by chat mutations
    if st.session_state.get("refresh_tasks", False) or "cached_tasks" not in st.session_state:
        try:
            st.session_state["cached_tasks"] = APIClient.list_tasks()
            st.session_state["refresh_tasks"] = False
        except APIError:
            st.session_state["cached_tasks"] = []

    tasks = st.session_state.get("cached_tasks", [])

    tab_today, tab_upcoming, tab_done = st.tabs(["Today", "Upcoming", "Completed"])

    now = datetime.now(timezone.utc)

    today_tasks = []
    upcoming_tasks = []
    completed_tasks = []

    for t in tasks:
        if t.get("status") == "completed":
            completed_tasks.append(t)
            continue

        due_at = t.get("due_at")
        if due_at:
            try:
                due_dt = datetime.fromisoformat(due_at.replace("Z", "+00:00"))
                if due_dt.date() <= now.date():
                    today_tasks.append(t)
                else:
                    upcoming_tasks.append(t)
            except ValueError:
                upcoming_tasks.append(t)
        else:
            today_tasks.append(t)

    with tab_today:
        if not today_tasks:
            st.info("No tasks due today.")
        for task in today_tasks:
            _render_task_card(task)

    with tab_upcoming:
        if not upcoming_tasks:
            st.info("No upcoming deadlines.")
        for task in upcoming_tasks:
            _render_task_card(task)

    with tab_done:
        if not completed_tasks:
            st.caption("No completed tasks yet.")
        for task in completed_tasks:
            _render_task_card(task)

    if st.button("🔄 Refresh List", use_container_width=True):
        st.session_state["refresh_tasks"] = True
        st.rerun()