import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import numpy as np
import time
import requests
import plotly.express as px
import urllib.parse
from io import BytesIO, StringIO
from concurrent.futures import ThreadPoolExecutor, as_completed

# Eliminar límite de celdas del Styler de Pandas — evita error con tablas grandes
pd.set_option("styler.render.max_elements", 2_000_000)

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

_GITHUB_API = {
    "SORIANA":  "https://api.github.com/repos/gamerhackleon-afk/RTLRAGA/commits?path=SORIANA.xlsx&per_page=1",
    "WALMART":  "https://api.github.com/repos/gamerhackleon-afk/RTLRAGA/commits?path=WALMART.xlsx&per_page=1",
    "CHEDRAUI": "https://api.github.com/repos/gamerhackleon-afk/RTLRAGA/commits?path=CHEDRAUI.xlsx&per_page=1",
}

@st.cache_data(ttl=3600, show_spinner=False)
def _get_last_update(key: str) -> str:
    try:
        resp = requests.get(_GITHUB_API[key], timeout=5,
                            headers={"Accept": "application/vnd.github+json"})
        if resp.status_code == 200:
            data = resp.json()
            if data:
                iso = data[0]["commit"]["committer"]["date"]
                from datetime import datetime, timezone, timedelta
                dt = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                dt_mx = dt - timedelta(hours=6)
                return dt_mx.strftime("%d/%m/%Y %H:%M") + " hrs"
    except Exception:
        pass
    return "Sin información"

RETAILER_COLORS = {
    "SORIANA": "#D32F2F",
    "WALMART": "#0071DC",
    "CHEDRAUI": "#FF6600"
}

# --- FUNCIÓN DE CONECTIVIDAD ---
def _check_online() -> bool:
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

_view_vars = [
    's_rojo','s_dias_inv','s_dias_prod','s_transito',
    's_rank_gen','s_rank_pas','s_rank_oli','s_rank_nut',
    'w_neg','w_4w','w_dias_inv','w_dias_prod',
    'w_rank_tiendas','w_rank_pastas','w_rank_olivas','w_nutri_top10',
    'c_neg_zero','c_dias_inv','c_transito','c_rank_gen','c_rank_pas','c_rank_oli','c_rank_nut',
]
for _v in _view_vars:
    if _v not in st.session_state:
        st.session_state[_v] = False

# --- 3. FUNCIONES UTILITARIAS ---
def safe_mean(series):
    return series.mean() if not series.empty else 0

def apply_filters(df, filter_cols, selections):
    mask = np.ones(len(df), dtype=bool)
    for col, sel in zip(filter_cols, selections):
        if sel and col in df.columns:
            col_vals = df[col].astype(str).str.strip().str.upper()
            sel_vals = {str(s).strip().upper() for s in sel}
            mask &= col_vals.isin(sel_vals).values
    return df[mask]

def get_kpi_mean(df, desc_col, days_col, pattern):
    """Solo para promedios (como días inventario) de agrupaciones si fuera necesario"""
    if "DESC_NORM" in df.columns:
        clean_desc = df["DESC_NORM"]
    else:
        clean_desc = df[desc_col].fillna("").str.upper().str.replace("&NBSP;", "", regex=False).str.replace(" ", "", regex=False)
    clean_pattern = pattern.upper().replace("&NBSP;", "").replace(" ", "")
    mask = clean_desc.str.contains(clean_pattern, case=False, na=False)
    return safe_mean(df.loc[mask, days_col])

# --- NUEVAS FUNCIONES DE ALTA PRECISIÓN (POR UPC/DESC EXACTA) ---
def get_kpi_sum_by_upc(df, upc, value_col="SO_$"):
    """Calcula suma exacta usando agrupamiento por tienda para evitar duplicidad de SKU"""
    if "CODIGO" not in df.columns:
        return 0
    df_upc = df[df["CODIGO"].astype(str).str.strip() == str(upc).strip()]
    if df_upc.empty:
        return 0
    # Evita duplicidad por tienda
    return df_upc.groupby(["CODIGO", "TIENDA"])[value_col].sum().sum()

def get_kpi_sum_exact_desc(df, desc, value_col="SO_$"):
    """Calcula suma exacta usando descripción completa por si no hay UPC"""
    if "DESCRIPCION" not in df.columns:
        return 0
    mask = df["DESCRIPCION"].astype(str).str.strip().str.upper() == str(desc).strip().upper()
    df_desc = df[mask]
    if df_desc.empty:
        return 0
    # Evita duplicidad por tienda
    return df_desc.groupby(["DESCRIPCION", "TIENDA"])[value_col].sum().sum()

def get_kpi_mean_by_upc(df, upc, value_col="DIAS_INV"):
    """Promedio exacto por código UPC para métricas no sumables (como Días de Inventario)"""
    if "CODIGO" not in df.columns:
        return 0
    mask = df["CODIGO"].astype(str).str.strip() == str(upc).strip()
    return safe_mean(df.loc[mask, value_col])

def get_kpi_mean_exact_desc(df, desc, value_col="DIAS_INV"):
    """Promedio exacto por descripción completa"""
    if "DESCRIPCION" not in df.columns:
        return 0
    mask = df["DESCRIPCION"].astype(str).str.strip().str.upper() == str(desc).strip().upper()
    return safe_mean(df.loc[mask, value_col])
# ----------------------------------------------------------------

def auto_height(df):
    return min(max(len(df) * 35 + 45, 100), 600)

def _filter_badge(filtros: dict, color_acento: str = "#0071DC"):
    lineas = []
    for etiqueta, valores in filtros.items():
        if valores:
            vals_str = ", ".join(str(v) for v in valores[:3])
            if len(valores) > 3:
                vals_str += f" +{len(valores)-3}"
            lineas.append(f"<b>{etiqueta}:</b> {vals_str}")
    if not lineas:
        return None  
    return dict(
        text="<br>".join(lineas),
        xref="paper", yref="paper",
        x=0.99, y=1.12,
        xanchor="right", yanchor="top",
        showarrow=False,
        bgcolor="rgba(255,255,255,0.92)",
        bordercolor=color_acento,
        borderwidth=1.5,
        borderpad=8,
        font=dict(size=12, family="Inter, Arial, sans-serif", color="#222222"),
        align="left",
    )

@st.cache_data(show_spinner=False)
def convert_df_to_excel(df):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Reporte')
    return output.getvalue()

@st.cache_data(show_spinner=False, ttl=14400)
def _make_pie(pie_df_json: str, domain: list, range_: list, val_col: str):
    import json
    pie_df = pd.read_json(StringIO(pie_df_json))
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

@st.cache_data(show_spinner=False, ttl=14400)
def _categorize_df(df_json: str, retailer: str) -> str:
    df = pd.read_json(StringIO(df_json))

    def _safe_str(series):
        return series.fillna("").astype(str).str.upper().str.replace(" ", "", regex=False).str.replace("&NBSP;", "", regex=False)

    if retailer == "SORIANA":
        desc = df["DESC_NORM"].astype(str) if "DESC_NORM" in df.columns else _safe_str(df["DESCRIPCION"])
        conditions = [
            desc.str.contains("SABROSANO",na=False), desc.str.contains("GRANTRADICION",na=False),
            desc.str.contains("BALSAMICO",na=False), desc.str.contains("MISAZON|MISAZÓN",na=False),
            desc.str.contains("AVE",na=False) & ~desc.str.contains("NUTRIOLI",na=False),
            desc.str.contains("PASTA|FUSILLI|SPAGUETTI|SPAGHETTI|FIDEO|CODO|PPS|MACARRON",na=False),
            desc.str.contains("OLI",na=False) & desc.str.contains("OLIVA|EV|AEROSOL|ADEREZO",na=False),
            desc.str.contains("NUTRIOLI",na=False) & desc.str.contains("400ML|850ML",na=False) & ~desc.str.contains("PROTECT|DEFENSAS",na=False),
            desc.str.contains("NUTRIOLI",na=False),
        ]
        choices = ["SABROSANO","GT","BALSAMICO","MI SAZON","AVE","PASTAS","OLIVAS","NUTRIOLI","REST NUTRIOLI"]
    elif retailer == "WALMART":
        borges_pat = "|".join([x.replace(" ","").upper() for x in ["BORGES ACEITE OLIVA EXTRA VIRGEN 500","BORGES ACEITE OLIVA EXTRA SUAVE","ACEITE DE OLIVA EXTRA VIRGEN KOSHER","ACEITE DE OLIVA A LA ALBAHACA FRESCA","ACEITE DE SOJA JENGIBRE","ACEITE DE OLIVA AL AJO FRITO","ACEITE DE OLIVA AL  ROMERO FRESCO","BORGES ACEITE DE PEPITA UVA 500ML","BORGES ACEITE DE OLIVA EXTRA VIRGEN ECOL","BORGES VINAGRE BALSAMICO 250ML","VINAGRE DE JEREZ 250 ML","VINAGRE DE SIDRA 250 ML","VINAGRE DE VINO FRAMBUESA","VINAGRE DE VINO AL  AJO 250 ML","BORGES VINAGRE VINO BLANCO","VINAGRE DE MANZANA ECOLOGICO","BORGES VINAGRE DE VINOTINTO","VINAGRE DE VINO DE RIOJA BOTELLA 250ML","BORGES ACEITE OLIVA 100 PURO CON AJO"]])
        desc = df["DESC_NORM"].astype(str) if "DESC_NORM" in df.columns else _safe_str(df["DESCRIPCION"])
        conditions = [
            desc.str.contains(borges_pat, regex=True, na=False),
            desc.str.contains("NUTRIOLI",na=False)&desc.str.contains("946",na=False),
            desc.str.contains("SABROSANO",na=False),
            desc.str.contains("GRANTRADICION",na=False),
            desc.str.contains("BALSAMICO",na=False),
            (desc.str.contains("OLISPRAY|OLICOCINA|OLIDENUTEV|ACEITEOLIDEOLIVA|OLIDENUT",na=False))&~desc.str.contains("BALSAMICO",na=False),
            desc.str.contains("PASTA|FUSILLI|SPAGUETTI|SPAGHETTI|FIDEO|CODO|PPS|MACARRON",na=False),
            desc.str.contains("NUTRIOLI",na=False),
        ]
        choices = ["BORGES","NUTRIOLI","SABROSANO","GT","BALSAMICO","OLIVAS","PASTAS","REST NUTRIOLI"]
    else:  
        desc = df["DESC_NORM"].astype(str) if "DESC_NORM" in df.columns else _safe_str(df["ARTICULO"])
        conditions = [
            desc.str.contains("BALSAMICO",na=False),
            desc.str.contains("SABROSANO",na=False),
            desc.str.contains("GRANTRADICION",na=False),
            desc.str.contains("MISAZON|MISAZÓN",na=False),
            desc.str.contains("AVE",na=False)&desc.str.contains("SOYA-CANOLA|AEROSOL",na=False),
            desc.str.contains("PASTA|FUSILLI|SPAGUETTI|SPAGHETTI|FIDEO|CODO|PPS|MACARRON",na=False),
            desc.str.contains("OLI",na=False)&desc.str.contains("OLIVA|EV|AEROSOL",na=False),
            desc.str.contains("NUTRIOLI",na=False)&desc.str.contains("400ML|850ML",na=False)&~desc.str.contains("PROTECT|DEFENSAS",na=False),
            desc.str.contains("NUTRIOLI",na=False),
        ]
        choices = ["BALSAMICO","SABROSANO","GT","MI SAZON","AVE","PASTAS","OLIVAS","NUTRIOLI","REST NUTRIOLI"]
    conditions = [c.to_numpy(dtype=bool) for c in conditions]
    df = df.copy()
    df['Category'] = np.select(conditions, choices, default=None)
    return df.to_json()

@st.cache_data(show_spinner=False, ttl=14400)
def categorize_full_df(df_json: str, retailer: str) -> str:
    return _categorize_df(df_json, retailer)

@st.cache_data(show_spinner=False, ttl=14400)
def build_pie_cached(pie_df_json: str, retailer: str):
    COLORS = {
        "SORIANA":  (["BALSAMICO","SABROSANO","PASTAS","OLIVAS","GT","NUTRIOLI","MI SAZON","AVE","REST NUTRIOLI"],
                     ["#e012a9","#f705ab","#4c915d","#97ad6a","#7d6010","#02c705","#e89015","#ff0000","#00ff04"],
                     "SO_$"),
        "WALMART":  (["SABROSANO","GT","OLIVAS","BALSAMICO","PASTAS","REST NUTRIOLI","NUTRIOLI","BORGES"],
                     ["#E4007C","#a18262","#6B8E23","#9f4576","#426045","#bfff00","#008f39","#FF0000"],
                     "SO_$"),
        "CHEDRAUI": (["BALSAMICO","SABROSANO","PASTAS","OLIVAS","GT","NUTRIOLI","MI SAZON","AVE","REST NUTRIOLI"],
                     ["#e012a9","#f705ab","#4c915d","#97ad6a","#7d6010","#02c705","#e89015","#ff0000","#00ff04"],
                     "SELL_OUT"),
    }
    domain, range_, val_col = COLORS[retailer]
    return _make_pie(pie_df_json, domain, range_, val_col)

@st.cache_data(show_spinner=False, ttl=14400)
def precompute_pie_base(df_cat_json: str, retailer: str) -> str:
    df = pd.read_json(StringIO(df_cat_json))
    if "Category" not in df.columns:
        return None
    val_col = "SELL_OUT" if retailer == "CHEDRAUI" else "SO_$"
    if val_col not in df.columns:
        return None
    pie_df = df.dropna(subset=["Category"]).groupby("Category")[val_col].sum().reset_index()
    pie_df = pie_df[pie_df[val_col] > 0]
    return pie_df.to_json() if not pie_df.empty else None

# --- SESSION HTTP GLOBAL ---
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

def _build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=0.4, status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET", "HEAD"], raise_on_status=False)
    adapter = HTTPAdapter(max_retries=retry, pool_connections=6, pool_maxsize=6)
    session.mount("https://", adapter)
    session.mount("http://",  adapter)
    session.headers.update({"User-Agent": "Mozilla/5.0", "Accept-Encoding": "gzip, deflate", "Connection": "keep-alive"})
    return session

