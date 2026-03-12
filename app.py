import streamlit as st
import pandas as pd
import numpy as np
import time
import requests
import plotly.express as px
from io import BytesIO

# --- 1. CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(
    page_title="Dashboard de Inventarios",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- 2. CONFIGURACIÓN CENTRALIZADA ---
CACHE_CONFIG = {'ttl': 3600, 'max_entries': 10, 'show_spinner': False}

URLS_DB = {
    "SORIANA": "https://github.com/gamerhackleon-afk/RTLRAGA/raw/main/SORIANA.xlsx",
    "WALMART": "https://github.com/gamerhackleon-afk/RTLRAGA/raw/main/WALMART.xlsx",
    "CHEDRAUI": "https://github.com/gamerhackleon-afk/RTLRAGA/raw/main/CHEDRAUI.xlsx"
}

RETAILER_COLORS = {
    "SORIANA": "#D32F2F",
    "WALMART": "#0071DC",
    "CHEDRAUI": "#FF6600"
}

if 'is_online' not in st.session_state:
    try:
        requests.head("https://github.com", timeout=1)
        st.session_state.is_online = True
    except:
        st.session_state.is_online = False

if 'active_retailer' not in st.session_state:
    st.session_state.active_retailer = 'WALMART'

if 'confirm_reset' not in st.session_state:
    st.session_state.confirm_reset = False

# --- 3. FUNCIONES UTILITARIAS Y CONTROL ---

def safe_mean(series):
    return series.mean() if not series.empty else 0

def apply_filters(df, filter_cols, selections):
    mask = pd.Series(True, index=df.index)
    for col, sel in zip(filter_cols, selections):
        if sel:
            mask &= df[col].isin(sel)  
    return df[mask]

def get_kpi_mean(df, desc_col, days_col, pattern):
    clean_desc = df[desc_col].str.upper().str.replace("&NBSP;", "", regex=False).str.replace(" ", "", regex=False)
    clean_pattern = pattern.upper().replace("&NBSP;", "").replace(" ", "")
    mask = clean_desc.str.contains(clean_pattern, case=False, na=False)
    return safe_mean(df.loc[mask, days_col])

def auto_height(df):
    return min(max(len(df) * 35 + 45, 100), 600)

def download_file(url_or_file):
    if isinstance(url_or_file, str):
        try:
            etag_key  = f'etag_{url_or_file}'
            cache_key = f'cached_file_{url_or_file}'
            headers = {
                'User-Agent': 'Mozilla/5.0',
                'If-None-Match': st.session_state.get(etag_key, '')
            }
            response = requests.get(url_or_file, headers=headers, timeout=10)
            if response.status_code == 304:
                cached = st.session_state.get(cache_key)
                if cached is not None:
                    cached.seek(0)
                    return cached
            response.raise_for_status()
            st.session_state[etag_key]  = response.headers.get('ETag', '')
            result = BytesIO(response.content)
            st.session_state[cache_key] = result
            return result
        except Exception:
            return None
    return url_or_file

def get_data(key, uploader_key, load_func):
    df = None
    if st.session_state.is_online and key in URLS_DB:
        try:
            with st.spinner(f"Sincronizando {key}..."):
                df = load_func(URLS_DB[key])
        except Exception:
            pass
    if df is None:
        if not st.session_state.is_online:
            st.warning("⚠️ Sin conexión a GitHub. Cargue el archivo localmente.")
        f = st.file_uploader(f"📂 Cargar Excel {key}", type=["xlsx"], key=uploader_key)
        if f:
            df = load_func(f)
    return df

def set_retailer(retailer_name):
    st.session_state.active_retailer = retailer_name
    logic_vars = [
        's_rojo','s_dias_inv','s_dias_prod','s_rank_gen','s_rank_pas','s_rank_oli','s_rank_nut',
        'w_neg','w_4w','w_dias_inv','w_dias_prod','w_rank_tiendas','w_rank_pastas','w_rank_olivas','w_nutri_top10',
        'c_alt','c_neg','c_dias_inv','c_neg_zero','c_under_10','c_rank_gen','c_rank_pas','c_rank_oli','c_rank_nut'
    ]
    for var in logic_vars:
        if var in st.session_state:
            st.session_state[var] = False

# --- 4. FUNCIONES DE LECTURA DE EXCEL (OPTIMIZADAS) ---

def optimize_floats(df):
    for col in df.select_dtypes(include=['float64']).columns:
        df[col] = df[col].astype('float32')
    return df

def _str_cols(df, cols):
    for c in cols:
        if c in df.columns:
            df[c] = df[c].astype(str)
    return df

@st.cache_data(**CACHE_CONFIG)
def load_sor(path):
    try:
        source = download_file(path)
        if source is None:
            return None
        needed_cols = [0, 2, 3, 4, 5, 6, 7, 8, 21, 22, 23, 24, 28, 30]
        df = pd.read_excel(source, engine='openpyxl', usecols=needed_cols)

        col_map = {
            df.columns[0]:  "RESURTIMIENTO",
            df.columns[1]:  "CODIGO",
            df.columns[2]:  "DESCRIPCION",
            df.columns[3]:  "NO_TIENDA",
            df.columns[4]:  "TIENDA",
            df.columns[5]:  "CIUDAD",
            df.columns[6]:  "ESTADO",
            df.columns[7]:  "FORMATO",
            df.columns[8]:  "SEM1",
            df.columns[9]:  "SEM2",
            df.columns[10]: "SEM3",
            df.columns[11]: "SO_$",
            df.columns[12]: "INV_CAJAS",
            df.columns[13]: "DIAS_INV",
        }
        df.rename(columns=col_map, inplace=True)

        df["CODIGO"] = df["CODIGO"].astype(str).str.replace(r'\.0*$', '', regex=True)
        for c in ["DIAS_INV", "INV_CAJAS", "SO_$", "SEM1", "SEM2", "SEM3"]:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)

        df['SO_4SEM'] = df[["SEM1", "SEM2", "SEM3", "SO_$"]].sum(axis=1)
        df['SIN_VTA'] = (df['SO_4SEM'] == 0)
        df['VTA_PROM'] = df['SO_4SEM']

        df = _str_cols(df, ["RESURTIMIENTO", "NO_TIENDA", "TIENDA", "CIUDAD", "ESTADO", "FORMATO", "DESCRIPCION"])
        return optimize_floats(df)
    except Exception:
        return None

@st.cache_data(**CACHE_CONFIG)
def load_wal(path):
    try:
        source = download_file(path)
        if source is None:
            return None
        needed_cols = [0, 4, 5, 7, 15, 16, 18, 33, 42, 73, 74, 75, 76, 95, 96]
        df = pd.read_excel(source, engine='openpyxl', usecols=needed_cols)

        col_map = {
            df.columns[0]:  "CODIGO",
            df.columns[1]:  "DESCRIPCION",
            df.columns[2]:  "CATEGORIA",
            df.columns[3]:  "ESTADO",
            df.columns[4]:  "TIENDA",
            df.columns[5]:  "FORMATO",
            df.columns[6]:  "MARCA",
            df.columns[7]:  "DIAS_INV",
            df.columns[8]:  "EXISTENCIA",
            df.columns[9]:  "VTA_S1",
            df.columns[10]: "VTA_S2",
            df.columns[11]: "VTA_S3",
            df.columns[12]: "VTA_S4",
            df.columns[13]: "SO_SEM_ANT",
            df.columns[14]: "SO_$",
        }
        df.rename(columns=col_map, inplace=True)

        df["CODIGO"] = df["CODIGO"].astype(str).str.replace(r'\.0*$', '', regex=True)
        for c in ["DIAS_INV", "EXISTENCIA", "VTA_S1", "VTA_S2", "VTA_S3", "VTA_S4", "SO_SEM_ANT", "SO_$"]:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)

        df['PROM_PZS_MENSUAL'] = df[["VTA_S1", "VTA_S2", "VTA_S3", "VTA_S4"]].mean(axis=1)

        df = _str_cols(df, ["CODIGO", "DESCRIPCION", "CATEGORIA", "ESTADO", "TIENDA", "FORMATO", "MARCA"])
        return optimize_floats(df)
    except Exception:
        return None

@st.cache_data(**CACHE_CONFIG)
def load_che(path):
    try:
        source = download_file(path)
        if source is None:
            return None
        needed_cols = [3, 4, 5, 6, 7, 8, 9, 10, 12, 13, 17, 18, 19]
        df = pd.read_excel(source, engine='openpyxl', usecols=needed_cols)

        col_map = {
            df.columns[0]: "ESTADO",
            df.columns[1]: "COORDINADOR",
            df.columns[2]: "EJECUTIVO",
            df.columns[3]: "PROMOTOR",
            df.columns[4]: "COL_FILTRO",
            df.columns[5]: "CATEGORIA",
            df.columns[6]: "NO_TIENDA",
            df.columns[7]: "TIENDA",
            df.columns[8]: "ARTICULO",
            df.columns[9]: "INV_ULT_SEM",
            df.columns[10]: "VTA_PROM_DIARIA",
            df.columns[11]: "DIAS_INV",
            df.columns[12]: "SELL_OUT",
        }
        df.rename(columns=col_map, inplace=True)

        col_h = pd.to_numeric(df["COL_FILTRO"], errors='coerce')
        df = df[col_h != 0]
        df = df.dropna(subset=["ARTICULO"])
        df = df[pd.to_numeric(df["NO_TIENDA"], errors='coerce').notna()]

        for col in ["INV_ULT_SEM", "VTA_PROM_DIARIA", "DIAS_INV", "SELL_OUT"]:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

        df = _str_cols(df, ["ESTADO", "COORDINADOR", "EJECUTIVO", "PROMOTOR", "CATEGORIA", "NO_TIENDA", "TIENDA", "ARTICULO"])
        return optimize_floats(df)
    except Exception:
        return None


