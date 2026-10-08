"""
Streamlit Web UI Entrypoint:
Orchestrates authentication checks, sidebar conversation switcher, and page layout.
"""

import streamlit as st

# Must be the very first Streamlit command
st.set_page_config(
    page_title="MCP Productivity Agent",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

from frontend.components.auth_view import render_auth_view
from frontend.components.chat import render_chat_view
from frontend.components.task_panel import render_task_panel
from frontend.utils.api_client import APIClient, APIError


def _init_session() -> None:
    if "auth_token" not in st.session_state:
        st.session_state["auth_token"] = None
    if "user" not in st.session_state:
        st.session_state["user"] = None
    if "active_thread_id" not in st.session_state:
        st.session_state["active_thread_id"] = None
    if "conversations" not in st.session_state:
        st.session_state["conversations"] = []


def render_sidebar() -> None:
    with st.sidebar:
        user = st.session_state.get("user")
        if user:
            st.markdown(f"### 👤 {user.get('name', 'User')}")
            st.caption(f"Connected: `{user.get('email', '')}`")
            st.divider()

        # New Chat Button
        if st.button("➕ New Chat", use_container_width=True, type="primary"):
            try:
                convo = APIClient.create_conversation("New Session")
                st.session_state["active_thread_id"] = convo["thread_id"]
                st.session_state["refresh_convos"] = True
                st.rerun()
            except APIError as e:
                st.error(e.message)

        st.markdown("#### Recent Conversations")

        # Refresh or fetch conversations
        if st.session_state.get("refresh_convos", True):
            try:
                st.session_state["conversations"] = APIClient.list_conversations()
                st.session_state["refresh_convos"] = False
            except APIError:
                st.session_state["conversations"] = []

        convos = st.session_state.get("conversations", [])

        # Default to first conversation if active one is unset
        if convos and not st.session_state["active_thread_id"]:
            st.session_state["active_thread_id"] = convos[0]["thread_id"]

        for convo in convos:
            tid = convo["thread_id"]
            title = convo.get("title") or "Conversation"
            is_active = tid == st.session_state.get("active_thread_id")
            
            button_label = f"💬 {title}" if not is_active else f"👉 {title}"
            if st.button(
                button_label,
                key=f"thread_btn_{tid}",
                use_container_width=True,
                disabled=is_active,
            ):
                st.session_state["active_thread_id"] = tid
                st.rerun()

        st.divider()
        if st.button("🚪 Logout", use_container_width=True):
            st.session_state["auth_token"] = None
            st.session_state["user"] = None
            st.session_state["active_thread_id"] = None
            st.session_state["conversations"] = []
            st.rerun()


def main() -> None:
    _init_session()

    # Route: Unauthenticated view
    if not st.session_state["auth_token"]:
        render_auth_view()
        return

    # Route: Authenticated Application Shell
    render_sidebar()

    active_thread = st.session_state.get("active_thread_id")
    if not active_thread:
        # Create an initial conversation thread automatically if none exists
        try:
            convo = APIClient.create_conversation("Initial Session")
            st.session_state["active_thread_id"] = convo["thread_id"]
            active_thread = convo["thread_id"]
        except APIError as e:
            st.error(f"Failed to bootstrap chat: {e.message}")
            return

    # Two-Column Dashboard Layout
    col_chat, col_tasks = st.columns([5, 3], gap="medium")

    with col_chat:
        render_chat_view(thread_id=active_thread)

    with col_tasks:
        render_task_panel()


if __name__ == "__main__":
    main()