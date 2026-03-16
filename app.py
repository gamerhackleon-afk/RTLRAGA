import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import numpy as np
import time
import requests
import plotly.express as px
from io import BytesIO
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
            mask &= df[col].isin(set(sel)).values  # set() O(1) + numpy array directo
    return df[mask]

def get_kpi_mean(df, desc_col, days_col, pattern):
    # Reutilizar DESC_NORM si existe — evita recalcular normalización en cada KPI
    if "DESC_NORM" in df.columns:
        clean_desc = df["DESC_NORM"]
    else:
        clean_desc = df[desc_col].fillna("").str.upper().str.replace("&NBSP;", "", regex=False).str.replace(" ", "", regex=False)
    clean_pattern = pattern.upper().replace("&NBSP;", "").replace(" ", "")
    mask = clean_desc.str.contains(clean_pattern, case=False, na=False)
    return safe_mean(df.loc[mask, days_col])

def auto_height(df):
    return min(max(len(df) * 35 + 45, 100), 600)

def _filter_badge(filtros: dict, color_acento: str = "#0071DC"):
    """Retorna un dict de anotación Plotly que flota arriba a la derecha
    del gráfico. Retorna None si no hay filtros activos."""
    lineas = []
    for etiqueta, valores in filtros.items():
        if valores:
            vals_str = ", ".join(str(v) for v in valores[:3])
            if len(valores) > 3:
                vals_str += f" +{len(valores)-3}"
            lineas.append(f"<b>{etiqueta}:</b> {vals_str}")
    if not lineas:
        return None  # Sin filtros activos
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