_HTTP_SESSION = _build_session()

def download_file_fast(url: str):
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
            st.session_state.pop(etag_key, None)
            response = _HTTP_SESSION.get(url, timeout=(5, 30), stream=True)
        response.raise_for_status()

        buf = BytesIO()
        for chunk in response.iter_content(chunk_size=256 * 1024):
            if chunk: buf.write(chunk)
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
    url_or_file.seek(0)
    return url_or_file

def set_retailer(retailer_name):
    st.session_state.active_retailer = retailer_name
    for var in _view_vars:
        if var in st.session_state:
            st.session_state[var] = False

# --- 4. MOTOR INTELIGENTE DE LECTURA DE COLUMNAS ---
def find_col(df, candidates):
    for name in candidates:
        for col in df.columns:
            if str(col).strip().upper() == name.upper():
                return col
    for name in candidates:
        for col in df.columns:
            if name.upper() in str(col).strip().upper():
                return col
    return None

def validate_columns(df, retailer, required_cols_dict):
    faltantes = []
    mapeo = {}
    for col_interna, candidatos in required_cols_dict.items():
        encontrada = find_col(df, candidatos)
        if encontrada:
            mapeo[encontrada] = col_interna
        else:
            faltantes.append(f"{col_interna} (ej. {candidatos[0]})")
    
    if faltantes:
        st.error(f"⚠️ **Error en la base de {retailer}:** El Excel cambió su estructura. No se encontraron las siguientes columnas:\n" + "\n".join(f"- {c}" for c in faltantes))
        return None
    
    df = df.rename(columns=mapeo)
    return df[list(required_cols_dict.keys())]

def optimize_floats(df):
    for col in df.select_dtypes(include=['float64']).columns:
        df[col] = df[col].astype('float32')
    return df

def _str_cols(df, cols):
    for c in cols:
        if c in df.columns:
            df[c] = df[c].astype(str)
    return df

# --- LOADERS ---
@st.cache_data(**CACHE_CONFIG)
def load_sor(path):
    try:
        source = download_file(path)
        if source is None: return None
        
        try:
            df = pd.read_excel(source, engine='calamine')
        except Exception:
            source.seek(0)
            df = pd.read_excel(source, engine='openpyxl')
            
        SORIANA_COLS = {
            "RESURTIMIENTO": ["Resurtible"],
            "CODIGO": ["Código de Barras Ragasa", "Codigo de Barras", "Codigo"],
            "DESCRIPCION": ["Descripción", "Descripcion"],
            "NO_TIENDA": ["No tienda", "No. Tienda", "# Tienda"],
            "TIENDA": ["Nombre Tienda", "Tienda"],
            "CIUDAD": ["Ciudad", "CIUDAD", "Municipio", "MUNICIPIO", "City"],
            "ESTADO": ["Estado"],
            "FORMATO": ["Formato"],
            "PEDIDOS": ["# PEDIDOS", "PEDIDOS"],
            "FECHA_ENTREGA": ["PROXIMA ENTREGA", "FECHA ENTREGA"],
            "CANTIDAD_PZS": ["CANTIDAD PROX A LLEGAR", "CANTIDAD PZS"],
            "INV_CAJAS": ["INV CAJAS", "INVENTARIO CAJAS", "INVENTARIO"],
            "PROM_SEM_CAJAS": ["PROM SEM CAJAS", "PROM SEMANAL CAJAS"],
            "DIAS_INV": ["DIAS INV TENDENCIA", "DIAS INV"],
            "COORDINADOR": ["COORDINADOR", "COORDINADOR VTAS"]
        }
        
        pedidos_col = find_col(df, ["# PEDIDOS", "PEDIDOS"])
        if pedidos_col:
            pedidos_idx = list(df.columns).index(pedidos_col)
            all_5_cols = df.columns[pedidos_idx-5 : pedidos_idx]   
            sem_completas = all_5_cols[:-1]                         
            for c in all_5_cols:
                df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
            df["SO_4SEM"] = df[sem_completas[-4:]].sum(axis=1)      
            df["SO_$"]    = df[sem_completas[-1]]                   
        else:
            df["SO_4SEM"] = 0
            df["SO_$"] = 0
            
        SORIANA_COLS["SO_$"] = ["SO_$"]
        SORIANA_COLS["SO_4SEM"] = ["SO_4SEM"]

        _ciudad_idx = df.iloc[:, 7].copy() if len(df.columns) > 7 else None

        df = validate_columns(df, "SORIANA", SORIANA_COLS)
        if df is None: return None

        if _ciudad_idx is not None:
            _ciu_str = _ciudad_idx.fillna("").astype(str).str.strip().str.upper()
            _tda_str = df["TIENDA"].fillna("").astype(str).str.strip().str.upper()
            if (_ciu_str == _tda_str).mean() > 0.5:
                df["CIUDAD"] = _ciu_str

        df["CODIGO"] = df["CODIGO"].fillna("").astype(str).str.replace(r'\.0*$', '', regex=True)
        for c in ["DIAS_INV", "INV_CAJAS", "PROM_SEM_CAJAS", "SO_$", "SO_4SEM", "PEDIDOS", "CANTIDAD_PZS"]:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
            
        df["FECHA_ENTREGA"] = df["FECHA_ENTREGA"].fillna("").astype(str).replace("nan", "")
        df['SIN_VTA'] = (df['SO_4SEM'] == 0)
        df['VTA_PROM'] = df['SO_4SEM']
        
        df = _str_cols(df, ["RESURTIMIENTO", "NO_TIENDA", "TIENDA", "CIUDAD", "ESTADO", "FORMATO", "DESCRIPCION", "COORDINADOR"])
        
        # LIMPIEZA PROFUNDA DE TEXTOS
        df["TIENDA"] = df["TIENDA"].str.replace(r'\s+', ' ', regex=True).str.strip().str.upper()
        df["ESTADO"] = df["ESTADO"].str.replace(r'\s+', ' ', regex=True).str.strip().str.upper()
        
        df["DESC_NORM"] = df["DESCRIPCION"].fillna("").str.upper().str.replace(" ", "", regex=False).str.replace("&NBSP;", "", regex=False)
        return optimize_floats(df)
    except Exception as e:
        st.error(f"Error procesando Soriana: {e}")
        return None

@st.cache_data(**CACHE_CONFIG)
def load_wal(path):
    try:
        source = download_file(path)
        if source is None: return None
        
        try:
            df = pd.read_excel(source, engine='calamine')
        except Exception:
            source.seek(0)
            df = pd.read_excel(source, engine='openpyxl')
            
        WALMART_COLS = {
            "CODIGO": ["UPC"],
            "DESCRIPCION": ["Item Desc"],
            "CATEGORIA": ["Category Name"],
            "ESTADO": ["EDO"],
            "TIENDA": ["Store Name"],
            "FORMATO": ["Business Format"],
            "MARCA": ["Marca"],
            "DIAS_INV": ["DDI OH"],
            "EXISTENCIA": ["OH"],
            "VTA_S1": ["SO - 4 P"],
            "VTA_S2": ["SO - 3 P"],
            "VTA_S3": ["SO - 2 P"],
            "VTA_S4": ["SO - 1 P"],
            "SO_$": ["SO - 1 $"],           
            "SO_CORRIENDO": ["Sell out Valor corriendo"]  
        }
        
        df = validate_columns(df, "WALMART", WALMART_COLS)
        if df is None: return None 

        df["CODIGO"] = df["CODIGO"].fillna("").astype(str).str.replace(r'\.0*$', '', regex=True)
        for c in ["DIAS_INV", "EXISTENCIA", "VTA_S1", "VTA_S2", "VTA_S3", "VTA_S4", "SO_$", "SO_CORRIENDO"]:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
            
        df['PROM_PZS_MENSUAL'] = df[["VTA_S1", "VTA_S2", "VTA_S3", "VTA_S4"]].mean(axis=1)
        df = _str_cols(df, ["CODIGO", "DESCRIPCION", "CATEGORIA", "ESTADO", "TIENDA", "FORMATO", "MARCA"])
        
        # LIMPIEZA PROFUNDA DE TEXTOS
        df["TIENDA"] = df["TIENDA"].str.replace(r'\s+', ' ', regex=True).str.strip().str.upper()
        df["ESTADO"] = df["ESTADO"].str.replace(r'\s+', ' ', regex=True).str.strip().str.upper()
        df["FORMATO"] = df["FORMATO"].str.replace(r'\s+', ' ', regex=True).str.strip().str.upper()
        
        df["DESC_NORM"] = df["DESCRIPCION"].fillna("").str.upper().str.replace(" ", "", regex=False).str.replace("&NBSP;", "", regex=False)
        for _cat_col in ["TIENDA", "ESTADO", "FORMATO", "MARCA", "CATEGORIA"]:
            if _cat_col in df.columns:
                df[_cat_col] = df[_cat_col].astype("category")
        return optimize_floats(df)
    except Exception as e:
        st.error(f"Error procesando Walmart: {e}")
        return None

@st.cache_data(**CACHE_CONFIG)
def load_che(path):
    try:
        source = download_file(path)
        if source is None: return None
        
        try:
            df = pd.read_excel(source, engine='calamine')
        except Exception:
            source.seek(0)
            df = pd.read_excel(source, engine='openpyxl')
        
        CHEDRAUI_COLS = {
            "CODIGO": ["CODIGO BARRAS", "Codigo Barras", "Codigo", "UPC"],
            "ESTADO": ["ESTADO", "Estado"],
            "COORDINADOR": ["COORDINADOR VTAS", "COORDINADOR"],
            "EJECUTIVO": ["EJECUTIVO", "Ejecutivo"],
            "PROMOTOR": ["PROMOTOR", "Promotor"],
            "COL_FILTRO": ["ESTATUS", "Estatus"],
            "CATEGORIA": ["CATEGORÍA", "CATEGORIA"],
            "NO_TIENDA": ["# TDA", "NO TIENDA", "NO_TIENDA"],
            "TIENDA": ["TIENDA", "Tienda"],
            "ARTICULO": ["DESCRIPCION", "DESCRIPCIÓN", "ARTICULO", "Sku"],
            "INV_ULT_SEM": ["INVENTARIO"],
            "TRANSITO_CEDIS": ["Transitos de cedis a tiendas", "TRANSITOS DE CEDIS A TIENDAS", "TRANSITO CEDIS"],
            "VTA_PROM_DIARIA": ["VENTA PROM DIARIO", "VTA PROM"],
            "DIAS_INV": ["DIAS DE INVENTARIO", "DIAS INV"],
            "SELL_OUT": ["VENTA $", "SELL OUT", "VENTA"]
        }
        
        df = validate_columns(df, "CHEDRAUI", CHEDRAUI_COLS)
        if df is None: return None 
        
        col_h = pd.to_numeric(df["COL_FILTRO"], errors='coerce')
        df = df[col_h != 0]
        df = df.dropna(subset=["ARTICULO"])
        df = df[pd.to_numeric(df["NO_TIENDA"], errors='coerce').notna()]
        
        if "CODIGO" in df.columns:
            df["CODIGO"] = df["CODIGO"].fillna("").astype(str).str.replace(r'\.0*$', '', regex=True)
        else:
            df["CODIGO"] = ""
            
        for col in ["INV_ULT_SEM", "TRANSITO_CEDIS", "VTA_PROM_DIARIA", "DIAS_INV", "SELL_OUT"]:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            
        df = _str_cols(df, ["ESTADO", "COORDINADOR", "EJECUTIVO", "PROMOTOR", "CATEGORIA", "NO_TIENDA", "TIENDA", "ARTICULO", "CODIGO"])
        
        # LIMPIEZA PROFUNDA DE TEXTOS
        df["TIENDA"] = df["TIENDA"].str.replace(r'^\d+\s+', '', regex=True).str.replace(r'\s+', ' ', regex=True).str.strip().str.upper()
        df["ESTADO"] = df["ESTADO"].str.replace(r'\s+', ' ', regex=True).str.strip().str.upper()
        
        # UNIFICACIÓN DE TIENDAS POR NÚMERO DE SUCURSAL
        if "NO_TIENDA" in df.columns:
            tienda_map = df.groupby("NO_TIENDA")["TIENDA"].first().to_dict()
            df["TIENDA"] = df["NO_TIENDA"].map(tienda_map).fillna(df["TIENDA"])
            
            estado_map = df.groupby("NO_TIENDA")["ESTADO"].first().to_dict()
            df["ESTADO"] = df["NO_TIENDA"].map(estado_map).fillna(df["ESTADO"])

        df["DESC_NORM"] = df["ARTICULO"].fillna("").str.upper().str.replace(" ", "", regex=False).str.replace("&NBSP;", "", regex=False)
        return optimize_floats(df)
    except Exception as e:
        st.error(f"Error procesando Chedraui: {e}")
        return None

@st.cache_data(ttl=14400, max_entries=3, show_spinner=False)
def _get_cached_df(key: str) -> pd.DataFrame | None:
    loaders = {"SORIANA": load_sor, "WALMART": load_wal, "CHEDRAUI": load_che}
    try:
        df = loaders[key](URLS_DB[key])
        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            return None
        return df
    except Exception:
        return None

def _get_df_with_fallback(key: str) -> "pd.DataFrame | None":
    """Intenta cache_data; si falla usa respaldo en session_state (modo offline)."""
    try:
        df = _get_cached_df(key)
        if df is not None and isinstance(df, pd.DataFrame) and not df.empty:
            st.session_state[f"_backup_{key}"] = df  # guardar respaldo
            return df
    except Exception:
        pass
    # Fallback offline
    backup = st.session_state.get(f"_backup_{key}")
    if backup is not None and isinstance(backup, pd.DataFrame) and not backup.empty:
        return backup
    return None

