"""
Chat View Component:
Renders conversation threads, MCP tool introspection telemetry, and user input.
"""

from typing import Any
import streamlit as st
from frontend.utils.api_client import APIClient, APIError


def _render_tool_telemetry(tool_records: list[dict[str, Any]]) -> None:
    """Renders formatted expanders for executed MCP tools."""
    if not tool_records:
        return

    with st.expander(f"🛠️ MCP Tools Executed ({len(tool_records)})", expanded=False):
        for idx, record in enumerate(tool_records, start=1):
            tool_name = record.get("tool_name", "unknown_tool")
            args = record.get("tool_args", {})
            output = record.get("output", "")
            ts = record.get("timestamp", "")

            st.markdown(f"**Step {idx}: `{tool_name}`** *({ts[:19] if ts else 'exec'})*")
            col_in, col_out = st.columns(2)
            with col_in:
                st.caption("Parameters")
                st.json(args)
            with col_out:
                st.caption("Database / Server Response")
                if isinstance(output, (dict, list)):
                    st.json(output)
                else:
                    st.code(str(output), language="json" if "{" in str(output) else "text")
            st.divider()


def render_chat_view(thread_id: str) -> None:
    # Ensure thread message container exists in state
    if "messages_by_thread" not in st.session_state:
        st.session_state["messages_by_thread"] = {}

    if thread_id not in st.session_state["messages_by_thread"]:
        st.session_state["messages_by_thread"][thread_id] = [
            {
                "role": "assistant",
                "content": "Hello! I am your personal productivity assistant. How can I help schedule or organize your tasks today?",
                "tools": [],
            }
        ]

    thread_messages = st.session_state["messages_by_thread"][thread_id]

    # Render Historical Messages
    chat_container = st.container()
    with chat_container:
        for msg in thread_messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                if msg.get("tools"):
                    _render_tool_telemetry(msg["tools"])

    # Chat Input Box
    if user_prompt := st.chat_input("Ask your agent to create, list, or update tasks..."):
        # Append User Message locally
        thread_messages.append({
            "role": "user",
            "content": user_prompt,
            "tools": [],
        })
        with chat_container:
            with st.chat_message("user"):
                st.markdown(user_prompt)

        # Call Backend Agent Loop
        with chat_container:
            with st.chat_message("assistant"):
                status_placeholder = st.status("Agent reasoning & inspecting MCP tools...", expanded=True)
                try:
                    res = APIClient.send_message(thread_id=thread_id, message=user_prompt)
                    status_placeholder.update(label="Complete", state="complete", expanded=False)

                    assistant_text = res.get("response", "")
                    tool_calls = res.get("tool_calls", [])

                    st.markdown(assistant_text)
                    if tool_calls:
                        _render_tool_telemetry(tool_calls)

                    # Persist response in session history
                    thread_messages.append({
                        "role": "assistant",
                        "content": assistant_text,
                        "tools": tool_calls,
                    })

                    # If tool operations modified state, trigger task panel refresh
                    st.session_state["refresh_tasks"] = True
                    st.rerun()

                except APIError as e:
                    status_placeholder.update(label="Failed", state="error")
                    st.error(f"Error processing message: {e.message}")