@st.cache_data(show_spinner=False, ttl=14400)
def _categorize_df(df_json: str, retailer: str) -> str:
    """Clasifica filas en categorías según retailer. Cacheado para no recalcular.
    Recibe y retorna JSON para compatibilidad con cache_data."""
    df = pd.read_json(df_json)

    def _safe_str(series):
        """Garantiza que la serie sea string antes de usar .str"""
        return series.fillna("").astype(str).str.upper().str.replace(" ", "", regex=False).str.replace("&NBSP;", "", regex=False)

    if retailer == "SORIANA":
        desc = df["DESC_NORM"].astype(str) if "DESC_NORM" in df.columns else _safe_str(df["DESCRIPCION"])
        conditions = [
            desc.str.contains("SABROSANO",na=False), desc.str.contains("GRANTRADICION",na=False),
            desc.str.contains("BALSAMICO",na=False), desc.str.contains("MISAZON|MISAZÓN",na=False),
            desc.str.contains("AVE",na=False) & ~desc.str.contains("NUTRIOLI",na=False),
            desc.str.contains("NUTRIOLI",na=False) & desc.str.contains("PASTA|FUSILLI|SPAGUETTI|FIDEO|CODO",na=False),
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
            desc.str.contains("NUTRIOLI",na=False)&desc.str.contains("SPAGUETTI|FIDEO|CODO|PASTA",na=False),
            desc.str.contains("NUTRIOLI",na=False),
        ]
        choices = ["BORGES","NUTRIOLI","SABROSANO","GT","BALSAMICO","OLIVAS","PASTAS","REST NUTRIOLI"]
    else:  # CHEDRAUI
        desc = df["DESC_NORM"].astype(str) if "DESC_NORM" in df.columns else _safe_str(df["ARTICULO"])
        conditions = [
            desc.str.contains("BALSAMICO",na=False),
            desc.str.contains("SABROSANO",na=False),
            desc.str.contains("GRANTRADICION",na=False),
            desc.str.contains("MISAZON|MISAZÓN",na=False),
            desc.str.contains("AVE",na=False)&desc.str.contains("SOYA-CANOLA|AEROSOL",na=False),
            desc.str.contains("NUTRIOLI",na=False)&desc.str.contains("FUSILLI|SPAGUETTI|FIDEO|CODO",na=False),
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
    """Categoriza el dataframe COMPLETO una sola vez al cargar la base.
    Los filtros luego operan sobre esta base ya categorizada — 3-5x más rápido."""
    return _categorize_df(df_json, retailer)

@st.cache_data(show_spinner=False, ttl=14400)
def build_pie_cached(pie_df_json: str, retailer: str):
    """Construye la figura Plotly cacheada a partir del groupby ya calculado.
    La clave de cache incluye el JSON del pie_df, por lo que se invalida solo
    cuando los datos agrupados cambian — no en cada rerun."""
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
    """Precalcula el groupby Category sobre la base completa ya categorizada.
    Retorna el pie_df como JSON listo para pasar a build_pie_cached.
    Se ejecuta una sola vez al cargar — los filtros reutilizan este JSON
    solo cuando no hay filtros activos (primer render instantáneo)."""
    df = pd.read_json(df_cat_json)
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
            "CIUDAD": ["Ciudad"],
            "ESTADO": ["Estado"],
            "FORMATO": ["Formato"],
            "PEDIDOS": ["# PEDIDOS", "PEDIDOS"],
            "FECHA_ENTREGA": ["PROXIMA ENTREGA", "FECHA ENTREGA"],
            "CANTIDAD_PZS": ["CANTIDAD PROX A LLEGAR", "CANTIDAD PZS"],
            "INV_CAJAS": ["INV CAJAS", "INVENTARIO CAJAS"],
            "DIAS_INV": ["DIAS INV TENDENCIA", "DIAS INV"]
        }
        
        # Búsqueda dinámica de las últimas 4 semanas sin depender del nombre "S10"
        pedidos_col = find_col(df, ["# PEDIDOS", "PEDIDOS"])
        if pedidos_col:
            pedidos_idx = list(df.columns).index(pedidos_col)
            last_4_cols = df.columns[pedidos_idx-4 : pedidos_idx]
            for c in last_4_cols:
                df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
            df["SO_4SEM"] = df[last_4_cols].sum(axis=1)
            df["SO_$"] = df[last_4_cols[-1]] # Tomamos la semana más reciente como principal
        else:
            df["SO_4SEM"] = 0
            df["SO_$"] = 0
            
        SORIANA_COLS["SO_$"] = ["SO_$"]
        SORIANA_COLS["SO_4SEM"] = ["SO_4SEM"]
        
        df = validate_columns(df, "SORIANA", SORIANA_COLS)
        if df is None: return None
        
        df["CODIGO"] = df["CODIGO"].fillna("").astype(str).str.replace(r'\.0*$', '', regex=True)
        for c in ["DIAS_INV", "INV_CAJAS", "SO_$", "SO_4SEM", "PEDIDOS", "CANTIDAD_PZS"]:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
            
        df["FECHA_ENTREGA"] = df["FECHA_ENTREGA"].fillna("").astype(str).replace("nan", "")
        df['SIN_VTA'] = (df['SO_4SEM'] == 0)
        df['VTA_PROM'] = df['SO_4SEM']
        
        df = _str_cols(df, ["RESURTIMIENTO", "NO_TIENDA", "TIENDA", "CIUDAD", "ESTADO", "FORMATO", "DESCRIPCION"])
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
            "SO_SEM_ANT": ["SO - 1 $"],
            "SO_$": ["Sell out Valor corriendo"]
        }
        
        df = validate_columns(df, "WALMART", WALMART_COLS)
        if df is None: return None 

        df["CODIGO"] = df["CODIGO"].fillna("").astype(str).str.replace(r'\.0*$', '', regex=True)
        for c in ["DIAS_INV", "EXISTENCIA", "VTA_S1", "VTA_S2", "VTA_S3", "VTA_S4", "SO_SEM_ANT", "SO_$"]:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
            
        df['PROM_PZS_MENSUAL'] = df[["VTA_S1", "VTA_S2", "VTA_S3", "VTA_S4"]].mean(axis=1)
        df = _str_cols(df, ["CODIGO", "DESCRIPCION", "CATEGORIA", "ESTADO", "TIENDA", "FORMATO", "MARCA"])
        df["DESC_NORM"] = df["DESCRIPCION"].fillna("").str.upper().str.replace(" ", "", regex=False).str.replace("&NBSP;", "", regex=False)
        # Columnas de tipo category: reduce memoria y acelera isin/groupby
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
        
        for col in ["INV_ULT_SEM", "TRANSITO_CEDIS", "VTA_PROM_DIARIA", "DIAS_INV", "SELL_OUT"]:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            
        df = _str_cols(df, ["ESTADO", "COORDINADOR", "EJECUTIVO", "PROMOTOR", "CATEGORIA", "NO_TIENDA", "TIENDA", "ARTICULO"])
        # Normalizar nombre de tienda: eliminar prefijos numéricos como "24070 CHEDRAUI..."
        # Así "24070 CHEDRAUI TLAJOMULCO 11-11" y "CHEDRAUI TLAJOMULCO 11-11" quedan iguales
        df["TIENDA"] = df["TIENDA"].str.strip().str.replace(r'^\d+\s+', '', regex=True).str.strip()
        df["DESC_NORM"] = df["ARTICULO"].fillna("").str.upper().str.replace(" ", "", regex=False).str.replace("&NBSP;", "", regex=False)
        return optimize_floats(df)
    except Exception as e:
        st.error(f"Error procesando Chedraui: {e}")
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
_CHE_RANK_PAS  = ["Pps Nutrioli Fusilli Integral (3878678)","Pps Nutrioli Spaguetti 200 (3878673)","Pps Nutrioli Fusilli Verduras (3878676)","Pps Nutrioli Fideo 200 Gr (3878671)","Pps Nutrioli Spaguetti Integra (3878677)","Pps Nutrioli Codo Verduras 200 (3878675)","Pps Nutrioli Codo 200 Gr (3878674)","Pps Nutrioli Fusilli 450 (3878672)","Aceite Nutrioli 850+Pps Fusill (3880416)","Aceite Nutrioli 850+Pps Codo 2 (3880415)"]
_CHE_RANK_OLI  = ["Ace Oliva EV Oli BOT 750 Ml (3284693)","Aceite Oliva Puro Oli Bote 750 Ml (3570620)","Ace Oliva EV Oli BOT 500 Ml (3368446)","Ace Oliva Puro Oli BOT 500 Ml (3570614)","Ace Oliva EV Oli BOT 250 Ml (3284690)","Aceite Oli Extra Virgen 500 Ml (3646332)","Aceite de Oliva Oli Nutrioli 250 Ml (3679970)","Aceite Aerosol Oli Oliva 145 Ml (3679971)","Ace Oliva EV Oli BOT 500 Ml (3428657)"]
_CHE_RANK_NUT  = ["Aceite De Soya Nutrioli Bot 850 Ml (3132396)"]

