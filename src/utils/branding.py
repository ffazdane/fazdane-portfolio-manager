import streamlit as st
import os
import base64

def get_base64_of_bin_file(bin_file):
    with open(bin_file, 'rb') as f:
        data = f.read()
    return base64.b64encode(data).decode()


def _inject_sidebar_brand(logo_path: str):
    """
    Injects a fully custom branded block at the very top of the sidebar.
    Hides Streamlit's native logo slot and replaces it with logo.png +
    'FAZDANE ANALYTICS / PORTFOLIO MANAGER' matching the design mockup.
    """
    # Encode logo to base64 so it works both locally and on Streamlit Cloud
    if os.path.exists(logo_path):
        b64 = get_base64_of_bin_file(logo_path)
        logo_img = f'<img src="data:image/png;base64,{b64}" style="height:56px; border-radius:6px; background:#fff; padding:3px 5px; box-shadow:0 2px 8px rgba(0,0,0,0.45);">'
    else:
        # Fallback: chart emoji when logo file is missing
        logo_img = '<div style="font-size:40px; line-height:1;">📊</div>'

    # Inject CSS that:
    #  1. Hides Streamlit's native logo / header area in the sidebar
    #  2. Removes default top-padding so our block sits flush at the top
    st.markdown("""
    <style>
        /* Hide native Streamlit sidebar header (logo slot + app name) */
        [data-testid="stSidebarHeader"] { display: none !important; }

        /* Remove extra top gap Streamlit leaves for the logo slot */
        section[data-testid="stSidebar"] > div:first-child {
            padding-top: 0 !important;
        }

        /* Our brand block */
        .faz-sidebar-brand {
            display: flex;
            align-items: center;
            gap: 14px;
            padding: 18px 16px 14px 16px;
            border-bottom: 1px solid rgba(0, 212, 170, 0.25);
            margin-bottom: 4px;
        }
        .faz-brand-text h2 {
            margin: 0; padding: 0;
            font-size: 18px;
            font-weight: 800;
            font-family: 'Inter', 'Segoe UI', sans-serif;
            letter-spacing: 0.5px;
            line-height: 1.1;
            color: #FAFAFA !important;
        }
        .faz-brand-text h2 span { color: #00D4AA; }
        .faz-brand-text p {
            margin: 2px 0 0 0; padding: 0;
            font-size: 10px;
            color: #888;
            text-transform: uppercase;
            letter-spacing: 2.5px;
            font-family: 'Inter', 'Segoe UI', sans-serif;
        }
    </style>
    """, unsafe_allow_html=True)

    # Render the brand block inside the sidebar
    st.sidebar.markdown(f"""
    <div class="faz-sidebar-brand">
        {logo_img}
        <div class="faz-brand-text">
            <h2>FazDane <span>Analytics</span></h2>
            <p>Portfolio Manager</p>
        </div>
    </div>
    """, unsafe_allow_html=True)


def setup_branding():
    """
    Apply FazDane Analytics branding across the application.
    Must be called after st.set_page_config() on every page.
    """
    # ── Force dark theme globally — overrides Streamlit Cloud's default light mode ──
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

    # ── Sidebar brand block ──
    logo_path = os.path.join(os.path.dirname(__file__), "..", "..", "logo.png")
    _inject_sidebar_brand(logo_path)

    # ── Main page header (logo + title strip) ──
    logo_html = ""
    if os.path.exists(logo_path):
        b64 = get_base64_of_bin_file(logo_path)
        logo_html = f'''
        <div style="display:flex; align-items:center; justify-content:flex-start;
                    padding:10px 0 15px 0; margin-bottom:22px;
                    border-bottom:1px solid rgba(0,212,170,0.3);">
            <img src="data:image/png;base64,{b64}"
                 style="height:72px; border-radius:6px;
                        box-shadow:0 2px 10px rgba(0,0,0,0.5);
                        background:#fff; padding:3px 5px;">
            <div style="margin-left:22px;">
                <h1 style="margin:0; padding:0; font-size:32px; font-weight:900;
                           font-family:'Inter',sans-serif; letter-spacing:1px;
                           line-height:1; color:#FAFAFA;">
                    FAZDANE <span style="color:#00D4AA;">ANALYTICS</span>
                </h1>
                <p style="margin:4px 0 0 0; padding:0; font-size:12px;
                          color:#888; text-transform:uppercase; letter-spacing:2.5px;">
                    Portfolio Manager
                </p>
            </div>
        </div>
        '''

    if logo_html:
        st.markdown(logo_html, unsafe_allow_html=True)
    else:
        st.markdown('''
        <div style="margin-bottom:22px; border-bottom:1px solid rgba(0,212,170,0.3); padding-bottom:14px;">
            <h1 style="margin:0; padding:0; font-size:32px; font-weight:900; color:#FFF;">
                FAZDANE <span style="color:#00D4AA;">ANALYTICS</span>
            </h1>
            <p style="margin:4px 0 0; font-size:12px; color:#888;
                      text-transform:uppercase; letter-spacing:2.5px;">Portfolio Manager</p>
        </div>''', unsafe_allow_html=True)
