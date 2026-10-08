"""
Authentication View Component:
Provides clean tabbed views for Login and Registration with input validation.
"""

import streamlit as st
from frontend.utils.api_client import APIClient, APIError


def render_auth_view() -> None:
    _, col_center, _ = st.columns([1, 2, 1])

    with col_center:
        st.markdown(
            """
            <div style="text-align: center; margin-bottom: 2rem;">
                <h1 style="margin-bottom: 0.2rem;">⚡ Productivity Agent</h1>
                <p style="color: #64748b;">Autonomous Task Management via Model Context Protocol</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        tab_login, tab_register = st.tabs(["Sign In", "Create Account"])

        with tab_login:
            with st.form("login_form", clear_on_submit=False):
                email = st.text_input("Email Address", placeholder="name@university.edu").strip()
                password = st.text_input("Password", type="password")
                submitted = st.form_submit_button("Sign In", use_container_width=True)

                if submitted:
                    if not email or not password:
                        st.error("Please provide both email and password.")
                    else:
                        try:
                            with st.spinner("Authenticating..."):
                                token_data = APIClient.login(email=email, password=password)
                                st.session_state["auth_token"] = token_data["access_token"]
                                
                                # Hydrate user profile
                                user_profile = APIClient.get_me()
                                st.session_state["user"] = user_profile
                                st.success("Signed in successfully!")
                                st.rerun()
                        except APIError as e:
                            st.error(f"Sign in failed: {e.message}")

        with tab_register:
            with st.form("register_form", clear_on_submit=False):
                name = st.text_input("Full Name", placeholder="Alex Mercer").strip()
                reg_email = st.text_input("Email", placeholder="alex@university.edu").strip()
                reg_password = st.text_input("Password (min. 8 characters)", type="password")
                reg_timezone = st.selectbox(
                    "Timezone",
                    options=["UTC", "America/New_York", "Europe/London", "Asia/Kolkata", "Asia/Tokyo"],
                    index=0,
                )
                reg_submitted = st.form_submit_button("Register", use_container_width=True)

                if reg_submitted:
                    if len(name) < 2:
                        st.error("Name must be at least 2 characters long.")
                    elif "@" not in reg_email or "." not in reg_email:
                        st.error("Please enter a valid email address.")
                    elif len(reg_password) < 8:
                        st.error("Password must be at least 8 characters long.")
                    else:
                        try:
                            with st.spinner("Creating account..."):
                                APIClient.register(
                                    name=name,
                                    email=reg_email,
                                    password=reg_password,
                                    timezone=reg_timezone,
                                )
                                # Auto login on successful registration
                                token_data = APIClient.login(email=reg_email, password=reg_password)
                                st.session_state["auth_token"] = token_data["access_token"]
                                st.session_state["user"] = APIClient.get_me()
                                st.success("Account created successfully!")
                                st.rerun()
                        except APIError as e:
                            st.error(f"Registration failed: {e.message}")