# ══════════════════════════════════════════════════════════════════════
# LISTAS DE PRODUCTOS
# ══════════════════════════════════════════════════════════════════════
_SOR_DIAS_PROD = ["ACEITE DE SOYA NUTRIOLI BOT 850 ML","ACEITE COMESTIBLE NUTRIOLI 400 ML","ACEITE COMESTIBLE SABROSANO 850 ML","ACEITE COMESTIBLE GRAN TRADICION 800 ML","ACEITE NUTRIOLI PROTECT DEFENSAS 850ML","ACEITE NUTRIOLI PROTECT MENTE 850 ML","ACEITE COMESTIBLE NUTRIOLI AEROSOL 180ML","ACEITE COMESTIBLE NUTRIOLI ANTIGOTEO 700","ACEITE OLI OLIVA EXTRA VIRGEN PZ 250ML","ACEITE OLI OLIVA EXTRA VIRGEN PZ 500ML","ACEITE OLI OLIVA EXTRA VIRGEN PZ 750ML","ADERE OLI OLIVA PARA COCINAR 500 ML OLI","ADERE OLI OLIVA PARA COCINAR 750 ML OLI","ADEREZO OLI 250 ML PZ","ADEREZO OLI 500 ML BOT","ACEITE COMESTIBLE AVE 850 ML","ACEITE COMESTIBLE AEROSOL 170GR","ACEITE OLIVA OLI PURO SPRAY 145 ML","ACEITE OLIVA OLI EV SPRAY 145 ML","PASTA FIDEO NUTRIOLI 200GR","PASTA SPAGHETTI NUTRIOLI INTEGRAL 200GR","PASTA FUSILLI INTEGRAL NUTRIOLI 200GR","PASTA CODO NUTRIOLI VERDURAS 200GR","PASTA FUSILLI VERDURAS NUTRIOLI 450GR","PASTA SPAGHETTI NUTRIOLI 200GR","PASTA CODO NUTRIOLI 200GR","VINAGRE BALSAMICO 250ML"]
_SOR_RANK_GEN  = ["ACEITE COMESTIBLE NUTRIOLI ANTIGOTEO 700","ACEITE COMESTIBLE GRAN TRADICION 900 ML","ACEITE COMESTIBLE SABROSANO +30 850 ML","ACEITE OLIVA OLI PURO SPRAY 145 ML","JUSTO 850 ML","ACEITE COMESTIBLE AEROSOL 170GR","ACEITE COMESTIBLE AVE 850 ML","ACEITE COMESTIBLE NUTRIOLI 400 ML","ACEITE COMESTIBLE NUTRIOLI AEROSOL 180ML","ACEITE COMESTIBLE NUTRIOLI DHA 850 ML","ACEITE COMESTIBLE SABROSANO 850 ML","SABROSANO RINDE+ 850 ML","ACEITE OLI OLIVA EXTRA VIRGEN PZ 250ML","ACEITE OLI OLIVA EXTRA VIRGEN PZ 500ML","ACEITE OLI OLIVA EXTRA VIRGEN PZ 750ML","ADERE OLI OLIVA PARA COCINAR 500 ML OLI","ADERE OLI OLIVA PARA COCINAR 750 ML OLI","ADEREZO OLI 250 ML PZ","ADEREZO OLI 500 ML BOT","ACEITE COMESTIBLE GRAN TRADICION 800 ML","ACEITE DE SOYA NUTRIOLI BOT 850 ML","VINAGRE BALSAMICO 250ML","ACEITE NUTRIOLI PROTECT DEFENSAS 850ML","ACEITE NUTRIOLI PROTECT MENTE 850 ML","PASTA FIDEO NUTRIOLI 200GR","PASTA SPAGHETTI NUTRIOLI INTEGRAL 200GR","PASTA FUSILLI INTEGRAL NUTRIOLI 200GR","PASTA CODO NUTRIOLI VERDURAS 200GR","PASTA FUSILLI VERDURAS NUTRIOLI 450GR","PASTA SPAGHETTI NUTRIOLI 200GR","PASTA CODO NUTRIOLI 200GR"]
_SOR_RANK_PAS  = ["PASTA FIDEO NUTRIOLI 200GR","PASTA SPAGHETTI NUTRIOLI INTEGRAL 200GR","PASTA FUSILLI INTEGRAL NUTRIOLI 200GR","PASTA CODO NUTRIOLI VERDURAS 200GR","PASTA FUSILLI VERDURAS NUTRIOLI 450GR","PASTA SPAGHETTI NUTRIOLI 200GR","PASTA CODO NUTRIOLI 200GR"]
_SOR_RANK_OLI  = ["ACEITE OLI OLIVA EXTRA VIRGEN PZ 250ML","ACEITE OLI OLIVA EXTRA VIRGEN PZ 500ML","ACEITE OLI OLIVA EXTRA VIRGEN PZ 750ML","ADERE OLI OLIVA PARA COCINAR 500 ML OLI","ADERE OLI OLIVA PARA COCINAR 750 ML OLI","ADEREZO OLI 250 ML PZ","ADEREZO OLI 500 ML BOT","ACEITE OLIVA OLI PURO SPRAY 145 ML"]
_SOR_RANK_NUT  = ["ACEITE DE SOYA NUTRIOLI BOT 850 ML"]

_WAL_DIAS_PROD = ["NUTRIOLI ACEITE PURO DE SOYA 946 ML","NUTRIOLI ACEITE PURO DE SOYA 400 ML","SABROSANO ACEITE 850ML MANTEQUILLA","ACEITE COMESTIBLE GRAN TRADICION 850ML","ACEITE SOYA NUTRIOLI ANTIGOTEO 700ML","ACEITE NUTRIOLI DEFENSAS 850 ML","NUTRIOLI ACEITE PROTECT MENTE 850 ML","NUTRIOLI SPRAY 180 ML","AVE AEROSOL 170GR","OLI SPRAY ACEITE DE OLIVA 145ML","OLI SPRAY ACEITE DE OLIVA EV 145ML","OLI DE NUTRIOLI EXTRA VIRGEN 250ML","OLI DE NUTRIOLI ACEITE DE OLIVA 500ML","OLI DE NUTRIOLI ACEITE DE OLIVA 750ML","OLI ACEITE DE OLIVA COCINA 250ML","ACEITE DE OLIVA EXTRA VIRGEN OLI DE NUTR","ACEITE OLI DE OLIVA EX VIRGEN ORGANICO","OLI NUTRIOLI VINAGRE BALSAMICO MODENA250","VINAGRE DE JEREZ 250 ML","VINAGRE DE MANZANA ECOLOGICO","VINAGRE DE SIDRA 250 ML","VINAGRE DE VINO AL  AJO 250 ML","VINAGRE DE VINO DE RIOJA BOTELLA 250ML","VINAGRE DE VINO FRAMBUESA","BORGES ACEITE DE OLIVA EXTRA VIRGEN ECOL","BORGES ACEITE DE PEPITA UVA 500ML","BORGES ACEITE OLIVA 100 PURO CON AJO","BORGES ACEITE OLIVA EXTRA SUAVE","BORGES ACEITE OLIVA EXTRA VIRGEN 500","BORGES VINAGRE BALSAMICO 250ML","BORGES VINAGRE DE VINOTINTO","BORGES VINAGRE VINO BLANCO","ACEITE DE OLIVA A LA ALBAHACA FRESCA","ACEITE DE OLIVA AL  ROMERO FRESCO","ACEITE DE OLIVA AL AJO FRITO","ACEITE DE OLIVA EXTRA VIRGEN KOSHER","ACEITE DE SOJA JENGIBRE"]

_CHE_RANK_GEN  = ["Vinagre Oli Nutrioli Balsámico 250 ml (3795515)","Aceite Sabrosano Mixto 850 ML (3691244)","Aceite Mi Sazón Vegetal 800 ML (3775895)","Pps Nutrioli Fusilli Integral (3878678)","Aceite Ave Soya-Canola 850 ML (3696190)","Pps Nutrioli Spaguetti 200 (3878673)","Pps Nutrioli Fusilli Verduras (3878676)","Pps Nutrioli Fideo 200 Gr (3878671)","Aceite Nutrioli Antigoteo 700 ML (3738492)","Pps Nutrioli Spaguetti Integra (3878677)","Pps Nutrioli Codo Verduras 200 (3878675)","Pps Nutrioli Codo 200 Gr (3878674)","Aceite Nutrioli Protect Defensas 850 ml (3828176)","Pps Nutrioli Fusilli 450 (3878672)","Ace Oliva EV Oli BOT 750 Ml (3284693)","Aceite Oliva Puro Oli Bote 750 Ml (3570620)","Ace Oliva EV Oli BOT 500 Ml (3368446)","Aceite Gran Tradición Soya-Canola 800 ML (3009894)","Aceite Nutrioli Protect Mente 850 Ml (3009960)","Aceite De Soya Nutrioli Bot 850 Ml (3132396)","Ace Oliva Puro Oli BOT 500 Ml (3570614)","Ace Oliva EV Oli BOT 250 Ml (3284690)","Aceite De Soya Nutrioli Bot 400 Ml (3590824)","Aceite Mi Sazón Mixto 400 ML","Aceite Aerosol Nutrioli Soya Lata 180 Gr (3317342)","Aceite Oli Extra Virgen 500 Ml (3646332)","Aceite Aerosol Ave Mixto 170 Gr (3693814)","Aceite de Oliva Oli Nutrioli 250 Ml (3679970)","Aceite Nutrioli Soya 850 ML (3676715)","Aceite Sabrosano Rinde + 850 ML (3782858)","Aceite Aerosol Oli Oliva 145 Ml (3679971)","Ace Oliva EV Oli BOT 500 Ml (3428657)","Aceite Nutrioli 850+Pps Fusill (3880416)","Aceite Nutrioli 850+Pps Codo 2 (3880415)"]
_CHE_RANK_PAS  = ["Pps Nutrioli Fusilli Integral (3878678)","Pps Nutrioli Spaguetti 200 (3878673)","Pps Nutrioli Fusilli Verduras (3878676)","Pps Nutrioli Fideo 200 Gr (3878671)","Pps Nutrioli Spaguetti Integra (3878677)","Pps Nutrioli Codo Verduras 200 (3878675)","Pps Nutrioli Codo 200 Gr (3878674)","Pps Nutrioli Fusilli 450 (3878672)"]
_CHE_RANK_OLI  = ["Ace Oliva EV Oli BOT 750 Ml (3284693)","Aceite Oliva Puro Oli Bote 750 Ml (3570620)","Ace Oliva EV Oli BOT 500 Ml (3368446)","Ace Oliva Puro Oli BOT 500 Ml (3570614)","Ace Oliva EV Oli BOT 250 Ml (3284690)","Aceite Oli Extra Virgen 500 Ml (3646332)","Aceite de Oliva Oli Nutrioli 250 Ml (3679970)","Aceite Aerosol Oli Oliva 145 Ml (3679971)","Ace Oliva EV Oli BOT 500 Ml (3428657)"]
_CHE_RANK_NUT  = ["Aceite De Soya Nutrioli Bot 850 Ml (3132396)"]

# --- 5. CARGA PARALELA DE LAS 3 BASES ---
def _download_raw(key: str) -> tuple[str, BytesIO | None, str | None]:
    try:
        buf = download_file_fast(URLS_DB[key])
        if buf is None:
            return key, None, "No se pudo descargar el archivo."
        return key, buf, None
    except Exception as e:
        return key, None, str(e)

def _parse_raw(key: str, buf: BytesIO):
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
        buf.seek(0)
        loaders = {"SORIANA": load_sor, "WALMART": load_wal, "CHEDRAUI": load_che}
        df = loaders[key](buf)
        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            return key, None, "Archivo vacío o sin columnas válidas."
        return key, df, None
    except Exception as e:
        return key, None, str(e)

def load_all_parallel():
    keys    = list(URLS_DB.keys())
    results = {}
    errors  = {}

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
            pct = 0.0 + (len(done_dl) / n) * 0.50
            msg = f"⬇️ {key} descargado" if buf else f"⚠️ Error descargando {key}"
            render_screen(pct, msg, done_dl if buf else set(), "📡 Fase 1/2 — Descargando archivos en paralelo")

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
            pct = 0.50 + (len(done_parse) / n) * 0.50
            msg = f"✅ {key} listo" if results.get(key) is not None else f"⚠️ Error en {key}"
            render_screen(pct, msg, {k for k in done_parse if results.get(k) is not None},
                          "⚙️ Fase 2/2 — Procesando Excel en paralelo")

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
c_transito_c = st.session_state.get('c_transito', False)
c_rank_gen = st.session_state.get('c_rank_gen', False)
c_rank_pas = st.session_state.get('c_rank_pas', False)
c_rank_oli = st.session_state.get('c_rank_oli', False)
c_rank_nut = st.session_state.get('c_rank_nut', False)