# --- 5. CSS AVANZADO ---
act = st.session_state.active_retailer
active_color = RETAILER_COLORS.get(act, "#333333")
style_on  = "opacity: 1 !important; border: 3px solid #ffffff !important; transform: scale(1.02) !important; box-shadow: 0 8px 16px rgba(0,0,0,0.3) !important; z-index: 10 !important;"
style_off = "opacity: 0.6 !important; transform: scale(0.98) !important; filter: grayscale(40%) !important; border: 1px solid transparent !important;"
css_styles = {k: style_on if act == k else style_off for k in ['SORIANA', 'WALMART', 'CHEDRAUI']}

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap&font-display=swap');
html, body {{ font-family: 'Inter', sans-serif; background-color: #f8f9fa; }}
.block-container {{ padding-top: 0.5rem !important; padding-bottom: 2rem !important; padding-left: 1rem !important; padding-right: 1rem !important; max-width: 100% !important; }}
.kpi-card {{ background: white; border: 1px solid #e0e0e0; border-radius: 12px; padding: 15px; text-align: center; box-shadow: 0 2px 6px rgba(0,0,0,0.05); margin-bottom: 15px; height: 100%; display: flex; flex-direction: column; justify-content: center; transition: transform 0.2s; }}
.kpi-card:active {{ transform: scale(0.98); }}
.kpi-title {{ font-size: 0.8rem; color: #666; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }}
.kpi-value {{ font-size: 2rem; font-weight: 800; margin-top: 5px; word-break: break-word; }}
.retailer-header {{ font-size: 1.2rem; font-weight: 800; color: white; padding: 10px 15px; border-radius: 8px; margin: 15px 0; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.1); text-shadow: 0 1px 2px rgba(0,0,0,0.2); }}

/* BOTONES PRINCIPALES DE NAVEGACIÓN */
div[data-testid="stHorizontalBlock"]:nth-of-type(1) button {{ border-radius: 10px !important; font-weight: 800 !important; text-transform: uppercase; transition: all 0.2s ease-in-out !important; border: none !important; }}
div[data-testid="stHorizontalBlock"]:nth-of-type(1) [data-testid="stColumn"]:nth-of-type(1) button {{ background: linear-gradient(135deg, #D32F2F, #B71C1C) !important; color: white !important; {css_styles['SORIANA']} }}
div[data-testid="stHorizontalBlock"]:nth-of-type(1) [data-testid="stColumn"]:nth-of-type(2) button {{ background: linear-gradient(135deg, #0071DC, #005BB5) !important; color: white !important; {css_styles['WALMART']} }}
div[data-testid="stHorizontalBlock"]:nth-of-type(1) [data-testid="stColumn"]:nth-of-type(3) button {{ background: linear-gradient(135deg, #FF6600, #E65100) !important; color: white !important; {css_styles['CHEDRAUI']} }}

/* ANIMACIÓN PARA SUB-BOTONES INACTIVOS (DEFAULT) */
div.stButton > button[kind="secondary"] {{ background-color: #ffffff !important; color: #555555 !important; border: 1px solid #dcdcdc !important; font-weight: 600 !important; border-radius: 8px !important; transition: all 0.2s ease-in-out !important; }}
div.stButton > button[kind="secondary"]:hover {{ border: 1px solid {active_color} !important; color: {active_color} !important; box-shadow: 0 2px 4px rgba(0,0,0,0.05) !important; }}

/* ANIMACIÓN PARA SUB-BOTONES ACTIVOS (GLOBALES) */
div.stButton > button[kind="primary"] {{ background-color: {active_color} !important; color: #ffffff !important; border: 2px solid {active_color} !important; font-weight: 800 !important; border-radius: 8px !important; box-shadow: 0 4px 12px rgba(0,0,0,0.25) !important; transform: scale(1.03) !important; transition: all 0.2s ease-in-out !important; }}

/* ---------------------------------------------------- */
/* ESTILOS DE LAYOUT PERSONALIZADO PARA BOTONES RANKING */
/* ---------------------------------------------------- */

/* GENERAL: Letras negras, fondo blanco */
div.element-container:has(.marker-gen) + div.element-container button {{ background-color: #FFFFFF !important; color: #000000 !important; border: 2px solid #000000 !important; font-weight: 800 !important; border-radius: 8px !important; transition: 0.2s !important; }}
div.element-container:has(.marker-gen) + div.element-container button[kind="primary"] {{ box-shadow: 0 4px 14px rgba(0,0,0,0.2) !important; opacity: 1 !important; transform: scale(1.04) !important; }}
div.element-container:has(.marker-gen) + div.element-container button[kind="secondary"] {{ opacity: 0.6 !important; transform: scale(0.98) !important; border: 1px solid #CCC !important; }}

/* PASTAS: Letras blancas, fondo amarillo espagueti */
div.element-container:has(.marker-pas) + div.element-container button {{ background-color: #F4B41A !important; color: #FFFFFF !important; border: 2px solid #F4B41A !important; font-weight: 800 !important; border-radius: 8px !important; transition: 0.2s !important; }}
div.element-container:has(.marker-pas) + div.element-container button[kind="primary"] {{ border: 2px solid #FFFFFF !important; box-shadow: 0 4px 14px rgba(244,180,26,0.6) !important; opacity: 1 !important; transform: scale(1.04) !important; }}
div.element-container:has(.marker-pas) + div.element-container button[kind="secondary"] {{ opacity: 0.6 !important; transform: scale(0.98) !important; filter: grayscale(20%); }}

/* OLIVAS: Letras negras, fondo verde oliva */
div.element-container:has(.marker-oli) + div.element-container button {{ background-color: #8A9A5B !important; color: #000000 !important; border: 2px solid #8A9A5B !important; font-weight: 800 !important; border-radius: 8px !important; transition: 0.2s !important; }}
div.element-container:has(.marker-oli) + div.element-container button[kind="primary"] {{ border: 2px solid #000000 !important; box-shadow: 0 4px 14px rgba(138,154,91,0.6) !important; opacity: 1 !important; transform: scale(1.04) !important; }}
div.element-container:has(.marker-oli) + div.element-container button[kind="secondary"] {{ opacity: 0.6 !important; transform: scale(0.98) !important; filter: grayscale(20%); }}

/* NUTRIOLI: Letras amarillas, fondo verde corporativo */
div.element-container:has(.marker-nut) + div.element-container button {{ background-color: #2E7D32 !important; color: #FFD700 !important; border: 2px solid #2E7D32 !important; font-weight: 800 !important; border-radius: 8px !important; transition: 0.2s !important; }}
div.element-container:has(.marker-nut) + div.element-container button[kind="primary"] {{ border: 2px solid #FFD700 !important; box-shadow: 0 4px 14px rgba(46,125,50,0.6) !important; opacity: 1 !important; transform: scale(1.04) !important; }}
div.element-container:has(.marker-nut) + div.element-container button[kind="secondary"] {{ opacity: 0.6 !important; transform: scale(0.98) !important; filter: grayscale(20%); }}

@media (max-width: 768px) {{
    .block-container {{ padding-left: 0.5rem !important; padding-right: 0.5rem !important; }}
    div[data-testid="stHorizontalBlock"] button {{ height: 50px !important; font-size: 0.8rem !important; padding: 0 !important; }}
    .retailer-header {{ font-size: 1rem; padding: 8px; margin: 10px 0; }}
    section[data-testid="stSidebar"] {{ display: none; }}
    canvas {{ max-width: 100% !important; }}
}}
@media (min-width: 769px) {{
    div[data-testid="stHorizontalBlock"] button {{ height: 70px !important; font-size: 1.1rem !important; }}
}}
</style>
""", unsafe_allow_html=True)

# --- 6. HEADER GLOBAL ---
c_head1, c_head2 = st.columns([1, 5])
with c_head1:
    try:
        st.image("ragasa_logo.png", use_container_width=True)
    except:
        st.write("📦 Logo Ragasa")
with c_head2:
    st.markdown("""
        <div style='display: flex; flex-direction: column; justify-content: center; height: 100%;'>
            <h2 style='margin:0; font-weight: 800; color: #333;'>DASHBOARD DE INVENTARIOS</h2>
            <p style='margin:0; font-size: 0.9rem; color: #666;'>desarrollada por Alexis</p>
        </div>
    """, unsafe_allow_html=True)

status_txt   = 'CONECTADO' if st.session_state.is_online else 'OFFLINE'
status_color = "#28a745"   if st.session_state.is_online else "#dc3545"
st.markdown(f"<div style='text-align:right; font-size:0.7rem; color:{status_color}; font-weight:bold; margin-top:-10px; margin-bottom:10px;'>● {status_txt}</div>", unsafe_allow_html=True)

# --- 7. NAVEGACIÓN PRINCIPAL ---
col1, col2, col3 = st.columns(3, gap="small")
with col1: st.button("SORIANA",  on_click=set_retailer, args=("SORIANA",),  use_container_width=True, key="nav_sor")
with col2: st.button("WALMART",  on_click=set_retailer, args=("WALMART",),  use_container_width=True, key="nav_wal")
with col3: st.button("CHEDRAUI", on_click=set_retailer, args=("CHEDRAUI",), use_container_width=True, key="nav_che")
st.markdown("<hr style='margin: 15px 0; border: 0; border-top: 1px solid #eee;'>", unsafe_allow_html=True)


# --- 8. VISTAS POR RETAILER ---

def view_soriana(df_s):
    st.markdown(f"<div class='retailer-header' style='background-color: {RETAILER_COLORS['SORIANA']}'>SORIANA</div>", unsafe_allow_html=True)

    s_vars = ['s_rojo','s_dias_inv','s_dias_prod','s_rank_gen','s_rank_pas','s_rank_oli','s_rank_nut']
    for v in s_vars:
        if v not in st.session_state: st.session_state[v] = False

    def tog_s_rojo():
        st.session_state.s_rojo      = not st.session_state.s_rojo
        st.session_state.s_dias_inv  = False
        st.session_state.s_dias_prod = False
    def tog_s_dias_inv():
        st.session_state.s_dias_inv  = not st.session_state.s_dias_inv
        st.session_state.s_rojo      = False
        st.session_state.s_dias_prod = False
    def tog_s_dias_prod():
        st.session_state.s_dias_prod = not st.session_state.s_dias_prod
        st.session_state.s_rojo      = False
        st.session_state.s_dias_inv  = False
    def set_s_rank(mode):
        for v in ['s_rank_gen','s_rank_pas','s_rank_oli','s_rank_nut']: st.session_state[v] = False
        if   mode == 'GEN': st.session_state.s_rank_gen = True
        elif mode == 'PAS': st.session_state.s_rank_pas = True
        elif mode == 'OLI': st.session_state.s_rank_oli = True
        elif mode == 'NUT': st.session_state.s_rank_nut = True

    if df_s is not None:
        with st.expander("🔍 Filtros Avanzados", expanded=True):
            c1, c2 = st.columns(2)
            with c1:
                opts_res = ["Todos"] + sorted(df_s["RESURTIMIENTO"].unique())
                def_res  = ["1.0"] if "1.0" in opts_res else (["1"] if "1" in opts_res else ["Todos"])
                fil_res  = st.multiselect("Resurtible", opts_res, default=def_res)
                fil_nda  = st.multiselect("No Tienda", sorted(df_s["NO_TIENDA"].unique()))
                fil_nom  = st.multiselect("Nombre",    sorted(df_s["TIENDA"].unique()))
            with c2:
                fil_cd  = st.multiselect("Ciudad",   sorted(df_s["CIUDAD"].unique()))
                fil_edo = st.multiselect("Estado",   sorted(df_s["ESTADO"].unique()))
                fil_fmt = st.multiselect("Formato",  sorted(df_s["FORMATO"].unique()))
                fil_art = st.multiselect("Artículo", sorted(df_s["DESCRIPCION"].unique()))

        dff = apply_filters(df_s,
            ["RESURTIMIENTO","NO_TIENDA","TIENDA","CIUDAD","ESTADO","FORMATO","DESCRIPCION"],
            [fil_res if "Todos" not in fil_res else None, fil_nda, fil_nom, fil_cd, fil_edo, fil_fmt, fil_art]
        )

        b1, b2, b3 = st.columns(3, gap="small")
        with b1: st.button("🔴 INV SIN VENTA", on_click=tog_s_rojo,     key="sor_btn_rojo",      use_container_width=True, type="primary" if st.session_state.s_rojo      else "secondary")
        with b2: st.button("📅 DIAS INV",      on_click=tog_s_dias_inv, key="sor_btn_dias_inv",  use_container_width=True, type="primary" if st.session_state.s_dias_inv  else "secondary")
        with b3: st.button("📋 DIAS X PROD",    on_click=tog_s_dias_prod,key="sor_btn_dias_prod", use_container_width=True, type="primary" if st.session_state.s_dias_prod else "secondary")

        if st.session_state.s_dias_prod:
            st.subheader("📋 Días Inventario x Producto")
            target_list = [
                "ACEITE DE SOYA NUTRIOLI BOT 850 ML","ACEITE COMESTIBLE NUTRIOLI 400 ML",
                "ACEITE COMESTIBLE SABROSANO 850 ML","ACEITE COMESTIBLE GRAN TRADICION 800 ML",
                "ACEITE NUTRIOLI PROTECT DEFENSAS 850ML","ACEITE NUTRIOLI PROTECT MENTE 850 ML",
                "ACEITE COMESTIBLE NUTRIOLI AEROSOL 180ML","ACEITE COMESTIBLE NUTRIOLI ANTIGOTEO 700",
                "ACEITE OLI OLIVA EXTRA VIRGEN PZ 250ML","ACEITE OLI OLIVA EXTRA VIRGEN PZ 500ML",
                "ACEITE OLI OLIVA EXTRA VIRGEN PZ 750ML","ADERE OLI OLIVA PARA COCINAR 500 ML OLI",
                "ADERE OLI OLIVA PARA COCINAR 750 ML OLI","ADEREZO OLI 250 ML PZ",
                "ADEREZO OLI 500 ML BOT","ACEITE COMESTIBLE AVE 850 ML",
                "ACEITE COMESTIBLE AEROSOL 170GR","ACEITE COMESTIBLE NUTRIOLI AEROSOL 180ML",
                "ACEITE OLIVA OLI PURO SPRAY 145 ML","ACEITE OLIVA OLI EV SPRAY 145 ML",
                "PASTA FIDEO NUTRIOLI 200GR","PASTA SPAGHETTI NUTRIOLI INTEGRAL 200GR",
                "PASTA FUSILLI INTEGRAL NUTRIOLI 200GR","PASTA CODO NUTRIOLI VERDURAS 200GR",
                "PASTA FUSILLI VERDURAS NUTRIOLI 450GR","PASTA SPAGHETTI NUTRIOLI 200GR",
                "PASTA CODO NUTRIOLI 200GR","VINAGRE BALSAMICO 250ML"
            ]
            desc_clean_col = dff["DESCRIPCION"].str.upper().str.replace(r'&NBSP;', ' ', regex=True).str.strip()
            res_rows = []
            for item in target_list:
                mask = desc_clean_col.str.contains(item.strip(), case=False, regex=False)
                if mask.any():
                    subset = dff[mask]
                    res_rows.append({"CODIGO": subset["CODIGO"].iloc[0], "ARTICULO": item, "DIAS INV": subset["DIAS_INV"].mean()})
                else:
                    res_rows.append({"CODIGO": "-", "ARTICULO": item, "DIAS INV": 0})
            df_prod_summary = pd.DataFrame(res_rows)
            st.dataframe(df_prod_summary.style.format({'DIAS INV': "{:,.1f}"}), use_container_width=True, hide_index=True, height=auto_height(df_prod_summary))

        elif st.session_state.s_dias_inv:
            st.subheader("📅 Reporte Días Inventario")
            val_nut = get_kpi_mean(dff, "DESCRIPCION", "DIAS_INV", "ACEITE DE SOYA NUTRIOLI BOT 850 ML")
            val_sab = get_kpi_mean(dff, "DESCRIPCION", "DIAS_INV", "ACEITE COMESTIBLE SABROSANO 850 ML")
            mask_pastas = dff["DESCRIPCION"].str.contains("PASTA", case=False, na=False)
            val_pas = dff.loc[mask_pastas, "DIAS_INV"].mean() if mask_pastas.any() else 0

            k1, k2, k3 = st.columns(3)
            k1.markdown(f"<div class='kpi-card'><div class='kpi-title'>NUTRIOLI 850ML</div><div class='kpi-value' style='color:#28a745;'>{val_nut:,.1f}</div></div>", unsafe_allow_html=True)
            k2.markdown(f"<div class='kpi-card'><div class='kpi-title'>SABROSANO 850ML</div><div class='kpi-value' style='color:#E4007C;'>{val_sab:,.1f}</div></div>", unsafe_allow_html=True)
            k3.markdown(f"<div class='kpi-card'><div class='kpi-title'>PASTAS</div><div class='kpi-value' style='color:#64DD17;'>{val_pas:,.1f}</div></div>", unsafe_allow_html=True)

            disp_sor_dias = dff[["NO_TIENDA","TIENDA","CODIGO","DESCRIPCION","INV_CAJAS","SO_$","SO_4SEM","DIAS_INV"]].copy()
            disp_sor_dias.columns = ['No.','TIENDA','CODIGO','ARTICULO','INV CAJAS','SELL OUT SEM','SELL OUT ULT 4 SEM','DIAS INV']
            st.dataframe(disp_sor_dias.style.format({'INV CAJAS':"{:,.0f}",'SELL OUT SEM':'${:,.2f}','SELL OUT ULT 4 SEM':'${:,.2f}','DIAS INV':"{:,.1f}"}), use_container_width=True, hide_index=True, height=auto_height(disp_sor_dias))

        else:
            desc = dff["DESCRIPCION"].str.upper().str.replace(" ", "", regex=False)
            conditions = [
                desc.str.contains("SABROSANO", na=False),
                desc.str.contains("GRANTRADICION", na=False),
                desc.str.contains("BALSAMICO", na=False),
                desc.str.contains("MISAZON", na=False) | desc.str.contains("MISAZÓN", na=False),
                desc.str.contains("AVE", na=False) & ~desc.str.contains("NUTRIOLI", na=False),
                desc.str.contains("NUTRIOLI", na=False) & desc.str.contains("PASTA|FUSILLI|SPAGUETTI|FIDEO|CODO", na=False),
                desc.str.contains("OLI", na=False) & (desc.str.contains("OLIVA|EV|AEROSOL|ADEREZO", na=False)),
                desc.str.contains("NUTRIOLI", na=False) & (desc.str.contains("400ML|850ML", na=False)) & ~desc.str.contains("PROTECT|DEFENSAS", na=False),
                desc.str.contains("NUTRIOLI", na=False),
            ]
            choices = ["SABROSANO","GT","BALSAMICO","MI SAZON","AVE","PASTAS","OLIVAS","NUTRIOLI","REST NUTRIOLI"]
            dff = dff.copy()
            dff['Category'] = np.select(conditions, choices, default=None)

            c_kpi, c_chart = st.columns([1, 2])
            with c_kpi:
                total_so = dff['SO_$'].sum()
                st.markdown(f"<div class='kpi-card' style='height: 450px;'><div class='kpi-title'>Total Sell Out Semanal</div><div class='kpi-value' style='color:#D32F2F;'>${total_so:,.2f}</div></div>", unsafe_allow_html=True)
            with c_chart:
                pie_df = dff.dropna(subset=['Category']).groupby('Category')['SO_$'].sum().reset_index()
                pie_df = pie_df[pie_df['SO_$'] > 0]
                if not pie_df.empty:
                    domain  = ["BALSAMICO","SABROSANO","PASTAS","OLIVAS","GT","NUTRIOLI","MI SAZON","AVE","REST NUTRIOLI"]
                    range_  = ["#e012a9","#f705ab","#4c915d","#97ad6a","#7d6010","#02c705","#e89015","#ff0000","#00ff04"]
                    color_map = dict(zip(domain, range_))
                    fig = px.pie(pie_df, values='SO_$', names='Category', color='Category', color_discrete_map=color_map, hole=0.45)
                    fig.update_traces(
                        textposition='outside', textinfo='label+percent+value',
                        texttemplate='<b>%{label}</b><br>%{percent:.0%} | $%{value:,.0f}',
                        hovertemplate='<b>%{label}</b><br>Sell Out: $%{value:,.2f}<br>Porcentaje: %{percent:.0%}<extra></extra>'
                    )
                    fig.update_layout(showlegend=False, margin=dict(t=50,b=50,l=100,r=100), height=450, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", uniformtext_minsize=9, uniformtext_mode='hide')
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("Sin datos para gráfica.")

            if st.session_state.s_rojo:
                dff = dff[dff['SIN_VTA']]
                st.caption("📋 Vista: Sin Venta")

            disp = dff[["NO_TIENDA","TIENDA","CODIGO","DESCRIPCION","INV_CAJAS","SO_$","SO_4SEM","DIAS_INV"]].copy()
            disp.columns = ['No.','TIENDA','CODIGO','ARTICULO','INV CAJAS','SELL OUT SEM','SELL OUT ULT 4 SEM','DIAS INV']
            disp = disp.sort_values(by='SELL OUT ULT 4 SEM', ascending=False)
            
            st.dataframe(disp.style.format({'INV CAJAS':"{:,.0f}",'SELL OUT SEM':'${:,.2f}','SELL OUT ULT 4 SEM':'${:,.2f}','DIAS INV':"{:,.1f}"}), use_container_width=True, hide_index=True, height=auto_height(disp))

        st.divider()
        st.markdown("<h3 style='text-align: center; color: #444;'>🏆 RANKING DE VENTAS</h3>", unsafe_allow_html=True)
        s_mod1, s_mod2 = st.columns(2)
        with s_mod1: sel_s_rank_st  = st.multiselect("Estado (Ranking)",  sorted(df_s["ESTADO"].unique()),  key="s_rnk_st")
        with s_mod2: sel_s_rank_fmt = st.multiselect("Formato (Ranking)", sorted(df_s["FORMATO"].unique()), key="s_rnk_fmt")

        sr1, sr2, sr3, sr4 = st.columns(4, gap="small")
        with sr1:
            st.markdown('<span class="marker-gen"></span>', unsafe_allow_html=True)
            st.button("📊 GENERAL",  key="s_rk_gen", on_click=set_s_rank, args=('GEN',), use_container_width=True, type="primary" if st.session_state.s_rank_gen else "secondary")
        with sr2:
            st.markdown('<span class="marker-pas"></span>', unsafe_allow_html=True)
            st.button("🍝 PASTAS",   key="s_rk_pas", on_click=set_s_rank, args=('PAS',), use_container_width=True, type="primary" if st.session_state.s_rank_pas else "secondary")
        with sr3:
            st.markdown('<span class="marker-oli"></span>', unsafe_allow_html=True)
            st.button("🫒 OLIVAS",   key="s_rk_oli", on_click=set_s_rank, args=('OLI',), use_container_width=True, type="primary" if st.session_state.s_rank_oli else "secondary")
        with sr4:
            st.markdown('<span class="marker-nut"></span>', unsafe_allow_html=True)
            st.button("🍃 NUTRIOLI", key="s_rk_nut", on_click=set_s_rank, args=('NUT',), use_container_width=True, type="primary" if st.session_state.s_rank_nut else "secondary")

        dff_s_rank = apply_filters(df_s, ["ESTADO","FORMATO"], [sel_s_rank_st, sel_s_rank_fmt])

        list_s_gen = ["ACEITE COMESTIBLE NUTRIOLI ANTIGOTEO 700","ACEITE COMESTIBLE GRAN TRADICION 900 ML","ACEITE COMESTIBLE SABROSANO +30 850 ML","ACEITE OLIVA OLI PURO SPRAY 145 ML","JUSTO 850 ML","ACEITE COMESTIBLE AEROSOL 170GR","ACEITE COMESTIBLE AVE 850 ML","ACEITE COMESTIBLE NUTRIOLI 400 ML","ACEITE COMESTIBLE NUTRIOLI AEROSOL 180ML","ACEITE COMESTIBLE NUTRIOLI DHA 850 ML","ACEITE COMESTIBLE SABROSANO 850 ML","SABROSANO RINDE+ 850 ML","ACEITE OLI OLIVA EXTRA VIRGEN PZ 250ML","ACEITE OLI OLIVA EXTRA VIRGEN PZ 500ML","ACEITE OLI OLIVA EXTRA VIRGEN PZ 750ML","ADERE OLI OLIVA PARA COCINAR 500 ML OLI","ADERE OLI OLIVA PARA COCINAR 750 ML OLI","ADEREZO OLI 250 ML PZ","ADEREZO OLI 500 ML BOT","ACEITE COMESTIBLE GRAN TRADICION 800 ML","ACEITE DE SOYA NUTRIOLI BOT 850 ML","VINAGRE BALSAMICO 250ML","ACEITE NUTRIOLI PROTECT DEFENSAS 850ML","ACEITE NUTRIOLI PROTECT MENTE 850 ML","PASTA FIDEO NUTRIOLI 200GR","PASTA SPAGHETTI NUTRIOLI INTEGRAL 200GR","PASTA FUSILLI INTEGRAL NUTRIOLI 200GR","PASTA CODO NUTRIOLI VERDURAS 200GR","PASTA FUSILLI VERDURAS NUTRIOLI 450GR","PASTA SPAGHETTI NUTRIOLI 200GR","PASTA CODO NUTRIOLI 200GR"]
        list_s_pas = ["PASTA FIDEO NUTRIOLI 200GR","PASTA SPAGHETTI NUTRIOLI INTEGRAL 200GR","PASTA FUSILLI INTEGRAL NUTRIOLI 200GR","PASTA CODO NUTRIOLI VERDURAS 200GR","PASTA FUSILLI VERDURAS NUTRIOLI 450GR","PASTA SPAGHETTI NUTRIOLI 200GR","PASTA CODO NUTRIOLI 200GR"]
        list_s_oli = ["ACEITE OLI OLIVA EXTRA VIRGEN PZ 250ML","ACEITE OLI OLIVA EXTRA VIRGEN PZ 500ML","ACEITE OLI OLIVA EXTRA VIRGEN PZ 750ML","ADERE OLI OLIVA PARA COCINAR 500 ML OLI","ADERE OLI OLIVA PARA COCINAR 750 ML OLI","ADEREZO OLI 250 ML PZ","ADEREZO OLI 500 ML BOT","ACEITE OLIVA OLI PURO SPRAY 145 ML"]
        list_s_nut = ["ACEITE DE SOYA NUTRIOLI BOT 850 ML"]

        target_list_s = []; rank_title_s = ""
        if   st.session_state.s_rank_gen: target_list_s = list_s_gen; rank_title_s = "VENTA GENERAL ($)"
        elif st.session_state.s_rank_pas: target_list_s = list_s_pas; rank_title_s = "VENTA PASTAS ($)"
        elif st.session_state.s_rank_oli: target_list_s = list_s_oli; rank_title_s = "VENTA OLIVAS ($)"
        elif st.session_state.s_rank_nut: target_list_s = list_s_nut; rank_title_s = "VENTA NUTRIOLI ($)"

        if target_list_s:
            target_set = set(t.strip() for t in target_list_s)
            dff_sub = dff_s_rank[dff_s_rank["DESCRIPCION"].str.strip().isin(target_set)]
            if not dff_sub.empty:
                final_s_rank = dff_sub.groupby(["NO_TIENDA","TIENDA"])['SO_$'].sum().reset_index()
                final_s_rank.columns = ['No Tienda','TIENDA', rank_title_s]
                final_s_rank = final_s_rank.sort_values(by=rank_title_s, ascending=False)
                st.dataframe(final_s_rank.style.format({rank_title_s:"${:,.2f}"}), use_container_width=True, hide_index=True, height=auto_height(final_s_rank))
            else:
                st.warning("⚠️ No se encontraron ventas para los productos seleccionados.")


def view_walmart(df_w):
    st.markdown(f"<div class='retailer-header' style='background-color: {RETAILER_COLORS['WALMART']}'>WALMART</div>", unsafe_allow_html=True)
    w_vars = ['w_neg','w_4w','w_dias_inv','w_dias_prod','w_rank_tiendas','w_rank_pastas','w_rank_olivas','w_nutri_top10']
    for v in w_vars:
        if v not in st.session_state: st.session_state[v] = False

    def tog_w(target):
        for v in ['w_neg','w_4w','w_dias_inv','w_dias_prod']:
            st.session_state[v] = True if v == target and not st.session_state[v] else False
    def set_rank(mode):
        for v in ['w_rank_tiendas','w_rank_pastas','w_rank_olivas','w_nutri_top10']: st.session_state[v] = False
        if   mode == 'tiendas':  st.session_state.w_rank_tiendas = True
        elif mode == 'pastas':   st.session_state.w_rank_pastas  = True
        elif mode == 'olivas':   st.session_state.w_rank_olivas  = True
        elif mode == 'nutrioli': st.session_state.w_nutri_top10  = True

    if df_w is not None:
        df_w = df_w[~df_w["FORMATO"].isin(['BAE','MB'])]

        with st.expander("🔍 Filtros Avanzados", expanded=True):
            c1, c2, c3 = st.columns(3)
            with c1:
                marca_opts = sorted([m for m in df_w["MARCA"].unique() if m.strip().upper() not in ["NUTRIOLI + PASTA","NUTRIOLI  PASTA","NUTRIOLI PASTA"]])
                sel_marca  = st.multiselect("Marca",  marca_opts)
                sel_state  = st.multiselect("Estado", sorted(df_w["ESTADO"].unique()))
            with c2:
                unique_stores = sorted(df_w[df_w["ESTADO"].isin(sel_state)]["TIENDA"].unique()) if sel_state else sorted(df_w["TIENDA"].unique())
                sel_store = st.multiselect("Tienda",  unique_stores)
                sel_fmt   = st.multiselect("Formato", sorted(df_w["FORMATO"].unique()))
            with c3:
                excluidas_clean = {"ACEITE VEGETAL SABROSANO RINDE MAS 850ML","OLI SPRAY ACEITE DE OLIVA 145ML",
                    "ACEITE MIXTO GRAN TRADICION 1L","ACEITE GRAN TRADICION 900ML",
                    "NUTRIOLI 946 ML +PASTA CODO 200G","NUTRIOLI 946 ML +FUSILLI VERDURAS 200G",
                    "NUTRIOLI SPAGUETTI ESENCIAL 200G","NUTRIOLI FIDEO ESENCIAL 200G",
                    "NUTRIOLI CODO ESENCIAL 200G","NUTRIOLI FUSILLI VERDURAS 200G","NUTRIOLI CODO VERDURAS 200G"}
                opciones_prod = [p for p in df_w["DESCRIPCION"].unique() if p.strip().upper() not in excluidas_clean]
                sel_prod = st.multiselect("Artículo", sorted(opciones_prod))

        dff_kpi = apply_filters(df_w, ["MARCA","ESTADO","TIENDA","FORMATO"], [sel_marca, sel_state, sel_store, sel_fmt])
        dff     = apply_filters(dff_kpi, ["DESCRIPCION"], [sel_prod])

        b1, b2, b3, b4 = st.columns(4, gap="small")
        with b1: st.button("📉 NEGATIVOS",   on_click=tog_w, args=('w_neg',),       key="btn_w_neg",       use_container_width=True, type="primary" if st.session_state.w_neg      else "secondary")
        with b2: st.button("🔴 SIN VTA 4SEM",on_click=tog_w, args=('w_4w',),        key="btn_w_4w",        use_container_width=True, type="primary" if st.session_state.w_4w       else "secondary")
        with b3: st.button("📅 DIAS INV",    on_click=tog_w, args=('w_dias_inv',),  key="btn_w_dias",      use_container_width=True, type="primary" if st.session_state.w_dias_inv  else "secondary")
        with b4: st.button("📋 DIAS X PROD", on_click=tog_w, args=('w_dias_prod',), key="btn_w_dias_prod", use_container_width=True, type="primary" if st.session_state.w_dias_prod else "secondary")

        if st.session_state.w_neg: dff = dff[dff["EXISTENCIA"] < 0]; st.warning("VISTA: NEGATIVOS")
        if st.session_state.w_4w:  dff = dff[(dff["VTA_S1"]==0)&(dff["VTA_S2"]==0)&(dff["VTA_S3"]==0)&(dff["VTA_S4"]==0)]; st.warning("VISTA: SIN VENTA 4 SEMANAS")

        borges_set = {x.replace(" ","").upper() for x in [
            "BORGES ACEITE OLIVA EXTRA VIRGEN 500","BORGES ACEITE OLIVA EXTRA SUAVE",
            "ACEITE DE OLIVA EXTRA VIRGEN KOSHER","ACEITE DE OLIVA A LA ALBAHACA FRESCA",
            "ACEITE DE SOJA JENGIBRE","ACEITE DE OLIVA AL AJO FRITO",
            "ACEITE DE OLIVA AL  ROMERO FRESCO","BORGES ACEITE DE PEPITA UVA 500ML",
            "BORGES ACEITE DE OLIVA EXTRA VIRGEN ECOL","BORGES VINAGRE BALSAMICO 250ML",
            "VINAGRE DE JEREZ 250 ML","VINAGRE DE SIDRA 250 ML","VINAGRE DE VINO FRAMBUESA",
            "VINAGRE DE VINO AL  AJO 250 ML","BORGES VINAGRE VINO BLANCO",
            "VINAGRE DE MANZANA ECOLOGICO","BORGES VINAGRE DE VINOTINTO",
            "VINAGRE DE VINO DE RIOJA BOTELLA 250ML","BORGES ACEITE OLIVA 100 PURO CON AJO"
        ]}

        desc_w = dff["DESCRIPCION"].str.upper().str.replace(" ","",regex=False).str.replace("&NBSP;","",regex=False)
        is_borges = desc_w.apply(lambda d: any(b in d for b in borges_set))
        conditions_w = [
            is_borges,
            desc_w.str.contains("NUTRIOLI",na=False) & desc_w.str.contains("946",na=False),
            desc_w.str.contains("SABROSANO",na=False),
            desc_w.str.contains("GRANTRADICION",na=False),
            desc_w.str.contains("BALSAMICO",na=False),
            (desc_w.str.contains("OLISPRAY|OLICOCINA|OLIDENUTEV|ACEITEOLIDEOLIVA|OLIDENUT",na=False)) & ~desc_w.str.contains("BALSAMICO",na=False),
            desc_w.str.contains("NUTRIOLI",na=False) & desc_w.str.contains("SPAGUETTI|FIDEO|CODO|PASTA",na=False),
            desc_w.str.contains("NUTRIOLI",na=False),
        ]
        choices_w = ["BORGES","NUTRIOLI","SABROSANO","GT","BALSAMICO","OLIVAS","PASTAS","REST NUTRIOLI"]
        dff = dff.copy()
        dff['Category'] = np.select(conditions_w, choices_w, default=None)

        if st.session_state.w_dias_prod:
            st.subheader("📋 Días Inventario x Producto")
            target_list = [
                "NUTRIOLI ACEITE PURO DE SOYA 946 ML","NUTRIOLI ACEITE PURO DE SOYA 400 ML",
                "SABROSANO ACEITE 850ML MANTEQUILLA","ACEITE COMESTIBLE GRAN TRADICION 850ML",
                "ACEITE SOYA NUTRIOLI ANTIGOTEO 700ML","ACEITE NUTRIOLI DEFENSAS 850 ML",
                "NUTRIOLI ACEITE PROTECT MENTE 850 ML","NUTRIOLI SPRAY 180 ML",
                "AVE AEROSOL 170GR","OLI SPRAY ACEITE DE OLIVA 145ML",
                "OLI SPRAY ACEITE DE OLIVA EV 145ML","OLI DE NUTRIOLI EXTRA VIRGEN 250ML",
                "OLI DE NUTRIOLI ACEITE DE OLIVA 500ML","OLI DE NUTRIOLI ACEITE DE OLIVA 750ML",
                "OLI ACEITE DE OLIVA COCINA 250ML","ACEITE DE OLIVA EXTRA VIRGEN OLI DE NUTR",
                "ACEITE OLI DE OLIVA EX VIRGEN ORGANICO","OLI NUTRIOLI VINAGRE BALSAMICO MODENA250",
                "VINAGRE DE JEREZ 250 ML","VINAGRE DE MANZANA ECOLOGICO","VINAGRE DE SIDRA 250 ML",
                "VINAGRE DE VINO AL  AJO 250 ML","VINAGRE DE VINO DE RIOJA BOTELLA 250ML",
                "VINAGRE DE VINO FRAMBUESA","BORGES ACEITE DE OLIVA EXTRA VIRGEN ECOL",
                "BORGES ACEITE DE PEPITA UVA 500ML","BORGES ACEITE OLIVA 100 PURO CON AJO",
                "BORGES ACEITE OLIVA EXTRA SUAVE","BORGES ACEITE OLIVA EXTRA VIRGEN 500",
                "BORGES VINAGRE BALSAMICO 250ML","BORGES VINAGRE DE VINOTINTO",
                "BORGES VINAGRE VINO BLANCO","ACEITE DE OLIVA A LA ALBAHACA FRESCA",
                "ACEITE DE OLIVA AL  ROMERO FRESCO","ACEITE DE OLIVA AL AJO FRITO",
                "ACEITE DE OLIVA EXTRA VIRGEN KOSHER","ACEITE DE SOJA JENGIBRE"
            ]
            desc_nospace = dff_kpi["DESCRIPCION"].str.upper().str.replace(r'&NBSP;','',regex=True).str.replace(" ","",regex=False)
            res_rows = []
            for item in target_list:
                clean_item = item.upper().replace("&NBSP;","").replace(" ","")
                mask = desc_nospace.str.contains(clean_item, case=False, regex=False)
                if mask.any():
                    subset = dff_kpi[mask]
                    res_rows.append({"CODIGO": subset["CODIGO"].iloc[0], "ARTICULO": item, "DIAS DE INV": subset["DIAS_INV"].mean(), "SELL OUT": subset["SO_$"].sum()})
                else:
                    res_rows.append({"CODIGO": "-", "ARTICULO": item, "DIAS DE INV": 0, "SELL OUT": 0})
            df_prod_summary = pd.DataFrame(res_rows)
            st.dataframe(df_prod_summary.style.format({'DIAS DE INV':"{:,.1f}",'SELL OUT':"${:,.2f}"}), use_container_width=True, hide_index=True, height=auto_height(df_prod_summary))

        elif st.session_state.w_dias_inv:
            st.subheader("📅 Reporte Días Inventario")
            val_nutri = get_kpi_mean(dff_kpi,"DESCRIPCION","DIAS_INV","NUTRIOLI ACEITE PURO DE SOYA 946 ML")
            val_sabro = get_kpi_mean(dff_kpi,"DESCRIPCION","DIAS_INV","SABROSANO ACEITE 850ML MANTEQUILLA")
            val_ave   = get_kpi_mean(dff_kpi,"DESCRIPCION","DIAS_INV","ACEITE AVE 850ML")
            val_gran  = get_kpi_mean(dff_kpi,"DESCRIPCION","DIAS_INV","ACEITE COMESTIBLE GRAN TRADICION 850ML")
            m1,m2,m3,m4 = st.columns(4)
            m1.markdown(f"<div class='kpi-card'><div class='kpi-title'>NUTRIOLI 946M</div><div class='kpi-value' style='color:#28a745;'>{val_nutri:,.1f}</div></div>", unsafe_allow_html=True)
            m2.markdown(f"<div class='kpi-card'><div class='kpi-title'>SABROSANO 850ML</div><div class='kpi-value' style='color:#E4007C;'>{val_sabro:,.1f}</div></div>", unsafe_allow_html=True)
            m3.markdown(f"<div class='kpi-card'><div class='kpi-title'>AVE 850ML</div><div class='kpi-value' style='color:#D32F2F;'>{val_ave:,.1f}</div></div>", unsafe_allow_html=True)
            m4.markdown(f"<div class='kpi-card'><div class='kpi-title'>GRAN TRADICION</div><div class='kpi-value' style='color:#8B4513;'>{val_gran:,.1f}</div></div>", unsafe_allow_html=True)
            disp_w_dias = dff[["TIENDA","CODIGO","DESCRIPCION","DIAS_INV"]].copy()
            disp_w_dias.columns = ["TIENDA","CODIGO","DESCRIPCION","DIAS INVENTARIO"]
            st.dataframe(disp_w_dias.style.format({'DIAS INVENTARIO':"{:,.1f}"}), use_container_width=True, hide_index=True, height=auto_height(disp_w_dias))

        else:
            c_kpi, c_chart = st.columns([1, 2])
            total_so = dff['SO_$'].sum()
            with c_kpi:
                st.markdown(f"<div class='kpi-card' style='height: 450px;'><div class='kpi-title'>Total Sell Out</div><div class='kpi-value' style='color:#28a745;'>${total_so:,.2f}</div></div>", unsafe_allow_html=True)
            with c_chart:
                pie_df = dff.dropna(subset=['Category']).groupby('Category')['SO_$'].sum().reset_index()
                pie_df = pie_df[pie_df['SO_$'] > 0]
                if not pie_df.empty:
                    domain  = ["SABROSANO","GT","OLIVAS","BALSAMICO","PASTAS","REST NUTRIOLI","NUTRIOLI","BORGES"]
                    range_  = ["#E4007C","#a18262","#6B8E23","#9f4576","#426045","#bfff00","#008f39","#FF0000"]
                    color_map = dict(zip(domain, range_))
                    fig = px.pie(pie_df, values='SO_$', names='Category', color='Category', color_discrete_map=color_map, hole=0.45)
                    fig.update_traces(
                        textposition='outside', textinfo='label+percent+value',
                        texttemplate='<b>%{label}</b><br>%{percent:.0%} | $%{value:,.0f}',
                        hovertemplate='<b>%{label}</b><br>Sell Out: $%{value:,.2f}<br>Porcentaje: %{percent:.0%}<extra></extra>'
                    )
                    fig.update_layout(showlegend=False, margin=dict(t=50,b=50,l=100,r=100), height=450, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", uniformtext_minsize=9, uniformtext_mode='hide')
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("Sin datos para gráfica.")

            disp = dff[["CODIGO","DESCRIPCION","TIENDA","EXISTENCIA","SO_$","PROM_PZS_MENSUAL"]].copy()
            disp.columns = ['CODIGO','DESCRIPCION','TIENDA','EXISTENCIA','SELL OUT','PROM PZS MENSUAL']
            st.dataframe(disp.style.format({'SELL OUT':'${:,.2f}','PROM PZS MENSUAL':'{:,.2f}'}), use_container_width=True, hide_index=True, height=auto_height(disp))

        st.divider()
        st.markdown("<h3 style='text-align: center; color: #444;'>🏆 RANKING DE VENTAS</h3>", unsafe_allow_html=True)
        c_mod1, c_mod2 = st.columns(2)
        with c_mod1: sel_st_rank  = st.multiselect("Estado (Ranking)",  sorted(df_w["ESTADO"].unique()),  key="rnk_st")
        with c_mod2: sel_fmt_rank = st.multiselect("Formato (Ranking)", sorted(df_w["FORMATO"].unique()), key="rnk_fmt")

        r1,r2,r3,r4 = st.columns(4, gap="small")
        with r1:
            st.markdown('<span class="marker-gen"></span>', unsafe_allow_html=True)
            st.button("📊 GENERAL",  key="w_rk_gen", on_click=set_rank, args=('tiendas',),  use_container_width=True, type="primary" if st.session_state.w_rank_tiendas else "secondary")
        with r2:
            st.markdown('<span class="marker-pas"></span>', unsafe_allow_html=True)
            st.button("🍝 PASTAS",   key="w_rk_pas", on_click=set_rank, args=('pastas',),   use_container_width=True, type="primary" if st.session_state.w_rank_pastas  else "secondary")
        with r3:
            st.markdown('<span class="marker-oli"></span>', unsafe_allow_html=True)
            st.button("🫒 OLIVAS",   key="w_rk_oli", on_click=set_rank, args=('olivas',),   use_container_width=True, type="primary" if st.session_state.w_rank_olivas  else "secondary")
        with r4:
            st.markdown('<span class="marker-nut"></span>', unsafe_allow_html=True)
            st.button("🏆 NUTRIOLI", key="w_rk_nut", on_click=set_rank, args=('nutrioli',), use_container_width=True, type="primary" if st.session_state.w_nutri_top10  else "secondary")

        dff_rank = apply_filters(df_w, ["ESTADO","FORMATO"], [sel_st_rank, sel_fmt_rank])
        final_rank = None
        
        if st.session_state.w_rank_tiendas:
            final_rank = dff_rank.groupby("TIENDA")['SO_$'].sum().reset_index().rename(columns={'SO_$':'VENTA TOTAL ($)'})
        elif st.session_state.w_rank_pastas:
            df_sub = dff_rank[dff_rank["CATEGORIA"].str.contains("PASTAS", case=False, na=False)]
            if not df_sub.empty: final_rank = df_sub.groupby("TIENDA")['SO_$'].sum().reset_index().rename(columns={'SO_$':'VENTA PASTAS ($)'})
        elif st.session_state.w_rank_olivas:
            df_sub = dff_rank[dff_rank["DESCRIPCION"].str.contains("OLI", case=False, na=False)]
            if not df_sub.empty: final_rank = df_sub.groupby("TIENDA")['SO_$'].sum().reset_index().rename(columns={'SO_$':'VENTA OLIVAS ($)'})
        elif st.session_state.w_nutri_top10:
            df_sub = dff_rank[dff_rank["DESCRIPCION"].str.contains("NUTRIOLI", case=False, na=False) & dff_rank["DESCRIPCION"].str.contains("946", case=False, na=False)]
            if not df_sub.empty: 
                final_rank = df_sub.groupby(["FORMATO", "TIENDA", "DESCRIPCION"])[['EXISTENCIA', 'SO_SEM_ANT', 'SO_$']].sum().reset_index()
                final_rank.columns = ["FORMATO", "TIENDA", "PRODUCTO", "INVENTARIO", "VTA SEM ANTERIOR ($)", "SELL OUT ($)"]

        if final_rank is not None:
            sort_col = final_rank.columns[-1]
            final_rank = final_rank.sort_values(by=sort_col, ascending=False)
            
            format_dict = {}
            for col in final_rank.columns:
                if "($)" in col or "$" in col:
                    format_dict[col] = "${:,.2f}"
                elif "INVENTARIO" in col:
                    format_dict[col] = "{:,.0f}"
                    
            st.dataframe(final_rank.style.format(format_dict), use_container_width=True, hide_index=True, height=auto_height(final_rank))


def view_chedraui(df_c):
    st.markdown(f"<div class='retailer-header' style='background-color: {RETAILER_COLORS['CHEDRAUI']}'>CHEDRAUI</div>", unsafe_allow_html=True)
    c_vars = ['c_neg_zero','c_dias_inv','c_rank_gen','c_rank_pas','c_rank_oli','c_rank_nut']
    for v in c_vars:
        if v not in st.session_state: st.session_state[v] = False

    def tog_c(target):
        for v in ['c_neg_zero','c_dias_inv']:
            st.session_state[v] = True if v == target and not st.session_state[v] else False
    def set_c_rank(mode):
        for v in ['c_rank_gen','c_rank_pas','c_rank_oli','c_rank_nut']: st.session_state[v] = False
        if   mode == 'GEN': st.session_state.c_rank_gen = True
        elif mode == 'PAS': st.session_state.c_rank_pas = True
        elif mode == 'OLI': st.session_state.c_rank_oli = True
        elif mode == 'NUT': st.session_state.c_rank_nut = True

    if df_c is not None:
        with st.expander("🔍 Filtros Avanzados", expanded=True):
            c1, c2 = st.columns(2)
            with c1:
                fil_no  = st.multiselect("No Tienda",  sorted(df_c["NO_TIENDA"].unique()))
                fil_ti  = st.multiselect("Tienda",     sorted(df_c["TIENDA"].unique()))
                fil_cat = st.multiselect("Categoría",  sorted(df_c["CATEGORIA"].unique()))
            with c2:
                fil_ed  = st.multiselect("Estado",     sorted(df_c["ESTADO"].unique()))
                fil_art = st.multiselect("Artículo",   sorted(df_c["ARTICULO"].unique()))

        dff_base = apply_filters(df_c, ["NO_TIENDA","TIENDA","ESTADO","CATEGORIA"], [fil_no, fil_ti, fil_ed, fil_cat])
        dff      = apply_filters(dff_base, ["ARTICULO"], [fil_art])

        b1, b2 = st.columns(2, gap="small")
        with b1: st.button("📉 NEGATIVOS",  on_click=tog_c, args=('c_neg_zero',), key="c_btn_nz",   use_container_width=True, type="primary" if st.session_state.c_neg_zero else "secondary")
        with b2: st.button("📅 DIAS INV",   on_click=tog_c, args=('c_dias_inv',), key="c_btn_dias", use_container_width=True, type="primary" if st.session_state.c_dias_inv  else "secondary")

        if st.session_state.c_dias_inv:
            st.subheader("📅 Reporte Días Inventario")
            val_nut = get_kpi_mean(dff_base,"ARTICULO","DIAS_INV","Nutrioli Bot 850")
            val_sab = get_kpi_mean(dff_base,"ARTICULO","DIAS_INV","Sabrosano Mixto 850")
            val_ave = get_kpi_mean(dff_base,"ARTICULO","DIAS_INV","Ave Soya-Canola 850")
            k1,k2,k3 = st.columns(3)
            k1.markdown(f"<div class='kpi-card'><div class='kpi-title'>NUTRIOLI 850ML</div><div class='kpi-value' style='color:#28a745;'>{val_nut:,.1f}</div></div>", unsafe_allow_html=True)
            k2.markdown(f"<div class='kpi-card'><div class='kpi-title'>SABROSANO 850ML</div><div class='kpi-value' style='color:#E4007C;'>{val_sab:,.1f}</div></div>", unsafe_allow_html=True)
            k3.markdown(f"<div class='kpi-card'><div class='kpi-title'>AVE 850ML</div><div class='kpi-value' style='color:#D32F2F;'>{val_ave:,.1f}</div></div>", unsafe_allow_html=True)
            
            disp = dff[["NO_TIENDA","TIENDA","ARTICULO","INV_ULT_SEM","VTA_PROM_DIARIA","DIAS_INV","SELL_OUT"]].copy()
            disp.columns = ['NO_TIENDA','TIENDA','ARTICULO','INV_ULT_SEM','VTA_PROM_DIARIA','DIAS_INV','SELL_OUT']
            st.dataframe(disp.style.format({'INV_ULT_SEM':"{:,.0f}",'VTA_PROM_DIARIA':"{:,.2f}",'DIAS_INV':"{:,.1f}",'SELL_OUT':"${:,.2f}"}), use_container_width=True, hide_index=True, height=auto_height(disp))

        elif st.session_state.c_neg_zero:
            dff_neg = dff[dff["INV_ULT_SEM"] < 0].copy()
            st.subheader("📉 Vista: Inventarios Negativos")
            
            disp_neg = dff_neg[["ESTADO", "COORDINADOR", "EJECUTIVO", "PROMOTOR", "CATEGORIA", "NO_TIENDA", "TIENDA", "ARTICULO", "INV_ULT_SEM"]].copy()
            disp_neg.columns = ["ESTADO", "Coordinador", "Ejecutivo", "Promotor", "Categoria", "No de tienda", "Tienda", "articulo", "Inventario 06 Mar 2026"]
            
            st.dataframe(disp_neg.style.format({'Inventario 06 Mar 2026': "{:,.0f}"}), use_container_width=True, hide_index=True, height=auto_height(disp_neg))

        else:
            desc_c = dff["ARTICULO"].str.upper().str.replace(" ","",regex=False)
            conditions_c = [
                desc_c.str.contains("BALSAMICO",na=False),
                desc_c.str.contains("SABROSANO",na=False),
                desc_c.str.contains("GRANTRADICION",na=False),
                desc_c.str.contains("MISAZON|MISAZÓN",na=False),
                desc_c.str.contains("AVE",na=False) & (desc_c.str.contains("SOYA-CANOLA|AEROSOL",na=False)),
                desc_c.str.contains("NUTRIOLI",na=False) & desc_c.str.contains("FUSILLI|SPAGUETTI|FIDEO|CODO",na=False),
                desc_c.str.contains("OLI",na=False) & desc_c.str.contains("OLIVA|EV|AEROSOL",na=False),
                desc_c.str.contains("NUTRIOLI",na=False) & desc_c.str.contains("400ML|850ML",na=False) & ~desc_c.str.contains("PROTECT|DEFENSAS",na=False),
                desc_c.str.contains("NUTRIOLI",na=False),
            ]
            choices_c = ["BALSAMICO","SABROSANO","GT","MI SAZON","AVE","PASTAS","OLIVAS","NUTRIOLI","REST NUTRIOLI"]
            dff = dff.copy()
            dff['Category'] = np.select(conditions_c, choices_c, default=None)

            c_kpi, c_chart = st.columns([1, 2])
            with c_kpi:
                total_so = dff['SELL_OUT'].sum()
                st.markdown(f"<div class='kpi-card' style='height: 450px;'><div class='kpi-title'>Total Sell Out</div><div class='kpi-value' style='color:#FF6600;'>${total_so:,.2f}</div></div>", unsafe_allow_html=True)
            with c_chart:
                pie_df = dff.dropna(subset=['Category']).groupby('Category')['SELL_OUT'].sum().reset_index()
                pie_df = pie_df[pie_df['SELL_OUT'] > 0]
                if not pie_df.empty:
                    domain  = ["BALSAMICO","SABROSANO","PASTAS","OLIVAS","GT","NUTRIOLI","MI SAZON","AVE","REST NUTRIOLI"]
                    range_  = ["#e012a9","#f705ab","#4c915d","#97ad6a","#7d6010","#02c705","#e89015","#ff0000","#00ff04"]
                    color_map = dict(zip(domain, range_))
                    fig = px.pie(pie_df, values='SELL_OUT', names='Category', color='Category', color_discrete_map=color_map, hole=0.45)
                    fig.update_traces(
                        textposition='outside', textinfo='label+percent+value',
                        texttemplate='<b>%{label}</b><br>%{percent:.0%} | $%{value:,.0f}',
                        hovertemplate='<b>%{label}</b><br>Sell Out: $%{value:,.2f}<br>Porcentaje: %{percent:.0%}<extra></extra>'
                    )
                    fig.update_layout(showlegend=False, margin=dict(t=50,b=50,l=100,r=100), height=450, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", uniformtext_minsize=9, uniformtext_mode='hide')
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("Sin datos para gráfica.")

            view_mode = ""
            st.caption(f"📋 Vista: Completa")
            
            disp = dff[["NO_TIENDA","TIENDA","ARTICULO","INV_ULT_SEM","VTA_PROM_DIARIA","DIAS_INV","SELL_OUT"]].copy()
            disp.columns = ['NO_TIENDA','TIENDA','ARTICULO','INV_ULT_SEM','VTA_PROM_DIARIA','DIAS_INV','SELL_OUT']
            st.dataframe(disp.style.format({'INV_ULT_SEM':"{:,.0f}",'VTA_PROM_DIARIA':"{:,.2f}",'DIAS_INV':"{:,.1f}",'SELL_OUT':"${:,.2f}"}), use_container_width=True, hide_index=True, height=auto_height(disp))

        st.divider()
        st.markdown("<h3 style='text-align: center; color: #444;'>🏆 RANKING DE VENTAS</h3>", unsafe_allow_html=True)
        sel_st_rank = st.selectbox("Filtrar Estado (Ranking)", ["Todos"] + sorted(df_c["ESTADO"].unique()), key="c_rnk_st")

        cr1,cr2,cr3,cr4 = st.columns(4, gap="small")
        with cr1:
            st.markdown('<span class="marker-gen"></span>', unsafe_allow_html=True)
            st.button("📊 GENERAL",  key="c_rk_gen", on_click=set_c_rank, args=('GEN',), use_container_width=True, type="primary" if st.session_state.c_rank_gen else "secondary")
        with cr2:
            st.markdown('<span class="marker-pas"></span>', unsafe_allow_html=True)
            st.button("🍝 PASTAS",   key="c_rk_pas", on_click=set_c_rank, args=('PAS',), use_container_width=True, type="primary" if st.session_state.c_rank_pas else "secondary")
        with cr3:
            st.markdown('<span class="marker-oli"></span>', unsafe_allow_html=True)
            st.button("🫒 OLIVAS",   key="c_rk_oli", on_click=set_c_rank, args=('OLI',), use_container_width=True, type="primary" if st.session_state.c_rank_oli else "secondary")
        with cr4:
            st.markdown('<span class="marker-nut"></span>', unsafe_allow_html=True)
            st.button("🍃 NUTRIOLI", key="c_rk_nut", on_click=set_c_rank, args=('NUT',), use_container_width=True, type="primary" if st.session_state.c_rank_nut else "secondary")

        dff_rank = df_c.copy()
        if sel_st_rank != "Todos":
            dff_rank = dff_rank[dff_rank["ESTADO"] == sel_st_rank]

        list_gen = ["Vinagre Oli Nutrioli Balsámico 250 ml (3795515)","Aceite Sabrosano Mixto 850 ML (3691244)","Aceite Mi Sazón Vegetal 800 ML (3775895)","Pps Nutrioli Fusilli Integral (3878678)","Aceite Ave Soya-Canola 850 ML (3696190)","Pps Nutrioli Spaguetti 200 (3878673)","Pps Nutrioli Fusilli Verduras (3878676)","Pps Nutrioli Fideo 200 Gr (3878671)","Aceite Nutrioli Antigoteo 700 ML (3738492)","Pps Nutrioli Spaguetti Integra (3878677)","Pps Nutrioli Codo Verduras 200 (3878675)","Pps Nutrioli Codo 200 Gr (3878674)","Aceite Nutrioli Protect Defensas 850 ml (3828176)","Pps Nutrioli Fusilli 450 (3878672)","Ace Oliva EV Oli BOT 750 Ml (3284693)","Aceite Oliva Puro Oli Bote 750 Ml (3570620)","Ace Oliva EV Oli BOT 500 Ml (3368446)","Aceite Gran Tradición Soya-Canola 800 ML (3009894)","Aceite Nutrioli Protect Mente 850 Ml (3009960)","Aceite De Soya Nutrioli Bot 850 Ml (3132396)","Ace Oliva Puro Oli BOT 500 Ml (3570614)","Ace Oliva EV Oli BOT 250 Ml (3284690)","Aceite De Soya Nutrioli Bot 400 Ml (3590824)","Aceite Mi Sazón Mixto 400 ML","Aceite Aerosol Nutrioli Soya Lata 180 Gr (3317342)","Aceite Oli Extra Virgen 500 Ml (3646332)","Aceite Aerosol Ave Mixto 170 Gr (3693814)","Aceite de Oliva Oli Nutrioli 250 Ml (3679970)","Aceite Nutrioli Soya 850 ML (3676715)","Aceite Sabrosano Rinde + 850 ML (3782858)","Aceite Aerosol Oli Oliva 145 Ml (3679971)","Ace Oliva EV Oli BOT 500 Ml (3428657)","Aceite Nutrioli 850+Pps Fusill (3880416)","Aceite Nutrioli 850+Pps Codo 2 (3880415)"]
        list_pas = ["Pps Nutrioli Fusilli Integral (3878678)","Pps Nutrioli Spaguetti 200 (3878673)","Pps Nutrioli Fusilli Verduras (3878676)","Pps Nutrioli Fideo 200 Gr (3878671)","Pps Nutrioli Spaguetti Integra (3878677)","Pps Nutrioli Codo Verduras 200 (3878675)","Pps Nutrioli Codo 200 Gr (3878674)","Pps Nutrioli Fusilli 450 (3878672)","Aceite Nutrioli 850+Pps Fusill (3880416)","Aceite Nutrioli 850+Pps Codo 2 (3880415)"]
        list_oli = ["Ace Oliva EV Oli BOT 750 Ml (3284693)","Aceite Oliva Puro Oli Bote 750 Ml (3570620)","Ace Oliva EV Oli BOT 500 Ml (3368446)","Ace Oliva Puro Oli BOT 500 Ml (3570614)","Ace Oliva EV Oli BOT 250 Ml (3284690)","Aceite Oli Extra Virgen 500 Ml (3646332)","Aceite de Oliva Oli Nutrioli 250 Ml (3679970)","Aceite Aerosol Oli Oliva 145 Ml (3679971)","Ace Oliva EV Oli BOT 500 Ml (3428657)"]
        list_nut = ["Aceite De Soya Nutrioli Bot 850 Ml (3132396)"]

        target_list = []; rank_title = ""
        if   st.session_state.c_rank_gen: target_list = list_gen; rank_title = "VENTA GENERAL ($)"
        elif st.session_state.c_rank_pas: target_list = list_pas; rank_title = "VENTA PASTAS ($)"
        elif st.session_state.c_rank_oli: target_list = list_oli; rank_title = "VENTA OLIVAS ($)"
        elif st.session_state.c_rank_nut: target_list = list_nut; rank_title = "VENTA NUTRIOLI ($)"

        if target_list:
            dff_rank = dff_rank[dff_rank["ARTICULO"].isin(target_list)]
            if not dff_rank.empty:
                final_c_rank = dff_rank.groupby(["NO_TIENDA","TIENDA"])['SELL_OUT'].sum().reset_index()
                final_c_rank.columns = ['No Tienda','TIENDA', rank_title]
                final_c_rank = final_c_rank.sort_values(by=rank_title, ascending=False)
                st.dataframe(final_c_rank.style.format({rank_title:"${:,.2f}"}), use_container_width=True, hide_index=True, height=auto_height(final_c_rank))
            else:
                st.warning("⚠️ No se encontraron ventas para los productos seleccionados en este estado.")


# --- 9. EJECUTAR VISTA ACTIVA ---
if st.session_state.active_retailer == 'SORIANA':
    df_s = get_data("SORIANA", "up_s", load_sor)
    if df_s is not None: view_soriana(df_s)

elif st.session_state.active_retailer == 'WALMART':
    df_w = get_data("WALMART", "up_w", load_wal)
    if df_w is not None: view_walmart(df_w)

elif st.session_state.active_retailer == 'CHEDRAUI':
    df_c = get_data("CHEDRAUI", "up_c", load_che)
    if df_c is not None: view_chedraui(df_c)


# --- 10. PIE DE PÁGINA ---
st.divider()
if st.button("🗑️ LIMPIAR MEMORIA / RESET", use_container_width=True, type="secondary"):
    if not st.session_state.confirm_reset:
        st.session_state.confirm_reset = True
        st.error("⚠️ ¡CONFIRMACIÓN REQUERIDA! Haz clic de nuevo para resetear todo.")
        st.rerun()
    else:
        st.cache_data.clear()
        for key in list(st.session_state.keys()): del st.session_state[key]
        st.success("✅ Memoria limpiada. Reiniciando...")
        time.sleep(1)
        st.rerun()