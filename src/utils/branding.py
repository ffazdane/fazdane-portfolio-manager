import streamlit as st
import os
import base64

def get_base64_of_bin_file(bin_file):
    with open(bin_file, 'rb') as f:
        data = f.read()
    return base64.b64encode(data).decode()

def setup_branding():
    """
    Apply FazDane Analytics branding across the application.
    Must be called after st.set_page_config() on every page.
    """
    # Force dark theme globally — overrides Streamlit Cloud's default light mode
    st.markdown("""
    <style>
        /* ── Core backgrounds ── */
        html, body, [data-testid="stAppViewContainer"], 
        [data-testid="stApp"] {
            background-color: #0E1117 !important;
            color: #FAFAFA !important;
        }
        /* Sidebar */
        [data-testid="stSidebar"], [data-testid="stSidebarContent"] {
            background-color: #1A1F2E !important;
        }
        /* Header / top bar */
        [data-testid="stHeader"] {
            background-color: #0E1117 !important;
        }
        /* Main content block */
        .main .block-container {
            background-color: #0E1117 !important;
        }
        /* Inputs, selects, text areas */
        [data-testid="stTextInput"] input,
        [data-testid="stSelectbox"] div[data-baseweb],
        [data-testid="stTextArea"] textarea,
        [data-testid="stNumberInput"] input {
            background-color: #1A1F2E !important;
            color: #FAFAFA !important;
            border-color: rgba(0, 212, 170, 0.3) !important;
        }
        /* Dropdown menus */
        [data-baseweb="popover"], [data-baseweb="menu"] {
            background-color: #1A1F2E !important;
            color: #FAFAFA !important;
        }
        /* Metric labels */
        [data-testid="stMetricLabel"], [data-testid="stMetricValue"] {
            color: #FAFAFA !important;
        }
        /* Dividers */
        hr { border-color: rgba(255,255,255,0.1) !important; }
        /* Markdown text */
        p, h1, h2, h3, h4, h5, h6, li { color: #FAFAFA !important; }
    </style>
    """, unsafe_allow_html=True)

    logo_path = os.path.join(os.path.dirname(__file__), "..", "..", "logo.png")
    
    logo_html = ""
    if os.path.exists(logo_path):
        b64 = get_base64_of_bin_file(logo_path)
        # Create a professional, horizontal header directly above the app
        logo_html = f'''
        <div style="display: flex; align-items: center; justify-content: flex-start; padding: 10px 0px 15px 0px; margin-bottom: 25px; border-bottom: 1px solid rgba(0, 212, 170, 0.3);">
            <img src="data:image/png;base64,{b64}" style="height: 65px; border-radius: 4px; box-shadow: 0px 2px 8px rgba(0,0,0,0.4); background-color: white; padding: 2px;">
            <div style="margin-left: 25px;">
                <h1 style="margin: 0; padding: 0; font-size: 30px; font-weight: 800; font-family: 'Inter', sans-serif; letter-spacing: 1px; line-height: 1;">
                    FAZDANE <span style="color:#00D4AA">ANALYTICS</span>
                </h1>
                <p style="margin: 0; padding: 0; font-size: 13px; color: #999; text-transform: uppercase; letter-spacing: 2px; margin-top: 4px;">
                    Portfolio Manager
                </p>
            </div>
        </div>
        '''
        
    if logo_html:
        st.markdown(logo_html, unsafe_allow_html=True)
    else:
        # Fallback text if logo missing
        st.markdown('''
        <div style="margin-bottom: 25px; border-bottom: 1px solid rgba(0, 212, 170, 0.3); padding-bottom: 15px;">
            <h1 style="margin: 0; padding: 0; font-size: 30px; font-weight: 800; color: #FFF;">
                FAZDANE <span style="color:#00D4AA">ANALYTICS</span>
            </h1>
        </div>''', unsafe_allow_html=True)

