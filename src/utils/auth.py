import streamlit as st
import os

def check_password():
    """Returns `True` if the user had the correct password."""

    # Check if authentication is disabled (useful for local development if needed)
    if os.getenv("DISABLE_AUTH", "false").lower() == "true":
        return True

    def password_entered():
        """Checks whether a password entered by the user is correct."""
        expected_password = None
        
        # Try to get password from Streamlit secrets
        if hasattr(st, "secrets"):
            expected_password = st.secrets.get("APP_PASSWORD")
            # Fallback: Check if they accidentally put it under [database.github]
            if not expected_password and "database" in st.secrets:
                db_secrets = st.secrets["database"]
                if "github" in db_secrets:
                    expected_password = db_secrets["github"].get("APP_PASSWORD")
                    
        # Fallback to env variable
        if not expected_password:
            expected_password = os.getenv("APP_PASSWORD")

        if not expected_password:
            # If no password is set anywhere, show an error.
            st.error("Authentication is not configured. Please set APP_PASSWORD in Streamlit Secrets at the very top of the box.")
            return

        if st.session_state["password"] == expected_password:
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # Don't keep password in session state
        else:
            st.session_state["password_correct"] = False

    if st.session_state.get("password_correct", False):
        return True

    # Show input for password if not authenticated
    st.markdown("### 🔒 Login Required")
    st.text_input(
        "Please enter your password", type="password", on_change=password_entered, key="password"
    )
    
    if "password_correct" in st.session_state:
        st.error("😕 Password incorrect")
    
    return False
