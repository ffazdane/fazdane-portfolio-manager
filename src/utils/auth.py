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
        
        # Try to get password from Streamlit secrets by searching everywhere
        if hasattr(st, "secrets"):
            def find_password(d):
                if "APP_PASSWORD" in d:
                    return d["APP_PASSWORD"]
                for k, v in d.items():
                    if isinstance(v, dict) or hasattr(v, "items"):
                        res = find_password(v)
                        if res: return res
                return None
            expected_password = find_password(st.secrets)
                    
        # Fallback to env variable
        if not expected_password:
            expected_password = os.getenv("APP_PASSWORD")

        if not expected_password:
            # If no password is set anywhere, show an error.
            keys_found = list(st.secrets.keys()) if hasattr(st, "secrets") else "None"
            st.error(f"Authentication is not configured. Keys found in secrets: {keys_found}. Please set APP_PASSWORD at the very top of the box.")
            return

        if st.session_state["password"] == expected_password:
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # Don't keep password in session state
        else:
            st.session_state["password_correct"] = False

    if st.session_state.get("password_correct", False):
        return True

    # Show input for password if not authenticated
    st.markdown("""
        <style>
            /* Hide the sidebar when logged out */
            [data-testid="collapsedControl"] {display: none;}
            [data-testid="stSidebar"] {display: none;}
            
            /* Hide the top header */
            header {visibility: hidden;}
            
            .brand-title-container {
                text-align: center;
                margin-top: -5px;
                margin-bottom: 5px;
                line-height: 1.1;
            }
            .brand-title-fazdane {
                font-size: 36px;
                font-weight: 800;
                color: #FFFFFF;
            }
            .brand-title-analytics {
                font-size: 36px;
                font-weight: 800;
                color: #00D4AA;
            }
            .brand-subtitle {
                color: #8da0b3;
                font-size: 14px;
                font-weight: 600;
                letter-spacing: 4px;
                text-transform: uppercase;
                text-align: center;
                margin-bottom: 25px;
            }
            
            /* Premium container styling for the login box */
            div[data-testid="stContainer"] {
                background: linear-gradient(135deg, #1A1F2E 0%, #252B3B 100%);
                padding: 30px;
                border-radius: 16px;
                border: 1px solid rgba(0, 212, 170, 0.2);
                box-shadow: 0 10px 40px rgba(0, 0, 0, 0.6);
            }
            
            /* Input styling */
            .stTextInput > div > div > input {
                background-color: #0E1117;
                border: 1px solid rgba(0, 212, 170, 0.3);
                border-radius: 8px;
                padding: 12px;
            }
            .stTextInput > div > div > input:focus {
                border-color: #00D4AA;
                box-shadow: 0 0 10px rgba(0, 212, 170, 0.2);
            }
        </style>
    """, unsafe_allow_html=True)

    # Push down vertically to center
    st.write("<br><br><br><br>", unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        with st.container():
            # Logo
            logo_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logo.png")
            if os.path.exists(logo_path):
                img_col1, img_col2, img_col3 = st.columns([1, 1.5, 1])
                with img_col2:
                    st.image(logo_path, use_container_width=True)
            
            st.markdown('''
                <div class="brand-title-container">
                    <span class="brand-title-fazdane">FazDane</span>
                    <span class="brand-title-analytics"> Analytics</span>
                </div>
            ''', unsafe_allow_html=True)
            st.markdown('<div class="brand-subtitle">PORTFOLIO<br>MANAGER</div>', unsafe_allow_html=True)
            
            st.markdown("<h4 style='text-align: center; color: #E0E0E0; font-weight: 400; margin-bottom: 20px;'>🔒 Secure Login</h4>", unsafe_allow_html=True)
            
            st.text_input(
                "Password", 
                type="password", 
                on_change=password_entered, 
                key="password",
                placeholder="Enter your password...",
                label_visibility="collapsed" # Hide the label to look cleaner
            )
            
            if "password_correct" in st.session_state and not st.session_state["password_correct"]:
                st.error("😕 Password incorrect")
    
    return False