# --- 5. CARGA PARALELA ---

# Función cacheada con clave fija: actúa como almacén persistente entre reruns
# Se usa como fuente de verdad en lugar de session_state para los DataFrames grandes
@st.cache_data(ttl=14400, max_entries=3, show_spinner=False)
def _get_cached_df(key: str) -> pd.DataFrame | None:
    """Descarga y procesa un retailer. El resultado queda en cache 4 horas
    y sobrevive a todos los reruns (cambio de pestaña, interacciones, etc.)."""
    loaders = {"SORIANA": load_sor, "WALMART": load_wal, "CHEDRAUI": load_che}
    try:
        df = loaders[key](URLS_DB[key])
        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            return None
        return df
    except Exception:
        return None

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

    # Estructura: (Label, BG_Color, Text_Color, Is_Active, Border_Active, Shadow_Active, Grayscale, Border_Inactive)
    STYLES = [
        # Navegación principal
        ("SORIANA",  "linear-gradient(135deg,#D32F2F,#B71C1C)", "#ffffff", act=="SORIANA",  "#ffffff", "rgba(255,41,0,0.85)",  False, "transparent"),
        ("WALMART",  "linear-gradient(135deg,#0071DC,#005BB5)", "#ffffff", act=="WALMART",  "#ffffff", "rgba(0,47,255,0.85)",  False, "transparent"),
        ("CHEDRAUI", "linear-gradient(135deg,#FF6600,#E65100)", "#ffffff", act=="CHEDRAUI", "#ffffff", "rgba(255,119,0,0.85)", False, "transparent"),
        
        # --- Botones de Acción SORIANA ---
        ("🔴 INV SIN VENTA", "#D32F2F", "#ffffff", s_rojo, "#ffffff", "rgba(211,47,47,0.85)", False, "#ef9a9a"),
        ("🚚 PEDIDOS EN TRANSITO", "#8507F0", "#ffffff", s_transito, "#ffffff", "rgba(176,108,240,0.85)", False, "#CE93D8"),
        
        # --- Botones de Acción WALMART ---
        ("🔴 SIN VTA 4SEM",  "#D32F2F", "#ffffff", w_4w,   "#ffffff", "rgba(0,113,220,0.85)", False, "#90CAF9"),
        
        # --- Botones de Acción CHEDRAUI ---
        # (Los de Chedraui se definen abajo vía los condicionales para evitar duplicados en la matriz)

        # Ranking Institucional
        ("📊 GENERAL",  "#FFFFFF","#5AB027", _gen_active, "#D4D4D4","rgba(46,125,50,0.70)", False, "#D4D4D4"),
        ("🍝 PASTAS",   "#DBBB35","#FFFFFF", _pas_active, "#D4D4D4","rgba(240,228,2,0.70)", True,  "transparent"),
        ("🫒 OLIVAS",   "#4E5C02","#FFFFFF", _oli_active, "#D4D4D4","rgba(46,125,50,0.70)", True,  "transparent"),
        ("🍃 NUTRIOLI", "#2E7D32","#FFD700", _nut_active, "#D4D4D4","rgba(46,125,50,0.70)", True,  "transparent"),
        ("🏆 NUTRIOLI", "#2E7D32","#FFD700", _nut_active, "#D4D4D4","rgba(46,125,50,0.70)", True,  "transparent"),
    ]
    
    # Manejo de botones dinámicos según Retailer para respetar la tabla del Prompt
    if act == "SORIANA":
        STYLES.extend([
            ("📅 DIAS INV",    "#00695C", "#ffffff", _dias_active, "#ffffff", "rgba(0,105,92,0.85)",    False, "#80CBC4"),
            ("📋 DIAS X PROD", "#00695C", "#ffffff", _prod_active, "#ffffff", "rgba(22,199,130,0.85)",  False, "#80CBC4"),
        ])
    elif act == "WALMART":
        STYLES.extend([
            ("📉 NEGATIVOS",   "#D32F2F", "#ffffff", _neg_active,  "#ffffff", "rgba(230,81,0,0.85)",    False, "#FFAB40"),
            ("📅 DIAS INV",    "#00695C", "#ffffff", _dias_active, "#ffffff", "rgba(0,105,92,0.85)",    False, "#80CBC4"),
            ("📋 DIAS X PROD", "#00695C", "#ffffff", _prod_active, "#ffffff", "rgba(22,199,130,0.85)",  False, "#80CBC4"),
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
/* Botones de acción: altura fija y fuente responsiva para uniformidad */
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
/* ── Multiselect: altura 100% fija, sin saltos de layout ── */
div[data-baseweb="select"] {{
    height: 42px !important;
    min-height: 42px !important;
    max-height: 42px !important;
    overflow: hidden !important;
}}
div[data-baseweb="select"] > div {{
    height: 42px !important;
    min-height: 42px !important;
    max-height: 42px !important;
    overflow: hidden !important;
    flex-wrap: nowrap !important;
    align-items: center !important;
}}
div[data-baseweb="select"] > div > div {{
    overflow: visible !important;
    display: flex !important;
    align-items: center !important;
    flex-wrap: nowrap !important;
    max-height: 42px !important;
}}
div[data-baseweb="select"] input {{
    line-height: 42px !important;
    font-size: 0.9rem !important;
    padding-left: 6px !important;
}}
div[data-baseweb="tag"] {{
    max-width: 90px !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
    white-space: nowrap !important;
    flex-shrink: 0 !important;
}}
div[data-baseweb="select"] span {{
    white-space: nowrap !important;
}}
/* Dropdown compacto — lista más rápida de renderizar */
div[data-baseweb="popover"] {{
    max-height: 320px !important;
    overflow-y: auto !important;
}}
/* Evitar que las columnas se desplacen al cambiar altura de sus hijos */
[data-testid="stHorizontalBlock"] {{
    align-items: flex-start !important;
}}
/* Evitar reposicionamiento de scroll al re-render */
[data-testid="stVerticalBlock"] {{
    scroll-margin-top: 0px !important;
}}
@media (max-width: 768px) {{
    .block-container {{ padding-left: 0.5rem !important; padding-right: 0.5rem !important; }}
    .retailer-header {{ font-size: 1rem; padding: 8px; margin: 10px 0; }}
    section[data-testid="stSidebar"] {{ display: none; }}
    div[data-testid="stHorizontalBlock"] button {{
        font-size: clamp(0.5rem, 3.2vw, 0.72rem) !important;
        height: 42px !important;
        min-height: 42px !important;
    }}
}}
</style>
""", unsafe_allow_html=True)

# Preservar posición de scroll durante reruns de Streamlit
st.components.v1.html("""
<script>
(function() {
    const win = window.parent;
    let savedScroll = 0;
    let restoring = false;

    function saveScroll() {
        savedScroll = win.scrollY;
        restoring = true;
    }

    function restoreScroll() {
        if (!restoring) return;
        win.scrollTo({ top: savedScroll, behavior: "instant" });
        restoring = false;
    }

    win.document.addEventListener("mousedown", saveScroll, true);

    new MutationObserver(restoreScroll).observe(
        win.document.body,
        { childList: true, subtree: true }
    );
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
        # Mostrar barra de progreso animada mientras _get_cached_df descarga/cachea
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
        st.session_state.data_loaded = True

    # Pre-categorizar bases y pre-calcular groupby base (una sola vez, TTL 4h)
    try:
        for _rk, _ss in [("SORIANA","df_soriana"),("WALMART","df_walmart"),("CHEDRAUI","df_chedraui")]:
            _df_pre = st.session_state.get(_ss)
            if _df_pre is None:
                continue
            _cat_key = f"cat_{_rk.lower()}"
            _pie_key = f"pie_base_{_rk.lower()}"
            # Categorizar si no está en session_state
            if _cat_key not in st.session_state:
                _cat_json = categorize_full_df(_df_pre.to_json(), _rk)  # JSON cacheado
                st.session_state[_cat_key] = pd.read_json(_cat_json)
            else:
                _cat_json = None  # ya en session_state, no necesitamos el JSON
            # Pre-calcular groupby base reutilizando _cat_json — evita to_json() extra
            if _pie_key not in st.session_state:
                _pie_src = _cat_json if _cat_json is not None else st.session_state[_cat_key].to_json()
                _pie_json = precompute_pie_base(_pie_src, _rk)
                if _pie_json:
                    st.session_state[_pie_key] = _pie_json
    except Exception:
        pass

else:
    # Ya cargado — restaurar desde cache si session_state fue limpiado (ej. cambio de pestaña)
    for k, ss_key in _df_map.items():
        if st.session_state.get(ss_key) is None:
            try:
                _df = _get_cached_df(k)
                if _df is not None:
                    st.session_state[ss_key] = _df
            except Exception:
                pass

if st.session_state.load_errors:
    for k, err in st.session_state.load_errors.items():
        st.warning(f"⚠️ {k}: {err}")

# --- 11. NAVEGACIÓN ---
col1, col2, col3 = st.columns(3, gap="small")
with col1: st.button("SORIANA",  on_click=set_retailer, args=("SORIANA",),  use_container_width=True)
with col2: st.button("WALMART",  on_click=set_retailer, args=("WALMART",),  use_container_width=True)
with col3: st.button("CHEDRAUI", on_click=set_retailer, args=("CHEDRAUI",), use_container_width=True)
st.markdown("<hr style='margin:15px 0;border:0;border-top:1px solid #eee;'>", unsafe_allow_html=True)

# --- 12. HELPER: OBTENER DATOS ---
def get_cached_or_upload(key, uploader_key, load_func):
    df_key_map = {"SORIANA": "df_soriana", "WALMART": "df_walmart", "CHEDRAUI": "df_chedraui"}
    ss_key = df_key_map[key]

    # 1) Buscar en session_state (más rápido, in-memory)
    df = st.session_state.get(ss_key)
    if df is not None and isinstance(df, pd.DataFrame) and not df.empty:
        return df

    # 2) Buscar en cache de Streamlit (sobrevive reruns y cambios de pestaña)
    try:
        df = _get_cached_df(key)
        if df is not None and isinstance(df, pd.DataFrame) and not df.empty:
            st.session_state[ss_key] = df  # Restaurar a session_state
            return df
    except Exception:
        pass

    # 3) Si no hay cache, ofrecer carga manual
    st.warning(f"⚠️ No se pudo cargar {key} automáticamente. Cargue el archivo manualmente.")
    f = st.file_uploader(f"📂 Cargar Excel {key}", type=["xlsx"], key=uploader_key)
    if f:
        with st.spinner(f"Procesando {key}..."):
            df = load_func(f)
        if df is not None:
            st.session_state[ss_key] = df
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
    df_s_cat = pd.read_json(categorize_full_df(df_s.to_json(), "SORIANA"))
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
        # ── Inicializar claves de session_state para los filtros en cascada ──
        for _k in ["s_fil_nda","s_fil_edo","s_fil_nom","s_fil_cd","s_fil_fmt"]:
            if _k not in st.session_state:
                st.session_state[_k] = []

        # ── Callback: cuando cambia No Tienda, sobreescribe los dependientes ─
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

        # ── Callback: cuando cambia Estado, limita opciones de los demás ─────
        def _on_edo_change():
            if st.session_state.get("s_fil_nda"):
                return  # No Tienda tiene prioridad
            edo = st.session_state.get("s_fil_edo", [])
            # Limpiar campos dependientes para que no queden valores fuera de rango
            st.session_state["s_fil_nom"] = []
            st.session_state["s_fil_cd"]  = []
            st.session_state["s_fil_fmt"] = []

        # ── Callback: cuando cambia Nombre, autocompleta No Tienda ───────────
        def _on_nom_change():
            if st.session_state.get("s_fil_nda"):
                return  # No Tienda ya está fijo
            nom = st.session_state.get("s_fil_nom", [])
            if nom:
                _t = df_s[df_s["TIENDA"].isin(nom)]
                st.session_state["s_fil_nda"] = list(_t["NO_TIENDA"].dropna().unique())

        with st.container():
            st.markdown("#### 🔍 Filtros Avanzados")
            c1, c2 = st.columns(2)

            # Calcular opciones dinámicas antes de renderizar
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

        # dff_graph con fallback progresivo — la gráfica SIEMPRE muestra datos
        # Nivel 1: filtros geográficos completos
        dff_graph = apply_filters(df_s, ["NO_TIENDA","TIENDA","CIUDAD","ESTADO"], [fil_nda, fil_nom, fil_cd, fil_edo])
        # Nivel 2: si queda vacío por combinación contradictoria, quitar Ciudad/Formato
        if dff_graph.empty and (fil_nda or fil_nom):
            dff_graph = apply_filters(df_s, ["NO_TIENDA","TIENDA"], [fil_nda, fil_nom])
        # Nivel 3: si sigue vacío, usar solo Estado
        if dff_graph.empty and fil_edo:
            dff_graph = apply_filters(df_s, ["ESTADO"], [fil_edo])
        # Nivel 4: sin filtros (nunca debe llegar aquí, pero garantía total)
        if dff_graph.empty:
            dff_graph = df_s

        b1, b2, b3, b4 = st.columns(4, gap="small")
        with b1: st.button("🔴 INV SIN VENTA", on_click=tog_s_rojo,      use_container_width=True, type="primary" if s_rojo      else "secondary")
        with b2: st.button("📅 DIAS INV",      on_click=tog_s_dias_inv,  use_container_width=True, type="primary" if s_dias_inv  else "secondary")
        with b3: st.button("📋 DIAS X PROD",   on_click=tog_s_dias_prod, use_container_width=True, type="primary" if s_dias_prod else "secondary")
        with b4: st.button("🚚 PEDIDOS EN TRANSITO", on_click=tog_s_transito, use_container_width=True, type="primary" if s_transito else "secondary")

        # ── Gráfica: merge con base categorizada — sin recalcular en cada filtro ──
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
                # Fallback: si combinación vacía, usar base completa categorizada
                if pie_df.empty:
                    _pie_json_s = st.session_state.get("pie_base_soriana")
                else:
                    _pie_json_s = pie_df.to_json()
            else:
                _pie_json_s = st.session_state.get("pie_base_soriana")
            # Garantía final: si aún no hay datos usar df_s_cat completo
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

        # ── Contenido de botones de acción (debajo de la gráfica) ────────────
        if st.session_state.s_transito:
            st.subheader("🚚 Pedidos en Tránsito")
            dff_transito = dff[dff["PEDIDOS"] > 0].copy()
            disp_transito = dff_transito[["FORMATO", "TIENDA", "CODIGO", "DESCRIPCION", "PEDIDOS", "FECHA_ENTREGA", "CANTIDAD_PZS"]].copy()
            disp_transito.columns = ['FORMATO', 'NOMBRE DE TIENDA', 'CODIGO', 'ARTICULO', 'PEDIDOS', 'FECHA DE ENTREGA', 'CANTIDAD EN PZS']
            st.dataframe(disp_transito.style.format({'PEDIDOS': "{:,.0f}", 'CANTIDAD EN PZS': "{:,.0f}"}), use_container_width=True, hide_index=True, height=auto_height(disp_transito))

        elif st.session_state.s_dias_prod:
            st.subheader("📋 Días Inventario x Producto")
            _base = df_s.copy()
            _base["_DESC_CMP"] = _base["DESCRIPCION"].fillna("").str.upper().str.strip()
            res_rows = []
            for item in _SOR_DIAS_PROD:
                _item_cmp = item.upper().strip()
                mask = _base["_DESC_CMP"] == _item_cmp
                if not mask.any():
                    mask = _base["_DESC_CMP"].str.contains(_item_cmp, case=False, regex=False, na=False)
                if mask.any():
                    subset = _base[mask]
                    res_rows.append({"CODIGO": subset["CODIGO"].iloc[0], "ARTICULO": item, "DIAS INV TENDENCIA": round(subset["DIAS_INV"].mean(), 1)})
                else:
                    res_rows.append({"CODIGO": "-", "ARTICULO": item, "DIAS INV TENDENCIA": 0})
            df_prod_summary = pd.DataFrame(res_rows)
            st.dataframe(df_prod_summary.style.format({'DIAS INV TENDENCIA':"{:,.1f}"}), use_container_width=True, hide_index=True, height=auto_height(df_prod_summary))

        elif st.session_state.s_dias_inv:
            st.subheader("📅 Reporte Días Inventario")
            val_nut = get_kpi_mean(dff,"DESCRIPCION","DIAS_INV","ACEITE DE SOYA NUTRIOLI BOT 850 ML")
            val_sab = get_kpi_mean(dff,"DESCRIPCION","DIAS_INV","ACEITE COMESTIBLE SABROSANO 850 ML")
            mask_pastas = dff["DESC_NORM"].str.contains("PASTA", na=False)
            val_pas = dff.loc[mask_pastas,"DIAS_INV"].mean() if mask_pastas.any() else 0
            k1,k2,k3 = st.columns(3)
            k1.markdown(f"<div class='kpi-card'><div class='kpi-title'>NUTRIOLI 850ML</div><div class='kpi-value' style='color:#28a745;'>{val_nut:,.1f}</div></div>", unsafe_allow_html=True)
            k2.markdown(f"<div class='kpi-card'><div class='kpi-title'>SABROSANO 850ML</div><div class='kpi-value' style='color:#E4007C;'>{val_sab:,.1f}</div></div>", unsafe_allow_html=True)
            k3.markdown(f"<div class='kpi-card'><div class='kpi-title'>PASTAS</div><div class='kpi-value' style='color:#64DD17;'>{val_pas:,.1f}</div></div>", unsafe_allow_html=True)
            disp = dff[["NO_TIENDA","TIENDA","CODIGO","DESCRIPCION","INV_CAJAS","SO_$","SO_4SEM","DIAS_INV"]].copy()
            disp.columns = ['No.','TIENDA','CODIGO','ARTICULO','INV CAJAS','SELL OUT SEM','SELL OUT ULT 4 SEM','DIAS INV']
            st.dataframe(disp.style.format({'INV CAJAS':"{:,.0f}",'SELL OUT SEM':'${:,.2f}','SELL OUT ULT 4 SEM':'${:,.2f}','DIAS INV':"{:,.1f}"}), use_container_width=True, hide_index=True, height=auto_height(disp))

        else:
            if st.session_state.s_rojo: dff_cat=dff_cat[dff_cat['SIN_VTA']]; st.caption("📋 Vista: Sin Venta")
            disp = dff_cat[["NO_TIENDA","TIENDA","CODIGO","DESCRIPCION","INV_CAJAS","SO_$","SO_4SEM","DIAS_INV"]].copy()
            disp.columns=['No.','TIENDA','CODIGO','ARTICULO','INV CAJAS','SELL OUT SEM','SELL OUT ULT 4 SEM','DIAS INV']
            disp = disp.sort_values(by='SELL OUT ULT 4 SEM',ascending=False)
            st.dataframe(disp.style.format({'INV CAJAS':"{:,.0f}",'SELL OUT SEM':'${:,.2f}','SELL OUT ULT 4 SEM':'${:,.2f}','DIAS INV':"{:,.1f}"}), use_container_width=True, hide_index=True, height=auto_height(disp))

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
            else: st.warning("⚠️ No se encontraron ventas para los productos seleccionados.")

def view_walmart(df_w):
    df_w_cat = pd.read_json(categorize_full_df(df_w.to_json(), "WALMART"))
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

        # ── Inicializar claves de session_state ──────────────────────────────
        for _k in ["w_fil_store","w_fil_state","w_fil_fmt"]:
            if _k not in st.session_state:
                st.session_state[_k] = []

        # ── Callback: Tienda → autocompleta Estado y Formato ─────────────────
        def _on_store_change():
            store = st.session_state.get("w_fil_store", [])
            if store:
                _t = df_w[df_w["TIENDA"].isin(store)]
                st.session_state["w_fil_state"] = sorted(_t["ESTADO"].dropna().unique())
                st.session_state["w_fil_fmt"]   = sorted(_t["FORMATO"].dropna().unique())
            else:
                st.session_state["w_fil_state"] = []
                st.session_state["w_fil_fmt"]   = []

        # ── Callback: Estado → limita Formato y limpia Tienda si incompatible ─
        def _on_state_change():
            if st.session_state.get("w_fil_store"):
                return  # Tienda tiene prioridad
            st.session_state["w_fil_fmt"]   = []
            st.session_state["w_fil_store"] = []

        # ── Callback: Formato → limpia Tienda si incompatible ────────────────
        def _on_fmt_change():
            if st.session_state.get("w_fil_store"):
                return  # Tienda tiene prioridad
            st.session_state["w_fil_store"] = []

        with st.container():
            st.markdown("#### 🔍 Filtros Avanzados")
            c1,c2,c3 = st.columns(3)

            # Calcular opciones dinámicas antes de renderizar
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

        # dff_graph con fallback progresivo
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

        # ── Gráfica: merge con base categorizada — sin recalcular en cada filtro ──
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
                _pie_json_w = st.session_state.get("pie_base_walmart")
            if not _pie_json_w:
                _fb = df_w_cat.dropna(subset=["Category"]).groupby("Category")["SO_$"].sum().reset_index()
                _fb = _fb[_fb["SO_$"]>0]
                _pie_json_w = _fb.to_json() if not _fb.empty else None
            if _pie_json_w:
                fig = build_pie_cached(_pie_json_w, "WALMART")
                _ann = _filter_badge({"Tienda": sel_store, "Estado": sel_state, "Formato": sel_fmt}, RETAILER_COLORS["WALMART"])
                if _ann: fig.add_annotation(**_ann)
                st.plotly_chart(fig, use_container_width=True)
            else: st.info("Sin datos para gráfica.")

        # ── Contenido de botones de acción (debajo de la gráfica) ────────────
        if st.session_state.w_neg:
            dff_neg = dff[dff["EXISTENCIA"]<0]
            st.warning("VISTA: NEGATIVOS")
            disp=dff_neg[["CODIGO","DESCRIPCION","TIENDA","EXISTENCIA","SO_$","PROM_PZS_MENSUAL"]].copy()
            disp.columns=['CODIGO','DESCRIPCION','TIENDA','EXISTENCIA','SELL OUT','PROM PZS MENSUAL']
            st.dataframe(disp.style.format({'SELL OUT':'${:,.2f}','PROM PZS MENSUAL':'{:,.2f}'}), use_container_width=True, hide_index=True, height=auto_height(disp))

        elif st.session_state.w_4w:
            dff_4w = dff[(dff["VTA_S1"]==0)&(dff["VTA_S2"]==0)&(dff["VTA_S3"]==0)&(dff["VTA_S4"]==0)]
            st.warning("VISTA: SIN VENTA 4 SEMANAS")
            disp=dff_4w[["CODIGO","DESCRIPCION","TIENDA","EXISTENCIA","SO_$","PROM_PZS_MENSUAL"]].copy()
            disp.columns=['CODIGO','DESCRIPCION','TIENDA','EXISTENCIA','SELL OUT','PROM PZS MENSUAL']
            st.dataframe(disp.style.format({'SELL OUT':'${:,.2f}','PROM PZS MENSUAL':'{:,.2f}'}), use_container_width=True, hide_index=True, height=auto_height(disp))

        elif st.session_state.w_dias_prod:
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
            disp=dff_cat[["CODIGO","DESCRIPCION","TIENDA","EXISTENCIA","SO_$","PROM_PZS_MENSUAL"]].copy()
            disp.columns=['CODIGO','DESCRIPCION','TIENDA','EXISTENCIA','SELL OUT','PROM PZS MENSUAL']
            st.dataframe(disp.style.format({'SELL OUT':'${:,.2f}','PROM PZS MENSUAL':'{:,.2f}'}), use_container_width=True, hide_index=True, height=auto_height(disp))

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

def view_chedraui(df_c):
    df_c_cat = pd.read_json(categorize_full_df(df_c.to_json(), "CHEDRAUI"))
    st.markdown(f"<div class='retailer-header' style='background-color:{RETAILER_COLORS['CHEDRAUI']}'>CHEDRAUI</div>", unsafe_allow_html=True)

    def tog_c(target):
        for v in ['c_neg_zero','c_dias_inv','c_transito']:
            st.session_state[v] = True if v==target and not st.session_state[v] else False
    def set_c_rank(mode):
        for v in ['c_rank_gen','c_rank_pas','c_rank_oli','c_rank_nut']: st.session_state[v]=False
        st.session_state[f'c_rank_{mode.lower()}']=True

    if df_c is not None:
        # ── Inicializar claves de session_state ──────────────────────────────
        for _k in ["c_fil_no","c_fil_ti","c_fil_ed"]:
            if _k not in st.session_state:
                st.session_state[_k] = []

        # ── Callback: Tienda → autocompleta No Tienda y Estado ───────────────
        def _on_ti_change():
            ti = st.session_state.get("c_fil_ti", [])
            if ti:
                _t = df_c[df_c["TIENDA"].isin(ti)]
                st.session_state["c_fil_no"] = sorted(_t["NO_TIENDA"].dropna().unique())
                st.session_state["c_fil_ed"] = sorted(_t["ESTADO"].dropna().unique())
            else:
                st.session_state["c_fil_no"] = []
                st.session_state["c_fil_ed"] = []

        # ── Callback: No Tienda → autocompleta Tienda y Estado ───────────────
        def _on_no_change():
            no = st.session_state.get("c_fil_no", [])
            if no:
                _t = df_c[df_c["NO_TIENDA"].isin(no)]
                st.session_state["c_fil_ti"] = sorted(_t["TIENDA"].dropna().unique())
                st.session_state["c_fil_ed"] = sorted(_t["ESTADO"].dropna().unique())
            else:
                st.session_state["c_fil_ti"] = []
                st.session_state["c_fil_ed"] = []

        # ── Callback: Estado → limita Tienda y No Tienda ─────────────────────
        def _on_ed_change():
            if st.session_state.get("c_fil_ti") or st.session_state.get("c_fil_no"):
                return  # Tienda / No Tienda tienen prioridad
            st.session_state["c_fil_ti"] = []
            st.session_state["c_fil_no"] = []

        with st.container():
            st.markdown("#### 🔍 Filtros Avanzados")
            c1,c2 = st.columns(2)

            # Calcular opciones dinámicas antes de renderizar
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

        # dff_graph con fallback progresivo
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

        # ── Gráfica: merge con base categorizada — sin recalcular en cada filtro ──
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

        # ── Contenido de botones de acción (debajo de la gráfica) ────────────
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
            k1,k2,k3 = st.columns(3)
            k1.markdown(f"<div class='kpi-card'><div class='kpi-title'>NUTRIOLI 850ML</div><div class='kpi-value' style='color:#28a745;'>{val_nut:,.1f}</div></div>", unsafe_allow_html=True)
            k2.markdown(f"<div class='kpi-card'><div class='kpi-title'>SABROSANO 850ML</div><div class='kpi-value' style='color:#E4007C;'>{val_sab:,.1f}</div></div>", unsafe_allow_html=True)
            k3.markdown(f"<div class='kpi-card'><div class='kpi-title'>AVE 850ML</div><div class='kpi-value' style='color:#D32F2F;'>{val_ave:,.1f}</div></div>", unsafe_allow_html=True)
            disp=dff[["NO_TIENDA","TIENDA","ARTICULO","INV_ULT_SEM","VTA_PROM_DIARIA","DIAS_INV","SELL_OUT"]].copy()
            disp.columns=['NO_TIENDA','TIENDA','ARTICULO','INV_ULT_SEM','VTA_PROM_DIARIA','DIAS_INV','SELL_OUT']
            st.dataframe(disp.style.format({'INV_ULT_SEM':"{:,.0f}",'VTA_PROM_DIARIA':"{:,.2f}",'DIAS_INV':"{:,.1f}",'SELL_OUT':"${:,.2f}"}), use_container_width=True, hide_index=True, height=auto_height(disp))

        elif st.session_state.c_neg_zero:
            dff_neg = dff[dff["INV_ULT_SEM"]<0].copy()
            st.subheader("📉 Vista: Inventarios Negativos")
            disp_neg = dff_neg[["ESTADO","COORDINADOR","EJECUTIVO","PROMOTOR","CATEGORIA","NO_TIENDA","TIENDA","ARTICULO","INV_ULT_SEM"]].copy()
            disp_neg.columns=["ESTADO","Coordinador","Ejecutivo","Promotor","Categoria","No de tienda","Tienda","articulo","Inventario 06 Mar 2026"]
            st.dataframe(disp_neg.style.format({'Inventario 06 Mar 2026':"{:,.0f}"}), use_container_width=True, hide_index=True, height=auto_height(disp_neg))

        else:
            st.caption("📋 Vista: Completa")
            disp=dff_cat[["NO_TIENDA","TIENDA","ARTICULO","INV_ULT_SEM","VTA_PROM_DIARIA","DIAS_INV","SELL_OUT"]].copy()
            disp.columns=['NO_TIENDA','TIENDA','ARTICULO','INV_ULT_SEM','VTA_PROM_DIARIA','DIAS_INV','SELL_OUT']
            st.dataframe(disp.style.format({'INV_ULT_SEM':"{:,.0f}",'VTA_PROM_DIARIA':"{:,.2f}",'DIAS_INV':"{:,.1f}",'SELL_OUT':"${:,.2f}"}), use_container_width=True, hide_index=True, height=auto_height(disp))

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