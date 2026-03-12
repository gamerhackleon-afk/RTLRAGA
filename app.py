import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import numpy as np
import time
import requests
import plotly.express as px
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 1. CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(
    page_title="Dashboard de Inventarios",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- 2. CONFIGURACIÓN CENTRALIZADA ---
CACHE_CONFIG = {'ttl': 14400, 'max_entries': 10, 'show_spinner': False}  # 4 horas

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

# --- FUNCIÓN DE CONECTIVIDAD (definida ANTES de session_state para evitar NameError) ---
def _check_online() -> bool:
    """Verifica conectividad en tiempo real (Fix 7)."""
    try:
        requests.head("https://github.com", timeout=2)
        return True
    except Exception:
        return False

# --- INICIALIZACIÓN DE SESSION STATE ---
if 'is_online' not in st.session_state:
    st.session_state.is_online = _check_online()

if 'active_retailer' not in st.session_state:
    st.session_state.active_retailer = 'WALMART'

if 'confirm_reset' not in st.session_state:
    st.session_state.confirm_reset = False

# Flags de precarga
if 'data_loaded' not in st.session_state:
    st.session_state.data_loaded = False

if 'df_soriana' not in st.session_state:
    st.session_state.df_soriana = None

if 'df_walmart' not in st.session_state:
    st.session_state.df_walmart = None

if 'df_chedraui' not in st.session_state:
    st.session_state.df_chedraui = None

if 'load_errors' not in st.session_state:
    st.session_state.load_errors = {}

# --- INICIALIZACIÓN DE VARS DE VISTA (una sola vez, no en cada render) ---
_view_vars = [
    's_rojo','s_dias_inv','s_dias_prod','s_transito',
    's_rank_gen','s_rank_pas','s_rank_oli','s_rank_nut',
    'w_neg','w_4w','w_dias_inv','w_dias_prod',
    'w_rank_tiendas','w_rank_pastas','w_rank_olivas','w_nutri_top10',
    'c_neg_zero','c_dias_inv','c_rank_gen','c_rank_pas','c_rank_oli','c_rank_nut',
]
for _v in _view_vars:
    if _v not in st.session_state:
        st.session_state[_v] = False

# --- 3. FUNCIONES UTILITARIAS ---
def safe_mean(series):
    return series.mean() if not series.empty else 0

def apply_filters(df, filter_cols, selections):
    """Fix 4: verifica que la columna exista antes de filtrar para evitar KeyError."""
    mask = pd.Series(True, index=df.index)
    for col, sel in zip(filter_cols, selections):
        if sel and col in df.columns:          # ← guard de columna
            mask &= df[col].isin(sel)
    return df[mask]

def get_kpi_mean(df, desc_col, days_col, pattern):
    # Fix 5: fillna("") antes de operaciones str para evitar NaN silenciosos
    clean_desc = df[desc_col].fillna("").str.upper().str.replace("&NBSP;", "", regex=False).str.replace(" ", "", regex=False)
    clean_pattern = pattern.upper().replace("&NBSP;", "").replace(" ", "")
    mask = clean_desc.str.contains(clean_pattern, case=False, na=False)
    return safe_mean(df.loc[mask, days_col])

def auto_height(df):
    return min(max(len(df) * 35 + 45, 100), 600)

@st.cache_data(show_spinner=False)
def convert_df_to_excel(df):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Reporte')
    return output.getvalue()

@st.cache_data(show_spinner=False, ttl=14400)
def _make_pie(pie_df_json: str, domain: list, range_: list, val_col: str):
    """
    Cachea la figura Plotly por combinación de datos+colores.
    pie_df_json es el DataFrame serializado como JSON para que sea hashable.
    Evita reconstruir el gráfico en cada re-render del script.
    """
    import json
    pie_df = pd.read_json(pie_df_json)
    fig = px.pie(
        pie_df, values=val_col, names='Category',
        color='Category', color_discrete_map=dict(zip(domain, range_)), hole=0.45
    )
    fig.update_traces(
        textposition='outside', textinfo='label+percent+value',
        texttemplate='<b>%{label}</b><br>%{percent:.0%} | $%{value:,.0f}',
        hovertemplate='<b>%{label}</b><br>Sell Out: $%{value:,.2f}<br>Porcentaje: %{percent:.0%}<extra></extra>'
    )
    fig.update_layout(
        showlegend=False, margin=dict(t=50, b=50, l=100, r=100),
        height=450, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        uniformtext_minsize=9, uniformtext_mode='hide'
    )
    return fig

# --- SESSION HTTP GLOBAL (variable de módulo — segura para threads, no session_state) ---
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

def _build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.4,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(
        max_retries=retry,
        pool_connections=6,
        pool_maxsize=6,
    )
    session.mount("https://", adapter)
    session.mount("http://",  adapter)
    session.headers.update({
        "User-Agent":      "Mozilla/5.0",
        "Accept-Encoding": "gzip, deflate",
        "Connection":      "keep-alive",
    })
    return session

# Variable de módulo: existe una vez por proceso Python, accesible desde cualquier thread
_HTTP_SESSION = _build_session()

def download_file_fast(url: str):
    """
    Descarga optimizada:
    - Session Keep-Alive: reutiliza TCP, elimina handshake TLS repetido
    - ETag: devuelve caché si el archivo no cambió en GitHub
    - Streaming chunked 256 KB: empieza a procesar mientras llega
    - Timeout (connect=5s, read=30s): falla rápido si no hay red
    - Retry automático vía HTTPAdapter
    """
    etag_key  = f'etag_{url}'
    cache_key = f'cached_file_{url}'

    headers = {"If-None-Match": st.session_state.get(etag_key, "")}

    try:
        response = _HTTP_SESSION.get(url, headers=headers, timeout=(5, 30), stream=True)

        if response.status_code == 304:
            cached = st.session_state.get(cache_key)
            if cached is not None:
                cached.seek(0)
                return cached
            # Caché local ausente — forzar re-descarga sin ETag
            st.session_state.pop(etag_key, None)
            response = _HTTP_SESSION.get(url, timeout=(5, 30), stream=True)

        response.raise_for_status()

        buf = BytesIO()
        for chunk in response.iter_content(chunk_size=256 * 1024):
            if chunk:
                buf.write(chunk)

        st.session_state[etag_key] = response.headers.get("ETag", "")

        raw = buf.getvalue()
        cached_copy = BytesIO(raw)
        cached_copy.seek(0)
        st.session_state[cache_key] = cached_copy

        buf.seek(0)
        return buf

    except requests.exceptions.Timeout:
        st.session_state.is_online = _check_online()
        return None
    except Exception:
        return None

def download_file(url_or_file):
    if isinstance(url_or_file, str):
        return download_file_fast(url_or_file)
    url_or_file.seek(0)   # garantizar seek(0) también en uploads manuales
    return url_or_file

def set_retailer(retailer_name):
    st.session_state.active_retailer = retailer_name
    logic_vars = [
        's_rojo','s_dias_inv','s_dias_prod','s_transito','s_rank_gen','s_rank_pas','s_rank_oli','s_rank_nut',
        'w_neg','w_4w','w_dias_inv','w_dias_prod','w_rank_tiendas','w_rank_pastas','w_rank_olivas','w_nutri_top10',
        'c_neg_zero','c_dias_inv','c_rank_gen','c_rank_pas','c_rank_oli','c_rank_nut'
    ]
    for var in logic_vars:
        if var in st.session_state:
            st.session_state[var] = False

# --- 4. LECTURA DE EXCEL OPTIMIZADA ---
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
        if source is None: return None
        needed_cols = [0, 2, 3, 4, 5, 6, 7, 8, 21, 22, 23, 24, 25, 26, 27, 28, 30]
        try:
            df = pd.read_excel(source, engine='calamine', usecols=needed_cols)
        except Exception:
            source.seek(0)
            df = pd.read_excel(source, engine='openpyxl', usecols=needed_cols)
        # Fix 1: validar que el Excel tenga las columnas esperadas antes de indexar
        if len(df.columns) < 17:
            return None
        col_map = {
            df.columns[0]:  "RESURTIMIENTO", df.columns[1]:  "CODIGO", df.columns[2]:  "DESCRIPCION",
            df.columns[3]:  "NO_TIENDA", df.columns[4]:  "TIENDA", df.columns[5]:  "CIUDAD",
            df.columns[6]:  "ESTADO", df.columns[7]:  "FORMATO", df.columns[8]:  "SEM1",
            df.columns[9]:  "SEM2", df.columns[10]: "SEM3", df.columns[11]: "SO_$",
            df.columns[12]: "PEDIDOS", df.columns[13]: "FECHA_ENTREGA", df.columns[14]: "CANTIDAD_PZS",
            df.columns[15]: "INV_CAJAS", df.columns[16]: "DIAS_INV",
        }
        df.rename(columns=col_map, inplace=True)
        df["CODIGO"] = df["CODIGO"].fillna("").astype(str).str.replace(r'\.0*$', '', regex=True)
        for c in ["DIAS_INV", "INV_CAJAS", "SO_$", "SEM1", "SEM2", "SEM3", "PEDIDOS", "CANTIDAD_PZS"]:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
        df["FECHA_ENTREGA"] = df["FECHA_ENTREGA"].fillna("").astype(str).replace("nan", "")
        df['SO_4SEM'] = df[["SEM1", "SEM2", "SEM3", "SO_$"]].sum(axis=1)
        df['SIN_VTA'] = (df['SO_4SEM'] == 0)
        df['VTA_PROM'] = df['SO_4SEM']
        df = _str_cols(df, ["RESURTIMIENTO", "NO_TIENDA", "TIENDA", "CIUDAD", "ESTADO", "FORMATO", "DESCRIPCION"])
        # Fix 5+6: columna de descripción normalizada precalculada una sola vez (evita recalcular en cada str.contains)
        df["DESC_NORM"] = df["DESCRIPCION"].fillna("").str.upper().str.replace(" ", "", regex=False).str.replace("&NBSP;", "", regex=False)
        return optimize_floats(df)
    except Exception:
        return None

@st.cache_data(**CACHE_CONFIG)
def load_wal(path):
    try:
        source = download_file(path)
        if source is None: return None
        needed_cols = [0, 4, 5, 7, 15, 16, 18, 33, 42, 73, 74, 75, 76, 95, 96]
        try:
            df = pd.read_excel(source, engine='calamine', usecols=needed_cols)
        except Exception:
            source.seek(0)
            df = pd.read_excel(source, engine='openpyxl', usecols=needed_cols)
        # Fix 1: validar columnas antes de indexar
        if len(df.columns) < 15:
            return None
        col_map = {df.columns[0]:"CODIGO",df.columns[1]:"DESCRIPCION",df.columns[2]:"CATEGORIA",
                   df.columns[3]:"ESTADO",df.columns[4]:"TIENDA",df.columns[5]:"FORMATO",
                   df.columns[6]:"MARCA",df.columns[7]:"DIAS_INV",df.columns[8]:"EXISTENCIA",
                   df.columns[9]:"VTA_S1",df.columns[10]:"VTA_S2",df.columns[11]:"VTA_S3",
                   df.columns[12]:"VTA_S4",df.columns[13]:"SO_SEM_ANT",df.columns[14]:"SO_$"}
        df.rename(columns=col_map, inplace=True)
        df["CODIGO"] = df["CODIGO"].fillna("").astype(str).str.replace(r'\.0*$', '', regex=True)
        for c in ["DIAS_INV","EXISTENCIA","VTA_S1","VTA_S2","VTA_S3","VTA_S4","SO_SEM_ANT","SO_$"]:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
        df['PROM_PZS_MENSUAL'] = df[["VTA_S1","VTA_S2","VTA_S3","VTA_S4"]].mean(axis=1)
        df = _str_cols(df, ["CODIGO","DESCRIPCION","CATEGORIA","ESTADO","TIENDA","FORMATO","MARCA"])
        # Fix 5+6: descripción normalizada precalculada
        df["DESC_NORM"] = df["DESCRIPCION"].fillna("").str.upper().str.replace(" ", "", regex=False).str.replace("&NBSP;", "", regex=False)
        return optimize_floats(df)
    except Exception:
        return None

@st.cache_data(**CACHE_CONFIG)
def load_che(path):
    try:
        source = download_file(path)
        if source is None: return None
        needed_cols = [3, 4, 5, 6, 7, 8, 9, 10, 12, 13, 17, 18, 19]
        try:
            df = pd.read_excel(source, engine='calamine', usecols=needed_cols)
        except Exception:
            source.seek(0)
            df = pd.read_excel(source, engine='openpyxl', usecols=needed_cols)
        # Fix 1: validar columnas antes de indexar
        if len(df.columns) < 13:
            return None
        col_map = {df.columns[0]:"ESTADO",df.columns[1]:"COORDINADOR",df.columns[2]:"EJECUTIVO",
                   df.columns[3]:"PROMOTOR",df.columns[4]:"COL_FILTRO",df.columns[5]:"CATEGORIA",
                   df.columns[6]:"NO_TIENDA",df.columns[7]:"TIENDA",df.columns[8]:"ARTICULO",
                   df.columns[9]:"INV_ULT_SEM",df.columns[10]:"VTA_PROM_DIARIA",
                   df.columns[11]:"DIAS_INV",df.columns[12]:"SELL_OUT"}
        df.rename(columns=col_map, inplace=True)
        col_h = pd.to_numeric(df["COL_FILTRO"], errors='coerce')
        df = df[col_h != 0]
        df = df.dropna(subset=["ARTICULO"])
        df = df[pd.to_numeric(df["NO_TIENDA"], errors='coerce').notna()]
        for col in ["INV_ULT_SEM", "VTA_PROM_DIARIA", "DIAS_INV", "SELL_OUT"]:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        df = _str_cols(df, ["ESTADO", "COORDINADOR", "EJECUTIVO", "PROMOTOR", "CATEGORIA", "NO_TIENDA", "TIENDA", "ARTICULO"])
        # Fix 5+6: artículo normalizado precalculado
        df["DESC_NORM"] = df["ARTICULO"].fillna("").str.upper().str.replace(" ", "", regex=False).str.replace("&NBSP;", "", regex=False)
        return optimize_floats(df)
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════
# LISTAS DE PRODUCTOS — constantes de módulo, se definen UNA SOLA VEZ
# No se recalculan en cada render (evita crear listas de 30+ strings
# en cada click del usuario)
# ══════════════════════════════════════════════════════════════════════
_SOR_DIAS_PROD = ["ACEITE DE SOYA NUTRIOLI BOT 850 ML","ACEITE COMESTIBLE NUTRIOLI 400 ML","ACEITE COMESTIBLE SABROSANO 850 ML","ACEITE COMESTIBLE GRAN TRADICION 800 ML","ACEITE NUTRIOLI PROTECT DEFENSAS 850ML","ACEITE NUTRIOLI PROTECT MENTE 850 ML","ACEITE COMESTIBLE NUTRIOLI AEROSOL 180ML","ACEITE COMESTIBLE NUTRIOLI ANTIGOTEO 700","ACEITE OLI OLIVA EXTRA VIRGEN PZ 250ML","ACEITE OLI OLIVA EXTRA VIRGEN PZ 500ML","ACEITE OLI OLIVA EXTRA VIRGEN PZ 750ML","ADERE OLI OLIVA PARA COCINAR 500 ML OLI","ADERE OLI OLIVA PARA COCINAR 750 ML OLI","ADEREZO OLI 250 ML PZ","ADEREZO OLI 500 ML BOT","ACEITE COMESTIBLE AVE 850 ML","ACEITE COMESTIBLE AEROSOL 170GR","ACEITE OLIVA OLI PURO SPRAY 145 ML","ACEITE OLIVA OLI EV SPRAY 145 ML","PASTA FIDEO NUTRIOLI 200GR","PASTA SPAGHETTI NUTRIOLI INTEGRAL 200GR","PASTA FUSILLI INTEGRAL NUTRIOLI 200GR","PASTA CODO NUTRIOLI VERDURAS 200GR","PASTA FUSILLI VERDURAS NUTRIOLI 450GR","PASTA SPAGHETTI NUTRIOLI 200GR","PASTA CODO NUTRIOLI 200GR","VINAGRE BALSAMICO 250ML"]
_SOR_RANK_GEN  = ["ACEITE COMESTIBLE NUTRIOLI ANTIGOTEO 700","ACEITE COMESTIBLE GRAN TRADICION 900 ML","ACEITE COMESTIBLE SABROSANO +30 850 ML","ACEITE OLIVA OLI PURO SPRAY 145 ML","JUSTO 850 ML","ACEITE COMESTIBLE AEROSOL 170GR","ACEITE COMESTIBLE AVE 850 ML","ACEITE COMESTIBLE NUTRIOLI 400 ML","ACEITE COMESTIBLE NUTRIOLI AEROSOL 180ML","ACEITE COMESTIBLE NUTRIOLI DHA 850 ML","ACEITE COMESTIBLE SABROSANO 850 ML","SABROSANO RINDE+ 850 ML","ACEITE OLI OLIVA EXTRA VIRGEN PZ 250ML","ACEITE OLI OLIVA EXTRA VIRGEN PZ 500ML","ACEITE OLI OLIVA EXTRA VIRGEN PZ 750ML","ADERE OLI OLIVA PARA COCINAR 500 ML OLI","ADERE OLI OLIVA PARA COCINAR 750 ML OLI","ADEREZO OLI 250 ML PZ","ADEREZO OLI 500 ML BOT","ACEITE COMESTIBLE GRAN TRADICION 800 ML","ACEITE DE SOYA NUTRIOLI BOT 850 ML","VINAGRE BALSAMICO 250ML","ACEITE NUTRIOLI PROTECT DEFENSAS 850ML","ACEITE NUTRIOLI PROTECT MENTE 850 ML","PASTA FIDEO NUTRIOLI 200GR","PASTA SPAGHETTI NUTRIOLI INTEGRAL 200GR","PASTA FUSILLI INTEGRAL NUTRIOLI 200GR","PASTA CODO NUTRIOLI VERDURAS 200GR","PASTA FUSILLI VERDURAS NUTRIOLI 450GR","PASTA SPAGHETTI NUTRIOLI 200GR","PASTA CODO NUTRIOLI 200GR"]
_SOR_RANK_PAS  = ["PASTA FIDEO NUTRIOLI 200GR","PASTA SPAGHETTI NUTRIOLI INTEGRAL 200GR","PASTA FUSILLI INTEGRAL NUTRIOLI 200GR","PASTA CODO NUTRIOLI VERDURAS 200GR","PASTA FUSILLI VERDURAS NUTRIOLI 450GR","PASTA SPAGHETTI NUTRIOLI 200GR","PASTA CODO NUTRIOLI 200GR"]
_SOR_RANK_OLI  = ["ACEITE OLI OLIVA EXTRA VIRGEN PZ 250ML","ACEITE OLI OLIVA EXTRA VIRGEN PZ 500ML","ACEITE OLI OLIVA EXTRA VIRGEN PZ 750ML","ADERE OLI OLIVA PARA COCINAR 500 ML OLI","ADERE OLI OLIVA PARA COCINAR 750 ML OLI","ADEREZO OLI 250 ML PZ","ADEREZO OLI 500 ML BOT","ACEITE OLIVA OLI PURO SPRAY 145 ML"]
_SOR_RANK_NUT  = ["ACEITE DE SOYA NUTRIOLI BOT 850 ML"]

_WAL_DIAS_PROD = ["NUTRIOLI ACEITE PURO DE SOYA 946 ML","NUTRIOLI ACEITE PURO DE SOYA 400 ML","SABROSANO ACEITE 850ML MANTEQUILLA","ACEITE COMESTIBLE GRAN TRADICION 850ML","ACEITE SOYA NUTRIOLI ANTIGOTEO 700ML","ACEITE NUTRIOLI DEFENSAS 850 ML","NUTRIOLI ACEITE PROTECT MENTE 850 ML","NUTRIOLI SPRAY 180 ML","AVE AEROSOL 170GR","OLI SPRAY ACEITE DE OLIVA 145ML","OLI SPRAY ACEITE DE OLIVA EV 145ML","OLI DE NUTRIOLI EXTRA VIRGEN 250ML","OLI DE NUTRIOLI ACEITE DE OLIVA 500ML","OLI DE NUTRIOLI ACEITE DE OLIVA 750ML","OLI ACEITE DE OLIVA COCINA 250ML","ACEITE DE OLIVA EXTRA VIRGEN OLI DE NUTR","ACEITE OLI DE OLIVA EX VIRGEN ORGANICO","OLI NUTRIOLI VINAGRE BALSAMICO MODENA250","VINAGRE DE JEREZ 250 ML","VINAGRE DE MANZANA ECOLOGICO","VINAGRE DE SIDRA 250 ML","VINAGRE DE VINO AL  AJO 250 ML","VINAGRE DE VINO DE RIOJA BOTELLA 250ML","VINAGRE DE VINO FRAMBUESA","BORGES ACEITE DE OLIVA EXTRA VIRGEN ECOL","BORGES ACEITE DE PEPITA UVA 500ML","BORGES ACEITE OLIVA 100 PURO CON AJO","BORGES ACEITE OLIVA EXTRA SUAVE","BORGES ACEITE OLIVA EXTRA VIRGEN 500","BORGES VINAGRE BALSAMICO 250ML","BORGES VINAGRE DE VINOTINTO","BORGES VINAGRE VINO BLANCO","ACEITE DE OLIVA A LA ALBAHACA FRESCA","ACEITE DE OLIVA AL  ROMERO FRESCO","ACEITE DE OLIVA AL AJO FRITO","ACEITE DE OLIVA EXTRA VIRGEN KOSHER","ACEITE DE SOJA JENGIBRE"]

_CHE_RANK_GEN  = ["Vinagre Oli Nutrioli Balsámico 250 ml (3795515)","Aceite Sabrosano Mixto 850 ML (3691244)","Aceite Mi Sazón Vegetal 800 ML (3775895)","Pps Nutrioli Fusilli Integral (3878678)","Aceite Ave Soya-Canola 850 ML (3696190)","Pps Nutrioli Spaguetti 200 (3878673)","Pps Nutrioli Fusilli Verduras (3878676)","Pps Nutrioli Fideo 200 Gr (3878671)","Aceite Nutrioli Antigoteo 700 ML (3738492)","Pps Nutrioli Spaguetti Integra (3878677)","Pps Nutrioli Codo Verduras 200 (3878675)","Pps Nutrioli Codo 200 Gr (3878674)","Aceite Nutrioli Protect Defensas 850 ml (3828176)","Pps Nutrioli Fusilli 450 (3878672)","Ace Oliva EV Oli BOT 750 Ml (3284693)","Aceite Oliva Puro Oli Bote 750 Ml (3570620)","Ace Oliva EV Oli BOT 500 Ml (3368446)","Aceite Gran Tradición Soya-Canola 800 ML (3009894)","Aceite Nutrioli Protect Mente 850 Ml (3009960)","Aceite De Soya Nutrioli Bot 850 Ml (3132396)","Ace Oliva Puro Oli BOT 500 Ml (3570614)","Ace Oliva EV Oli BOT 250 Ml (3284690)","Aceite De Soya Nutrioli Bot 400 Ml (3590824)","Aceite Mi Sazón Mixto 400 ML","Aceite Aerosol Nutrioli Soya Lata 180 Gr (3317342)","Aceite Oli Extra Virgen 500 Ml (3646332)","Aceite Aerosol Ave Mixto 170 Gr (3693814)","Aceite de Oliva Oli Nutrioli 250 Ml (3679970)","Aceite Nutrioli Soya 850 ML (3676715)","Aceite Sabrosano Rinde + 850 ML (3782858)","Aceite Aerosol Oli Oliva 145 Ml (3679971)","Ace Oliva EV Oli BOT 500 Ml (3428657)","Aceite Nutrioli 850+Pps Fusill (3880416)","Aceite Nutrioli 850+Pps Codo 2 (3880415)"]
_CHE_RANK_PAS  = ["Pps Nutrioli Fusilli Integral (3878678)","Pps Nutrioli Spaguetti 200 (3878673)","Pps Nutrioli Fusilli Verduras (3878676)","Pps Nutrioli Fideo 200 Gr (3878671)","Pps Nutrioli Spaguetti Integra (3878677)","Pps Nutrioli Codo Verduras 200 (3878675)","Pps Nutrioli Codo 200 Gr (3878674)","Pps Nutrioli Fusilli 450 (3878672)","Aceite Nutrioli 850+Pps Fusill (3880416)","Aceite Nutrioli 850+Pps Codo 2 (3880415)"]
_CHE_RANK_OLI  = ["Ace Oliva EV Oli BOT 750 Ml (3284693)","Aceite Oliva Puro Oli Bote 750 Ml (3570620)","Ace Oliva EV Oli BOT 500 Ml (3368446)","Ace Oliva Puro Oli BOT 500 Ml (3570614)","Ace Oliva EV Oli BOT 250 Ml (3284690)","Aceite Oli Extra Virgen 500 Ml (3646332)","Aceite de Oliva Oli Nutrioli 250 Ml (3679970)","Aceite Aerosol Oli Oliva 145 Ml (3679971)","Ace Oliva EV Oli BOT 500 Ml (3428657)"]
_CHE_RANK_NUT  = ["Aceite De Soya Nutrioli Bot 850 Ml (3132396)"]

# Sets precalculados para isin() — O(1) lookup en lugar de O(n) en lista
_SOR_RANK_GEN_SET  = frozenset(s.strip() for s in _SOR_RANK_GEN)
_SOR_RANK_PAS_SET  = frozenset(s.strip() for s in _SOR_RANK_PAS)
_SOR_RANK_OLI_SET  = frozenset(s.strip() for s in _SOR_RANK_OLI)
_SOR_RANK_NUT_SET  = frozenset(s.strip() for s in _SOR_RANK_NUT)
_CHE_RANK_GEN_SET  = frozenset(s.strip() for s in _CHE_RANK_GEN)
_CHE_RANK_PAS_SET  = frozenset(s.strip() for s in _CHE_RANK_PAS)
_CHE_RANK_OLI_SET  = frozenset(s.strip() for s in _CHE_RANK_OLI)
_CHE_RANK_NUT_SET  = frozenset(s.strip() for s in _CHE_RANK_NUT)
# Patrones normalizados para dias_prod (pre-strip una vez)
_SOR_DIAS_PROD_NORM = [s.upper().replace("&NBSP;","").replace(" ","") for s in _SOR_DIAS_PROD]
_WAL_DIAS_PROD_NORM = [s.upper().replace("&NBSP;","").replace(" ","") for s in _WAL_DIAS_PROD]

# --- 5. CARGA PARALELA DE LAS 3 BASES ---
def _download_raw(key: str) -> tuple[str, BytesIO | None, str | None]:
    """
    Fase 1: solo descarga bytes — sin parsear.
    Corre en thread propio para solapar las 3 descargas de red simultáneamente.
    """
    try:
        buf = download_file_fast(URLS_DB[key])
        if buf is None:
            return key, None, "No se pudo descargar el archivo."
        return key, buf, None
    except Exception as e:
        return key, None, str(e)

def _parse_raw(key: str, buf: BytesIO):
    """
    Fase 2: parseo CPU sobre el buf ya descargado — sin tocar la red.
    Recibe el BytesIO directamente para evitar doble descarga.
    """
    NEEDED = {"SORIANA": 17, "WALMART": 15, "CHEDRAUI": 13}
    try:
        buf.seek(0)
        try:
            df = pd.read_excel(buf, engine='calamine')
        except Exception:
            buf.seek(0)
            df = pd.read_excel(buf, engine='openpyxl')
        if len(df.columns) < NEEDED[key]:
            return key, None, f"Columnas insuficientes ({len(df.columns)} < {NEEDED[key]})"
        # Reusar el loader completo pasando el buf como archivo local
        buf.seek(0)
        loaders = {"SORIANA": load_sor, "WALMART": load_wal, "CHEDRAUI": load_che}
        df = loaders[key](buf)
        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            return key, None, "Archivo vacío o sin columnas válidas."
        return key, df, None
    except Exception as e:
        return key, None, str(e)

def _load_one(key: str) -> tuple[str, object, str | None]:
    """Descarga + parseo completo para un retailer."""
    loaders = {"SORIANA": load_sor, "WALMART": load_wal, "CHEDRAUI": load_che}
    try:
        df = loaders[key](URLS_DB[key])
        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            return key, None, "Archivo vacío o sin columnas válidas."
        return key, df, None
    except Exception as e:
        return key, None, str(e)

def load_all_parallel():
    """
    Pipeline de 2 fases para máxima velocidad:

    FASE 1 — Descarga paralela (I/O puro, 3 threads):
      Las 3 descargas de red corren simultáneamente.
      El tiempo total = el archivo más lento (no la suma de los 3).

    FASE 2 — Parseo paralelo (CPU, 3 threads):
      Los 3 pd.read_excel corren simultáneamente sobre los bytes ya en memoria.
      GIL no es problema aquí porque read_excel libera el GIL en I/O de BytesIO.

    Session HTTP con Keep-Alive: la conexión TCP a GitHub CDN se reutiliza
    entre las descargas, eliminando el handshake TLS repetido.
    """
    keys    = list(URLS_DB.keys())
    results = {}
    errors  = {}

    # ── Pantalla de carga ──────────────────────────────────────────────
    st.markdown("""
    <style>
    .loader-wrap {
        display:flex; flex-direction:column; align-items:center;
        justify-content:center; padding: 60px 20px;
    }
    .loader-title {
        font-size:1.6rem; font-weight:800; color:#333;
        margin-bottom:8px; text-align:center;
    }
    .loader-sub {
        font-size:0.95rem; color:#777; margin-bottom:32px; text-align:center;
    }
    .retailer-badges { display:flex; gap:16px; margin-bottom:32px; flex-wrap:wrap; justify-content:center; }
    .badge {
        padding:8px 20px; border-radius:20px; font-weight:700;
        font-size:0.85rem; color:white; opacity:0.4;
        transition: opacity 0.3s;
    }
    .badge.done { opacity:1; }
    .badge-sor { background:#D32F2F; }
    .badge-wal { background:#0071DC; }
    .badge-che { background:#FF6600; }
    </style>
    """, unsafe_allow_html=True)

    placeholder  = st.empty()
    progress_bar = st.progress(0)
    status_text  = st.empty()

    def render_screen(pct, msg, done_set, phase=""):
        sor_cls = "done" if "SORIANA"  in done_set else ""
        wal_cls = "done" if "WALMART"  in done_set else ""
        che_cls = "done" if "CHEDRAUI" in done_set else ""
        placeholder.markdown(f"""
        <div class="loader-wrap">
            <div class="loader-title">⚙️ Sincronizando bases de datos</div>
            <div class="loader-sub">{phase}</div>
            <div class="retailer-badges">
                <span class="badge badge-sor {sor_cls}">{'✅' if sor_cls else '⏳'} SORIANA</span>
                <span class="badge badge-wal {wal_cls}">{'✅' if wal_cls else '⏳'} WALMART</span>
                <span class="badge badge-che {che_cls}">{'✅' if che_cls else '⏳'} CHEDRAUI</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
        progress_bar.progress(pct)
        status_text.markdown(
            f"<p style='text-align:center;color:#555;font-size:0.9rem;'>{msg} — <b>{int(pct*100)}%</b></p>",
            unsafe_allow_html=True
        )

    # ── FASE 1: descarga paralela (0% → 50%) ──────────────────────────
    render_screen(0.0, "Conectando a GitHub CDN…", set(), "📡 Fase 1/2 — Descargando archivos en paralelo")
    raw_buffers = {}
    done_dl = set()
    n = len(keys)

    with ThreadPoolExecutor(max_workers=min(3, n)) as executor:
        future_map = {executor.submit(_download_raw, k): k for k in keys}
        for future in as_completed(future_map):
            key, buf, err = future.result()
            if buf is not None:
                raw_buffers[key] = buf
            else:
                errors[key] = err or "Error de descarga"
                results[key] = None
            done_dl.add(key)
            pct = 0.0 + (len(done_dl) / n) * 0.50   # 0% → 50%
            msg = f"⬇️ {key} descargado" if buf else f"⚠️ Error descargando {key}"
            render_screen(pct, msg, done_dl if buf else set(), "📡 Fase 1/2 — Descargando archivos en paralelo")

    # ── FASE 2: parseo paralelo (50% → 100%) ──────────────────────────
    render_screen(0.50, "Procesando archivos Excel…", set(), "⚙️ Fase 2/2 — Procesando Excel en paralelo")
    done_parse = set()
    keys_to_parse = [k for k in keys if k in raw_buffers]

    with ThreadPoolExecutor(max_workers=min(3, len(keys_to_parse) or 1)) as executor:
        future_map = {executor.submit(_parse_raw, k, raw_buffers[k]): k for k in keys_to_parse}
        for future in as_completed(future_map):
            key, df, err = future.result()
            if df is not None and isinstance(df, pd.DataFrame) and not df.empty:
                results[key] = df
            else:
                results[key] = None
                if not errors.get(key):
                    errors[key] = err or "Parseo fallido"
            done_parse.add(key)
            pct = 0.50 + (len(done_parse) / n) * 0.50   # 50% → 100%
            msg = f"✅ {key} listo" if results.get(key) is not None else f"⚠️ Error en {key}"
            all_done = done_dl | {k for k in done_parse}
            render_screen(pct, msg, {k for k in done_parse if results.get(k) is not None},
                          "⚙️ Fase 2/2 — Procesando Excel en paralelo")

    # ── Finalizar ──────────────────────────────────────────────────────
    ok_count = sum(1 for v in results.values() if v is not None)
    progress_bar.progress(1.0)
    status_text.markdown(
        f"<p style='text-align:center;color:#28a745;font-weight:700;font-size:1rem;'>"
        f"✅ ¡Carga completa! {ok_count}/{n} bases cargadas — 100%</p>",
        unsafe_allow_html=True
    )
    time.sleep(0.5)
    placeholder.empty()
    progress_bar.empty()
    status_text.empty()

    return results, errors


# --- 6. ESTADOS ACTUALES ---
act          = st.session_state.active_retailer
active_color = RETAILER_COLORS.get(act, "#333333")

s_rojo       = st.session_state.get('s_rojo',       False)
s_dias_inv   = st.session_state.get('s_dias_inv',   False)
s_dias_prod  = st.session_state.get('s_dias_prod',  False)
s_transito   = st.session_state.get('s_transito',   False)
s_rank_gen   = st.session_state.get('s_rank_gen',   False)
s_rank_pas   = st.session_state.get('s_rank_pas',   False)
s_rank_oli   = st.session_state.get('s_rank_oli',   False)
s_rank_nut   = st.session_state.get('s_rank_nut',   False)

w_neg          = st.session_state.get('w_neg',          False)
w_4w           = st.session_state.get('w_4w',           False)
w_dias_inv     = st.session_state.get('w_dias_inv',     False)
w_dias_prod    = st.session_state.get('w_dias_prod',    False)
w_rank_tiendas = st.session_state.get('w_rank_tiendas', False)
w_rank_pastas  = st.session_state.get('w_rank_pastas',  False)
w_rank_olivas  = st.session_state.get('w_rank_olivas',  False)
w_nutri_top10  = st.session_state.get('w_nutri_top10',  False)

c_neg_zero = st.session_state.get('c_neg_zero', False)
c_dias_inv = st.session_state.get('c_dias_inv', False)
c_rank_gen = st.session_state.get('c_rank_gen', False)
c_rank_pas = st.session_state.get('c_rank_pas', False)
c_rank_oli = st.session_state.get('c_rank_oli', False)
c_rank_nut = st.session_state.get('c_rank_nut', False)

# --- 7. FUNCIÓN INYECTORA DE ESTILOS JS ---
def inject_button_styles():
    _dias_active = s_dias_inv or w_dias_inv or c_dias_inv
    _prod_active = s_dias_prod or w_dias_prod
    _neg_active  = w_neg or c_neg_zero

    _dias_bg = "#00695C"
    _dias_shadow = "rgba(0,105,92,0.85)"
    _dias_border_inact = "#80CBC4"

    _prod_bg = "#1D362B"
    _prod_shadow = "rgba(74,20,140,0.85)"
    _prod_border_inact = "#CE93D8"

    _neg_bg = "#D32F2F"
    if act == "WALMART":
        _neg_shadow = "rgba(230,81,0,0.85)"
        _neg_border_inact = "#FFAB40"
    else:
        _neg_shadow = "rgba(183,28,28,0.85)"
        _neg_border_inact = "#EF9A9A"

    _gen_active = s_rank_gen or w_rank_tiendas or c_rank_gen
    _pas_active = s_rank_pas or w_rank_pastas  or c_rank_pas
    _oli_active = s_rank_oli or w_rank_olivas  or c_rank_oli
    _nut_active = s_rank_nut or w_nutri_top10  or c_rank_nut

    STYLES = [
        ("SORIANA",  "linear-gradient(135deg,#D32F2F,#B71C1C)", "#ffffff", act=="SORIANA",  "#ffffff", "rgba(0,0,0,0.3)", False, "transparent"),
        ("WALMART",  "linear-gradient(135deg,#0071DC,#005BB5)", "#ffffff", act=="WALMART",  "#ffffff", "rgba(0,0,0,0.3)", False, "transparent"),
        ("CHEDRAUI", "linear-gradient(135deg,#FF6600,#E65100)", "#ffffff", act=="CHEDRAUI", "#ffffff", "rgba(0,0,0,0.3)", False, "transparent"),
        ("🔴 INV SIN VENTA", "#D32F2F", "#ffffff", s_rojo, "#ffffff", "rgba(211,47,47,0.85)", False, "#ef9a9a"),
        ("🚚 PEDIDOS EN TRANSITO", "#8507F0", "#ffffff", s_transito, "#ffffff", "rgba(176,108,240,0.85)", False, "#CE93D8"),
        ("🔴 SIN VTA 4SEM",  "#D32F2F", "#ffffff", w_4w,   "#ffffff", "rgba(0,113,220,0.85)", False, "#90CAF9"),
        ("📅 DIAS INV",    _dias_bg, "#ffffff", _dias_active, "#ffffff", _dias_shadow,  False, _dias_border_inact),
        ("📋 DIAS X PROD", _prod_bg, "#ffffff", _prod_active, "#ffffff", _prod_shadow, False, _prod_border_inact),
        ("📉 NEGATIVOS",   _neg_bg,  "#ffffff", _neg_active,  "#ffffff", _neg_shadow,  False, _neg_border_inact),
        ("📊 GENERAL",  "#FFFFFF","#5AB027", _gen_active, "#D4D4D4","rgba(46,125,50,0.70)", False, "#D4D4D4"),
        ("🍝 PASTAS",   "#DBBB35","#FFFFFF", _pas_active, "#D4D4D4","rgba(240,228,2,0.70)", True,  "transparent"),
        ("🫒 OLIVAS",   "#4E5C02","#FFFFFF", _oli_active, "#D4D4D4","rgba(46,125,50,0.70)", True,  "transparent"),
        ("🍃 NUTRIOLI", "#2E7D32","#FFD700", _nut_active, "#D4D4D4","rgba(46,125,50,0.70)", True,  "transparent"),
        ("🏆 NUTRIOLI", "#2E7D32","#FFD700", _nut_active, "#D4D4D4","rgba(46,125,50,0.70)", True,  "transparent"),
    ]

    js_cases = []
    for (label, bg, fg, active, border_act, shadow_act, gs, border_inact) in STYLES:
        gs_val = "grayscale(100%)" if gs else "none"
        esc    = label.replace("\\","\\\\").replace("'","\\'")
        border_inact_str = "none" if border_inact == "transparent" else f"1px solid {border_inact}"

        if active:
            props = (
                f"b.style.setProperty('background','{bg}','important');"
                f"b.style.setProperty('color','{fg}','important');"
                f"b.style.setProperty('font-weight','800','important');"
                f"b.style.setProperty('border-radius','8px','important');"
                f"b.style.setProperty('border','2px solid {border_act}','important');"
                f"b.style.setProperty('box-shadow','0 4px 18px {shadow_act}','important');"
                f"b.style.setProperty('opacity','1','important');"
                f"b.style.setProperty('transform','scale(1.04)','important');"
                f"b.style.setProperty('filter','none','important');"
                f"b.style.setProperty('transition','all 0.2s','important');"
            )
            if label in ("SORIANA","WALMART","CHEDRAUI"):
                props += (
                    "b.style.setProperty('border','3px solid #ffffff','important');"
                    "b.style.setProperty('transform','scale(1.02)','important');"
                    "b.style.setProperty('box-shadow','0 8px 16px rgba(0,0,0,0.3)','important');"
                    "b.style.setProperty('height',window.innerWidth<=768?'50px':'70px','important');"
                    "b.style.setProperty('font-size',window.innerWidth<=768?'0.8rem':'1.1rem','important');"
                    "b.style.setProperty('text-transform','uppercase','important');"
                    "b.style.setProperty('border-radius','10px','important');"
                )
        else:
            props = (
                f"b.style.setProperty('background','{bg}','important');"
                f"b.style.setProperty('color','{fg}','important');"
                f"b.style.setProperty('font-weight','800','important');"
                f"b.style.setProperty('border-radius','8px','important');"
                f"b.style.setProperty('border','{border_inact_str}','important');"
                f"b.style.setProperty('box-shadow','none','important');"
                f"b.style.setProperty('opacity','0.5','important');"
                f"b.style.setProperty('transform','scale(0.97)','important');"
                f"b.style.setProperty('filter','{gs_val}','important');"
                f"b.style.setProperty('transition','all 0.2s','important');"
            )
            if label in ("SORIANA","WALMART","CHEDRAUI"):
                props += (
                    "b.style.setProperty('opacity','0.6','important');"
                    "b.style.setProperty('transform','scale(0.98)','important');"
                    "b.style.setProperty('filter','grayscale(40%)','important');"
                    "b.style.setProperty('border','1px solid transparent','important');"
                    "b.style.setProperty('height',window.innerWidth<=768?'50px':'70px','important');"
                    "b.style.setProperty('font-size',window.innerWidth<=768?'0.8rem':'1.1rem','important');"
                    "b.style.setProperty('text-transform','uppercase','important');"
                    "b.style.setProperty('border-radius','10px','important');"
                )

        js_cases.append(f"if(t==='{esc}'){{{props}}}")

    all_cases = "\n        ".join(js_cases)
    html_code = f"""
<script>
(function() {{
    var doc = window.parent.document;
    function applyStyles() {{
        doc.querySelectorAll('button').forEach(function(b) {{
            var t = (b.innerText || b.textContent || '').trim();
            {all_cases}
        }});
    }}
    applyStyles();
    new MutationObserver(applyStyles).observe(doc.body, {{childList:true, subtree:true}});
}})();
</script>
"""
    components.html(html_code, height=0, scrolling=False)

# --- 8. CSS BASE ---
st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap');
html, body {{ font-family: 'Inter', sans-serif; background-color: #f8f9fa; }}
.block-container {{ padding-top: 0.5rem !important; padding-bottom: 2rem !important;
    padding-left: 1rem !important; padding-right: 1rem !important; max-width: 100% !important; }}
.kpi-card {{ background: white; border: 1px solid #e0e0e0; border-radius: 12px; padding: 15px;
    text-align: center; box-shadow: 0 2px 6px rgba(0,0,0,0.05); margin-bottom: 15px;
    height: 100%; display: flex; flex-direction: column; justify-content: center; }}
.kpi-title {{ font-size: 0.8rem; color: #666; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }}
.kpi-value {{ font-size: 2rem; font-weight: 800; margin-top: 5px; word-break: break-word; }}
.retailer-header {{ font-size: 1.2rem; font-weight: 800; color: white; padding: 10px 15px;
    border-radius: 8px; margin: 15px 0; text-align: center;
    box-shadow: 0 4px 6px rgba(0,0,0,0.1); text-shadow: 0 1px 2px rgba(0,0,0,0.2); }}
@media (max-width: 768px) {{
    .block-container {{ padding-left: 0.5rem !important; padding-right: 0.5rem !important; }}
    .retailer-header {{ font-size: 1rem; padding: 8px; margin: 10px 0; }}
    section[data-testid="stSidebar"] {{ display: none; }}
}}
</style>
""", unsafe_allow_html=True)

# --- 9. HEADER ---
c_head1, c_head2 = st.columns([1, 5])
with c_head1:
    try:
        st.image("ragasa_logo.png", use_container_width=True)
    except:
        st.write("📦 Logo Ragasa")
with c_head2:
    st.markdown("""
        <div style='display:flex;flex-direction:column;justify-content:center;height:100%;'>
            <h2 style='margin:0;font-weight:800;color:#333;'>DASHBOARD DE INVENTARIOS</h2>
            <p style='margin:0;font-size:0.9rem;color:#666;'>desarrollada por Alexis</p>
        </div>""", unsafe_allow_html=True)

status_txt   = 'CONECTADO' if st.session_state.is_online else 'OFFLINE'
status_color = "#28a745"   if st.session_state.is_online else "#dc3545"
st.markdown(f"<div style='text-align:right;font-size:0.7rem;color:{status_color};font-weight:bold;margin-top:-10px;margin-bottom:10px;'>● {status_txt}</div>", unsafe_allow_html=True)

# --- 10. CARGA AUTOMÁTICA PARALELA AL INICIAR ---
if not st.session_state.data_loaded:
    # Fix 7: re-verificar conectividad real antes de intentar descargar
    st.session_state.is_online = _check_online()

if not st.session_state.data_loaded and st.session_state.is_online:
    results, errors = load_all_parallel()
    st.session_state.df_soriana  = results.get("SORIANA")
    st.session_state.df_walmart  = results.get("WALMART")
    st.session_state.df_chedraui = results.get("CHEDRAUI")
    st.session_state.load_errors = errors
    st.session_state.data_loaded = True

elif not st.session_state.data_loaded and not st.session_state.is_online:
    st.session_state.data_loaded = True  # Marcar como intentado; pedirá archivos abajo

# Mostrar errores de carga si los hubo
if st.session_state.load_errors:
    for k, err in st.session_state.load_errors.items():
        st.warning(f"⚠️ {k}: {err}")

# --- 11. NAVEGACIÓN ---
col1, col2, col3 = st.columns(3, gap="small")
with col1: st.button("SORIANA",  on_click=set_retailer, args=("SORIANA",),  use_container_width=True)
with col2: st.button("WALMART",  on_click=set_retailer, args=("WALMART",),  use_container_width=True)
with col3: st.button("CHEDRAUI", on_click=set_retailer, args=("CHEDRAUI",), use_container_width=True)
st.markdown("<hr style='margin:15px 0;border:0;border-top:1px solid #eee;'>", unsafe_allow_html=True)

# --- 12. HELPER: OBTENER DATOS (online ya cargados o pedir upload offline) ---
def get_cached_or_upload(key, uploader_key, load_func):
    """Si ya tenemos datos en session_state los devuelve; si no, pide archivo."""
    df_key_map = {"SORIANA": "df_soriana", "WALMART": "df_walmart", "CHEDRAUI": "df_chedraui"}
    df = st.session_state.get(df_key_map[key])
    if df is not None:
        return df
    # Fallback: upload manual
    st.warning(f"⚠️ No se pudo cargar {key} automáticamente. Cargue el archivo manualmente.")
    f = st.file_uploader(f"📂 Cargar Excel {key}", type=["xlsx"], key=uploader_key)
    if f:
        with st.spinner(f"Procesando {key}..."):
            df = load_func(f)
        if df is not None:
            st.session_state[df_key_map[key]] = df
        return df
    return None


@st.cache_data(show_spinner=False, ttl=14400)
def _unique_sorted(series_hash: int, vals_tuple: tuple) -> list:
    """Cachea sorted(unique()) — se recalcula solo si cambia el contenido del df."""
    return sorted(vals_tuple)

def _us(series) -> list:
    """Shorthand: unique sorted con caché por contenido."""
    vals = tuple(series.dropna().unique())
    return _unique_sorted(hash(vals), vals)

# --- 13. VISTAS ---
def view_soriana(df_s):
    st.markdown(f"<div class='retailer-header' style='background-color:{RETAILER_COLORS['SORIANA']}'>SORIANA</div>", unsafe_allow_html=True)

    def tog_s_rojo():
        st.session_state.s_rojo      = not st.session_state.s_rojo
        st.session_state.s_dias_inv  = False
        st.session_state.s_dias_prod = False
        st.session_state.s_transito  = False
    def tog_s_dias_inv():
        st.session_state.s_dias_inv  = not st.session_state.s_dias_inv
        st.session_state.s_rojo      = False
        st.session_state.s_dias_prod = False
        st.session_state.s_transito  = False
    def tog_s_dias_prod():
        st.session_state.s_dias_prod = not st.session_state.s_dias_prod
        st.session_state.s_rojo      = False
        st.session_state.s_dias_inv  = False
        st.session_state.s_transito  = False
    def tog_s_transito():
        st.session_state.s_transito  = not st.session_state.s_transito
        st.session_state.s_rojo      = False
        st.session_state.s_dias_inv  = False
        st.session_state.s_dias_prod = False
    def set_s_rank(mode):
        for v in ['s_rank_gen','s_rank_pas','s_rank_oli','s_rank_nut']: st.session_state[v]=False
        st.session_state[f's_rank_{mode.lower()}']=True

    if df_s is not None:
        with st.expander("🔍 Filtros Avanzados", expanded=True):
            c1, c2 = st.columns(2)
            with c1:
                opts_res = ["Todos"] + _us(df_s["RESURTIMIENTO"])
                def_res  = ["1.0"] if "1.0" in opts_res else (["1"] if "1" in opts_res else ["Todos"])
                fil_res  = st.multiselect("Resurtible", opts_res, default=def_res)
                fil_nda  = st.multiselect("No Tienda", _us(df_s["NO_TIENDA"]))
                fil_nom  = st.multiselect("Nombre",    _us(df_s["TIENDA"]))
            with c2:
                fil_cd  = st.multiselect("Ciudad",   _us(df_s["CIUDAD"]))
                fil_edo = st.multiselect("Estado",   _us(df_s["ESTADO"]))
                fil_fmt = st.multiselect("Formato",  _us(df_s["FORMATO"]))
                fil_art = st.multiselect("Artículo", _us(df_s["DESCRIPCION"]))

        dff = apply_filters(df_s,
            ["RESURTIMIENTO","NO_TIENDA","TIENDA","CIUDAD","ESTADO","FORMATO","DESCRIPCION"],
            [fil_res if "Todos" not in fil_res else None, fil_nda, fil_nom, fil_cd, fil_edo, fil_fmt, fil_art])

        b1, b2, b3, b4 = st.columns(4, gap="small")
        with b1: st.button("🔴 INV SIN VENTA", on_click=tog_s_rojo,      use_container_width=True, type="primary" if s_rojo      else "secondary")
        with b2: st.button("📅 DIAS INV",      on_click=tog_s_dias_inv,  use_container_width=True, type="primary" if s_dias_inv  else "secondary")
        with b3: st.button("📋 DIAS X PROD",   on_click=tog_s_dias_prod, use_container_width=True, type="primary" if s_dias_prod else "secondary")
        with b4: st.button("🚚 PEDIDOS EN TRANSITO", on_click=tog_s_transito, use_container_width=True, type="primary" if s_transito else "secondary")

        if st.session_state.s_transito:
            st.subheader("🚚 Pedidos en Tránsito")
            dff_transito = dff[dff["PEDIDOS"] > 0].copy()
            disp_transito = dff_transito[["FORMATO", "TIENDA", "CODIGO", "DESCRIPCION", "PEDIDOS", "FECHA_ENTREGA", "CANTIDAD_PZS"]].copy()
            disp_transito.columns = ['FORMATO', 'NOMBRE DE TIENDA', 'CODIGO', 'ARTICULO', 'PEDIDOS', 'FECHA DE ENTREGA', 'CANTIDAD EN PZS']
            st.dataframe(disp_transito.style.format({'PEDIDOS': "{:,.0f}", 'CANTIDAD EN PZS': "{:,.0f}"}), use_container_width=True, hide_index=True, height=auto_height(disp_transito))
            st.download_button("📥 DESCARGAR EXCEL", data=convert_df_to_excel(disp_transito), file_name="Soriana_Pedidos_Transito.xlsx", use_container_width=True)

        elif st.session_state.s_dias_prod:
            st.subheader("📋 Días Inventario x Producto")
            target_list = _SOR_DIAS_PROD
            desc_clean_col = dff["DESCRIPCION"].str.upper().str.replace(r'&NBSP;',' ',regex=True).str.replace(" ","",regex=False)
            res_rows = []
            for item in target_list:
                clean_item = item.upper().replace("&NBSP;","").replace(" ","")
                mask = desc_clean_col.str.contains(clean_item, case=False, regex=False)
                if mask.any():
                    subset = dff[mask]
                    res_rows.append({"CODIGO": subset["CODIGO"].iloc[0], "ARTICULO": item, "DIAS INV": subset["DIAS_INV"].mean()})
                else:
                    res_rows.append({"CODIGO": "-", "ARTICULO": item, "DIAS INV": 0})
            df_prod_summary = pd.DataFrame(res_rows)
            st.dataframe(df_prod_summary.style.format({'DIAS INV':"{:,.1f}"}), use_container_width=True, hide_index=True, height=auto_height(df_prod_summary))

        elif st.session_state.s_dias_inv:
            st.subheader("📅 Reporte Días Inventario")
            val_nut = get_kpi_mean(dff,"DESCRIPCION","DIAS_INV","ACEITE DE SOYA NUTRIOLI BOT 850 ML")
            val_sab = get_kpi_mean(dff,"DESCRIPCION","DIAS_INV","ACEITE COMESTIBLE SABROSANO 850 ML")
            mask_pastas = dff["DESC_NORM"].str.contains("PASTA", na=False)  # Fix4: usa DESC_NORM
            val_pas = dff.loc[mask_pastas,"DIAS_INV"].mean() if mask_pastas.any() else 0
            k1,k2,k3 = st.columns(3)
            k1.markdown(f"<div class='kpi-card'><div class='kpi-title'>NUTRIOLI 850ML</div><div class='kpi-value' style='color:#28a745;'>{val_nut:,.1f}</div></div>", unsafe_allow_html=True)
            k2.markdown(f"<div class='kpi-card'><div class='kpi-title'>SABROSANO 850ML</div><div class='kpi-value' style='color:#E4007C;'>{val_sab:,.1f}</div></div>", unsafe_allow_html=True)
            k3.markdown(f"<div class='kpi-card'><div class='kpi-title'>PASTAS</div><div class='kpi-value' style='color:#64DD17;'>{val_pas:,.1f}</div></div>", unsafe_allow_html=True)
            disp = dff[["NO_TIENDA","TIENDA","CODIGO","DESCRIPCION","INV_CAJAS","SO_$","SO_4SEM","DIAS_INV"]].copy()
            disp.columns = ['No.','TIENDA','CODIGO','ARTICULO','INV CAJAS','SELL OUT SEM','SELL OUT ULT 4 SEM','DIAS INV']
            st.dataframe(disp.style.format({'INV CAJAS':"{:,.0f}",'SELL OUT SEM':'${:,.2f}','SELL OUT ULT 4 SEM':'${:,.2f}','DIAS INV':"{:,.1f}"}), use_container_width=True, hide_index=True, height=auto_height(disp))

        else:
            desc = dff["DESC_NORM"] if "DESC_NORM" in dff.columns else dff["DESCRIPCION"].fillna("").str.upper().str.replace(" ","",regex=False)
            conditions = [
                desc.str.contains("SABROSANO",na=False), desc.str.contains("GRANTRADICION",na=False),
                desc.str.contains("BALSAMICO",na=False), desc.str.contains("MISAZON|MISAZÓN",na=False),
                desc.str.contains("AVE",na=False) & ~desc.str.contains("NUTRIOLI",na=False),
                desc.str.contains("NUTRIOLI",na=False) & desc.str.contains("PASTA|FUSILLI|SPAGUETTI|FIDEO|CODO",na=False),
                desc.str.contains("OLI",na=False) & desc.str.contains("OLIVA|EV|AEROSOL|ADEREZO",na=False),
                desc.str.contains("NUTRIOLI",na=False) & desc.str.contains("400ML|850ML",na=False) & ~desc.str.contains("PROTECT|DEFENSAS",na=False),
                desc.str.contains("NUTRIOLI",na=False),
            ]
            conditions = [c.to_numpy(dtype=bool) for c in conditions]
            choices = ["SABROSANO","GT","BALSAMICO","MI SAZON","AVE","PASTAS","OLIVAS","NUTRIOLI","REST NUTRIOLI"]
            dff = dff.copy(); dff['Category'] = np.select(conditions, choices, default=None)
            c_kpi, c_chart = st.columns([1,2])
            with c_kpi:
                total_so = dff['SO_$'].sum()
                st.markdown(f"<div class='kpi-card' style='height:450px;'><div class='kpi-title'>Total Sell Out Semanal</div><div class='kpi-value' style='color:#D32F2F;'>${total_so:,.2f}</div></div>", unsafe_allow_html=True)
            with c_chart:
                pie_df = dff.dropna(subset=['Category']).groupby('Category')['SO_$'].sum().reset_index()
                pie_df = pie_df[pie_df['SO_$']>0]
                if not pie_df.empty:
                    domain = ["BALSAMICO","SABROSANO","PASTAS","OLIVAS","GT","NUTRIOLI","MI SAZON","AVE","REST NUTRIOLI"]
                    range_ = ["#e012a9","#f705ab","#4c915d","#97ad6a","#7d6010","#02c705","#e89015","#ff0000","#00ff04"]
                    fig = _make_pie(pie_df.to_json(), domain, range_, 'SO_$')
                    st.plotly_chart(fig, use_container_width=True)
                else: st.info("Sin datos para gráfica.")
            if st.session_state.s_rojo: dff=dff[dff['SIN_VTA']]; st.caption("📋 Vista: Sin Venta")
            disp = dff[["NO_TIENDA","TIENDA","CODIGO","DESCRIPCION","INV_CAJAS","SO_$","SO_4SEM","DIAS_INV"]].copy()
            disp.columns=['No.','TIENDA','CODIGO','ARTICULO','INV CAJAS','SELL OUT SEM','SELL OUT ULT 4 SEM','DIAS INV']
            disp = disp.sort_values(by='SELL OUT ULT 4 SEM',ascending=False)
            st.dataframe(disp.style.format({'INV CAJAS':"{:,.0f}",'SELL OUT SEM':'${:,.2f}','SELL OUT ULT 4 SEM':'${:,.2f}','DIAS INV':"{:,.1f}"}), use_container_width=True, hide_index=True, height=auto_height(disp))
            st.download_button("📥 DESCARGAR EXCEL", data=convert_df_to_excel(disp), file_name="Soriana_General.xlsx", use_container_width=True)

        st.divider()
        st.markdown("<h3 style='text-align:center;color:#444;'>🏆 RANKING DE VENTAS</h3>", unsafe_allow_html=True)
        sm1,sm2 = st.columns(2)
        with sm1: sel_s_rank_st  = st.multiselect("Estado (Ranking)",  _us(df_s["ESTADO"]),  key="s_rnk_st")
        with sm2: sel_s_rank_fmt = st.multiselect("Formato (Ranking)", _us(df_s["FORMATO"]), key="s_rnk_fmt")
        sr1,sr2,sr3,sr4 = st.columns(4,gap="small")
        with sr1: st.button("📊 GENERAL",  on_click=set_s_rank, args=('GEN',), use_container_width=True, type="primary" if s_rank_gen else "secondary")
        with sr2: st.button("🍝 PASTAS",   on_click=set_s_rank, args=('PAS',), use_container_width=True, type="primary" if s_rank_pas else "secondary")
        with sr3: st.button("🫒 OLIVAS",   on_click=set_s_rank, args=('OLI',), use_container_width=True, type="primary" if s_rank_oli else "secondary")
        with sr4: st.button("🍃 NUTRIOLI", on_click=set_s_rank, args=('NUT',), use_container_width=True, type="primary" if s_rank_nut else "secondary")

        dff_s_rank = apply_filters(df_s,["ESTADO","FORMATO"],[sel_s_rank_st,sel_s_rank_fmt])
        list_s_gen = _SOR_RANK_GEN
        list_s_pas = _SOR_RANK_PAS
        list_s_oli = _SOR_RANK_OLI
        list_s_nut = _SOR_RANK_NUT
        target_list_s=[]; rank_title_s=""
        if   s_rank_gen: target_list_s=list_s_gen; rank_title_s="VENTA GENERAL ($)"
        elif s_rank_pas: target_list_s=list_s_pas; rank_title_s="VENTA PASTAS ($)"
        elif s_rank_oli: target_list_s=list_s_oli; rank_title_s="VENTA OLIVAS ($)"
        elif s_rank_nut: target_list_s=list_s_nut; rank_title_s="VENTA NUTRIOLI ($)"
        if target_list_s:
            dff_sub = dff_s_rank[dff_s_rank["DESCRIPCION"].str.strip().isin(set(t.strip() for t in target_list_s))]
            if not dff_sub.empty:
                final_s_rank = dff_sub.groupby(["NO_TIENDA","TIENDA"])['SO_$'].sum().reset_index()
                final_s_rank.columns=['No Tienda','TIENDA',rank_title_s]
                st.dataframe(final_s_rank.sort_values(by=rank_title_s,ascending=False).style.format({rank_title_s:"${:,.2f}"}), use_container_width=True, hide_index=True, height=auto_height(final_s_rank))
                st.download_button("📥 DESCARGAR EXCEL", data=convert_df_to_excel(final_s_rank), file_name="Soriana_Ranking.xlsx", use_container_width=True)
            else: st.warning("⚠️ No se encontraron ventas para los productos seleccionados.")


def view_walmart(df_w):
    st.markdown(f"<div class='retailer-header' style='background-color:{RETAILER_COLORS['WALMART']}'>WALMART</div>", unsafe_allow_html=True)

    def tog_w(target):
        for v in ['w_neg','w_4w','w_dias_inv','w_dias_prod']:
            st.session_state[v] = True if v==target and not st.session_state[v] else False
    def set_rank(mode):
        for v in ['w_rank_tiendas','w_rank_pastas','w_rank_olivas','w_nutri_top10']: st.session_state[v]=False
        if   mode=='tiendas':  st.session_state.w_rank_tiendas=True
        elif mode=='pastas':   st.session_state.w_rank_pastas=True
        elif mode=='olivas':   st.session_state.w_rank_olivas=True
        elif mode=='nutrioli': st.session_state.w_nutri_top10=True

    if df_w is not None:
        df_w = df_w[~df_w["FORMATO"].isin(['BAE','MB'])]
        with st.expander("🔍 Filtros Avanzados", expanded=True):
            c1,c2,c3 = st.columns(3)
            with c1:
                marca_opts = sorted([m for m in df_w["MARCA"].dropna().unique() if m.strip().upper() not in ["NUTRIOLI + PASTA","NUTRIOLI  PASTA","NUTRIOLI PASTA"]])
                sel_marca = st.multiselect("Marca", marca_opts)
                sel_state = st.multiselect("Estado", _us(df_w["ESTADO"]))
            with c2:
                unique_stores = _us(df_w[df_w["ESTADO"].isin(sel_state)]["TIENDA"]) if sel_state else _us(df_w["TIENDA"])
                sel_store = st.multiselect("Tienda",  unique_stores)
                sel_fmt   = st.multiselect("Formato", _us(df_w["FORMATO"]))
            with c3:
                excluidas_clean = {"ACEITE VEGETAL SABROSANO RINDE MAS 850ML","OLI SPRAY ACEITE DE OLIVA 145ML","ACEITE MIXTO GRAN TRADICION 1L","ACEITE GRAN TRADICION 900ML","NUTRIOLI 946 ML +PASTA CODO 200G","NUTRIOLI 946 ML +FUSILLI VERDURAS 200G","NUTRIOLI SPAGUETTI ESENCIAL 200G","NUTRIOLI FIDEO ESENCIAL 200G","NUTRIOLI CODO ESENCIAL 200G","NUTRIOLI FUSILLI VERDURAS 200G","NUTRIOLI CODO VERDURAS 200G"}
                sel_prod = st.multiselect("Artículo", sorted([p for p in df_w["DESCRIPCION"].dropna().unique() if p.strip().upper() not in excluidas_clean]))

        dff_kpi = apply_filters(df_w,["MARCA","ESTADO","TIENDA","FORMATO"],[sel_marca,sel_state,sel_store,sel_fmt])
        dff     = apply_filters(dff_kpi,["DESCRIPCION"],[sel_prod])

        b1,b2,b3,b4 = st.columns(4,gap="small")
        with b1: st.button("📉 NEGATIVOS",    on_click=tog_w, args=('w_neg',),       use_container_width=True, type="primary" if w_neg      else "secondary")
        with b2: st.button("🔴 SIN VTA 4SEM", on_click=tog_w, args=('w_4w',),        use_container_width=True, type="primary" if w_4w       else "secondary")
        with b3: st.button("📅 DIAS INV",     on_click=tog_w, args=('w_dias_inv',),  use_container_width=True, type="primary" if w_dias_inv  else "secondary")
        with b4: st.button("📋 DIAS X PROD",  on_click=tog_w, args=('w_dias_prod',), use_container_width=True, type="primary" if w_dias_prod else "secondary")

        if st.session_state.w_neg: dff=dff[dff["EXISTENCIA"]<0]; st.warning("VISTA: NEGATIVOS")
        if st.session_state.w_4w:  dff=dff[(dff["VTA_S1"]==0)&(dff["VTA_S2"]==0)&(dff["VTA_S3"]==0)&(dff["VTA_S4"]==0)]; st.warning("VISTA: SIN VENTA 4 SEMANAS")

        borges_list = ["BORGES ACEITE OLIVA EXTRA VIRGEN 500","BORGES ACEITE OLIVA EXTRA SUAVE","ACEITE DE OLIVA EXTRA VIRGEN KOSHER","ACEITE DE OLIVA A LA ALBAHACA FRESCA","ACEITE DE SOJA JENGIBRE","ACEITE DE OLIVA AL AJO FRITO","ACEITE DE OLIVA AL  ROMERO FRESCO","BORGES ACEITE DE PEPITA UVA 500ML","BORGES ACEITE DE OLIVA EXTRA VIRGEN ECOL","BORGES VINAGRE BALSAMICO 250ML","VINAGRE DE JEREZ 250 ML","VINAGRE DE SIDRA 250 ML","VINAGRE DE VINO FRAMBUESA","VINAGRE DE VINO AL  AJO 250 ML","BORGES VINAGRE VINO BLANCO","VINAGRE DE MANZANA ECOLOGICO","BORGES VINAGRE DE VINOTINTO","VINAGRE DE VINO DE RIOJA BOTELLA 250ML","BORGES ACEITE OLIVA 100 PURO CON AJO"]
        borges_pat = "|".join([x.replace(" ","").upper() for x in borges_list])
        desc_w = dff["DESC_NORM"] if "DESC_NORM" in dff.columns else dff["DESCRIPCION"].fillna("").str.upper().str.replace(" ","",regex=False).str.replace("&NBSP;","",regex=False)
        conditions_w = [
            desc_w.str.contains(borges_pat, regex=True, na=False),
            desc_w.str.contains("NUTRIOLI",na=False)&desc_w.str.contains("946",na=False),
            desc_w.str.contains("SABROSANO",na=False),
            desc_w.str.contains("GRANTRADICION",na=False),
            desc_w.str.contains("BALSAMICO",na=False),
            (desc_w.str.contains("OLISPRAY|OLICOCINA|OLIDENUTEV|ACEITEOLIDEOLIVA|OLIDENUT",na=False))&~desc_w.str.contains("BALSAMICO",na=False),
            desc_w.str.contains("NUTRIOLI",na=False)&desc_w.str.contains("SPAGUETTI|FIDEO|CODO|PASTA",na=False),
            desc_w.str.contains("NUTRIOLI",na=False)
        ]
        conditions_w = [c.to_numpy(dtype=bool) for c in conditions_w]
        choices_w = ["BORGES","NUTRIOLI","SABROSANO","GT","BALSAMICO","OLIVAS","PASTAS","REST NUTRIOLI"]
        dff = dff.copy(); dff['Category'] = np.select(conditions_w, choices_w, default=None)

        if st.session_state.w_dias_prod:
            st.subheader("📋 Días Inventario x Producto")
            target_list = _WAL_DIAS_PROD
            desc_nospace = dff_kpi["DESCRIPCION"].str.upper().str.replace(r'&NBSP;','',regex=True).str.replace(" ","",regex=False)
            res_rows = []
            for item in target_list:
                clean_item = item.upper().replace("&NBSP;","").replace(" ","")
                mask = desc_nospace.str.contains(clean_item, case=False, regex=False)
                if mask.any():
                    subset = dff_kpi[mask]
                    res_rows.append({"CODIGO":subset["CODIGO"].iloc[0],"ARTICULO":item,"DIAS DE INV":subset["DIAS_INV"].mean(),"SELL OUT":subset["SO_$"].sum()})
                else:
                    res_rows.append({"CODIGO":"-","ARTICULO":item,"DIAS DE INV":0,"SELL OUT":0})
            df_ps = pd.DataFrame(res_rows)
            st.dataframe(df_ps.style.format({'DIAS DE INV':"{:,.1f}",'SELL OUT':"${:,.2f}"}), use_container_width=True, hide_index=True, height=auto_height(df_ps))
            st.download_button("📥 DESCARGAR EXCEL", data=convert_df_to_excel(df_ps), file_name="Walmart_Dias_Producto.xlsx", use_container_width=True)

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
            st.download_button("📥 DESCARGAR EXCEL", data=convert_df_to_excel(disp_w_dias), file_name="Walmart_Reporte_Dias.xlsx", use_container_width=True)

        else:
            c_kpi,c_chart = st.columns([1,2])
            total_so = dff['SO_$'].sum()
            with c_kpi:
                st.markdown(f"<div class='kpi-card' style='height:450px;'><div class='kpi-title'>Total Sell Out</div><div class='kpi-value' style='color:#28a745;'>${total_so:,.2f}</div></div>", unsafe_allow_html=True)
            with c_chart:
                pie_df = dff.dropna(subset=['Category']).groupby('Category')['SO_$'].sum().reset_index()
                pie_df = pie_df[pie_df['SO_$']>0]
                if not pie_df.empty:
                    domain=["SABROSANO","GT","OLIVAS","BALSAMICO","PASTAS","REST NUTRIOLI","NUTRIOLI","BORGES"]
                    range_=["#E4007C","#a18262","#6B8E23","#9f4576","#426045","#bfff00","#008f39","#FF0000"]
                    fig = _make_pie(pie_df.to_json(), domain, range_, 'SO_$')
                    st.plotly_chart(fig, use_container_width=True)
                else: st.info("Sin datos para gráfica.")
            disp=dff[["CODIGO","DESCRIPCION","TIENDA","EXISTENCIA","SO_$","PROM_PZS_MENSUAL"]].copy()
            disp.columns=['CODIGO','DESCRIPCION','TIENDA','EXISTENCIA','SELL OUT','PROM PZS MENSUAL']
            st.dataframe(disp.style.format({'SELL OUT':'${:,.2f}','PROM PZS MENSUAL':'{:,.2f}'}), use_container_width=True, hide_index=True, height=auto_height(disp))
            st.download_button("📥 DESCARGAR EXCEL", data=convert_df_to_excel(disp), file_name="Walmart_General.xlsx", use_container_width=True)

        st.divider()
        st.markdown("<h3 style='text-align:center;color:#444;'>🏆 RANKING DE VENTAS</h3>", unsafe_allow_html=True)
        cm1,cm2 = st.columns(2)
        with cm1: sel_st_rank  = st.multiselect("Estado (Ranking)",  _us(df_w["ESTADO"]),  key="rnk_st")
        with cm2: sel_fmt_rank = st.multiselect("Formato (Ranking)", _us(df_w["FORMATO"]), key="rnk_fmt")
        sr1,sr2,sr3,sr4 = st.columns(4,gap="small")
        with sr1: st.button("📊 GENERAL",  on_click=set_rank, args=('tiendas',),  use_container_width=True, type="primary" if w_rank_tiendas else "secondary")
        with sr2: st.button("🍝 PASTAS",   on_click=set_rank, args=('pastas',),   use_container_width=True, type="primary" if w_rank_pastas  else "secondary")
        with sr3: st.button("🫒 OLIVAS",   on_click=set_rank, args=('olivas',),   use_container_width=True, type="primary" if w_rank_olivas  else "secondary")
        with sr4: st.button("🏆 NUTRIOLI", on_click=set_rank, args=('nutrioli',), use_container_width=True, type="primary" if w_nutri_top10  else "secondary")

        dff_rank = apply_filters(df_w,["ESTADO","FORMATO"],[sel_st_rank,sel_fmt_rank])
        final_rank = None
        if st.session_state.w_rank_tiendas:
            final_rank = dff_rank.groupby("TIENDA")['SO_$'].sum().reset_index().rename(columns={'SO_$':'VENTA TOTAL ($)'})
        elif st.session_state.w_rank_pastas:
            df_sub = dff_rank[dff_rank["CATEGORIA"].str.contains("PASTAS",na=False)]
            if not df_sub.empty: final_rank = df_sub.groupby("TIENDA")['SO_$'].sum().reset_index().rename(columns={'SO_$':'VENTA PASTAS ($)'})
        elif st.session_state.w_rank_olivas:
            df_sub = dff_rank[dff_rank["DESC_NORM"].str.contains("OLI",na=False)]
            if not df_sub.empty: final_rank = df_sub.groupby("TIENDA")['SO_$'].sum().reset_index().rename(columns={'SO_$':'VENTA OLIVAS ($)'})
        elif st.session_state.w_nutri_top10:
            df_sub = dff_rank[dff_rank["DESC_NORM"].str.contains("NUTRIOLI",na=False)&dff_rank["DESC_NORM"].str.contains("946",na=False)]
            if not df_sub.empty:
                final_rank = df_sub.groupby(["FORMATO","TIENDA","DESCRIPCION"])[['EXISTENCIA','SO_SEM_ANT','SO_$']].sum().reset_index()
                final_rank.columns=["FORMATO","TIENDA","PRODUCTO","INVENTARIO","VTA SEM ANTERIOR ($)","SELL OUT ($)"]
        if final_rank is not None:
            sort_col = final_rank.columns[-1]
            final_rank = final_rank.sort_values(by=sort_col,ascending=False)
            fmt_dict = {c:"${:,.2f}" for c in final_rank.columns if "($)" in c or "$" in c}
            if "INVENTARIO" in final_rank.columns: fmt_dict["INVENTARIO"]="{:,.0f}"
            st.dataframe(final_rank.style.format(fmt_dict), use_container_width=True, hide_index=True, height=auto_height(final_rank))
            st.download_button("📥 DESCARGAR EXCEL", data=convert_df_to_excel(final_rank), file_name="Walmart_Ranking.xlsx", use_container_width=True)


def view_chedraui(df_c):
    st.markdown(f"<div class='retailer-header' style='background-color:{RETAILER_COLORS['CHEDRAUI']}'>CHEDRAUI</div>", unsafe_allow_html=True)

    def tog_c(target):
        for v in ['c_neg_zero','c_dias_inv']:
            st.session_state[v] = True if v==target and not st.session_state[v] else False
    def set_c_rank(mode):
        for v in ['c_rank_gen','c_rank_pas','c_rank_oli','c_rank_nut']: st.session_state[v]=False
        st.session_state[f'c_rank_{mode.lower()}']=True

    if df_c is not None:
        with st.expander("🔍 Filtros Avanzados", expanded=True):
            c1,c2 = st.columns(2)
            with c1:
                fil_no  = st.multiselect("No Tienda",  _us(df_c["NO_TIENDA"]))
                fil_ti  = st.multiselect("Tienda",     _us(df_c["TIENDA"]))
                fil_cat = st.multiselect("Categoría",  _us(df_c["CATEGORIA"]))
            with c2:
                fil_ed  = st.multiselect("Estado",     _us(df_c["ESTADO"]))
                fil_art = st.multiselect("Artículo",   _us(df_c["ARTICULO"]))

        dff_base = apply_filters(df_c,["NO_TIENDA","TIENDA","ESTADO","CATEGORIA"],[fil_no,fil_ti,fil_ed,fil_cat])
        dff      = apply_filters(dff_base,["ARTICULO"],[fil_art])

        b1,b2 = st.columns(2,gap="small")
        with b1: st.button("📉 NEGATIVOS", on_click=tog_c, args=('c_neg_zero',), use_container_width=True, type="primary" if c_neg_zero else "secondary")
        with b2: st.button("📅 DIAS INV",  on_click=tog_c, args=('c_dias_inv',), use_container_width=True, type="primary" if c_dias_inv else "secondary")

        if st.session_state.c_dias_inv:
            st.subheader("📅 Reporte Días Inventario")
            val_nut = get_kpi_mean(dff_base,"ARTICULO","DIAS_INV","Nutrioli Bot 850")
            val_sab = get_kpi_mean(dff_base,"ARTICULO","DIAS_INV","Sabrosano Mixto 850")
            val_ave = get_kpi_mean(dff_base,"ARTICULO","DIAS_INV","Ave Soya-Canola 850")
            k1,k2,k3 = st.columns(3)
            k1.markdown(f"<div class='kpi-card'><div class='kpi-title'>NUTRIOLI 850ML</div><div class='kpi-value' style='color:#28a745;'>{val_nut:,.1f}</div></div>", unsafe_allow_html=True)
            k2.markdown(f"<div class='kpi-card'><div class='kpi-title'>SABROSANO 850ML</div><div class='kpi-value' style='color:#E4007C;'>{val_sab:,.1f}</div></div>", unsafe_allow_html=True)
            k3.markdown(f"<div class='kpi-card'><div class='kpi-title'>AVE 850ML</div><div class='kpi-value' style='color:#D32F2F;'>{val_ave:,.1f}</div></div>", unsafe_allow_html=True)
            disp=dff[["NO_TIENDA","TIENDA","ARTICULO","INV_ULT_SEM","VTA_PROM_DIARIA","DIAS_INV","SELL_OUT"]].copy()
            disp.columns=['NO_TIENDA','TIENDA','ARTICULO','INV_ULT_SEM','VTA_PROM_DIARIA','DIAS_INV','SELL_OUT']
            st.dataframe(disp.style.format({'INV_ULT_SEM':"{:,.0f}",'VTA_PROM_DIARIA':"{:,.2f}",'DIAS_INV':"{:,.1f}",'SELL_OUT':"${:,.2f}"}), use_container_width=True, hide_index=True, height=auto_height(disp))
            st.download_button("📥 DESCARGAR EXCEL", data=convert_df_to_excel(disp), file_name="Chedraui_Dias_Inventario.xlsx", use_container_width=True)

        elif st.session_state.c_neg_zero:
            dff_neg = dff[dff["INV_ULT_SEM"]<0].copy()
            st.subheader("📉 Vista: Inventarios Negativos")
            disp_neg = dff_neg[["ESTADO","COORDINADOR","EJECUTIVO","PROMOTOR","CATEGORIA","NO_TIENDA","TIENDA","ARTICULO","INV_ULT_SEM"]].copy()
            disp_neg.columns=["ESTADO","Coordinador","Ejecutivo","Promotor","Categoria","No de tienda","Tienda","articulo","Inventario 06 Mar 2026"]
            st.dataframe(disp_neg.style.format({'Inventario 06 Mar 2026':"{:,.0f}"}), use_container_width=True, hide_index=True, height=auto_height(disp_neg))
            st.download_button("📥 DESCARGAR EXCEL", data=convert_df_to_excel(disp_neg), file_name="Chedraui_Negativos.xlsx", use_container_width=True)

        else:
            desc_c = dff["DESC_NORM"] if "DESC_NORM" in dff.columns else dff["ARTICULO"].fillna("").str.upper().str.replace(" ","",regex=False)
            conditions_c = [
                desc_c.str.contains("BALSAMICO",na=False), desc_c.str.contains("SABROSANO",na=False),
                desc_c.str.contains("GRANTRADICION",na=False), desc_c.str.contains("MISAZON|MISAZÓN",na=False),
                desc_c.str.contains("AVE",na=False)&desc_c.str.contains("SOYA-CANOLA|AEROSOL",na=False),
                desc_c.str.contains("NUTRIOLI",na=False)&desc_c.str.contains("FUSILLI|SPAGUETTI|FIDEO|CODO",na=False),
                desc_c.str.contains("OLI",na=False)&desc_c.str.contains("OLIVA|EV|AEROSOL",na=False),
                desc_c.str.contains("NUTRIOLI",na=False)&desc_c.str.contains("400ML|850ML",na=False)&~desc_c.str.contains("PROTECT|DEFENSAS",na=False),
                desc_c.str.contains("NUTRIOLI",na=False)
            ]
            conditions_c = [c.to_numpy(dtype=bool) for c in conditions_c]
            choices_c = ["BALSAMICO","SABROSANO","GT","MI SAZON","AVE","PASTAS","OLIVAS","NUTRIOLI","REST NUTRIOLI"]
            dff=dff.copy(); dff['Category']=np.select(conditions_c,choices_c,default=None)
            c_kpi,c_chart = st.columns([1,2])
            with c_kpi:
                total_so = dff['SELL_OUT'].sum()
                st.markdown(f"<div class='kpi-card' style='height:450px;'><div class='kpi-title'>Total Sell Out</div><div class='kpi-value' style='color:#FF6600;'>${total_so:,.2f}</div></div>", unsafe_allow_html=True)
            with c_chart:
                pie_df = dff.dropna(subset=['Category']).groupby('Category')['SELL_OUT'].sum().reset_index()
                pie_df = pie_df[pie_df['SELL_OUT']>0]
                if not pie_df.empty:
                    domain=["BALSAMICO","SABROSANO","PASTAS","OLIVAS","GT","NUTRIOLI","MI SAZON","AVE","REST NUTRIOLI"]
                    range_=["#e012a9","#f705ab","#4c915d","#97ad6a","#7d6010","#02c705","#e89015","#ff0000","#00ff04"]
                    fig = _make_pie(pie_df.to_json(), domain, range_, 'SELL_OUT')
                    st.plotly_chart(fig, use_container_width=True)
                else: st.info("Sin datos para gráfica.")
            st.caption("📋 Vista: Completa")
            disp=dff[["NO_TIENDA","TIENDA","ARTICULO","INV_ULT_SEM","VTA_PROM_DIARIA","DIAS_INV","SELL_OUT"]].copy()
            disp.columns=['NO_TIENDA','TIENDA','ARTICULO','INV_ULT_SEM','VTA_PROM_DIARIA','DIAS_INV','SELL_OUT']
            st.dataframe(disp.style.format({'INV_ULT_SEM':"{:,.0f}",'VTA_PROM_DIARIA':"{:,.2f}",'DIAS_INV':"{:,.1f}",'SELL_OUT':"${:,.2f}"}), use_container_width=True, hide_index=True, height=auto_height(disp))
            st.download_button("📥 DESCARGAR EXCEL", data=convert_df_to_excel(disp), file_name="Chedraui_General.xlsx", use_container_width=True)

        st.divider()
        st.markdown("<h3 style='text-align:center;color:#444;'>🏆 RANKING DE VENTAS</h3>", unsafe_allow_html=True)
        sel_st_rank = st.selectbox("Filtrar Estado (Ranking)", ["Todos"]+_us(df_c["ESTADO"]), key="c_rnk_st")
        cr1,cr2,cr3,cr4 = st.columns(4,gap="small")
        with cr1: st.button("📊 GENERAL",  on_click=set_c_rank, args=('GEN',), use_container_width=True, type="primary" if c_rank_gen else "secondary")
        with cr2: st.button("🍝 PASTAS",   on_click=set_c_rank, args=('PAS',), use_container_width=True, type="primary" if c_rank_pas else "secondary")
        with cr3: st.button("🫒 OLIVAS",   on_click=set_c_rank, args=('OLI',), use_container_width=True, type="primary" if c_rank_oli else "secondary")
        with cr4: st.button("🍃 NUTRIOLI", on_click=set_c_rank, args=('NUT',), use_container_width=True, type="primary" if c_rank_nut else "secondary")

        dff_rank = df_c.copy()
        if sel_st_rank != "Todos": dff_rank = dff_rank[dff_rank["ESTADO"]==sel_st_rank]
        list_gen=_CHE_RANK_GEN
        list_pas=_CHE_RANK_PAS
        list_oli=_CHE_RANK_OLI
        list_nut=_CHE_RANK_NUT
        target_list=[]; rank_title=""
        if   c_rank_gen: target_list=list_gen; rank_title="VENTA GENERAL ($)"
        elif c_rank_pas: target_list=list_pas; rank_title="VENTA PASTAS ($)"
        elif c_rank_oli: target_list=list_oli; rank_title="VENTA OLIVAS ($)"
        elif c_rank_nut: target_list=list_nut; rank_title="VENTA NUTRIOLI ($)"
        if target_list:
            dff_sub = dff_rank[dff_rank["ARTICULO"].str.strip().isin(set(t.strip() for t in target_list))]
            if not dff_sub.empty:
                final_c_rank = dff_sub.groupby(["NO_TIENDA","TIENDA"])['SELL_OUT'].sum().reset_index()
                final_c_rank.columns=['No Tienda','TIENDA',rank_title]
                final_c_rank = final_c_rank.sort_values(by=rank_title,ascending=False)
                st.dataframe(final_c_rank.style.format({rank_title:"${:,.2f}"}), use_container_width=True, hide_index=True, height=auto_height(final_c_rank))
                st.download_button("📥 DESCARGAR EXCEL", data=convert_df_to_excel(final_c_rank), file_name="Chedraui_Ranking.xlsx", use_container_width=True)
            else: st.warning("⚠️ No se encontraron ventas para los productos seleccionados en este estado.")

# --- 14. EJECUTAR VISTA ACTIVA ---
# inject_button_styles ANTES de las vistas: el JS ya está listo cuando el DOM se construye
inject_button_styles()

_act = st.session_state.active_retailer
with st.container(key=f"view_{_act}"):
    if _act == 'SORIANA':
        df_s = get_cached_or_upload("SORIANA", "up_s", load_sor)
        if df_s is not None: view_soriana(df_s)
    elif _act == 'WALMART':
        df_w = get_cached_or_upload("WALMART", "up_w", load_wal)
        if df_w is not None: view_walmart(df_w)
    elif _act == 'CHEDRAUI':
        df_c = get_cached_or_upload("CHEDRAUI", "up_c", load_che)
        if df_c is not None: view_chedraui(df_c)

# --- 15. PIE DE PÁGINA ---
st.divider()
if st.button("🗑️ LIMPIAR MEMORIA / RESET", use_container_width=True, type="secondary", key="reset_btn"):
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