# --- 7. FUNCIÓN INYECTORA DE ESTILOS JS EXACTA ---
def inject_button_styles():
    _dias_active = s_dias_inv or w_dias_inv or c_dias_inv
    _prod_active = s_dias_prod or w_dias_prod
    _neg_active  = w_neg or c_neg_zero

    _gen_active = s_rank_gen or w_rank_tiendas or c_rank_gen
    _pas_active = s_rank_pas or w_rank_pastas  or c_rank_pas
    _oli_active = s_rank_oli or w_rank_olivas  or c_rank_oli
    _nut_active = s_rank_nut or w_nutri_top10  or c_rank_nut

    STYLES = [
        # Navegación principal
        ("SORIANA",  "linear-gradient(135deg,#D32F2F,#B71C1C)", "#ffffff", act=="SORIANA",  "#ffffff", "rgba(255,41,0,0.85)",  False, "transparent"),
        ("WALMART",  "linear-gradient(135deg,#0071DC,#005BB5)", "#ffffff", act=="WALMART",  "#ffffff", "rgba(0,47,255,0.85)",  False, "transparent"),
        ("CHEDRAUI", "linear-gradient(135deg,#FF6600,#E65100)", "#ffffff", act=="CHEDRAUI", "#ffffff", "rgba(255,119,0,0.85)", False, "transparent"),
        
        # --- Botones de Acción SORIANA ---
        ("🔴 INV SIN VENTA", "#D32F2F", "#ffffff", s_rojo, "#ffffff", "rgba(211,47,47,0.85)", False, "#ef9a9a"),
        ("🚚 PEDIDOS EN TRANSITO", "#8507F0", "#ffffff", s_transito, "#ffffff", "rgba(176,108,240,0.85)", False, "#CE93D8"),
        
        # --- Botones de Acción WALMART ---
        ("🔴 SIN VTA 4SEM",  "#D32F2F", "#ffffff", w_4w,   "#ffffff", "rgba(211,47,47,0.85)", False, "#90CAF9"),
        
        # Ranking Institucional
        ("📊 GENERAL",  "#FFFFFF","#5AB027", _gen_active, "#D4D4D4","rgba(46,125,50,0.70)", False, "#D4D4D4"),
        ("🍝 PASTAS",   "#DBBB35","#FFFFFF", _pas_active, "#D4D4D4","rgba(240,228,2,0.70)", True,  "transparent"),
        ("🫒 OLIVAS",   "#4E5C02","#FFFFFF", _oli_active, "#D4D4D4","rgba(46,125,50,0.70)", True,  "transparent"),
        ("🍃 NUTRIOLI", "#2E7D32","#FFD700", _nut_active, "#D4D4D4","rgba(46,125,50,0.70)", True,  "transparent"),
        ("🏆 NUTRIOLI", "#2E7D32","#FFD700", _nut_active, "#D4D4D4","rgba(46,125,50,0.70)", True,  "transparent"),
    ]
    
    if act == "SORIANA":
        STYLES.extend([
            ("📅 DIAS INV",    "#00695C", "#ffffff", _dias_active, "#ffffff", "rgba(211,47,47,0.85)",    False, "#80CBC4"),
            ("📋 DIAS X PROD", "#1D362B", "#ffffff", _prod_active, "#ffffff", "rgba(0,105,92,0.85)",  False, "#CE93D8"),
        ])
    elif act == "WALMART":
        STYLES.extend([
            ("📉 NEGATIVOS",   "#D32F2F", "#ffffff", _neg_active,  "#ffffff", "rgba(211,47,47,0.85)",    False, "#FFAB40"),
            ("📅 DIAS INV",    "#00695C", "#ffffff", _dias_active, "#ffffff", "rgba(0,105,92,0.85)",    False, "#80CBC4"),
            ("📋 DIAS X PROD", "#1D362B", "#ffffff", _prod_active, "#ffffff", "rgba(0,105,92,0.85)",  False, "#CE93D8"),
        ])
    elif act == "CHEDRAUI":
        STYLES.extend([
            ("📉 NEGATIVOS",          "#B71C1C", "#ffffff", _neg_active,     "#ffffff", "rgba(183,28,28,0.85)",   False, "#EF9A9A"),
            ("📅 DIAS INV",           "#00695C", "#ffffff", _dias_active,    "#ffffff", "rgba(0,105,92,0.85)",    False, "#80CBC4"),
            ("🚚 PEDIDOS EN TRANSITO","#8507F0", "#ffffff", c_transito_c,    "#ffffff", "rgba(176,108,240,0.85)", False, "#CE93D8"),
        ])

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
div[data-testid="stHorizontalBlock"] button {{
    font-size: clamp(0.55rem, 1.8vw, 0.85rem) !important;
    white-space: nowrap !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
    min-height: 42px !important;
    height: 42px !important;
    padding: 0 6px !important;
    line-height: 1 !important;
}}
div[data-baseweb="select"] {{ height: 42px !important; min-height: 42px !important; max-height: 42px !important; overflow: hidden !important; }}
div[data-baseweb="select"] > div {{ height: 42px !important; min-height: 42px !important; max-height: 42px !important; overflow: hidden !important; flex-wrap: nowrap !important; align-items: center !important; }}
div[data-baseweb="select"] > div > div {{ overflow: visible !important; display: flex !important; align-items: center !important; flex-wrap: nowrap !important; max-height: 42px !important; }}
div[data-baseweb="select"] input {{ line-height: 42px !important; font-size: 0.9rem !important; padding-left: 6px !important; }}
div[data-baseweb="tag"] {{ max-width: 90px !important; overflow: hidden !important; text-overflow: ellipsis !important; white-space: nowrap !important; flex-shrink: 0 !important; }}
div[data-baseweb="select"] span {{ white-space: nowrap !important; }}
div[data-baseweb="popover"] {{ max-height: 320px !important; overflow-y: auto !important; }}
[data-testid="stHorizontalBlock"] {{ align-items: flex-start !important; }}
[data-testid="stVerticalBlock"] {{ scroll-margin-top: 0px !important; }}
@media (max-width: 768px) {{
    .block-container {{ padding-left: 0.5rem !important; padding-right: 0.5rem !important; }}
    .retailer-header {{ font-size: 1rem; padding: 8px; margin: 10px 0; }}
    section[data-testid="stSidebar"] {{ display: none; }}
    div[data-testid="stHorizontalBlock"] button {{ font-size: clamp(0.5rem, 3.2vw, 0.72rem) !important; height: 42px !important; min-height: 42px !important; }}
}}
</style>
""", unsafe_allow_html=True)

st.components.v1.html("""
<script>
(function() {
    const win = window.parent;
    let savedScroll = 0;
    let restoring = false;
    function saveScroll() { savedScroll = win.scrollY; restoring = true; }
    function restoreScroll() {
        if (!restoring) return;
        win.scrollTo({ top: savedScroll, behavior: "instant" });
        restoring = false;
    }
    win.document.addEventListener("mousedown", saveScroll, true);
    new MutationObserver(restoreScroll).observe(win.document.body, { childList: true, subtree: true });
})();
</script>
""", height=0, scrolling=False)

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
_df_map = {"SORIANA": "df_soriana", "WALMART": "df_walmart", "CHEDRAUI": "df_chedraui"}

if not st.session_state.data_loaded:
    st.session_state.is_online = _check_online()

    if st.session_state.is_online:
        _keys = list(_df_map.keys())

        st.markdown("""
        <style>
        .loader-wrap { display:flex; flex-direction:column; align-items:center; justify-content:center; padding: 60px 20px; }
        .loader-title { font-size:1.6rem; font-weight:800; color:#333; margin-bottom:8px; text-align:center; }
        .loader-sub { font-size:0.95rem; color:#777; margin-bottom:32px; text-align:center; }
        .retailer-badges { display:flex; gap:16px; margin-bottom:32px; flex-wrap:wrap; justify-content:center; }
        .badge { padding:8px 20px; border-radius:20px; font-weight:700; font-size:0.85rem; color:white; opacity:0.4; transition: opacity 0.3s; }
        .badge.done { opacity:1; }
        .badge-sor { background:#D32F2F; }
        .badge-wal { background:#0071DC; }
        .badge-che { background:#FF6600; }
        </style>
        """, unsafe_allow_html=True)

        _placeholder  = st.empty()
        _progress_bar = st.progress(0)
        _status_text  = st.empty()

        def _render(pct, msg, done_set, phase=""):
            sor_cls = "done" if "SORIANA"  in done_set else ""
            wal_cls = "done" if "WALMART"  in done_set else ""
            che_cls = "done" if "CHEDRAUI" in done_set else ""
            _placeholder.markdown(f"""
            <div class="loader-wrap">
                <div class="loader-title">⚙️ Sincronizando bases de datos</div>
                <div class="loader-sub">{phase}</div>
                <div class="retailer-badges">
                    <span class="badge badge-sor {sor_cls}">{"✅" if sor_cls else "⏳"} SORIANA</span>
                    <span class="badge badge-wal {wal_cls}">{"✅" if wal_cls else "⏳"} WALMART</span>
                    <span class="badge badge-che {che_cls}">{"✅" if che_cls else "⏳"} CHEDRAUI</span>
                </div>
            </div>
            """, unsafe_allow_html=True)
            _progress_bar.progress(pct)
            _status_text.markdown(f"<p style='text-align:center;color:#555;font-size:0.9rem;'>{msg} — <b>{int(pct*100)}%</b></p>", unsafe_allow_html=True)

        _render(0.0, "Conectando a GitHub CDN…", set(), "📡 Descargando bases en paralelo")
        _errors = {}
        _done = set()
        _n = len(_keys)

        with ThreadPoolExecutor(max_workers=3) as _ex:
            _fmap = {_ex.submit(_get_cached_df, k): k for k in _keys}
            for _fut in as_completed(_fmap):
                _k = _fmap[_fut]
                try:
                    _df = _fut.result()
                except Exception as _e:
                    _df = None
                    _errors[_k] = str(_e)
                if _df is not None:
                    st.session_state[_df_map[_k]] = _df
                    _done.add(_k)
                else:
                    if _k not in _errors:
                        _errors[_k] = "No se pudo cargar"
                _pct = len(_done) / _n
                _msg = f"✅ {_k} listo" if _df is not None else f"⚠️ Error en {_k}"
                _render(_pct, _msg, _done, "📡 Descargando bases en paralelo")

        _render(1.0, "¡Carga completa!", _done, "✅ Listo")
        time.sleep(0.5)
        _placeholder.empty(); _progress_bar.empty(); _status_text.empty()

        st.session_state.load_errors = _errors
        st.session_state.data_loaded = True

    else:
        # Sin internet — recuperar desde respaldo en session_state
        st.session_state.data_loaded = True
        _recovered = 0
        for _rk, _ss in [("SORIANA","df_soriana"),("WALMART","df_walmart"),("CHEDRAUI","df_chedraui")]:
            _df_off = _get_df_with_fallback(_rk)
            if _df_off is not None:
                st.session_state[_ss] = _df_off
                _recovered += 1
        if _recovered == 0:
            st.warning("⚠️ Sin conexión y sin datos en caché. Conéctese a internet para cargar las bases.")
        else:
            st.info(f"📴 Modo OFFLINE — {_recovered}/3 bases disponibles desde caché")

    try:
        for _rk, _ss in [("SORIANA","df_soriana"),("WALMART","df_walmart"),("CHEDRAUI","df_chedraui")]:
            _df_pre = _get_df_with_fallback(_rk)
            if _df_pre is None:
                continue
            _pie_key = f"pie_base_{_rk.lower()}"
            # cat_ NO se guarda en session_state — vive en @st.cache_data (ahorra ~60% RAM)
            if _pie_key not in st.session_state:
                _cat_json = categorize_full_df(_df_pre.to_json(), _rk)
                _pie_json = precompute_pie_base(_cat_json, _rk)
                if _pie_json:
                    st.session_state[_pie_key] = _pie_json  # Solo JSON pequeño del groupby
    except Exception:
        pass

else:
    pass  # DataFrames viven en @st.cache_data — no se duplican en session_state

if st.session_state.load_errors:
    for k, err in st.session_state.load_errors.items():
        st.warning(f"⚠️ {k}: {err}")

# --- 11. NAVEGACIÓN ---
col1, col2, col3 = st.columns(3, gap="small")
with col1: st.button("SORIANA",  on_click=set_retailer, args=("SORIANA",),  use_container_width=True)
with col2: st.button("WALMART",  on_click=set_retailer, args=("WALMART",),  use_container_width=True)
with col3: st.button("CHEDRAUI", on_click=set_retailer, args=("CHEDRAUI",), use_container_width=True)
st.markdown("<hr style='margin:15px 0;border:0;border-top:1px solid #eee;'>", unsafe_allow_html=True)

inject_button_styles()

# --- 12. HELPER: OBTENER DATOS ---
def get_cached_or_upload(key, uploader_key, load_func):
    df_key_map = {"SORIANA": "df_soriana", "WALMART": "df_walmart", "CHEDRAUI": "df_chedraui"}
    ss_key = df_key_map[key]

    # Leer con fallback offline
    try:
        df = _get_df_with_fallback(key)
        if df is not None and isinstance(df, pd.DataFrame) and not df.empty:
            return df
    except Exception:
        pass

    st.warning(f"⚠️ No se pudo cargar {key} automáticamente. Cargue el archivo manualmente.")
    f = st.file_uploader(f"📂 Cargar Excel {key}", type=["xlsx"], key=uploader_key)
    if f:
        with st.spinner(f"Procesando {key}..."):
            df = load_func(f)
        return df
    return None

@st.cache_data(show_spinner=False, ttl=14400)
def _unique_sorted(series_hash: int, vals_tuple: tuple) -> list:
    return sorted(vals_tuple)

def _us(series) -> list:
    vals = tuple(series.dropna().unique())
    return _unique_sorted(hash(vals), vals)

# --- 13. VISTAS ---
def view_soriana(df_s):
    df_s_cat = pd.read_json(StringIO(categorize_full_df(df_s.to_json(), "SORIANA")))  # @cache_data TTL 4h
    st.markdown(f"<div class='retailer-header' style='background-color:{RETAILER_COLORS['SORIANA']}'>SORIANA</div>", unsafe_allow_html=True)
    _upd_s = _get_last_update("SORIANA")
    st.markdown(f"<p style='text-align:right;color:#888;font-size:0.75rem;margin:-8px 0 4px 0;'>🕐 Última actualización: <b>{_upd_s}</b></p>", unsafe_allow_html=True)

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
        for _k in ["s_fil_nda","s_fil_edo","s_fil_nom","s_fil_cd","s_fil_fmt"]:
            if _k not in st.session_state:
                st.session_state[_k] = []

        def _on_nda_change():
            nda = st.session_state.get("s_fil_nda", [])
            if nda:
                _t = df_s[df_s["NO_TIENDA"].isin(nda)]
                st.session_state["s_fil_nom"] = sorted(_t["TIENDA"].dropna().unique())
                st.session_state["s_fil_edo"] = sorted(_t["ESTADO"].dropna().unique())
                st.session_state["s_fil_cd"]  = sorted(_t["CIUDAD"].dropna().unique())
                st.session_state["s_fil_fmt"] = sorted(_t["FORMATO"].dropna().unique())
            else:
                st.session_state["s_fil_nom"] = []
                st.session_state["s_fil_edo"] = []
                st.session_state["s_fil_cd"]  = []
                st.session_state["s_fil_fmt"] = []

        def _on_edo_change():
            if st.session_state.get("s_fil_nda"):
                return
            edo = st.session_state.get("s_fil_edo", [])
            if edo:
                _t = df_s[df_s["ESTADO"].isin(edo)]
                _ciudades = _t["CIUDAD"].dropna().unique()
                _nombres  = set(_t["TIENDA"].dropna().str.strip().str.upper())
                _limpias  = [c for c in _ciudades if str(c).strip().upper() not in _nombres]
                st.session_state["s_fil_cd"]  = sorted(_limpias) if _limpias else sorted(_ciudades)
                st.session_state["s_fil_fmt"] = sorted(_t["FORMATO"].dropna().unique())
            else:
                st.session_state["s_fil_cd"]  = []
                st.session_state["s_fil_fmt"] = []
            st.session_state["s_fil_nom"] = []
            st.session_state["s_fil_nda"] = []

        def _on_nom_change():
            if st.session_state.get("s_fil_nda"):
                return
            nom = st.session_state.get("s_fil_nom", [])
            if nom:
                _t = df_s[df_s["TIENDA"].isin(nom)]
                st.session_state["s_fil_nda"] = sorted(_t["NO_TIENDA"].dropna().unique())
                st.session_state["s_fil_edo"] = sorted(_t["ESTADO"].dropna().unique())
                _ciudades = _t["CIUDAD"].dropna().unique()
                _nombres  = set(_t["TIENDA"].dropna().str.strip().str.upper())
                _limpias  = [c for c in _ciudades if str(c).strip().upper() not in _nombres]
                st.session_state["s_fil_cd"]  = sorted(_limpias) if _limpias else sorted(_ciudades)
                st.session_state["s_fil_fmt"] = sorted(_t["FORMATO"].dropna().unique())
            else:
                st.session_state["s_fil_nda"] = []
                st.session_state["s_fil_edo"] = []
                st.session_state["s_fil_cd"]  = []
                st.session_state["s_fil_fmt"] = []

        def _reset_sor_filters():
            for _k in ["s_fil_nda","s_fil_edo","s_fil_nom","s_fil_cd","s_fil_fmt"]:
                st.session_state[_k] = []

        _rc1, _rc2 = st.columns([8, 2])
        with _rc1: st.markdown("#### 🔍 Filtros Avanzados")
        with _rc2: st.button("🗑️ Limpiar filtros", key="btn_reset_sor", on_click=_reset_sor_filters, use_container_width=True, type="secondary")

        with st.container():
            c1, c2 = st.columns(2)

            _edo_sel = st.session_state.get("s_fil_edo", [])
            _nda_sel = st.session_state.get("s_fil_nda", [])
            if _nda_sel:
                _df_scope = df_s[df_s["NO_TIENDA"].isin(_nda_sel)]
            elif _edo_sel:
                _df_scope = df_s[df_s["ESTADO"].isin(_edo_sel)]
            else:
                _df_scope = df_s
            _opts_nom = sorted(_df_scope["TIENDA"].dropna().unique())
            _opts_cd  = sorted(_df_scope["CIUDAD"].dropna().unique())
            _opts_fmt = sorted(_df_scope["FORMATO"].dropna().unique())

            with c1:
                opts_res = ["Todos"] + _us(df_s["RESURTIMIENTO"])
                def_res  = ["1.0"] if "1.0" in opts_res else (["1"] if "1" in opts_res else ["Todos"])
                fil_res = st.multiselect("Resurtible", opts_res, default=def_res, placeholder="Seleccionar...")
                fil_nda = st.multiselect("No Tienda", _us(df_s["NO_TIENDA"]), placeholder="Buscar no. tienda...",
                                         key="s_fil_nda", on_change=_on_nda_change)
                fil_nom = st.multiselect("Nombre", _opts_nom, placeholder="Buscar tienda...",
                                         key="s_fil_nom", on_change=_on_nom_change)
            with c2:
                fil_edo = st.multiselect("Estado", _us(df_s["ESTADO"]), placeholder="Seleccionar...",
                                         key="s_fil_edo", on_change=_on_edo_change)
                fil_cd  = st.multiselect("Ciudad",  _opts_cd,  key="s_fil_cd", placeholder="Seleccionar...")
                fil_fmt = st.multiselect("Formato", _opts_fmt, key="s_fil_fmt", placeholder="Seleccionar...")
                fil_art = st.multiselect("Artículo", _us(df_s["DESCRIPCION"]), placeholder="Seleccionar...")

        dff = apply_filters(df_s,
            ["RESURTIMIENTO","NO_TIENDA","TIENDA","CIUDAD","ESTADO","FORMATO","DESCRIPCION"],
            [fil_res if "Todos" not in fil_res else None, fil_nda, fil_nom, fil_cd, fil_edo, fil_fmt, fil_art])

        dff_graph = apply_filters(df_s, ["NO_TIENDA","TIENDA","CIUDAD","ESTADO"], [fil_nda, fil_nom, fil_cd, fil_edo])
        if dff_graph.empty and (fil_nda or fil_nom):
            dff_graph = apply_filters(df_s, ["NO_TIENDA","TIENDA"], [fil_nda, fil_nom])
        if dff_graph.empty and fil_edo:
            dff_graph = apply_filters(df_s, ["ESTADO"], [fil_edo])
        if dff_graph.empty:
            dff_graph = df_s

        b1, b2, b3, b4 = st.columns(4, gap="small")
        with b1: st.button("🔴 INV SIN VENTA", on_click=tog_s_rojo,      use_container_width=True, type="primary" if s_rojo      else "secondary")
        with b2: st.button("📅 DIAS INV",      on_click=tog_s_dias_inv,  use_container_width=True, type="primary" if s_dias_inv  else "secondary")
        with b3: st.button("📋 DIAS X PROD",   on_click=tog_s_dias_prod, use_container_width=True, type="primary" if s_dias_prod else "secondary")
        with b4: st.button("🚚 PEDIDOS EN TRANSITO", on_click=tog_s_transito, use_container_width=True, type="primary" if s_transito else "secondary")

        dff_cat = dff_graph.merge(df_s_cat[["Category"]], left_index=True, right_index=True, how="left")
        c_kpi, c_chart = st.columns([1,2])
        with c_kpi:
            total_so = dff_cat['SO_$'].sum()
            st.markdown(f"<div class='kpi-card' style='height:450px;'><div class='kpi-title'>Total Sell Out Semanal</div><div class='kpi-value' style='color:#D32F2F;'>${total_so:,.2f}</div></div>", unsafe_allow_html=True)
        with c_chart:
            _hay_filtros_s = any([fil_nda, fil_nom, fil_cd, fil_edo])
            if _hay_filtros_s:
                pie_df = dff_cat.dropna(subset=['Category']).groupby('Category')['SO_$'].sum().reset_index()
                pie_df = pie_df[pie_df['SO_$']>0]
                if pie_df.empty:
                    _pie_json_s = st.session_state.get("pie_base_soriana")
                else:
                    _pie_json_s = pie_df.to_json()
            else:
                _pie_json_s = st.session_state.get("pie_base_soriana")
            if not _pie_json_s:
                _fb = df_s_cat.dropna(subset=["Category"]).groupby("Category")["SO_$"].sum().reset_index()
                _fb = _fb[_fb["SO_$"]>0]
                _pie_json_s = _fb.to_json() if not _fb.empty else None
            if _pie_json_s:
                fig = build_pie_cached(_pie_json_s, "SORIANA")
                _ann = _filter_badge({"No tienda": fil_nda, "Nombre": fil_nom, "Ciudad": fil_cd, "Estado": fil_edo}, RETAILER_COLORS["SORIANA"])
                if _ann: fig.add_annotation(**_ann)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Sin datos para gráfica.")

        # --- FUNCION CRITICA: CALCULO DE DIAS INV SORIANA ---
        _SOR_COORDS_NORM = [c.replace(" ", "") for c in [
            "EDGAR IVAN MORENO", "JORGE MENDOZA", "JOSE LUIS ONTIVEROS CASTELLANOS", 
            "OLIVER GOMEZ RODRIGUEZ", "BRYAN ALEXIS GALLEGOS PEREZ", "SIN ASIGNAR", 
            "MARTHA MENESES ABUNDEZ"
        ]]
        
        def calc_sor_dias_inv(df_in):
            """
            Calcula: (SUM(INV_CAJAS) / SUM(PROM_SEM_CAJAS)) * 7 
            Filtrando estrictamente por Resurtible=1 y la lista de Coordinadores activa.
            """
            m_res = df_in["RESURTIMIENTO"].astype(str).str.strip().str.startswith("1")
            if "COORDINADOR" in df_in.columns:
                m_coord = df_in["COORDINADOR"].fillna("").astype(str).str.upper().str.replace(" ", "", regex=False).isin(_SOR_COORDS_NORM)
                df_f = df_in[m_res & m_coord]
            else:
                df_f = df_in[m_res]
                
            sum_inv = df_f["INV_CAJAS"].sum()
            
            if "PROM_SEM_CAJAS" in df_f.columns:
                sum_prom = df_f["PROM_SEM_CAJAS"].sum()
            else:
                sum_prom = df_f["SO_4SEM"].sum() / 4.0 if df_f["SO_4SEM"].sum() > 0 else 0
                
            dias = (sum_inv / sum_prom) * 7.0 if sum_prom > 0 else 0
            so = df_f["SO_$"].sum()
            return dias, so


        if st.session_state.s_transito:
            st.subheader("🚚 Pedidos en Tránsito")
            dff_transito = dff[dff["PEDIDOS"] > 0].copy()
            disp_transito = dff_transito[["FORMATO", "TIENDA", "CODIGO", "DESCRIPCION", "PEDIDOS", "FECHA_ENTREGA", "CANTIDAD_PZS"]].copy()
            disp_transito.columns = ['FORMATO', 'NOMBRE DE TIENDA', 'CODIGO', 'ARTICULO', 'PEDIDOS', 'FECHA DE ENTREGA', 'CANTIDAD EN PZS']
            st.dataframe(disp_transito.style.format({'PEDIDOS': "{:,.0f}", 'CANTIDAD EN PZS': "{:,.0f}"}), use_container_width=True, hide_index=True, height=auto_height(disp_transito))
            st.download_button("📥 DESCARGAR EXCEL", data=convert_df_to_excel(disp_transito), file_name="Soriana_Pedidos_Transito.xlsx", use_container_width=True)

        elif st.session_state.s_dias_prod:
            st.subheader("📋 Días Inventario x Producto")
            _base = dff.copy()
            _base["_DESC_CMP"] = _base["DESCRIPCION"].fillna("").str.upper().str.strip()
            res_rows = []
            for item in _SOR_DIAS_PROD:
                _item_cmp = item.upper().strip()
                mask = _base["_DESC_CMP"] == _item_cmp
                if not mask.any():
                    mask = _base["_DESC_CMP"].str.contains(_item_cmp, case=False, regex=False, na=False)
                if mask.any():
                    subset = _base[mask]
                    val_dias, so_val = calc_sor_dias_inv(subset)
                    res_rows.append({"CODIGO": subset["CODIGO"].iloc[0], "ARTICULO": item, "DIAS INV TENDENCIA": val_dias, "SELL OUT": so_val})
                else:
                    res_rows.append({"CODIGO": "-", "ARTICULO": item, "DIAS INV TENDENCIA": 0, "SELL OUT": 0})
            df_prod_summary = pd.DataFrame(res_rows)
            st.dataframe(df_prod_summary.style.format({'DIAS INV TENDENCIA':"{:,.0f}", 'SELL OUT':"${:,.2f}"}), use_container_width=True, hide_index=True, height=auto_height(df_prod_summary))
            st.download_button("📥 DESCARGAR EXCEL", data=convert_df_to_excel(df_prod_summary), file_name="Soriana_Dias_Producto.xlsx", use_container_width=True)

        elif st.session_state.s_dias_inv:
            st.subheader("📅 Reporte Días Inventario")
            
            def get_sor_kpi(pattern):
                _mask = dff["DESC_NORM"].str.contains(pattern.replace(" ", ""), case=False, na=False)
                return calc_sor_dias_inv(dff[_mask])

            val_nut, _so_nut = get_sor_kpi("ACEITEDESOYANUTRIOLIBOT850ML")
            val_sab, _so_sab = get_sor_kpi("ACEITECOMESTIBLESABROSANO850ML")
            val_gt, _so_gt   = get_sor_kpi("ACEITECOMESTIBLEGRANTRADICION800ML")

            # Mismo filtro exacto para las pastas que la gráfica general
            _mask_all_pastas = dff["DESC_NORM"].str.contains("NUTRIOLI",na=False) & dff["DESC_NORM"].str.contains("PASTA|FUSILLI|SPAGUETTI|FIDEO|CODO",na=False)
            m_res2 = dff["RESURTIMIENTO"].astype(str).str.strip().str.startswith("1")
            if "COORDINADOR" in dff.columns:
                m_coord2 = dff["COORDINADOR"].fillna("").astype(str).str.upper().str.replace(" ", "", regex=False).isin(_SOR_COORDS_NORM)
                _mask_dias_pastas = m_res2 & m_coord2
            else:
                _mask_dias_pastas = m_res2
            
            _so_pastas_total = dff.loc[_mask_all_pastas & _mask_dias_pastas, "SO_$"].sum()

            _pastas_map = [
                ("PASTAFIDEONUTRIOLI200GR",            "Fideo 200 Gr"),
                ("PASTASPAGHETTINUTRIOLIINTEGRAL200GR","Spaguetti Integra"),
                ("PASTAFUSILLIINTEGRALNUTRIOLI200GR",  "Fusilli Integral"),
                ("PASTACODONUTRIOLIVERDURAS200GR",     "Codo Verduras 200"),
                ("PASTAFUSILLIVERDURASNUTRIOLI450GR",  "Fusilli 450"),
                ("PASTASPAGHETTINUTRIOLI200GR",        "Spaguetti 200"),
                ("PASTACODONUTRIOLI200GR",             "Codo 200 Gr"),
            ]
            
            _pasta_rows = ""
            for desc_norm, abrev in _pastas_map:
                _v, _so_p = get_sor_kpi(desc_norm)
                _pasta_rows += (
                    f"<div style='display:flex;justify-content:space-between;align-items:center;"
                    f"border-bottom:1px solid #f0f0f0;padding:2px 0;gap:4px;'>"
                    f"<span style='font-size:0.6rem;color:#666;flex:1;'>{abrev}</span>"
                    f"<span style='font-size:0.7rem;font-weight:700;color:#64DD17;white-space:nowrap;'>{_v:,.0f}</span>"
                    f"<span style='font-size:0.6rem;color:#888;white-space:nowrap;margin-left:4px;'>${_so_p:,.2f}</span>"
                    f"</div>"
                )

            k1, k2, k3, k4 = st.columns(4)
            k1.markdown(
                f"<div class='kpi-card' style='height:100%;min-height:240px;justify-content:center;'>"
                f"<div class='kpi-title'>NUTRIOLI 850ML</div>"
                f"<div class='kpi-value' style='color:#28a745;'>{val_nut:,.0f}</div>"
                f"<div style='font-size:0.75rem;color:#555;margin-top:6px;font-weight:600;'>${_so_nut:,.2f}</div>"
                f"</div>", unsafe_allow_html=True)
            k2.markdown(
                f"<div class='kpi-card' style='height:100%;min-height:240px;justify-content:center;'>"
                f"<div class='kpi-title'>SABROSANO 850ML</div>"
                f"<div class='kpi-value' style='color:#E4007C;'>{val_sab:,.0f}</div>"
                f"<div style='font-size:0.75rem;color:#555;margin-top:6px;font-weight:600;'>${_so_sab:,.2f}</div>"
                f"</div>", unsafe_allow_html=True)
            k3.markdown(
                f"<div class='kpi-card' style='height:100%;min-height:240px;justify-content:center;'>"
                f"<div class='kpi-title'>GT 800ML</div>"
                f"<div class='kpi-value' style='color:#8B4513;'>{val_gt:,.0f}</div>"
                f"<div style='font-size:0.75rem;color:#555;margin-top:6px;font-weight:600;'>${_so_gt:,.2f}</div>"
                f"</div>", unsafe_allow_html=True)
            k4.markdown(
                f"<div class='kpi-card' style='height:100%;min-height:240px;padding:10px 12px;justify-content:flex-start;'>"
                f"<div class='kpi-title' style='margin-bottom:5px;'>PASTAS &nbsp;"
                f"<span style='color:#999;font-weight:400;font-size:0.65rem;'>${_so_pastas_total:,.2f}</span></div>"
                f"{_pasta_rows}"
                f"</div>",
                unsafe_allow_html=True
            )
            disp = dff[["NO_TIENDA","TIENDA","CODIGO","DESCRIPCION","INV_CAJAS","SO_$","SO_4SEM","DIAS_INV"]].copy()
            disp.columns = ['No.','TIENDA','CODIGO','ARTICULO','INV CAJAS','SELL OUT SEM','SELL OUT ULT 4 SEM','DIAS INV']
            st.dataframe(disp.style.format({'INV CAJAS':"{:,.0f}",'SELL OUT SEM':'${:,.2f}','SELL OUT ULT 4 SEM':'${:,.2f}','DIAS INV':"{:,.1f}"}), use_container_width=True, hide_index=True, height=auto_height(disp))
            st.download_button("📥 DESCARGAR EXCEL", data=convert_df_to_excel(disp), file_name="Soriana_Reporte_Dias.xlsx", use_container_width=True)

        else:
            dff_vista = dff[dff['SIN_VTA']].copy() if st.session_state.s_rojo else dff.copy()
            if st.session_state.s_rojo:
                st.caption("📋 Vista: Sin Venta")
            disp = dff_vista[["NO_TIENDA","TIENDA","CODIGO","DESCRIPCION","INV_CAJAS","SO_$","SO_4SEM","DIAS_INV"]].copy()
            disp.columns=['No.','TIENDA','CODIGO','ARTICULO','INV CAJAS','SELL OUT SEM','SELL OUT ULT 4 SEM','DIAS INV']
            disp = disp.sort_values(by='SELL OUT ULT 4 SEM',ascending=False)
            st.dataframe(disp.style.format({'INV CAJAS':"{:,.0f}",'SELL OUT SEM':'${:,.2f}','SELL OUT ULT 4 SEM':'${:,.2f}','DIAS INV':"{:,.1f}"}), use_container_width=True, hide_index=True, height=auto_height(disp))
            st.download_button("📥 DESCARGAR EXCEL", data=convert_df_to_excel(disp), file_name="Soriana_General.xlsx", use_container_width=True)

        st.divider()
        st.markdown("<h3 style='text-align:center;color:#444;'>🏆 RANKING DE VENTAS</h3>", unsafe_allow_html=True)
        sm1,sm2 = st.columns(2)
        with sm1: sel_s_rank_st  = st.multiselect("Estado (Ranking)",  _us(df_s["ESTADO"]),  key="s_rnk_st", placeholder="Seleccionar...")
        with sm2: sel_s_rank_fmt = st.multiselect("Formato (Ranking)", _us(df_s["FORMATO"]), key="s_rnk_fmt", placeholder="Seleccionar...")
        sr1,sr2,sr3,sr4 = st.columns(4,gap="small")
        with sr1: st.button("📊 GENERAL",  on_click=set_s_rank, args=('GEN',), use_container_width=True, type="primary" if s_rank_gen else "secondary")
        with sr2: st.button("🍝 PASTAS",   on_click=set_s_rank, args=('PAS',), use_container_width=True, type="primary" if s_rank_pas else "secondary")
        with sr3: st.button("🫒 OLIVAS",   on_click=set_s_rank, args=('OLI',), use_container_width=True, type="primary" if s_rank_oli else "secondary")
        with sr4: st.button("🍃 NUTRIOLI", on_click=set_s_rank, args=('NUT',), use_container_width=True, type="primary" if s_rank_nut else "secondary")

        dff_s_rank = apply_filters(df_s,["ESTADO","FORMATO"],[sel_s_rank_st,sel_s_rank_fmt])
        target_list_s=[]; rank_title_s=""
        if   s_rank_gen: target_list_s=_SOR_RANK_GEN; rank_title_s="VENTA GENERAL ($)"
        elif s_rank_pas: target_list_s=_SOR_RANK_PAS; rank_title_s="VENTA PASTAS ($)"
        elif s_rank_oli: target_list_s=_SOR_RANK_OLI; rank_title_s="VENTA OLIVAS ($)"
        elif s_rank_nut: target_list_s=_SOR_RANK_NUT; rank_title_s="VENTA NUTRIOLI ($)"
        if target_list_s:
            dff_sub = dff_s_rank[dff_s_rank["DESCRIPCION"].str.strip().isin(set(t.strip() for t in target_list_s))]
            if not dff_sub.empty:
                final_s_rank = dff_sub.groupby(["NO_TIENDA","TIENDA"])['SO_$'].sum().reset_index()
                final_s_rank.columns=['No Tienda','TIENDA',rank_title_s]
                final_s_rank = final_s_rank.sort_values(by=rank_title_s,ascending=False)
                st.dataframe(final_s_rank.style.format({rank_title_s:"${:,.2f}"}), use_container_width=True, hide_index=True, height=auto_height(final_s_rank))
                st.download_button("📥 DESCARGAR EXCEL", data=convert_df_to_excel(final_s_rank), file_name="Soriana_Ranking.xlsx", use_container_width=True)
            else: st.warning("⚠️ No se encontraron ventas para los productos seleccionados.")

def view_walmart(df_w):
    df_w_cat = pd.read_json(StringIO(categorize_full_df(df_w.to_json(), "WALMART")))  # @cache_data TTL 4h
    st.markdown(f"<div class='retailer-header' style='background-color:{RETAILER_COLORS['WALMART']}'>WALMART</div>", unsafe_allow_html=True)
    _upd_w = _get_last_update("WALMART")
    st.markdown(f"<p style='text-align:right;color:#888;font-size:0.75rem;margin:-8px 0 4px 0;'>🕐 Última actualización: <b>{_upd_w}</b></p>", unsafe_allow_html=True)

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
        # EXCLUSIÓN IMPORTANTE DE BAE y MB que aplica para todo en esta vista
        df_w = df_w[~df_w["FORMATO"].isin(['BAE','MB'])]

        for _k in ["w_fil_store","w_fil_state","w_fil_fmt"]:
            if _k not in st.session_state:
                st.session_state[_k] = []

        def _on_store_change():
            store = st.session_state.get("w_fil_store", [])
            if store:
                _t = df_w[df_w["TIENDA"].isin(store)]
                st.session_state["w_fil_state"] = sorted(_t["ESTADO"].dropna().unique())
                st.session_state["w_fil_fmt"]   = sorted(_t["FORMATO"].dropna().unique())
            else:
                st.session_state["w_fil_state"] = []
                st.session_state["w_fil_fmt"]   = []

        def _on_state_change():
            if st.session_state.get("w_fil_store"):
                return  
            st.session_state["w_fil_fmt"]   = []
            st.session_state["w_fil_store"] = []

        def _on_fmt_change():
            if st.session_state.get("w_fil_store"):
                return  
            st.session_state["w_fil_store"] = []

        def _reset_wal_filters():
            for _k in ["w_fil_store","w_fil_state","w_fil_fmt"]:
                st.session_state[_k] = []

        _wc1, _wc2 = st.columns([8, 2])
        with _wc1: st.markdown("#### 🔍 Filtros Avanzados")
        with _wc2: st.button("🗑️ Limpiar filtros", key="btn_reset_wal", on_click=_reset_wal_filters, use_container_width=True, type="secondary")

        with st.container():
            c1,c2,c3 = st.columns(3)

            _store_sel = st.session_state.get("w_fil_store", [])
            _state_sel = st.session_state.get("w_fil_state", [])
            _fmt_sel   = st.session_state.get("w_fil_fmt",   [])

            if _store_sel:
                _df_w_scope = df_w[df_w["TIENDA"].isin(_store_sel)]
            elif _state_sel:
                _df_w_scope = df_w[df_w["ESTADO"].isin(_state_sel)]
            else:
                _df_w_scope = df_w
            _fmt_opts_w    = sorted(_df_w_scope["FORMATO"].dropna().unique())
            _df_w_fmt_scope = _df_w_scope[_df_w_scope["FORMATO"].isin(_fmt_sel)] if _fmt_sel else _df_w_scope
            _tienda_opts_w  = sorted(_df_w_fmt_scope["TIENDA"].dropna().unique())

            with c1:
                marca_opts = sorted([m for m in df_w["MARCA"].dropna().unique() if m.strip().upper() not in ["NUTRIOLI + PASTA","NUTRIOLI  PASTA","NUTRIOLI PASTA"]])
                sel_marca = st.multiselect("Marca", marca_opts, placeholder="Seleccionar...")
                sel_state = st.multiselect("Estado", _us(df_w["ESTADO"]), placeholder="Seleccionar...",
                                           key="w_fil_state", on_change=_on_state_change)
            with c2:
                sel_fmt   = st.multiselect("Formato", _fmt_opts_w, placeholder="Seleccionar...",
                                           key="w_fil_fmt", on_change=_on_fmt_change)
                sel_store = st.multiselect("Tienda",  _tienda_opts_w, placeholder="Buscar tienda...",
                                           key="w_fil_store", on_change=_on_store_change)
            with c3:
                excluidas_clean = {"ACEITE VEGETAL SABROSANO RINDE MAS 850ML","OLI SPRAY ACEITE DE OLIVA 145ML","ACEITE MIXTO GRAN TRADICION 1L","ACEITE GRAN TRADICION 900ML","NUTRIOLI 946 ML +PASTA CODO 200G","NUTRIOLI 946 ML +FUSILLI VERDURAS 200G","NUTRIOLI SPAGUETTI ESENCIAL 200G","NUTRIOLI FIDEO ESENCIAL 200G","NUTRIOLI CODO ESENCIAL 200G","NUTRIOLI FUSILLI VERDURAS 200G","NUTRIOLI CODO VERDURAS 200G"}
                sel_prod = st.multiselect("Artículo", sorted([p for p in df_w["DESCRIPCION"].dropna().unique() if p.strip().upper() not in excluidas_clean]), placeholder="Seleccionar...")

        dff_kpi = apply_filters(df_w,["MARCA","ESTADO","TIENDA","FORMATO"],[sel_marca,sel_state,sel_store,sel_fmt])
        dff     = apply_filters(dff_kpi,["DESCRIPCION"],[sel_prod])

        dff_graph = apply_filters(df_w,["ESTADO","TIENDA","FORMATO"],[sel_state,sel_store,sel_fmt])
        if dff_graph.empty and sel_store:
            dff_graph = apply_filters(df_w,["TIENDA"],[sel_store])
        if dff_graph.empty and sel_state:
            dff_graph = apply_filters(df_w,["ESTADO"],[sel_state])
        if dff_graph.empty:
            dff_graph = df_w

        b1,b2,b3,b4 = st.columns(4,gap="small")
        with b1: st.button("📉 NEGATIVOS",    on_click=tog_w, args=('w_neg',),       use_container_width=True, type="primary" if w_neg      else "secondary")
        with b2: st.button("🔴 SIN VTA 4SEM", on_click=tog_w, args=('w_4w',),        use_container_width=True, type="primary" if w_4w       else "secondary")
        with b3: st.button("📅 DIAS INV",     on_click=tog_w, args=('w_dias_inv',),  use_container_width=True, type="primary" if w_dias_inv  else "secondary")
        with b4: st.button("📋 DIAS X PROD",  on_click=tog_w, args=('w_dias_prod',), use_container_width=True, type="primary" if w_dias_prod else "secondary")

        if st.session_state.w_neg: dff=dff[dff["EXISTENCIA"]<0]; st.warning("VISTA: NEGATIVOS")
        if st.session_state.w_4w:  dff=dff[(dff["VTA_S1"]==0)&(dff["VTA_S2"]==0)&(dff["VTA_S3"]==0)&(dff["VTA_S4"]==0)]; st.warning("VISTA: SIN VENTA 4 SEMANAS")

        dff_cat = dff_graph.merge(df_w_cat[["Category"]], left_index=True, right_index=True, how="left")
        c_kpi,c_chart = st.columns([1,2])
        total_so = dff_cat['SO_$'].sum()
        with c_kpi:
            st.markdown(f"<div class='kpi-card' style='height:450px;'><div class='kpi-title'>Total Sell Out</div><div class='kpi-value' style='color:#28a745;'>${total_so:,.2f}</div></div>", unsafe_allow_html=True)
        with c_chart:
            _hay_filtros_w = any([sel_store, sel_state, sel_fmt])
            if _hay_filtros_w:
                pie_df = dff_cat.dropna(subset=['Category']).groupby('Category')['SO_$'].sum().reset_index()
                pie_df = pie_df[pie_df['SO_$']>0]
                if pie_df.empty:
                    _pie_json_w = st.session_state.get("pie_base_walmart")
                else:
                    _pie_json_w = pie_df.to_json()
            else:
                _fb = df_w_cat.dropna(subset=["Category"]).copy()
                _fb = _fb.loc[_fb.index.isin(df_w.index)]
                _fb = _fb.groupby("Category")["SO_$"].sum().reset_index()
                _fb = _fb[_fb["SO_$"]>0]
                _pie_json_w = _fb.to_json() if not _fb.empty else None

            if _pie_json_w:
                fig = build_pie_cached(_pie_json_w, "WALMART")
                _ann = _filter_badge({"Tienda": sel_store, "Estado": sel_state, "Formato": sel_fmt}, RETAILER_COLORS["WALMART"])
                if _ann: fig.add_annotation(**_ann)
                st.plotly_chart(fig, use_container_width=True)
            else: st.info("Sin datos para gráfica.")

        if st.session_state.w_dias_prod:
            st.subheader("📋 Días Inventario x Producto")
            desc_nospace = dff_kpi["DESCRIPCION"].str.upper().str.replace(r'&NBSP;','',regex=True).str.replace(" ","",regex=False)
            res_rows = []
            for item in _WAL_DIAS_PROD:
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
            
            # 1. Días de Inventario Promedio (Cálculo exacto para no mezclar)
            val_nutri = get_kpi_mean_by_upc(dff_kpi, "750103912014", "DIAS_INV")
            val_sabro = get_kpi_mean_by_upc(dff_kpi, "750103912209", "DIAS_INV")
            val_ave   = get_kpi_mean_exact_desc(dff_kpi, "ACEITE AVE 850ML", "DIAS_INV")
            val_gran  = get_kpi_mean_exact_desc(dff_kpi, "ACEITE COMESTIBLE GRAN TRADICION 850ML", "DIAS_INV")

            # 2. Sell Out (Suma exacta por UPC/Desc en columna SO_$)
            so_nutri = get_kpi_sum_by_upc(dff_kpi, "750103912014", "SO_$")
            so_sabro = get_kpi_sum_by_upc(dff_kpi, "750103912209", "SO_$")
            so_ave   = get_kpi_sum_exact_desc(dff_kpi, "ACEITE AVE 850ML", "SO_$")
            so_gran  = get_kpi_sum_exact_desc(dff_kpi, "ACEITE COMESTIBLE GRAN TRADICION 850ML", "SO_$")
            
            m1,m2,m3,m4 = st.columns(4)
            m1.markdown(
                f"<div class='kpi-card' style='height:100%;min-height:240px;justify-content:center;'>"
                f"<div class='kpi-title'>NUTRIOLI 946ML</div>"
                f"<div class='kpi-value' style='color:#28a745;'>{val_nutri:,.1f}</div>"
                f"<div style='font-size:0.75rem;color:#555;margin-top:6px;font-weight:600;'>${so_nutri:,.0f}</div>"
                f"</div>", unsafe_allow_html=True)
            m2.markdown(
                f"<div class='kpi-card' style='height:100%;min-height:240px;justify-content:center;'>"
                f"<div class='kpi-title'>SABROSANO 850ML</div>"
                f"<div class='kpi-value' style='color:#E4007C;'>{val_sabro:,.1f}</div>"
                f"<div style='font-size:0.75rem;color:#555;margin-top:6px;font-weight:600;'>${so_sabro:,.0f}</div>"
                f"</div>", unsafe_allow_html=True)
            m3.markdown(
                f"<div class='kpi-card' style='height:100%;min-height:240px;justify-content:center;'>"
                f"<div class='kpi-title'>AVE 850ML</div>"
                f"<div class='kpi-value' style='color:#D32F2F;'>{val_ave:,.1f}</div>"
                f"<div style='font-size:0.75rem;color:#555;margin-top:6px;font-weight:600;'>${so_ave:,.0f}</div>"
                f"</div>", unsafe_allow_html=True)
            m4.markdown(
                f"<div class='kpi-card' style='height:100%;min-height:240px;justify-content:center;'>"
                f"<div class='kpi-title'>GRAN TRADICION</div>"
                f"<div class='kpi-value' style='color:#8B4513;'>{val_gran:,.1f}</div>"
                f"<div style='font-size:0.75rem;color:#555;margin-top:6px;font-weight:600;'>${so_gran:,.0f}</div>"
                f"</div>", unsafe_allow_html=True)
            
            disp_w_dias = dff[["TIENDA","CODIGO","DESCRIPCION","DIAS_INV"]].copy()
            disp_w_dias.columns = ["TIENDA","CODIGO","DESCRIPCION","DIAS INVENTARIO"]
            st.dataframe(disp_w_dias.style.format({'DIAS INVENTARIO':"{:,.1f}"}), use_container_width=True, hide_index=True, height=auto_height(disp_w_dias))
            st.download_button("📥 DESCARGAR EXCEL", data=convert_df_to_excel(disp_w_dias), file_name="Walmart_Reporte_Dias.xlsx", use_container_width=True)

        elif st.session_state.w_neg:
            st.subheader("📉 Vista: Inventarios Negativos")
            disp_neg = dff[["CODIGO", "DESCRIPCION", "TIENDA", "EXISTENCIA", "SO_$"]].copy()
            disp_neg.columns = ["CODIGO", "DESCRIPCION", "TIENDA", "INVENTARIO", "SELL OUT"]
            disp_neg = disp_neg.sort_values(by="INVENTARIO", ascending=True)
            st.dataframe(disp_neg.style.format({'INVENTARIO':"{:,.0f}", 'SELL OUT':'${:,.2f}'}), use_container_width=True, hide_index=True, height=auto_height(disp_neg))
            
            c_btn1, c_btn2 = st.columns(2)
            with c_btn1:
                st.download_button("📥 DESCARGAR EXCEL", data=convert_df_to_excel(disp_neg), file_name="Walmart_Negativos.xlsx", use_container_width=True)
            with c_btn2:
                msg_lines = ["*🚨 INVENTARIOS NEGATIVOS WALMART*"]
                max_items = 50
                for idx, row in enumerate(disp_neg.itertuples()):
                    if idx >= max_items:
                        msg_lines.append("\n_... (Mostrando los primeros 50 registros)_")
                        break
                    msg_lines.append(f"🔢 *CÓDIGO:* {row.CODIGO}\n📦 *DESCRIPCIÓN:* {row.DESCRIPCION}\n🏪 *TIENDA:* {row.TIENDA}\n📉 *INVENTARIO:* {row.INVENTARIO}\n")
                
                wa_text = "\n".join(msg_lines)
                wa_url = f"https://wa.me/?text={urllib.parse.quote(wa_text)}"
                st.markdown(f'<a href="{wa_url}" target="_blank" style="display: flex; align-items: center; justify-content: center; background-color: #25D366; color: white; padding: 8px 12px; border-radius: 6px; text-decoration: none; font-weight: 800; font-family: sans-serif; height: 42px; margin-top: 0px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">📲 ENVIAR POR WHATSAPP</a>', unsafe_allow_html=True)

        else:
            disp=dff[["CODIGO","DESCRIPCION","TIENDA","EXISTENCIA","SO_$","PROM_PZS_MENSUAL"]].copy()
            disp.columns=['CODIGO','DESCRIPCION','TIENDA','EXISTENCIA','SELL OUT','PROM PZS MENSUAL']
            st.dataframe(disp.style.format({'SELL OUT':'${:,.2f}','PROM PZS MENSUAL':'{:,.2f}'}), use_container_width=True, hide_index=True, height=auto_height(disp))
            st.download_button("📥 DESCARGAR EXCEL", data=convert_df_to_excel(disp), file_name="Walmart_General.xlsx", use_container_width=True)

        st.divider()
        st.markdown("<h3 style='text-align:center;color:#444;'>🏆 RANKING DE VENTAS</h3>", unsafe_allow_html=True)
        cm1,cm2 = st.columns(2)
        with cm1: sel_st_rank  = st.multiselect("Estado (Ranking)",  _us(df_w["ESTADO"]),  key="rnk_st", placeholder="Seleccionar...")
        with cm2: sel_fmt_rank = st.multiselect("Formato (Ranking)", _us(df_w["FORMATO"]), key="rnk_fmt", placeholder="Seleccionar...")
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
            mask_946 = (
                (dff_rank["CODIGO"].astype(str).str.strip() == "750103912014") |
                (dff_rank["DESC_NORM"].str.contains("NUTRIOLI", na=False) &
                 dff_rank["DESC_NORM"].str.contains("946", na=False))
            )
            df_sub = dff_rank[mask_946]
            # Excluir tiendas sin ninguna actividad (todo en cero)
            if not df_sub.empty:
                _vta_col = "VTA_S4" if "VTA_S4" in df_sub.columns else None
                _mask_activo = df_sub["SO_$"] > 0
                if _vta_col:
                    _mask_activo = _mask_activo | (df_sub[_vta_col] > 0)
                _mask_activo = _mask_activo | (df_sub["EXISTENCIA"] > 0)
                df_sub = df_sub[_mask_activo]
            if not df_sub.empty:
                cols_disponibles = ["EXISTENCIA", "VTA_S4", "SO_$"]
                cols_sum = [c for c in cols_disponibles if c in df_sub.columns]
                final_rank = df_sub.groupby(["FORMATO","TIENDA","DESCRIPCION"])[cols_sum].sum().reset_index()
                nombres = ["FORMATO", "TIENDA", "PRODUCTO"]
                if "EXISTENCIA" in cols_sum: nombres.append("INVENTARIO (PZS)")
                if "VTA_S4"     in cols_sum: nombres.append("VTA SEM ANT (PZS)")
                if "SO_$"       in cols_sum: nombres.append("SELL OUT ($)")
                final_rank.columns = nombres
                # Excluir filas donde todo sea 0 post-groupby
                _num_cols = [c for c in final_rank.columns if c not in ["FORMATO","TIENDA","PRODUCTO"]]
                final_rank = final_rank[final_rank[_num_cols].sum(axis=1) > 0]
        if final_rank is not None:
            sort_col = final_rank.columns[-1]
            final_rank = final_rank.sort_values(by=sort_col,ascending=False)
            fmt_dict = {c:"${:,.2f}" for c in final_rank.columns if "($)" in c or "$" in c}
            if "INVENTARIO (PZS)" in final_rank.columns: fmt_dict["INVENTARIO (PZS)"]="{:,.0f}"
            if "VTA SEM ANT (PZS)" in final_rank.columns: fmt_dict["VTA SEM ANT (PZS)"]="{:,.0f}"
            st.dataframe(final_rank.style.format(fmt_dict), use_container_width=True, hide_index=True, height=auto_height(final_rank))
            st.download_button("📥 DESCARGAR EXCEL", data=convert_df_to_excel(final_rank), file_name="Walmart_Ranking.xlsx", use_container_width=True)

def view_chedraui(df_c):
    df_c_cat = pd.read_json(StringIO(categorize_full_df(df_c.to_json(), "CHEDRAUI")))  # @cache_data TTL 4h
    st.markdown(f"<div class='retailer-header' style='background-color:{RETAILER_COLORS['CHEDRAUI']}'>CHEDRAUI</div>", unsafe_allow_html=True)
    _upd_c = _get_last_update("CHEDRAUI")
    st.markdown(f"<p style='text-align:right;color:#888;font-size:0.75rem;margin:-8px 0 4px 0;'>🕐 Última actualización: <b>{_upd_c}</b></p>", unsafe_allow_html=True)

    def tog_c(target):
        for v in ['c_neg_zero','c_dias_inv','c_transito']:
            st.session_state[v] = True if v==target and not st.session_state[v] else False
    def set_c_rank(mode):
        for v in ['c_rank_gen','c_rank_pas','c_rank_oli','c_rank_nut']: st.session_state[v]=False
        st.session_state[f'c_rank_{mode.lower()}']=True

    if df_c is not None:
        for _k in ["c_fil_no","c_fil_ti","c_fil_ed"]:
            if _k not in st.session_state:
                st.session_state[_k] = []

        def _on_ti_change():
            ti = st.session_state.get("c_fil_ti", [])
            if ti:
                _t = df_c[df_c["TIENDA"].isin(ti)]
                st.session_state["c_fil_no"] = sorted(_t["NO_TIENDA"].dropna().unique())
                st.session_state["c_fil_ed"] = sorted(_t["ESTADO"].dropna().unique())
            else:
                st.session_state["c_fil_no"] = []
                st.session_state["c_fil_ed"] = []

        def _on_no_change():
            no = st.session_state.get("c_fil_no", [])
            if no:
                _t = df_c[df_c["NO_TIENDA"].isin(no)]
                st.session_state["c_fil_ti"] = sorted(_t["TIENDA"].dropna().unique())
                st.session_state["c_fil_ed"] = sorted(_t["ESTADO"].dropna().unique())
            else:
                st.session_state["c_fil_ti"] = []
                st.session_state["c_fil_ed"] = []

        def _on_ed_change():
            if st.session_state.get("c_fil_ti") or st.session_state.get("c_fil_no"):
                return  
            st.session_state["c_fil_ti"] = []
            st.session_state["c_fil_no"] = []

        with st.container():
            st.markdown("#### 🔍 Filtros Avanzados")
            c1,c2 = st.columns(2)

            _ti_sel = st.session_state.get("c_fil_ti", [])
            _no_sel = st.session_state.get("c_fil_no", [])
            _ed_sel = st.session_state.get("c_fil_ed", [])

            if _ti_sel or _no_sel:
                _scope = df_c[df_c["TIENDA"].isin(_ti_sel)] if _ti_sel else df_c[df_c["NO_TIENDA"].isin(_no_sel)]
            elif _ed_sel:
                _scope = df_c[df_c["ESTADO"].isin(_ed_sel)]
            else:
                _scope = df_c
            _tienda_opts_c = sorted(_scope["TIENDA"].dropna().unique())
            _no_opts_c     = sorted(_scope["NO_TIENDA"].dropna().unique())

        def _reset_che_filters():
            for _k in ["c_fil_no","c_fil_ti","c_fil_ed"]:
                st.session_state[_k] = []

        _cc1, _cc2 = st.columns([8, 2])
        with _cc1: st.markdown("#### 🔍 Filtros Avanzados")
        with _cc2: st.button("🗑️ Limpiar filtros", key="btn_reset_che", on_click=_reset_che_filters, use_container_width=True, type="secondary")

        with st.container():
            c1, c2 = st.columns(2)
            with c1:
                fil_no  = st.multiselect("No Tienda", _no_opts_c, placeholder="Buscar no. tienda...",
                                         key="c_fil_no", on_change=_on_no_change)
                fil_cat = st.multiselect("Categoría", _us(df_c["CATEGORIA"]), placeholder="Seleccionar...")
                fil_ti  = st.multiselect("Tienda", _tienda_opts_c, placeholder="Buscar tienda...",
                                         key="c_fil_ti", on_change=_on_ti_change)
            with c2:
                fil_ed  = st.multiselect("Estado", _us(df_c["ESTADO"]), placeholder="Seleccionar...",
                                         key="c_fil_ed", on_change=_on_ed_change)
                fil_art = st.multiselect("Artículo", _us(df_c["ARTICULO"]), placeholder="Seleccionar...")

        dff_base = apply_filters(df_c,["NO_TIENDA","TIENDA","ESTADO","CATEGORIA"],[fil_no,fil_ti,fil_ed,fil_cat])
        dff      = apply_filters(dff_base,["ARTICULO"],[fil_art])

        dff_graph = apply_filters(df_c,["NO_TIENDA","TIENDA","ESTADO"],[fil_no,fil_ti,fil_ed])
        if dff_graph.empty and (fil_no or fil_ti):
            dff_graph = apply_filters(df_c,["NO_TIENDA","TIENDA"],[fil_no,fil_ti])
        if dff_graph.empty and fil_ed:
            dff_graph = apply_filters(df_c,["ESTADO"],[fil_ed])
        if dff_graph.empty:
            dff_graph = df_c

        b1,b2,b3 = st.columns(3,gap="small")
        with b1: st.button("📉 NEGATIVOS",         on_click=tog_c, args=('c_neg_zero',), use_container_width=True, type="primary" if c_neg_zero   else "secondary")
        with b2: st.button("📅 DIAS INV",           on_click=tog_c, args=('c_dias_inv',), use_container_width=True, type="primary" if c_dias_inv   else "secondary")
        with b3: st.button("🚚 PEDIDOS EN TRANSITO",on_click=tog_c, args=('c_transito',), use_container_width=True, type="primary" if c_transito_c else "secondary")

        dff_cat = dff_graph.merge(df_c_cat[["Category"]], left_index=True, right_index=True, how="left")
        c_kpi,c_chart = st.columns([1,2])
        with c_kpi:
            total_so = dff_cat['SELL_OUT'].sum()
            st.markdown(f"<div class='kpi-card' style='height:450px;'><div class='kpi-title'>Total Sell Out</div><div class='kpi-value' style='color:#FF6600;'>${total_so:,.2f}</div></div>", unsafe_allow_html=True)
        with c_chart:
            _hay_filtros_c = any([fil_no, fil_ti, fil_ed])
            if _hay_filtros_c:
                pie_df = dff_cat.dropna(subset=['Category']).groupby('Category')['SELL_OUT'].sum().reset_index()
                pie_df = pie_df[pie_df['SELL_OUT']>0]
                if pie_df.empty:
                    _pie_json_c = st.session_state.get("pie_base_chedraui")
                else:
                    _pie_json_c = pie_df.to_json()
            else:
                _pie_json_c = st.session_state.get("pie_base_chedraui")
            if not _pie_json_c:
                _fb = df_c_cat.dropna(subset=["Category"]).groupby("Category")["SELL_OUT"].sum().reset_index()
                _fb = _fb[_fb["SELL_OUT"]>0]
                _pie_json_c = _fb.to_json() if not _fb.empty else None
            if _pie_json_c:
                fig = build_pie_cached(_pie_json_c, "CHEDRAUI")
                _ann = _filter_badge({"No tienda": fil_no, "Tienda": fil_ti, "Estado": fil_ed}, RETAILER_COLORS["CHEDRAUI"])
                if _ann: fig.add_annotation(**_ann)
                st.plotly_chart(fig, use_container_width=True)
            else: st.info("Sin datos para gráfica.")

        if st.session_state.get('c_transito'):
            st.subheader("🚚 Pedidos en Tránsito — Cédis a Tiendas")
            if "TRANSITO_CEDIS" in dff.columns:
                dff_transito_c = dff[dff["TRANSITO_CEDIS"] > 0].copy()
                if not dff_transito_c.empty:
                    disp_tc = dff_transito_c[["ESTADO","NO_TIENDA","TIENDA","ARTICULO","INV_ULT_SEM","TRANSITO_CEDIS"]].copy()
                    disp_tc.columns = ["ESTADO","NO TIENDA","TIENDA","ARTÍCULO","INVENTARIO","TRÁNSITO CEDIS"]
                    st.dataframe(disp_tc.style.format({"INVENTARIO":"{:,.0f}","TRÁNSITO CEDIS":"{:,.0f}"}),
                                 use_container_width=True, hide_index=True, height=auto_height(disp_tc))
                else:
                    st.info("✅ No hay pedidos en tránsito para los filtros seleccionados.")
            else:
                st.warning("⚠️ La columna 'Transitos de cedis a tiendas' no se encontró en la base de Chedraui.")

        elif st.session_state.c_dias_inv:
            st.subheader("📅 Reporte Días Inventario")
            
            val_nut = get_kpi_mean(dff_base,"ARTICULO","DIAS_INV","Nutrioli Bot 850")
            val_sab = get_kpi_mean(dff_base,"ARTICULO","DIAS_INV","Sabrosano Mixto 850")
            val_ave = get_kpi_mean(dff_base,"ARTICULO","DIAS_INV","Ave Soya-Canola 850")
            
            _mask_nut = dff_base["ARTICULO"].str.contains("Nutrioli Bot 850", case=False, na=False)
            _so_nut   = dff_base.loc[_mask_nut, "SELL_OUT"].sum()
            
            _mask_sab = dff_base["ARTICULO"].str.contains("Sabrosano Mixto 850", case=False, na=False)
            _so_sab   = dff_base.loc[_mask_sab, "SELL_OUT"].sum()
            
            _mask_ave = dff_base["ARTICULO"].str.contains("Ave Soya-Canola 850", case=False, na=False)
            _so_ave   = dff_base.loc[_mask_ave, "SELL_OUT"].sum()

            _pastas_che = [
                ("3878674", "Nutrioli Codo 200 Gr"),
                ("3878675", "Nutrioli Codo Verduras 200"),
                ("3878671", "Nutrioli Fideo 200 Gr"),
                ("3878672", "Nutrioli Fusilli 450"),
                ("3878678", "Nutrioli Fusilli Integral"),
                ("3878676", "Nutrioli Fusilli Verduras"),
                ("3878673", "Nutrioli Spaguetti 200"),
                ("3878677", "Nutrioli Spaguetti Integra"),
            ]
            
            _pasta_rows_c = ""
            _so_pastas_total_c = 0
            
            for sku, abrev in _pastas_che:
                abrev_clean = abrev.upper().replace(" ", "")
                _mask_p = dff_base["ARTICULO"].astype(str).str.contains(sku, na=False) | dff_base["DESC_NORM"].str.contains(abrev_clean, case=False, na=False)
                _v = safe_mean(dff_base.loc[_mask_p, "DIAS_INV"])
                _so_p   = dff_base.loc[_mask_p, "SELL_OUT"].sum()
                _so_pastas_total_c += _so_p
                
                _pasta_rows_c += (
                    f"<div style='display:flex;justify-content:space-between;align-items:center;"
                    f"border-bottom:1px solid #f0f0f0;padding:2px 0;gap:4px;'>"
                    f"<span style='font-size:0.6rem;color:#666;flex:1;'>{abrev}</span>"
                    f"<span style='font-size:0.7rem;font-weight:700;color:#64DD17;white-space:nowrap;'>{_v:,.0f}</span>"
                    f"<span style='font-size:0.6rem;color:#888;white-space:nowrap;margin-left:4px;'>${_so_p:,.2f}</span>"
                    f"</div>"
                )

            k1, k2, k3, k4 = st.columns(4)
            k1.markdown(
                f"<div class='kpi-card' style='height:100%;min-height:240px;justify-content:center;'>"
                f"<div class='kpi-title'>NUTRIOLI 850ML</div>"
                f"<div class='kpi-value' style='color:#28a745;'>{val_nut:,.1f}</div>"
                f"<div style='font-size:0.75rem;color:#555;margin-top:6px;font-weight:600;'>${_so_nut:,.2f}</div>"
                f"</div>", unsafe_allow_html=True)
            k2.markdown(
                f"<div class='kpi-card' style='height:100%;min-height:240px;justify-content:center;'>"
                f"<div class='kpi-title'>SABROSANO 850ML</div>"
                f"<div class='kpi-value' style='color:#E4007C;'>{val_sab:,.1f}</div>"
                f"<div style='font-size:0.75rem;color:#555;margin-top:6px;font-weight:600;'>${_so_sab:,.2f}</div>"
                f"</div>", unsafe_allow_html=True)
            k3.markdown(
                f"<div class='kpi-card' style='height:100%;min-height:240px;justify-content:center;'>"
                f"<div class='kpi-title'>AVE 850ML</div>"
                f"<div class='kpi-value' style='color:#D32F2F;'>{val_ave:,.1f}</div>"
                f"<div style='font-size:0.75rem;color:#555;margin-top:6px;font-weight:600;'>${_so_ave:,.2f}</div>"
                f"</div>", unsafe_allow_html=True)
            k4.markdown(
                f"<div class='kpi-card' style='height:100%;min-height:240px;padding:10px 12px;justify-content:flex-start;'>"
                f"<div class='kpi-title' style='margin-bottom:5px;'>PASTAS &nbsp;"
                f"<span style='color:#999;font-weight:400;font-size:0.65rem;'>${_so_pastas_total_c:,.2f}</span></div>"
                f"{_pasta_rows_c}"
                f"</div>",
                unsafe_allow_html=True
            )
            
            disp=dff[["NO_TIENDA","TIENDA","ARTICULO","INV_ULT_SEM","VTA_PROM_DIARIA","DIAS_INV","SELL_OUT"]].copy()
            disp.columns=['NO_TIENDA','TIENDA','ARTICULO','INV_ULT_SEM','VTA_PROM_DIARIA','DIAS_INV','SELL_OUT']
            st.dataframe(disp.style.format({'INV_ULT_SEM':"{:,.0f}",'VTA_PROM_DIARIA':"{:,.2f}",'DIAS_INV':"{:,.1f}",'SELL_OUT':"${:,.2f}"}), use_container_width=True, hide_index=True, height=auto_height(disp))
            st.download_button("📥 DESCARGAR EXCEL", data=convert_df_to_excel(disp), file_name="Chedraui_Dias_Inventario.xlsx", use_container_width=True)

        elif st.session_state.c_neg_zero:
            dff_neg = dff[dff["INV_ULT_SEM"]<0].copy()
            st.subheader("📉 Vista: Inventarios Negativos")
            disp_neg = dff_neg[["CODIGO", "ARTICULO", "TIENDA", "INV_ULT_SEM", "SELL_OUT"]].copy()
            disp_neg.columns = ["CODIGO", "DESCRIPCION", "TIENDA", "INVENTARIO", "SELL OUT"]
            disp_neg = disp_neg.sort_values(by="INVENTARIO", ascending=True)
            st.dataframe(disp_neg.style.format({'INVENTARIO':"{:,.0f}", 'SELL OUT':'${:,.2f}'}), use_container_width=True, hide_index=True, height=auto_height(disp_neg))
            
            c_btn1, c_btn2 = st.columns(2)
            with c_btn1:
                st.download_button("📥 DESCARGAR EXCEL", data=convert_df_to_excel(disp_neg), file_name="Chedraui_Negativos.xlsx", use_container_width=True)
            with c_btn2:
                msg_lines = ["*🚨 INVENTARIOS NEGATIVOS CHEDRAUI*"]
                max_items = 50
                for idx, row in enumerate(disp_neg.itertuples()):
                    if idx >= max_items:
                        msg_lines.append("\n_... (Mostrando los primeros 50 registros)_")
                        break
                    msg_lines.append(f"🏪 *Tienda:* {row.TIENDA}\n🔢 *CÓDIGO:* {row.CODIGO}\n📦 *DESCRIPCIÓN:* {row.DESCRIPCION}\n📉 *Inventario:* {row.INVENTARIO}\n")
                
                wa_text = "\n".join(msg_lines)
                wa_url = f"https://wa.me/?text={urllib.parse.quote(wa_text)}"
                st.markdown(f'<a href="{wa_url}" target="_blank" style="display: flex; align-items: center; justify-content: center; background-color: #25D366; color: white; padding: 8px 12px; border-radius: 6px; text-decoration: none; font-weight: 800; font-family: sans-serif; height: 42px; margin-top: 0px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">📲 ENVIAR POR WHATSAPP</a>', unsafe_allow_html=True)

        else:
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