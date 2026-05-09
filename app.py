import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import numpy as np
import time
import re
import unicodedata
import requests
import plotly.express as px
import urllib.parse
import os
import re
import unicodedata
from io import BytesIO, StringIO
from concurrent.futures import ThreadPoolExecutor, as_completed

import logging

logging.basicConfig(level=logging.INFO)

# ─────────────────────────────────────────────────────────────
# NORMALIZADOR UNIVERSAL DE ENCABEZADOS
# ─────────────────────────────────────────────────────────────
def normalize_header(value):

    if pd.isna(value):
        return ""

    value = str(value)

    value = unicodedata.normalize("NFKD", value)
    value = "".join(c for c in value if not unicodedata.combining(c))

    value = value.upper().strip()

    value = re.sub(r"\s+", " ", value)

    return value


def log_error(context: str, error: Exception):
    logging.error(f"{context} → {str(error)}")


def safe_numeric(series, col_name: str):
    """Convierte a numérico con log de errores silenciosos."""
    try:
        return pd.to_numeric(series, errors='coerce').fillna(0)
    except Exception as e:
        log_error(f"safe_numeric:{col_name}", e)
        return pd.Series([0] * len(series))

def validate_df(df, name: str) -> bool:
    """Valida que un DataFrame sea usable. Registra error silencioso si no."""
    if df is None:
        log_error("validate_df", Exception(f"{name} no cargó correctamente."))
        return False
    if df.empty:
        log_error("validate_df", Exception(f"{name} está vacío."))
        return False
    return True


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
CACHE_CONFIG = {'ttl': 1800, 'max_entries': 3, 'show_spinner': False}   # 30 min

URLS_DB = {
    "SORIANA": "https://raw.githubusercontent.com/gamerhackleon-afk/RTLRAGA/main/SORIANA.xlsx",
    "WALMART": "https://raw.githubusercontent.com/gamerhackleon-afk/RTLRAGA/main/WALMART.xlsx",
    "CHEDRAUI": "https://raw.githubusercontent.com/gamerhackleon-afk/RTLRAGA/main/CHEDRAUI.xlsx",
    "FRESKO":   "https://raw.githubusercontent.com/gamerhackleon-afk/RTLRAGA/main/FRESKO.xlsx"
}


# ── CATEGORÍAS FRESKO POR SKU ─────────────────────────────────────────────────
CATEGORIA_MAP = {
    # BORGES
    "8410179100043":"BORGES","8410179304144":"BORGES","8410179005935":"BORGES",
    "8410179300825":"BORGES","8410179100708":"BORGES","8410179100357":"BORGES",
    "8410179100920":"BORGES","8410179005928":"BORGES","8410179100036":"BORGES",
    "8410179000640":"BORGES","8410179308142":"BORGES","8410179100050":"BORGES",
    "8410179510118":"BORGES","8410179301082":"BORGES","8410179800127":"BORGES",
    "8410179900254":"BORGES","8410179305141":"BORGES","8410179200811":"BORGES",
    "8410179000084":"BORGES","8410179100821":"BORGES","8410179200828":"BORGES",
    "8410179000961":"BORGES","8410179000046":"BORGES","8410179306148":"BORGES",
    "8410179000077":"BORGES","8410179000053":"BORGES",
    # OLI
    "7501039122280":"OLI","7501039127308":"OLI","7501039127285":"OLI",
    "7501039122631":"OLI","7501039122624":"OLI","7501039122020":"OLI",
    "7501039127292":"OLI","7501039122013":"OLI",
    # REST NUTRIOLI
    "7501039124406":"REST NUTRIOLI","7501039122228":"REST NUTRIOLI",
    "7501039124390":"REST NUTRIOLI","7501039123553":"REST NUTRIOLI",
    # BALSAMICO
    "7501039124512":"BALSAMICO",
    # PASTAS
    "7501039127025":"PASTAS","7501039127124":"PASTAS",
    # AVE
    "7501039122105":"AVE","7501039123287":"GRAN TRADICION",
    # NUTRIOLI
    "7501039121610":"NUTRIOLI",
}

RETAILER_COLORS = {
    "SORIANA": "#D32F2F",
    "WALMART": "#0071DC",
    "CHEDRAUI": "#FF6600",
    "FRESKO":   "#B3FF00"
}

# --- INICIALIZACIÓN DE SESSION STATE ---
import time as _time


# Sin default — ningún botón de ranking activo hasta que el usuario lo presione
for _retailer in ["SORIANA", "WALMART", "CHEDRAUI", "FRESKO"]:
    st.session_state.setdefault(f"rank_btn_{_retailer}", "")

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
if 'df_fresko' not in st.session_state:
    st.session_state.df_fresko = None
if 'fre_neg'       not in st.session_state: st.session_state.fre_neg       = False
if 'fre_dias'      not in st.session_state: st.session_state.fre_dias      = False
if 'fre_trans'     not in st.session_state: st.session_state.fre_trans     = False
if 'fre_rank_gen'  not in st.session_state: st.session_state.fre_rank_gen  = False
if 'fre_rank_pas'  not in st.session_state: st.session_state.fre_rank_pas  = False
if 'fre_rank_oli'  not in st.session_state: st.session_state.fre_rank_oli  = False
if 'fre_rank_nut'  not in st.session_state: st.session_state.fre_rank_nut  = False
if 'fre_rank_bor'  not in st.session_state: st.session_state.fre_rank_bor  = False

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
    st.session_state.setdefault(_v, False)

# --- 3. FUNCIONES UTILITARIAS ---
def normalize_desc(series):
    return (
        series.fillna("")
        .str.upper()
        .str.replace(" ", "", regex=False)
        .str.replace("&NBSP;", "", regex=False)
    )

def safe_mean(series):
    return series.values.mean() if len(series) else 0

def apply_filters(df, filter_cols_or_dict, selections=None):
    """
    Acepta dict {col: [vals]} o listas paralelas.
    Limpia valores vacios/NAN antes de filtrar — elimina filtros fantasma.
    OPT D: Early-return si no hay selecciones activas (evita O(n) innecesario).
    """
    # Early-return: si selections es lista vacía o todos None/vacíos, retornar sin iterar
    if selections is not None and not any(
        str(s).strip().upper() not in ("", "NAN", "NONE", "NAT")
        for sel in (selections if isinstance(selections, list) else [])
        for s in (sel or [])
    ):
        return df
    mask = np.ones(len(df), dtype=bool)
    if isinstance(filter_cols_or_dict, dict):
        items = filter_cols_or_dict.items()
    else:
        items = zip(filter_cols_or_dict, selections or [])
    for col, sel in items:
        clean_sel = [
            str(s).strip().upper()
            for s in (sel or [])
            if str(s).strip().upper() not in ("", "NAN", "NONE", "NAT")
        ]
        if clean_sel and col in df.columns:
            # FIX DEFINITIVO:
            # normalizar SIEMPRE valores del dataframe antes de comparar
            # evita problemas con:
            # - mayúsculas/minúsculas
            # - espacios invisibles
            # - tipos object/category
            # - filtros FORMATO de Soriana
            col_series = (
                df[col]
                .fillna("")
                .astype(str)
                .apply(normalize_header)
            )

            sel_set = set(clean_sel)

            mask &= col_series.isin(sel_set).values
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
    try:
        if df is None or df.empty:
            return 0
        if "CODIGO" not in df.columns:
            return 0
        df_upc = df[df["CODIGO"] == str(upc).strip()]
        if df_upc.empty:
            return 0
        # Evita duplicidad por tienda
        return df_upc.groupby(["CODIGO", "TIENDA"], sort=False)[value_col].sum().to_numpy().sum()
    except Exception as e:
        log_error("get_kpi_sum_by_upc", e)
        return 0

def get_kpi_sum_exact_desc(df, desc, value_col="SO_$"):
    """Calcula suma exacta usando descripción completa por si no hay UPC"""
    if "DESCRIPCION" not in df.columns:
        return 0
    mask = df["DESCRIPCION"] == str(desc).strip().upper()
    df_desc = df[mask]
    if df_desc.empty:
        return 0
    # Evita duplicidad por tienda
    return df_desc.groupby(["DESCRIPCION", "TIENDA"], sort=False)[value_col].sum().to_numpy().sum()

def get_kpi_mean_by_upc(df, upc, value_col="DIAS_INV"):
    """Promedio exacto por código UPC para métricas no sumables (como Días de Inventario)"""
    if "CODIGO" not in df.columns:
        return 0
    mask = df["CODIGO"] == str(upc).strip()
    return safe_mean(df.loc[mask, value_col])

def get_kpi_mean_exact_desc(df, desc, value_col="DIAS_INV"):
    """Promedio exacto por descripción completa"""
    if "DESCRIPCION" not in df.columns:
        return 0
    mask = df["DESCRIPCION"] == str(desc).strip().upper()
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

@st.cache_data(show_spinner=False, ttl=1800)
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

@st.cache_data(show_spinner=False, ttl=1800)
def _categorize_df(df_json: str, retailer: str) -> str:
    df = pd.read_json(StringIO(df_json))
    # FIX: asegurar columnas como texto limpio
    df.columns = [str(c).strip() for c in df.columns]

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
    elif retailer == "FRESKO":
        # FRESKO ya tiene CATEGORIA asignada por CATEGORIA_MAP en load_fre
        # NO usar "OTROS" — solo categorías definidas aparecen en la gráfica
        df = df.copy()
        df["Category"]     = df["CATEGORIA"] if "CATEGORIA" in df.columns else None
        df["Category_PIE"] = df["Category"]
        return df.to_json(date_format='iso')
    else:  
        desc = df["DESC_NORM"].astype(str) if "DESC_NORM" in df.columns else _safe_str(df["ARTICULO"])
        # ── FIX CRÍTICO: BORGES en CHEDRAUI NO viene en DESC_NORM sino en columna CATEGORIA
        # Se detecta por columna CATEGORIA OR por descripción (doble seguridad)
        cat_col = df["CATEGORIA"].astype(str).str.upper() if "CATEGORIA" in df.columns else pd.Series([""] * len(df), index=df.index)
        conditions = [
            (cat_col.str.contains("BORGES", na=False)) | (desc.str.contains("BORGES", na=False)),
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
        choices = ["BORGES","BALSAMICO","SABROSANO","GT","MI SAZON","AVE","PASTAS","OLIVAS","NUTRIOLI","REST NUTRIOLI"]
    conditions = [c.to_numpy(dtype=bool) for c in conditions]
    df = df.copy()
    df['Category'] = np.select(conditions, choices, default=None)
    # ── FIX: Category_PIE incluye REST NUTRIOLI (solo para gráfica circular)
    #         Category limpia NO tiene REST NUTRIOLI (para tabla y Excel)
    df['Category_PIE'] = df['Category']
    df.loc[df['Category'] == "REST NUTRIOLI", 'Category'] = None
    return df.to_json(date_format='iso')

@st.cache_data(show_spinner=False, ttl=1800)
def categorize_full_df(df_json: str, retailer: str) -> str:
    return _categorize_df(df_json, retailer)

@st.cache_data(show_spinner=False, ttl=1800)
def build_pie_cached(pie_df_json: str, retailer: str):
    COLORS = {
        "SORIANA":  (["BALSAMICO","SABROSANO","PASTAS","OLIVAS","GT","NUTRIOLI","MI SAZON","AVE","REST NUTRIOLI"],
                     ["#e012a9","#f705ab","#4c915d","#97ad6a","#7d6010","#02c705","#e89015","#ff0000","#00ff04"],
                     "SO_$"),
        "WALMART":  (["SABROSANO","GT","OLIVAS","BALSAMICO","PASTAS","REST NUTRIOLI","NUTRIOLI","BORGES"],
                     ["#E4007C","#a18262","#6B8E23","#9f4576","#426045","#bfff00","#008f39","#7B1A1A"],
                     "SO_$"),
        "CHEDRAUI": (["BORGES","BALSAMICO","SABROSANO","PASTAS","OLIVAS","GT","NUTRIOLI","MI SAZON","AVE","REST NUTRIOLI"],
                     ["#691D08","#e012a9","#f705ab","#4c915d","#97ad6a","#7d6010","#02c705","#e89015","#ff0000","#00ff04"],
                     "SELL_OUT"),
        "FRESKO":   (["BORGES","OLI","REST NUTRIOLI","BALSAMICO","PASTAS","AVE","GRAN TRADICION","NUTRIOLI"],
                     ["#D3F202","#6A7848","#9AF5B7","#943280","#F2D01F","#C20000","#784400","#03663D"],
                     "IMPORTEABR"),
    }
    domain, range_, val_col = COLORS.get(retailer, COLORS["CHEDRAUI"])
    return _make_pie(pie_df_json, domain, range_, val_col)

@st.cache_data(show_spinner=False, ttl=1800)
def precompute_pie_base(df_cat_json: str, retailer: str) -> str:
    df = pd.read_json(StringIO(df_cat_json))
    # Usar Category_PIE (incluye REST NUTRIOLI) para la gráfica
    cat_field = "Category_PIE" if "Category_PIE" in df.columns else "Category"
    if cat_field not in df.columns:
        return None
    if retailer == "CHEDRAUI":
        val_col = "SELL_OUT"
    elif retailer == "FRESKO":
        val_col = "IMPORTEABR"
    else:
        val_col = "SO_$"
    if val_col not in df.columns:
        return None
    pie_df = df.dropna(subset=[cat_field]).groupby(cat_field)[val_col].sum().reset_index()
    pie_df = pie_df.rename(columns={cat_field: "Category"})
    pie_df = pie_df[pie_df[val_col] > 0]
    return pie_df.to_json(date_format='iso') if not pie_df.empty else None

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
    # proxies={} bypasea proxy local (Kaspersky/antivirus que inyecta HTML)
    _req_kwargs = dict(
        timeout=(8, 45),
        stream=True,
        headers={"User-Agent": "Mozilla/5.0"},
        proxies={"http": None, "https": None},
        allow_redirects=True,
    )
    urls_to_try = [url]
    # Alternar entre raw.githubusercontent y github.com/raw como fallback
    if "raw.githubusercontent.com" in url:
        alt = url.replace("raw.githubusercontent.com","github.com").replace("/main/","/raw/refs/heads/main/")
        urls_to_try.append(alt)
    elif "github.com" in url and "/raw/" in url:
        alt = url.replace("github.com","raw.githubusercontent.com").replace("/raw/refs/heads/","/" ).replace("/raw/","/" )
        urls_to_try.append(alt)

    for _url in urls_to_try:
        try:
            response = requests.get(_url, **_req_kwargs)
            response.raise_for_status()
            buf = BytesIO()
            for chunk in response.iter_content(chunk_size=4 * 1024 * 1024):
                if chunk:
                    buf.write(chunk)
            raw = buf.getvalue()
            # Validar que sea xlsx (magic bytes PK) y no HTML de antivirus
            if raw[:2] != b"PK":
                logging.warning(f"download_file_fast: respuesta no es xlsx en {_url[:60]} — bytes={raw[:8]}")
                continue
            buf.seek(0)
            return buf
        except requests.exceptions.Timeout:
            logging.warning(f"download_file_fast timeout: {_url[:60]}")
            continue
        except Exception as e:
            log_error("download_file_fast", e)
            continue
    return None

def download_file(url_or_file):
    if isinstance(url_or_file, str):
        return download_file_fast(url_or_file)
    url_or_file.seek(0)
    return url_or_file


# _view_vars definida al inicio del archivo (usar esa — nombres canónicos con guion bajo)

def reset_views():
    for var in _view_vars:
        if var in st.session_state:
            st.session_state[var] = False

def set_retailer(retailer_name):
    st.session_state.active_retailer = retailer_name
    reset_views()

# --- 4. MOTOR INTELIGENTE DE LECTURA DE COLUMNAS ---
def find_col(df, candidates):
    """
    Busca columnas aunque:
    - cambien mayúsculas
    - tengan espacios
    - tengan acentos
    - Excel convierta fechas
    """

    import re as _re

    normalized_cols = {
        normalize_header(c): c
        for c in df.columns
    }

    for name in candidates:

        sname = str(name)

        # REGEX
        if sname.startswith("~"):

            pattern = normalize_header(sname[1:])

            for norm_col, real_col in normalized_cols.items():
                if _re.search(pattern, norm_col, _re.IGNORECASE):
                    return real_col

        else:

            target = normalize_header(sname)

            # MATCH EXACTO
            if target in normalized_cols:
                return normalized_cols[target]

            # MATCH PARCIAL
            for norm_col, real_col in normalized_cols.items():
                if target in norm_col:
                    return real_col

    return None
def validate_columns(df, retailer, required_cols_dict):
    """
    Mapea columnas del Excel a nombres internos.
    Claves con prefijo '?' son OPCIONALES — no interrumpen la carga si faltan.
    """
    faltantes = []
    mapeo = {}
    for col_interna, candidatos in required_cols_dict.items():
        opcional  = col_interna.startswith("?")
        col_key   = col_interna.lstrip("?")
        encontrada = find_col(df, candidatos)
        if encontrada:
            mapeo[encontrada] = col_key
        elif not opcional:
            faltantes.append(f"{col_key} (ej. {candidatos[0]})")

    if faltantes:
        _missing_msg = ", ".join(faltantes)
        log_error("validate_columns", Exception(f"Columnas faltantes en {retailer}: {_missing_msg}"))
        return None

    for col_encontrada, col_interna in mapeo.items():
        if col_encontrada in df.columns and df[col_encontrada].isna().all():
            log_error("validate_columns", Exception(f"Columna vacía '{col_encontrada}' en {retailer}"))

    df = df.rename(columns=mapeo)
    keep = [col_interna.lstrip("?") for col_interna in required_cols_dict.keys()
            if col_interna.lstrip("?") in df.columns]
    return df[keep]

def clean_text(series):
    """Limpieza vectorizada: fillna + strip + upper + espacios normalizados."""
    return (
        series.fillna("")
        .astype(str)
        .str.replace("  ", " ", regex=False)
        .str.strip()
        .str.upper()
    )

def optimize_floats(df):
    float_cols = df.columns[df.dtypes == 'float64']
    int_cols   = df.columns[df.dtypes == 'int64']
    if len(float_cols):
        df[float_cols] = df[float_cols].astype('float32')
    if len(int_cols):
        df[int_cols] = df[int_cols].astype('int32')
    df = df.convert_dtypes(convert_floating=False)
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
            df = pd.read_excel(source, engine='calamine', dtype_backend='numpy_nullable')
        except Exception:
            source.seek(0)
            df = pd.read_excel(source, engine='openpyxl')

        # BLINDAJE ESTABLE
        df.columns = [normalize_header(c) for c in df.columns]
        df = df.loc[:, ~df.columns.duplicated()]

        # BLINDAJE ESTABLE
        df.columns = [normalize_header(c) for c in df.columns]
        df = df.loc[:, ~df.columns.duplicated()]
            
        SORIANA_COLS = {
            "RESURTIMIENTO":  ["Resurtible", "Resurtible?", "RESURTIBLE"],
            "CODIGO":         ["Código de Barras Ragasa", "Codigo de Barras Ragasa",
                               "Codigo de Barras", "Codigo", "UPC", "EAN", "~BARRAS"],
            "DESCRIPCION":    ["Descripción", "Descripcion", "DESCRIPCION",
                               "Desc", "Artículo", "Articulo"],
            "NO_TIENDA":      ["No tienda", "No. Tienda", "# Tienda", "NUM TIENDA",
                               "NOTIENDA", "~^NO.*TIENDA"],
            "TIENDA":         ["Nombre Tienda", "Tienda", "TIENDA", "NOMBRE TIENDA"],
            "CIUDAD":         ["Ciudad", "CIUDAD"],
            "ESTADO":         ["Estado", "ESTADO"],
            "FORMATO":        ["Formato", "FORMATO"],
            "PEDIDOS":        ["# PEDIDOS", "PEDIDOS", "NUM PEDIDOS"],
            "FECHA_ENTREGA":  ["PROXIMA ENTREGA", "FECHA ENTREGA", "PROX ENTREGA",
                               "~PROX.*ENTREGA", "~ENTREGA"],
            "CANTIDAD_PZS":   ["CANTIDAD PROX A LLEGAR", "CANTIDAD PZS",
                               "CANT PZS", "~CANTIDAD.*LLEGAR"],
            "INV_CAJAS":      ["INV CAJAS", "INVENTARIO CAJAS", "INVENTARIO",
                               "~INV.*CAJAS"],
            "PROM_SEM_CAJAS": ["PROM SEM CAJAS", "PROM SEMANAL CAJAS",
                               "~PROM.*SEM.*CAJAS"],
            "DIAS_INV":       ["DIAS INV TENDENCIA", "DIAS INV", "DIT",
                               "~DIAS.*INV"],
            "COORDINADOR":    ["COORDINADOR", "COORDINADOR VTAS"],
            "?PROMOTOR":      ["PROMOTOR", "Promotor"],
            "?EJECUTIVO":     ["EJECUTIVO", "Ejecutivo"],
            "?TUBERIA":       ["TUBERIA CJS", "TUBERIA", "~TUBERIA"],
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
        
        if len(df.columns) < 10:
            return None
        df = validate_columns(df, "SORIANA", SORIANA_COLS)
        if df is None: return None
        
        df["CODIGO"] = df["CODIGO"].fillna("").astype(str).str.replace(r'\.0*$', '', regex=True)
        _cols_num = [c for c in ["DIAS_INV","INV_CAJAS","PROM_SEM_CAJAS","SO_$","SO_4SEM","PEDIDOS","CANTIDAD_PZS"] if c in df.columns]
        for _c in _cols_num:
            df[_c] = pd.to_numeric(df[_c], errors='coerce')
        df[_cols_num] = df[_cols_num].fillna(0)
            
        df["FECHA_ENTREGA"] = df["FECHA_ENTREGA"].fillna("").astype(str).replace("nan", "")
        df['SIN_VTA'] = (df['SO_4SEM'] == 0)
        df['VTA_PROM'] = df['SO_4SEM']
        
        df = _str_cols(df, ["RESURTIMIENTO", "NO_TIENDA", "TIENDA", "CIUDAD", "ESTADO", "FORMATO", "DESCRIPCION", "COORDINADOR"])
        
        # LIMPIEZA PROFUNDA DE TEXTOS
        df["TIENDA"] = clean_text(df["TIENDA"])
        df["ESTADO"] = clean_text(df["ESTADO"])

        # FIX: normalizar FORMATO para que apply_filters funcione correctamente
        # (antes había diferencias invisibles de espacios/mayúsculas)
        if "FORMATO" in df.columns:
            df["FORMATO"] = clean_text(df["FORMATO"])

        df["DESC_NORM"] = normalize_desc(df["DESCRIPCION"])
        return optimize_floats(df)
    except Exception as e:
        log_error("load_sor", e)
        return None

@st.cache_data(**CACHE_CONFIG)
def load_wal(path):
    try:
        source = download_file(path)
        if source is None: return None
        
        try:
            df = pd.read_excel(source, engine='calamine', dtype_backend='numpy_nullable')
        except Exception:
            source.seek(0)
            df = pd.read_excel(source, engine='openpyxl')

        # BLINDAJE ESTABLE
        df.columns = [normalize_header(c) for c in df.columns]
        df = df.loc[:, ~df.columns.duplicated()]
            
        WALMART_COLS = {
            "CODIGO":       ["UPC", "Código de Barras", "Codigo", "~^UPC"],
            "DESCRIPCION":  ["Item Desc", "Descripcion", "DESCRIPCION",
                             "~Item.*Desc"],
            "CATEGORIA":    ["Category Name", "Categoria", "CATEGORIA",
                             "~Categor"],
            "ESTADO":       ["EDO", "Estado", "ESTADO"],
            "TIENDA":       ["Store Name", "Tienda", "TIENDA",
                             "~Store.*Name"],
            "FORMATO":      ["Business Format", "Formato", "FORMATO",
                             "~Business.*Format"],
            "MARCA":        ["Marca", "MARCA", "Brand", "~[Mm]arca"],
            "DIAS_INV":     ["DDI OH", "DIAS INV", "DDI", "~DDI"],
            "EXISTENCIA":   ["OH", "Existencia", "EXISTENCIA", "Inventario",
                             "~^OH$"],
            "VTA_S1":       ["SO - 4 P", "SO-4P", "~SO.*4.*P$"],
            "VTA_S2":       ["SO - 3 P", "SO-3P", "~SO.*3.*P$"],
            "VTA_S3":       ["SO - 2 P", "SO-2P", "~SO.*2.*P$"],
            "VTA_S4":       ["SO - 1 P", "SO-1P", "~SO.*1.*P$"],
            "SO_$":         ["SO - 1 $", "SO-1$", "~SO.*1.*[$]"],
            "SO_CORRIENDO": ["Sell out Valor corriendo", "SO Corriendo",
                             "~Sell.*[Vv]alor.*corriendo"],
        }
        
        if len(df.columns) < 10:
            return None
        df = validate_columns(df, "WALMART", WALMART_COLS)
        if df is None: return None 

        df["CODIGO"] = df["CODIGO"].fillna("").astype(str).str.replace(r'\.0*$', '', regex=True)
        _cols_num = [c for c in ["DIAS_INV","EXISTENCIA","VTA_S1","VTA_S2","VTA_S3","VTA_S4","SO_$","SO_CORRIENDO"] if c in df.columns]
        for _c in _cols_num:
            df[_c] = pd.to_numeric(df[_c], errors='coerce')
        df[_cols_num] = df[_cols_num].fillna(0)
            
        df['PROM_PZS_MENSUAL'] = df[["VTA_S1", "VTA_S2", "VTA_S3", "VTA_S4"]].mean(axis=1)
        df = _str_cols(df, ["CODIGO", "DESCRIPCION", "CATEGORIA", "ESTADO", "TIENDA", "FORMATO", "MARCA"])
        
        # LIMPIEZA PROFUNDA DE TEXTOS
        df["TIENDA"] = clean_text(df["TIENDA"])
        df["ESTADO"] = clean_text(df["ESTADO"])
        df["FORMATO"] = clean_text(df["FORMATO"])
        
        df["DESC_NORM"] = normalize_desc(df["DESCRIPCION"])
        # ── CORRECCIÓN: NO convertir a category TIENDA/ESTADO/FORMATO — rompe apply_filters
        for _cat_col in ["MARCA", "CATEGORIA"]:
            if _cat_col in df.columns:
                df[_cat_col] = df[_cat_col].astype("category")
        return optimize_floats(df)
    except Exception as e:
        log_error("load_wal", e)
        return None

@st.cache_data(**CACHE_CONFIG)
def load_che(path):
    try:
        source = download_file(path)
        if source is None: return None
        
        # FIX DEFINITIVO CHEDRAUI:
        # evitar error:
        # Invalid value '' for dtype 'Int64'
        # causado por calamine + dtype_backend
        source.seek(0)
        df = pd.read_excel(source, engine='openpyxl')

        # BLINDAJE ESTABLE
        df.columns = [normalize_header(c) for c in df.columns]
        df = df.loc[:, ~df.columns.duplicated()]
        
        CHEDRAUI_COLS = {
            "CODIGO":          ["CODIGO BARRAS", "Codigo Barras", "Codigo", "UPC",
                                "CÓDIGO DE BARRAS", "~CODIGO.*BARRAS", "~BARRAS"],
            "ESTADO":          ["ESTADO", "Estado"],
            "COORDINADOR":     ["COORDINADOR VTAS", "Coordinador Vtas", "COORDINADOR",
                                "~COORDINADOR"],
            "EJECUTIVO":       ["EJECUTIVO", "Ejecutivo"],
            "PROMOTOR":        ["PROMOTOR", "Promotor"],
            "COL_FILTRO":      ["ESTATUS", "Estatus", "STATUS", "~ESTATUS"],
            "CATEGORIA":       ["CATEGORÍA", "CATEGORIA", "Categoría", "Category",
                                "~CATEG"],
            "NO_TIENDA":       ["# TDA", "NO TIENDA", "NO_TIENDA", "NUM TIENDA",
                                "NOTIENDA", "# TIENDA", "~^#.*TDA", "~^NO.*TIENDA"],
            "TIENDA":          ["TIENDA", "Tienda"],
            "ARTICULO":        ["DESCRIPCION", "DESCRIPCIÓN", "Descripcion",
                                "ARTICULO", "Sku", "SKU", "~DESCRIP"],
            # ★ CORRECCIÓN CRÍTICA: antes solo buscaba "INVENTARIO" y fallaba
            #   con "Inventario 24 Abril 2026". Ahora cubre fechas dinámicas.
            "INV_ULT_SEM":     ["Inventario 24 Abril 2026", "Inventario 17 Abril 2026",
                                "Inventario 24 Abr 2026",  "Inventario 17 Abr 2026",
                                "Inventario 10 Abr 2026",  "Inventario 3 Abr 2026",
                                "INVENTARIO", "Inventario", "~^Inventario[\\s]+[\\d]+"],
            "TRANSITO_CEDIS":  ["Transitos de cedis a tiendas",
                                "TRANSITOS DE CEDIS A TIENDAS", "TRANSITO CEDIS",
                                "Tránsitos de cedis", "~TRANSITO.*CEDIS"],
            "VTA_PROM_DIARIA": ["VENTA PROM DIARIO", "VTA PROM", "VENTA PROMEDIO",
                                "~VENTA.*PROM"],
            "DIAS_INV":        ["DIAS DE INVENTARIO", "DIAS INV", "DÍAS DE INVENTARIO",
                                "~DIAS.*INV"],
            "SELL_OUT":        ["VENTA $", "SELL OUT", "VENTA", "Venta $",
                                "~VENTA.*[$]"],
            # Opcionales — presentes en el Excel actual pero no usadas antes
            "?VTA_ULT_MES":    ["Venta Unidades Abril 2026", "Venta Unidades Mayo 2026",
                                "Venta Unidades Marzo 2026", "~Venta Unidades.*202"],
            "?VTA_MES_ANT":    ["Venta Neta en Unidades Ant. Mar 2025",
                                "Venta Neta Anterior", "~Venta Neta.*Ant"],
        }
        
        if len(df.columns) < 10:
            return None
        df = validate_columns(df, "CHEDRAUI", CHEDRAUI_COLS)
        if df is None: return None 
        
        # ── FIX: normalizar COL_FILTRO para incluir estatus 1, 0 y vacío correctamente
        if "COL_FILTRO" in df.columns:
            df["COL_FILTRO"] = df["COL_FILTRO"].fillna("").astype(str).str.strip()
        # No filtrar por COL_FILTRO — se suman todos los estatus (1, 0 y vacío)
        df = df.dropna(subset=["ARTICULO"])
        df = df[pd.to_numeric(df["NO_TIENDA"], errors='coerce').notna()]
        
        if "CODIGO" in df.columns:
            df["CODIGO"] = df["CODIGO"].fillna("").astype(str).str.replace(r'\.0*$', '', regex=True)
        else:
            df["CODIGO"] = ""
            
        _cols_num = [c for c in ["INV_ULT_SEM","TRANSITO_CEDIS","VTA_PROM_DIARIA","DIAS_INV","SELL_OUT"] if c in df.columns]
        for _c in _cols_num:
            df[_c] = pd.to_numeric(df[_c], errors='coerce')
        df[_cols_num] = df[_cols_num].fillna(0)
            
        df = _str_cols(df, ["ESTADO", "COORDINADOR", "EJECUTIVO", "PROMOTOR", "CATEGORIA", "NO_TIENDA", "TIENDA", "ARTICULO", "CODIGO"])
        
        # LIMPIEZA PROFUNDA DE TEXTOS
        df["TIENDA"] = clean_text(df["TIENDA"])
        df["ESTADO"] = clean_text(df["ESTADO"])
        
        # UNIFICACIÓN DE TIENDAS POR NÚMERO DE SUCURSAL
        if "NO_TIENDA" in df.columns:
            tienda_map = df.groupby("NO_TIENDA")["TIENDA"].first().to_dict()
            df["TIENDA"] = df["NO_TIENDA"].map(tienda_map).fillna(df["TIENDA"])
            
            estado_map = df.groupby("NO_TIENDA")["ESTADO"].first().to_dict()
            df["ESTADO"] = df["NO_TIENDA"].map(estado_map).fillna(df["ESTADO"])

        df["DESC_NORM"] = df["ARTICULO"].fillna("").str.upper().str.replace(" ", "", regex=False).str.replace("&NBSP;", "", regex=False)
        return optimize_floats(df)
    except Exception as e:
        log_error("load_che", e)
        return None


def _fre_detect_dynamic_cols(df):
    """
    Detecta automáticamente las columnas de FRESKO que cambian cada mes
    (ventas, importe, inventario) usando semántica + posición relativa.

    Estrategia:
      - Las columnas de texto fijo (ESTADO, TIENDA, etc.) se mapean por alias normales.
      - Las columnas "móviles" (Unidades venta MesX, Inventario DD MMM AAAA, IMPORTE)
        se detectan con regex independientes del mes/año/formato de fecha.
      - Cuando hay DOS columnas "Unidades venta …", la primera = VTAMZO (mes anterior),
        la segunda = VTAABR (mes en curso / al corte).
      - Si solo hay UNA columna "Unidades venta …", se asigna a VTAABR.

    Retorna un dict  col_interna → nombre_real_en_df  (o None si no encontrada).
    """
    import re as _re

    norm = {normalize_header(c): c for c in df.columns}

    def _find(pattern):
        """Devuelve la primera columna real que coincide con el regex (sobre header normalizado)."""
        for nk, real in norm.items():
            if _re.search(pattern, nk, _re.IGNORECASE):
                return real
        return None

    def _find_all(pattern):
        """Devuelve TODAS las columnas reales que coinciden, en orden de aparición."""
        matches = []
        for col in df.columns:                       # orden original
            if _re.search(pattern, normalize_header(col), _re.IGNORECASE):
                matches.append(col)
        return matches

    result = {}

    # ── columnas de unidades vendidas ──────────────────────────────────────────
    # Patrón: "Unidades" + ("venta" o "vendidas") — ignora mes, año, saltos de línea
    venta_cols = _find_all(r"unidades[\s\n]+vent")
    if len(venta_cols) >= 2:
        result["VTAMZO"] = venta_cols[0]   # mes anterior (primer bloque)
        result["VTAABR"] = venta_cols[1]   # mes en curso (segundo bloque)
    elif len(venta_cols) == 1:
        result["VTAABR"] = venta_cols[0]   # solo hay un bloque → mes en curso

    # ── importe ────────────────────────────────────────────────────────────────
    # Puede llamarse IMPORTE, Importe, "Importe venta Abr´26", "Importe Mayo 26", etc.
    result["IMPORTEABR"] = _find(r"\bimporte\b")

    # ── inventario / existencia ────────────────────────────────────────────────
    # Puede ser "Inventario 08 mayo 2026", "Inventario 24 Abr 2026", "Existencia", etc.
    result["EXISTENCIA"] = _find(r"inventario|existencia")

    # ── tránsito ───────────────────────────────────────────────────────────────
    result["TRANSITO"] = _find(r"tr[aá]nsito|transito")

    # ── promedios y días ───────────────────────────────────────────────────────
    result["VTAPROM"]  = _find(r"vta[\s_]*prom|prom[\s_]*vta|promedio[\s_]*vent")
    result["DIASINV"]  = _find(r"d[ií][aá]s?[\s_]*inv|di[\s_]*inv")

    return result   # solo incluye claves donde se encontró algo


@st.cache_data(**CACHE_CONFIG)
def load_fre(path):
    try:
        source = download_file(path)
        if source is None:
            return None
        try:
            df = pd.read_excel(source, engine="calamine")
        except Exception:
            source.seek(0)
            df = pd.read_excel(source, engine="openpyxl")

        # Eliminar filas completamente vacías
        df = df.dropna(how="all").reset_index(drop=True)

        if len(df.columns) < 10:
            return None

        # ── 1. Columnas FIJAS (no cambian entre meses) ─────────────────────────
        FRESKO_COLS_FIJOS = {
            "ANIO":        ["Año", "Anio", "AÑO", "ANIO", "~^A[NÑ]O$"],
            "MES":         ["Mes", "MES", "~^MES$"],
            "ESTADO":      ["ESTADO", "Estado", "~^ESTADO$"],
            "COORDINADOR": ["Coordinador Vtas", "Coordinador", "COORDINADOR",
                            "~COORDINAD"],
            "EJECUTIVO":   ["Ejecutivo de ventas", "Ejecutivo", "EJECUTIVO",
                            "~EJECUTIV"],
            "PROMOTOR":    ["Promotor", "PROMOTOR", "~^PROMOTOR$"],
            "FORMATO":     ["FORMATO", "Formato", "~^FORMATO$"],
            "ESTATUS":     ["ESTATUS", "Estatus", "~^ESTATUS$", "~^STATUS$"],
            "NOTIENDA":    ["# Tda", "No Tienda", "NOTIENDA", "NUM TIENDA",
                            "~^#.*TDA", "~NUM.*TIENDA", "~NO.*TIENDA"],
            "TIENDA":      ["Tienda", "TIENDA", "~^TIENDA$", "~NOMBRE.*TIENDA"],
            "CODIGO":      ["Sku", "SKU", "UPC", "Codigo", "CODIGO",
                            "~^SKU", "~^UPC", "~^CODIGO", "~^EAN"],
            "DESCRIPCION": ["Descripcion", "DESCRIPCION", "Descripción",
                            "Desc", "ARTICULO", "~^DESC", "~^ARTICULO"],
        }

        df = validate_columns(df, "FRESKO", FRESKO_COLS_FIJOS)
        if df is None:
            return None

        # ── 2. Columnas DINÁMICAS — detección semántica ────────────────────────
        # Nota: trabajamos sobre el df original para buscarlas, luego las unimos.
        source2 = download_file(path)
        try:
            df_raw = pd.read_excel(source2, engine="calamine")
        except Exception:
            source2.seek(0)
            df_raw = pd.read_excel(source2, engine="openpyxl")
        df_raw = df_raw.dropna(how="all").reset_index(drop=True)

        dynamic_map = _fre_detect_dynamic_cols(df_raw)

        col_interno_to_alias = {
            "VTAMZO":     ["VTAMZO",     "~Unidades.*[Mm]arzo",   "~Unidades.*[Aa]bril"],
            "VTAABR":     ["VTAABR",     "~Unidades.*vent"],
            "IMPORTEABR": ["IMPORTEABR", "IMPORTE",    "~[Ii]mporte"],
            "EXISTENCIA": ["EXISTENCIA", "Inventario", "~[Ii]nventar", "~[Ee]xistencia"],
            "TRANSITO":   ["TRANSITO",   "Unidades tránsito", "~[Tt]r.nsito"],
            "VTAPROM":    ["VTAPROM",    "VTA PROM",  "~VTA.*PROM"],
            "DIASINV":    ["DIASINV",    "DI INV",    "~D[IA]+S.*INV"],
        }

        for col_int, real_col in dynamic_map.items():
            if real_col is not None and real_col in df_raw.columns:
                df[col_int] = df_raw[real_col].values

        # Si alguna dinámica no se detectó, intentar con aliases legacy como último recurso
        for col_int, aliases in col_interno_to_alias.items():
            if col_int not in df.columns:
                fallback = find_col(df_raw, aliases)
                if fallback is not None:
                    df[col_int] = df_raw[fallback].values

        # ── 3. Limpieza numérica ───────────────────────────────────────────────
        for c in ["VTAMZO","VTAABR","IMPORTEABR","EXISTENCIA","TRANSITO","VTAPROM","DIASINV"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
            else:
                df[c] = 0   # garantiza que la columna siempre existe

        # ── 4. Limpieza de texto ───────────────────────────────────────────────
        if "CODIGO" in df.columns:
            # Convertir a numérico primero para manejar notación científica (ej. 8.41018e+12)
            # luego a entero y finalmente a string limpio sin decimales.
            def _clean_codigo(val):
                s = str(val).strip()
                if s in ("", "nan", "None", "NaN"):
                    return ""
                try:
                    # Maneja notación científica y decimales (.0, .00, etc.)
                    return str(int(float(s)))
                except (ValueError, OverflowError):
                    # Si no es numérico puro, limpiar solo los .0 finales
                    import re as _re
                    return _re.sub(r"\.0+$", "", s).strip()

            df["CODIGO"] = df["CODIGO"].apply(_clean_codigo)

        df = _str_cols(df, ["ESTADO","COORDINADOR","EJECUTIVO","PROMOTOR","FORMATO","ESTATUS","TIENDA","DESCRIPCION","CODIGO"])
        df["CATEGORIA"] = df["CODIGO"].astype(str).map(CATEGORIA_MAP)
        if "TIENDA"  in df.columns: df["TIENDA"]  = clean_text(df["TIENDA"])
        if "ESTADO"  in df.columns: df["ESTADO"]  = clean_text(df["ESTADO"])
        if "FORMATO" in df.columns: df["FORMATO"] = clean_text(df["FORMATO"])
        df["DESC_NORM"] = df["DESCRIPCION"].fillna("").str.upper().str.replace("\u00A0"," ",regex=False).str.replace("  "," ",regex=False)

        return optimize_floats(df)
    except Exception as e:
        log_error("load_fre", e)
        return None

@st.cache_data(ttl=1800, max_entries=3, show_spinner=False)
def _get_cached_df(key: str) -> pd.DataFrame | None:
    """Lee desde session_state — nunca re-descarga tras el startup."""
    _ss_map = {"SORIANA":"df_soriana","WALMART":"df_walmart",
               "CHEDRAUI":"df_chedraui","FRESKO":"df_fresko"}
    ss_key = _ss_map.get(key)
    if ss_key and ss_key in st.session_state:
        df = st.session_state[ss_key]
        if isinstance(df, pd.DataFrame) and not df.empty:
            return df
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

# ── Listas Ranking FRESKO ─────────────────────────────────────────────────────
_FRE_RANK_GEN = [
    "ACEITE DE SOYA NUTRIOLI BOT 850 ML","ACEITE COMESTIBLE NUTRIOLI 400 ML",
    "ACEITE COMESTIBLE SABROSANO 850 ML","ACEITE COMESTIBLE GRAN TRADICION 800 ML",
    "ACEITE NUTRIOLI PROTECT DEFENSAS 850ML","ACEITE NUTRIOLI PROTECT MENTE 850 ML",
    "ACEITE COMESTIBLE NUTRIOLI AEROSOL 180ML","ACEITE COMESTIBLE NUTRIOLI ANTIGOTEO 700",
    "ACEITE OLI OLIVA EXTRA VIRGEN PZ 250ML","ACEITE OLI OLIVA EXTRA VIRGEN PZ 500ML",
    "ACEITE OLI OLIVA EXTRA VIRGEN PZ 750ML","ADERE OLI OLIVA PARA COCINAR 500 ML OLI",
    "ADERE OLI OLIVA PARA COCINAR 750 ML OLI","ADEREZO OLI 250 ML PZ","ADEREZO OLI 500 ML BOT",
    "ACEITE COMESTIBLE AVE 850 ML","ACEITE COMESTIBLE AEROSOL 170GR",
    "ACEITE OLIVA OLI PURO SPRAY 145 ML","ACEITE OLIVA OLI EV SPRAY 145 ML",
    "PASTA FIDEO NUTRIOLI 200GR","PASTA SPAGHETTI NUTRIOLI INTEGRAL 200GR",
    "PASTA FUSILLI INTEGRAL NUTRIOLI 200GR","PASTA CODO NUTRIOLI VERDURAS 200GR",
    "PASTA FUSILLI VERDURAS NUTRIOLI 450GR","PASTA SPAGHETTI NUTRIOLI 200GR",
    "PASTA CODO NUTRIOLI 200GR","VINAGRE BALSAMICO 250ML",
]
_FRE_RANK_PAS = [
    "PASTA FIDEO NUTRIOLI 200GR","PASTA SPAGHETTI NUTRIOLI INTEGRAL 200GR",
    "PASTA FUSILLI INTEGRAL NUTRIOLI 200GR","PASTA CODO NUTRIOLI VERDURAS 200GR",
    "PASTA FUSILLI VERDURAS NUTRIOLI 450GR","PASTA SPAGHETTI NUTRIOLI 200GR",
    "PASTA CODO NUTRIOLI 200GR",
]
_FRE_RANK_OLI = [
    "ACEITE OLI OLIVA EXTRA VIRGEN PZ 250ML","ACEITE OLI OLIVA EXTRA VIRGEN PZ 500ML",
    "ACEITE OLI OLIVA EXTRA VIRGEN PZ 750ML","ADERE OLI OLIVA PARA COCINAR 500 ML OLI",
    "ADERE OLI OLIVA PARA COCINAR 750 ML OLI","ADEREZO OLI 250 ML PZ","ADEREZO OLI 500 ML BOT",
    "ACEITE OLIVA OLI PURO SPRAY 145 ML","ACEITE OLIVA OLI EV SPRAY 145 ML",
]
_FRE_RANK_NUT = [
    "ACEITE DE SOYA NUTRIOLI BOT 850 ML",
]
_FRE_RANK_BOR = [
    "BORGES ACEITE DE OLIVA EXTRA VIRGEN 500","BORGES ACEITE OLIVA EXTRA SUAVE",
    "BORGES ACEITE DE PEPITA UVA 500ML","BORGES ACEITE OLIVA 100 PURO CON AJO",
    "BORGES ACEITE OLIVA EXTRA VIRGEN ECOL","BORGES VINAGRE BALSAMICO 250ML",
    "BORGES VINAGRE DE VINOTINTO","BORGES VINAGRE VINO BLANCO",
    "ACEITE DE OLIVA A LA ALBAHACA FRESCA","ACEITE DE OLIVA AL ROMERO FRESCO",
    "ACEITE DE OLIVA AL AJO FRITO","ACEITE DE OLIVA EXTRA VIRGEN KOSHER",
    "ACEITE DE SOJA JENGIBRE","VINAGRE DE JEREZ 250 ML","VINAGRE DE SIDRA 250 ML",
    "VINAGRE DE VINO FRAMBUESA","VINAGRE DE VINO AL AJO 250 ML",
    "VINAGRE DE MANZANA ECOLOGICO","VINAGRE DE VINO DE RIOJA BOTELLA 250ML",
]


# --- 5. CARGA PARALELA DE LAS 3 BASES ---
def _download_raw(key: str) -> tuple[str, BytesIO | None, str | None]:
    try:
        buf = download_file_fast(URLS_DB[key])
        if buf is None:
            return key, None, "No se pudo descargar el archivo."
        return key, buf, None
    except Exception as e:
        log_error(f"download_raw:{key}", e)
        return key, None, str(e)

def _parse_raw(key: str, buf: BytesIO):
    try:
        loaders = {"SORIANA": load_sor, "WALMART": load_wal, "CHEDRAUI": load_che, "FRESKO": load_fre}
        buf.seek(0)
        df = loaders[key](buf)
        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            return key, None, "Archivo vacío o sin columnas válidas."
        return key, df, None
    except Exception as e:
        log_error(f"parse_raw:{key}", e)
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
    .badge-fre { background:#B3FF00 !important; color:#111111 !important; }
    .badge-fre:not(.done) { opacity:0.55 !important; }
    </style>
    """, unsafe_allow_html=True)

    placeholder  = st.empty()
    progress_bar = st.progress(0)
    status_text  = st.empty()

    def render_screen(pct, msg, done_set, phase=""):
        sor_cls = "done" if "SORIANA"  in done_set else ""
        wal_cls = "done" if "WALMART"  in done_set else ""
        che_cls = "done" if "CHEDRAUI" in done_set else ""
        fre_cls = "done" if "FRESKO"   in done_set else ""
        placeholder.markdown(f"""
        <div class="loader-wrap">
            <div class="loader-title">⚙️ Sincronizando bases de datos</div>
            <div class="loader-sub">{phase}</div>
            <div class="retailer-badges">
                <span class="badge badge-sor {sor_cls}">{'✅' if sor_cls else '⏳'} SORIANA</span>
                <span class="badge badge-wal {wal_cls}">{'✅' if wal_cls else '⏳'} WALMART</span>
                <span class="badge badge-che {che_cls}">{'✅' if che_cls else '⏳'} CHEDRAUI</span>
                <span class="badge badge-fre {fre_cls}">{'✅' if fre_cls else '⏳'} FRESKO</span>
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

    with ThreadPoolExecutor(max_workers=min(4, os.cpu_count() or 4)) as executor:
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

    with ThreadPoolExecutor(max_workers=min(4, os.cpu_count() or 4)) as executor:
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

    del raw_buffers  # liberar memoria de buffers Excel
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

    # Estado de botones ranking — 100% determinista por retailer activo
    _rank_btn   = st.session_state.get(f"rank_btn_{act}", "")
    _gen_active = _rank_btn == "GEN"
    _pas_active = _rank_btn == "PAS"
    _oli_active = _rank_btn == "OLI"
    _nut_active = _rank_btn == "NUT"


    STYLES = [
        # Navegación principal
        ("SORIANA",  "linear-gradient(135deg,#D32F2F,#B71C1C)", "#ffffff", act=="SORIANA",  "#ffffff", "rgba(255,41,0,0.85)",  False, "transparent"),
        ("WALMART",  "linear-gradient(135deg,#0071DC,#005BB5)", "#ffffff", act=="WALMART",  "#ffffff", "rgba(0,47,255,0.85)",  False, "transparent"),
        ("CHEDRAUI", "linear-gradient(135deg,#FF6600,#E65100)", "#ffffff", act=="CHEDRAUI", "#ffffff", "rgba(255,119,0,0.85)", False, "transparent"),
        ("FRESKO",   "linear-gradient(135deg,#B3FF00,#8FCC00)", "#ffffff", act=="FRESKO",   "#ffffff", "rgba(179,255,0,0.85)",  False, "transparent"),
        
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
    elif act == "FRESKO":
        _fre_neg      = st.session_state.get('fre_neg',      False)
        _fre_dias     = st.session_state.get('fre_dias',     False)
        _fre_trans    = st.session_state.get('fre_trans',    False)
        _fre_rank_bor = st.session_state.get('fre_rank_bor', False)
        STYLES.extend([
            ("📉 NEGATIVOS",           "#B71C1C", "#ffffff", _fre_neg,      "#ffffff", "rgba(183,28,28,0.85)",   False, "#EF9A9A"),
            ("📅 DIAS INV",            "#00695C", "#ffffff", _fre_dias,     "#ffffff", "rgba(0,105,92,0.85)",    False, "#80CBC4"),
            ("🚚 PEDIDOS EN TRANSITO", "#8507F0", "#ffffff", _fre_trans,    "#ffffff", "rgba(176,108,240,0.85)", False, "#CE93D8"),
            ("🍷 BORGES",              "#F0002E", "#FFFFFF", _fre_rank_bor, "#FFFFFF", "rgba(255,17,0,0.85)",    False, "transparent"),
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
            if label in ("SORIANA","WALMART","CHEDRAUI","FRESKO"):
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
            if label in ("SORIANA","WALMART","CHEDRAUI","FRESKO"):
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
.kpi-card {{ background: #ffffff; border: 1px solid #f0f0f0; border-radius: 16px;
    padding: 18px 20px; box-shadow: 0 6px 18px rgba(0,0,0,0.08); margin-bottom: 15px;
    height: 100%; display: flex; flex-direction: column; justify-content: center; }}
.kpi-title {{ font-size: 12px; color: #777; font-weight: 600; text-transform: uppercase;
    letter-spacing: 0.5px; }}
.kpi-value {{ font-size: 2rem; font-weight: 800; margin-top: 6px; word-break: break-word;
    line-height: 1.1; }}
.kpi-subtitle {{ font-size: 11px; color: #999; margin-top: 2px; }}
.kpi-amount {{ font-size: 13px; font-weight: 600; color: #444; margin-top: 8px; }}
.retailer-header {{ font-size: 1.2rem; font-weight: 800; color: white; padding: 10px 15px;
    border-radius: 8px; margin: 15px 0; text-align: center;
    box-shadow: 0 4px 6px rgba(0,0,0,0.1); text-shadow: 0 1px 2px rgba(0,0,0,0.2); }}
div[data-testid="column"] {{
    padding-top: 0px !important;
}}
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
    let restoreTimer = null;

    function saveScroll() {
        savedScroll = win.scrollY;
        restoring = true;
    }

    function restoreScroll() {
        if (!restoring) return;
        clearTimeout(restoreTimer);
        restoreTimer = setTimeout(function() {
            win.scrollTo({ top: savedScroll, behavior: "instant" });
            restoring = false;
        }, 60);
    }

    // Capturar scroll ANTES del click (mousedown es más temprano que click)
    win.document.addEventListener("mousedown", saveScroll, true);
    // También capturar en touchstart para móvil
    win.document.addEventListener("touchstart", saveScroll, true);

    // Primer click: el DOM puede no estar listo → esperar con retry
    let retryCount = 0;
    function restoreWithRetry() {
        if (!restoring) return;
        win.scrollTo({ top: savedScroll, behavior: "instant" });
        retryCount++;
        if (retryCount < 4) {
            setTimeout(restoreWithRetry, 80);
        } else {
            retryCount = 0;
            restoring = false;
        }
    }

    var _scrollTimer;
    new MutationObserver(function(mutations) {
        if (!restoring) return;
        clearTimeout(_scrollTimer);
        _scrollTimer = setTimeout(restoreWithRetry, 60);
    }).observe(win.document.body, { childList: true, subtree: true });
})();
</script>
""", height=0, scrolling=False)

# --- 9. HEADER ---
c_head1, c_head2 = st.columns([1, 5])
with c_head1:
    try:
        st.image("ragasa_logo.png", width='stretch')
    except:
        st.write("📦 Logo Ragasa")
with c_head2:
    st.markdown("""
        <div style='display:flex;flex-direction:column;justify-content:center;height:100%;'>
            <h2 style='margin:0;font-weight:800;color:#333;'>DASHBOARD DE INVENTARIOS</h2>
            <p style='margin:0;font-size:0.9rem;color:#666;'>desarrollada por Alexis</p>
        </div>""", unsafe_allow_html=True)

status_txt   = '✅ CONECTADO'
status_color = "#28a745"
st.markdown(f"<div style='text-align:right;font-size:0.7rem;color:{status_color};font-weight:bold;margin-top:-10px;margin-bottom:10px;'>● {status_txt}</div>", unsafe_allow_html=True)

# --- 10. CARGA AUTOMÁTICA PARALELA AL INICIAR ---
_df_map = {"SORIANA": "df_soriana", "WALMART": "df_walmart", "CHEDRAUI": "df_chedraui", "FRESKO": "df_fresko"}

if not st.session_state.data_loaded:
    if True:
        _keys = list(URLS_DB.keys())

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
        .badge-fre { background:#B3FF00 !important; color:#111111 !important; }
        .badge-fre:not(.done) { opacity:0.55 !important; }
        </style>
        """, unsafe_allow_html=True)

        _placeholder  = st.empty()
        _progress_bar = st.progress(0)
        _status_text  = st.empty()

        def _render(pct, msg, done_set, phase=""):
            sor_cls = "done" if "SORIANA"  in done_set else ""
            wal_cls = "done" if "WALMART"  in done_set else ""
            che_cls = "done" if "CHEDRAUI" in done_set else ""
            fre_cls = "done" if "FRESKO"   in done_set else ""
            _placeholder.markdown(f"""
            <div class="loader-wrap">
                <div class="loader-title">⚙️ Sincronizando bases de datos</div>
                <div class="loader-sub">{phase}</div>
                <div class="retailer-badges">
                    <span class="badge badge-sor {sor_cls}">{"✅" if sor_cls else "⏳"} SORIANA</span>
                    <span class="badge badge-wal {wal_cls}">{"✅" if wal_cls else "⏳"} WALMART</span>
                    <span class="badge badge-che {che_cls}">{"✅" if che_cls else "⏳"} CHEDRAUI</span>
                    <span class="badge badge-fre {fre_cls}">{"✅" if fre_cls else "⏳"} FRESKO</span>
                </div>
            </div>
            """, unsafe_allow_html=True)
            _progress_bar.progress(pct)
            _status_text.markdown(f"<p style='text-align:center;color:#555;font-size:0.9rem;'>{msg} — <b>{int(pct*100)}%</b></p>", unsafe_allow_html=True)

        _render(0.0, "Conectando a GitHub CDN…", set(), "📡 Descargando bases en paralelo")
        _errors = {}
        _done = set()
        _n = len(_keys)

        _loaders = {"SORIANA": load_sor, "WALMART": load_wal, "CHEDRAUI": load_che, "FRESKO": load_fre}

        def _load_one(k):
            try:
                buf = download_file_fast(URLS_DB[k])
                if buf is None:
                    return k, None, "Sin respuesta del servidor"
                buf.seek(0)
                df = _loaders[k](buf)
                if df is None or df.empty:
                    return k, None, "Archivo vacío"
                return k, df, None
            except Exception as e:
                return k, None, str(e)

        with ThreadPoolExecutor(max_workers=min(4, os.cpu_count() or 4)) as _ex:
            _fmap = {_ex.submit(_load_one, k): k for k in _keys}
            for _fut in as_completed(_fmap):
                _k = _fmap[_fut]
                try:
                    _k2, _df, _err = _fut.result()
                except Exception as _e:
                    _df = None
                    _err = str(_e)
                if _df is not None:
                    st.session_state[_df_map[_k]] = _df
                    _done.add(_k)
                else:
                    _errors[_k] = _err or "No se pudo cargar"
                _pct = len(_done) / _n
                _msg = f"✅ {_k} listo" if _df is not None else f"⚠️ Error en {_k}"
                _render(_pct, _msg, _done, "📡 Descargando bases en paralelo")

        _render(1.0, "¡Carga completa!", _done, "✅ Listo")
        time.sleep(0.1)
        _placeholder.empty(); _progress_bar.empty(); _status_text.empty()

        st.session_state.load_errors = _errors
        st.session_state.data_loaded = True

    try:
        for _rk in ["SORIANA","WALMART","CHEDRAUI","FRESKO"]:
            _df_pre = _get_cached_df(_rk)
            if _df_pre is None:
                continue
            _pie_key = f"pie_base_{_rk.lower()}"
            if _pie_key not in st.session_state:
                _cat_json = categorize_full_df(_df_pre.to_json(date_format='iso'), _rk)
                _pie_json = precompute_pie_base(_cat_json, _rk)
                if _pie_json:
                    st.session_state[_pie_key] = _pie_json
    except Exception:
        pass

else:
    pass  # DataFrames viven en @st.cache_data — no se duplican en session_state




if st.session_state.load_errors:
    for k, err in st.session_state.load_errors.items():
        log_error("loader_errors", Exception(f"{k}: {err}"))

# --- 11. NAVEGACIÓN ---
col1, col2, col3, col4 = st.columns(4, gap="small")
with col1: st.button("SORIANA",  on_click=set_retailer, args=("SORIANA",),  width='stretch')
with col2: st.button("WALMART",  on_click=set_retailer, args=("WALMART",),  width='stretch')
with col3: st.button("CHEDRAUI", on_click=set_retailer, args=("CHEDRAUI",), width='stretch')
with col4: st.button("FRESKO",   on_click=set_retailer, args=("FRESKO",),   width='stretch')
st.markdown("<hr style='margin:15px 0;border:0;border-top:1px solid #eee;'>", unsafe_allow_html=True)

inject_button_styles()

# --- 12. HELPER: OBTENER DATOS ---
def get_cached_or_upload(key, uploader_key, load_func):
    df_key_map = {"SORIANA": "df_soriana", "WALMART": "df_walmart", "CHEDRAUI": "df_chedraui", "FRESKO": "df_fresko"}
    ss_key = df_key_map[key]

    # FAST PATH: ya cargado en startup → retorno inmediato sin red
    df = _get_cached_df(key)
    if df is not None:
        return df

    # Descarga secundaria (startup falló) con progreso visible
    try:
        with st.status(f"⏳ Cargando {key}...", expanded=False) as _st_load:
            df = load_func(URLS_DB[key])
            if df is not None and not df.empty:
                _st_load.update(label=f"✅ {key} — {len(df):,} registros",
                                state="complete", expanded=False)
                _ss_key = {"SORIANA":"df_soriana","WALMART":"df_walmart",
                           "CHEDRAUI":"df_chedraui","FRESKO":"df_fresko"}.get(key)
                if _ss_key:
                    st.session_state[_ss_key] = df
                return df
            else:
                _st_load.update(label=f"⚠️ {key}: sin datos",
                                state="error", expanded=False)
    except Exception as _e:
        log_error(f"get_cached_or_upload retry {key}", _e)

    log_error("get_cached_or_upload", Exception(f"No se pudo cargar {key}"))
    _rc = RETAILER_COLORS.get(key, "#555555")
    st.markdown(f"<p style='color:{_rc};font-weight:800;font-size:1rem;margin-bottom:4px;'>📂 Cargar Excel {key}</p>", unsafe_allow_html=True)
    f = st.file_uploader(f"Cargar Excel {key}", type=["xlsx"], key=uploader_key, label_visibility="collapsed")
    if f:
        with st.spinner(f"Procesando {key}..."):
            df = load_func(f)
        return df
    return None

@st.cache_data(show_spinner=False, ttl=1800)
def _unique_sorted(series_hash: int, vals_tuple: tuple) -> list:
    return sorted(vals_tuple)

def _us(series) -> list:
    vals = tuple(series.dropna().unique())
    return _unique_sorted(hash(vals), vals)

# --- 13. VISTAS ---
def view_soriana(df_s):
    df_s_cat = pd.read_json(StringIO(categorize_full_df(df_s.to_json(date_format='iso'), "SORIANA")))  # @cache_data TTL 4h
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
        st.session_state['rank_btn_SORIANA'] = mode.upper()

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
            st.session_state["s_fil_nom"] = []
            st.session_state["s_fil_cd"]  = []
            st.session_state["s_fil_fmt"] = []

        def _on_nom_change():
            nom = st.session_state.get("s_fil_nom", [])
            if nom:
                _t = df_s[df_s["TIENDA"].isin(nom)]
                st.session_state["s_fil_nda"] = list(_t["NO_TIENDA"].dropna().unique())
                st.session_state["s_fil_edo"] = sorted(_t["ESTADO"].dropna().unique())
                st.session_state["s_fil_cd"]  = sorted(_t["CIUDAD"].dropna().unique())
                st.session_state["s_fil_fmt"] = sorted(_t["FORMATO"].dropna().unique())
            else:
                st.session_state["s_fil_nda"] = []
                st.session_state["s_fil_edo"] = []
                st.session_state["s_fil_cd"]  = []
                st.session_state["s_fil_fmt"] = []

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

        def _clear_sor():
            for _k in ["s_fil_nda","s_fil_nom","s_fil_edo","s_fil_cd","s_fil_fmt"]: st.session_state[_k]=[]
        if any([st.session_state.get("s_fil_nda"),st.session_state.get("s_fil_nom"),
                st.session_state.get("s_fil_edo"),st.session_state.get("s_fil_cd"),st.session_state.get("s_fil_fmt")]):
            st.button("🗑️ Borrar filtros", on_click=_clear_sor, key="btn_cls_sor", type="secondary")
        dff = apply_filters(df_s,
            ["RESURTIMIENTO","NO_TIENDA","TIENDA","CIUDAD","ESTADO","FORMATO","DESCRIPCION"],
            [fil_res if "Todos" not in fil_res else None, fil_nda, fil_nom, fil_cd, fil_edo, fil_fmt, fil_art])

        # FIX DEFINITIVO:
        # incluir FORMATO y ARTICULO en TODOS los cálculos
        # (antes KPI/gráfica ignoraban estos filtros)
        dff_graph = apply_filters(
            df_s,
            ["NO_TIENDA","TIENDA","CIUDAD","ESTADO","FORMATO","DESCRIPCION"],
            [fil_nda, fil_nom, fil_cd, fil_edo, fil_fmt, fil_art]
        )
        if dff_graph.empty and (fil_nda or fil_nom or fil_fmt):
            dff_graph = apply_filters(
                df_s,
                ["NO_TIENDA","TIENDA","FORMATO"],
                [fil_nda, fil_nom, fil_fmt]
            )
        if dff_graph.empty and fil_edo:
            dff_graph = apply_filters(df_s, ["ESTADO"], [fil_edo])
        if dff_graph.empty:
            dff_graph = df_s

        b1, b2, b3, b4 = st.columns(4, gap="small")
        with b1: st.button("🔴 INV SIN VENTA", on_click=tog_s_rojo,      width='stretch', type="primary" if s_rojo      else "secondary")
        with b2: st.button("📅 DIAS INV",      on_click=tog_s_dias_inv,  width='stretch', type="primary" if s_dias_inv  else "secondary")
        with b3: st.button("📋 DIAS X PROD",   on_click=tog_s_dias_prod, width='stretch', type="primary" if s_dias_prod else "secondary")
        with b4: st.button("🚚 PEDIDOS EN TRANSITO", on_click=tog_s_transito, width='stretch', type="primary" if s_transito else "secondary")

        dff_cat = dff_graph.merge(df_s_cat[["Category","Category_PIE"]], left_index=True, right_index=True, how="left")
        c_kpi, c_chart = st.columns([1,2])
        with c_kpi:
            total_so = dff_cat['SO_$'].sum()
            st.markdown(f"<div class='kpi-card' style='height:450px;'><div class='kpi-title'>Total Sell Out Semanal</div><div class='kpi-value' style='color:#D32F2F;'>${total_so:,.2f}</div></div>", unsafe_allow_html=True)
        with c_chart:
            # FIX:
            # FORMATO y ARTICULO también deben refrescar gráfica/KPI
            _hay_filtros_s = any([
                fil_nda,
                fil_nom,
                fil_cd,
                fil_edo,
                fil_fmt,
                fil_art
            ])
            if _hay_filtros_s:
                _cat_pie_s = "Category_PIE" if "Category_PIE" in dff_cat.columns else "Category"
                pie_df = dff_cat[[_cat_pie_s, 'SO_$']].dropna(subset=[_cat_pie_s]).groupby(_cat_pie_s)['SO_$'].sum().reset_index()
                pie_df = pie_df.rename(columns={_cat_pie_s: "Category"})
                pie_df = pie_df[pie_df['SO_$']>0]
                if pie_df.empty:
                    _pie_json_s = st.session_state.get("pie_base_soriana")
                else:
                    _pie_json_s = pie_df.to_json(date_format='iso')
            else:
                _pie_json_s = st.session_state.get("pie_base_soriana")
            if not _pie_json_s:
                _cat_pie_s2 = "Category_PIE" if "Category_PIE" in df_s_cat.columns else "Category"
                _fb = df_s_cat[[_cat_pie_s2, "SO_$"]].dropna(subset=[_cat_pie_s2]).groupby(_cat_pie_s2)["SO_$"].sum().reset_index()
                _fb = _fb.rename(columns={_cat_pie_s2: "Category"})
                _fb = _fb[_fb["SO_$"]>0]
                _pie_json_s = _fb.to_json(date_format='iso') if not _fb.empty else None
            if _pie_json_s:
                fig = build_pie_cached(_pie_json_s, "SORIANA")
                _ann = _filter_badge({"No tienda": fil_nda, "Nombre": fil_nom, "Ciudad": fil_cd, "Estado": fil_edo}, RETAILER_COLORS["SORIANA"])
                if _ann: fig.add_annotation(**_ann)
                st.plotly_chart(fig, width='stretch')
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
            st.dataframe(disp_transito.style.format({'PEDIDOS': "{:,.0f}", 'CANTIDAD EN PZS': "{:,.0f}"}), width='stretch', hide_index=True, height=auto_height(disp_transito))
            st.download_button("📥 DESCARGAR EXCEL", data=convert_df_to_excel(disp_transito), file_name="Soriana_Pedidos_Transito.xlsx", width='stretch')

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
            st.dataframe(df_prod_summary.style.format({'DIAS INV TENDENCIA':"{:,.0f}", 'SELL OUT':"${:,.2f}"}), width='stretch', hide_index=True, height=auto_height(df_prod_summary))
            st.download_button("📥 DESCARGAR EXCEL", data=convert_df_to_excel(df_prod_summary), file_name="Soriana_Dias_Producto.xlsx", width='stretch')

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
            st.dataframe(disp.style.format({'INV CAJAS':"{:,.0f}",'SELL OUT SEM':'${:,.2f}','SELL OUT ULT 4 SEM':'${:,.2f}','DIAS INV':"{:,.1f}"}), width='stretch', hide_index=True, height=auto_height(disp))
            st.download_button("📥 DESCARGAR EXCEL", data=convert_df_to_excel(disp), file_name="Soriana_Reporte_Dias.xlsx", width='stretch')

        else:
            dff_vista = dff[dff['SIN_VTA']].copy() if st.session_state.s_rojo else dff.copy()
            if st.session_state.s_rojo:
                pass
            disp = dff_vista[["NO_TIENDA","TIENDA","CODIGO","DESCRIPCION","INV_CAJAS","SO_$","SO_4SEM","DIAS_INV"]].copy()
            disp.columns=['No.','TIENDA','CODIGO','ARTICULO','INV CAJAS','SELL OUT SEM','SELL OUT ULT 4 SEM','DIAS INV']
            disp = disp.sort_values(by='SELL OUT ULT 4 SEM',ascending=False)
            st.dataframe(disp.style.format({'INV CAJAS':"{:,.0f}",'SELL OUT SEM':'${:,.2f}','SELL OUT ULT 4 SEM':'${:,.2f}','DIAS INV':"{:,.1f}"}), width='stretch', hide_index=True, height=auto_height(disp))
            st.download_button("📥 DESCARGAR EXCEL", data=convert_df_to_excel(disp), file_name="Soriana_General.xlsx", width='stretch')

        st.divider()
        st.markdown("<h3 style='text-align:center;color:#444;'>🏆 RANKING DE VENTAS</h3>", unsafe_allow_html=True)
        sm1,sm2 = st.columns(2)
        with sm1: sel_s_rank_st  = st.multiselect("Estado (Ranking)",  _us(df_s["ESTADO"]),  key="s_rnk_st", placeholder="Seleccionar...")
        with sm2: sel_s_rank_fmt = st.multiselect("Formato (Ranking)", _us(df_s["FORMATO"]), key="s_rnk_fmt", placeholder="Seleccionar...")
        sr1,sr2,sr3,sr4 = st.columns(4,gap="small")
        with sr1: st.button("📊 GENERAL",  on_click=set_s_rank, args=('GEN',), width='stretch', type="primary" if s_rank_gen else "secondary")
        with sr2: st.button("🍝 PASTAS",   on_click=set_s_rank, args=('PAS',), width='stretch', type="primary" if s_rank_pas else "secondary")
        with sr3: st.button("🫒 OLIVAS",   on_click=set_s_rank, args=('OLI',), width='stretch', type="primary" if s_rank_oli else "secondary")
        with sr4: st.button("🍃 NUTRIOLI", on_click=set_s_rank, args=('NUT',), width='stretch', type="primary" if s_rank_nut else "secondary")

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
                st.dataframe(final_s_rank.style.format({rank_title_s:"${:,.2f}"}), width='stretch', hide_index=True, height=auto_height(final_s_rank))
                st.download_button("📥 DESCARGAR EXCEL", data=convert_df_to_excel(final_s_rank), file_name="Soriana_Ranking.xlsx", width='stretch')
            

def view_walmart(df_w):
    df_w_cat = pd.read_json(StringIO(categorize_full_df(df_w.to_json(date_format='iso'), "WALMART")))  # @cache_data TTL 4h
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
        _btn_map = {'tiendas':'GEN','pastas':'PAS','olivas':'OLI','nutrioli':'NUT'}
        st.session_state['rank_btn_WALMART'] = _btn_map.get(mode, 'GEN')

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

        def _clear_wal():
            for _k in ["w_fil_store","w_fil_state","w_fil_fmt"]: st.session_state[_k]=[]
        if any([st.session_state.get("w_fil_store"),st.session_state.get("w_fil_state"),st.session_state.get("w_fil_fmt")]):
            st.button("🗑️ Borrar filtros", on_click=_clear_wal, key="btn_cls_wal", type="secondary")
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
        with b1: st.button("📉 NEGATIVOS",    on_click=tog_w, args=('w_neg',),       width='stretch', type="primary" if w_neg      else "secondary")
        with b2: st.button("🔴 SIN VTA 4SEM", on_click=tog_w, args=('w_4w',),        width='stretch', type="primary" if w_4w       else "secondary")
        with b3: st.button("📅 DIAS INV",     on_click=tog_w, args=('w_dias_inv',),  width='stretch', type="primary" if w_dias_inv  else "secondary")
        with b4: st.button("📋 DIAS X PROD",  on_click=tog_w, args=('w_dias_prod',), width='stretch', type="primary" if w_dias_prod else "secondary")

        if st.session_state.w_neg: dff=dff[dff["EXISTENCIA"]<0]
        if st.session_state.w_4w:  dff=dff[(dff["VTA_S1"]==0)&(dff["VTA_S2"]==0)&(dff["VTA_S3"]==0)&(dff["VTA_S4"]==0)]

        dff_cat = dff_graph.merge(df_w_cat[["Category","Category_PIE"]], left_index=True, right_index=True, how="left")
        c_kpi,c_chart = st.columns([1,2])
        total_so = dff_cat['SO_$'].sum()
        with c_kpi:
            st.markdown(f"<div class='kpi-card' style='height:450px;'><div class='kpi-title'>Total Sell Out</div><div class='kpi-value' style='color:#28a745;'>${total_so:,.2f}</div></div>", unsafe_allow_html=True)
        with c_chart:
            _hay_filtros_w = any([sel_store, sel_state, sel_fmt])
            if _hay_filtros_w:
                _cat_pie_w = "Category_PIE" if "Category_PIE" in dff_cat.columns else "Category"
                pie_df = dff_cat[[_cat_pie_w, 'SO_$']].dropna(subset=[_cat_pie_w]).groupby(_cat_pie_w)['SO_$'].sum().reset_index()
                pie_df = pie_df.rename(columns={_cat_pie_w: "Category"})
                pie_df = pie_df[pie_df['SO_$']>0]
                if pie_df.empty:
                    _pie_json_w = st.session_state.get("pie_base_walmart")
                else:
                    _pie_json_w = pie_df.to_json(date_format='iso')
            else:
                _cat_pie_w2 = "Category_PIE" if "Category_PIE" in df_w_cat.columns else "Category"
                _fb = df_w_cat.dropna(subset=[_cat_pie_w2]).copy()
                _fb = _fb.loc[_fb.index.isin(df_w.index)]
                _fb = _fb[[_cat_pie_w2, "SO_$"]].groupby(_cat_pie_w2)["SO_$"].sum().reset_index()
                _fb = _fb.rename(columns={_cat_pie_w2: "Category"})
                _fb = _fb[_fb["SO_$"]>0]
                _pie_json_w = _fb.to_json(date_format='iso') if not _fb.empty else None

            if _pie_json_w:
                fig = build_pie_cached(_pie_json_w, "WALMART")
                _ann = _filter_badge({"Tienda": sel_store, "Estado": sel_state, "Formato": sel_fmt}, RETAILER_COLORS["WALMART"])
                if _ann: fig.add_annotation(**_ann)
                st.plotly_chart(fig, width='stretch')
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
            st.dataframe(df_ps.style.format({'DIAS DE INV':"{:,.1f}",'SELL OUT':"${:,.2f}"}), width='stretch', hide_index=True, height=auto_height(df_ps))
            st.download_button("📥 DESCARGAR EXCEL", data=convert_df_to_excel(df_ps), file_name="Walmart_Dias_Producto.xlsx", width='stretch')

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
            st.dataframe(disp_w_dias.style.format({'DIAS INVENTARIO':"{:,.1f}"}), width='stretch', hide_index=True, height=auto_height(disp_w_dias))
            st.download_button("📥 DESCARGAR EXCEL", data=convert_df_to_excel(disp_w_dias), file_name="Walmart_Reporte_Dias.xlsx", width='stretch')

        elif st.session_state.w_neg:
            st.subheader("📉 Vista: Inventarios Negativos")
            disp_neg = dff[["CODIGO", "DESCRIPCION", "TIENDA", "EXISTENCIA", "SO_$"]].copy()
            disp_neg.columns = ["CODIGO", "DESCRIPCION", "TIENDA", "INVENTARIO", "SELL OUT"]
            disp_neg = disp_neg.sort_values(by="INVENTARIO", ascending=True)
            st.dataframe(disp_neg.style.format({'INVENTARIO':"{:,.0f}", 'SELL OUT':'${:,.2f}'}), width='stretch', hide_index=True, height=auto_height(disp_neg))
            
            c_btn1, c_btn2 = st.columns(2)
            with c_btn1:
                st.download_button("📥 DESCARGAR EXCEL", data=convert_df_to_excel(disp_neg), file_name="Walmart_Negativos.xlsx", width='stretch')
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
            st.dataframe(disp.style.format({'SELL OUT':'${:,.2f}','PROM PZS MENSUAL':'{:,.2f}'}), width='stretch', hide_index=True, height=auto_height(disp))
            st.download_button("📥 DESCARGAR EXCEL", data=convert_df_to_excel(disp), file_name="Walmart_General.xlsx", width='stretch')

        st.divider()
        st.markdown("<h3 style='text-align:center;color:#444;'>🏆 RANKING DE VENTAS</h3>", unsafe_allow_html=True)
        cm1,cm2 = st.columns(2)
        with cm1: sel_st_rank  = st.multiselect("Estado (Ranking)",  _us(df_w["ESTADO"]),  key="rnk_st", placeholder="Seleccionar...")
        with cm2: sel_fmt_rank = st.multiselect("Formato (Ranking)", _us(df_w["FORMATO"]), key="rnk_fmt", placeholder="Seleccionar...")
        sr1,sr2,sr3,sr4 = st.columns(4,gap="small")
        with sr1: st.button("📊 GENERAL",  on_click=set_rank, args=('tiendas',),  width='stretch', type="primary" if w_rank_tiendas else "secondary")
        with sr2: st.button("🍝 PASTAS",   on_click=set_rank, args=('pastas',),   width='stretch', type="primary" if w_rank_pastas  else "secondary")
        with sr3: st.button("🫒 OLIVAS",   on_click=set_rank, args=('olivas',),   width='stretch', type="primary" if w_rank_olivas  else "secondary")
        with sr4: st.button("🏆 NUTRIOLI", on_click=set_rank, args=('nutrioli',), width='stretch', type="primary" if w_nutri_top10  else "secondary")

        dff_rank = apply_filters(df_w,["ESTADO","FORMATO"],[sel_st_rank,sel_fmt_rank])
        # ── CORRECCIÓN: eliminar filas con SO_$ = 0 Y EXISTENCIA = 0 del ranking
        if "SO_$" in dff_rank.columns and "EXISTENCIA" in dff_rank.columns:
            dff_rank = dff_rank[(dff_rank["SO_$"] > 0) | (dff_rank["EXISTENCIA"] > 0)]
        elif "SO_$" in dff_rank.columns:
            dff_rank = dff_rank[dff_rank["SO_$"] > 0]
        final_rank = None
        if st.session_state.w_rank_tiendas:
            final_rank = dff_rank.groupby("TIENDA")['SO_$'].sum().reset_index().rename(columns={'SO_$':'VENTA TOTAL ($)'})
        elif st.session_state.w_rank_pastas:
            df_sub = dff_rank[dff_rank["CATEGORIA"].str.contains("PASTAS",na=False)]
            if not df_sub.empty: final_rank = df_sub.groupby("TIENDA")['SO_$'].sum().reset_index().rename(columns={'SO_$':'VENTA PASTAS ($)'})
        elif st.session_state.w_rank_olivas:
            # FIX: filtro preciso línea OLI — DESC_NORM empieza con "OLI" O contiene "OLIVA"
            # Corrige bug donde NUTRIOLI soya (946ML, 400ML, ANTIGOTEO, etc.) se sumaba
            # en el ranking de Olivas por compartir las letras "OLI" en su nombre normalizado
            _dn = dff_rank["DESC_NORM"]
            df_sub = dff_rank[_dn.str.startswith("OLI", na=False) | _dn.str.contains("OLIVA", na=False)]
            if not df_sub.empty: final_rank = df_sub.groupby("TIENDA")['SO_$'].sum().reset_index().rename(columns={'SO_$':'VENTA OLIVAS ($)'})
        elif st.session_state.w_nutri_top10:
            # ── CORRECCIÓN: filtro EXCLUSIVAMENTE por columna FORMATO (eliminado OR con prefijo tienda)
            # Normalizar a str para evitar bug de category dtype
            _base_nutri = df_w.copy()
            for _col in ["ESTADO", "FORMATO", "TIENDA"]:
                if _col in _base_nutri.columns:
                    _base_nutri[_col] = _base_nutri[_col].astype(str).str.strip().str.upper()

            # Filtrar Estado
            if sel_st_rank:
                _sel_estados = [s.strip().upper() for s in sel_st_rank]
                _base_nutri = _base_nutri[_base_nutri["ESTADO"].isin(_sel_estados)]

            # Filtrar Formato — SOLO por columna FORMATO (no OR con prefijo de tienda)
            if sel_fmt_rank:
                _sel_fmt = [f.strip().upper() for f in sel_fmt_rank]
                _base_nutri = _base_nutri[_base_nutri["FORMATO"].isin(_sel_fmt)]

            _desc_up = _base_nutri["DESCRIPCION"].astype(str).str.upper().str.strip()
            _mask_946 = (
                _desc_up.str.contains("946", na=False) &
                _desc_up.str.contains("NUTRIOLI", na=False) &
                ~_desc_up.str.contains(r"\+", na=False)
            )
            df_sub = _base_nutri[_mask_946]
            if df_sub.empty:
                df_sub = _base_nutri[
                    _desc_up.str.contains("946", na=False) &
                    _desc_up.str.contains("NUTRIOLI", na=False)
                ]

            # ── CORRECCIÓN: eliminar filas con SO_$ = 0 Y EXISTENCIA = 0
            if not df_sub.empty:
                _has_so    = "SO_$"       in df_sub.columns
                _has_exist = "EXISTENCIA" in df_sub.columns
                if _has_so and _has_exist:
                    df_sub = df_sub[(df_sub["SO_$"] > 0) | (df_sub["EXISTENCIA"] > 0)]
                elif _has_so:
                    df_sub = df_sub[df_sub["SO_$"] > 0]

            if not df_sub.empty:
                _grp_cols = ["TIENDA","DESCRIPCION"]
                if not sel_fmt_rank or len(sel_fmt_rank) != 1:
                    _grp_cols = ["FORMATO"] + _grp_cols
                _nutri_agg_cols = [c for c in ["EXISTENCIA","SO_SEM_ANT","SO_$"] if c in df_sub.columns]
                final_rank = df_sub.groupby(_grp_cols)[_nutri_agg_cols].sum().reset_index()
                _rename = {"FORMATO":"FORMATO","TIENDA":"TIENDA","DESCRIPCION":"PRODUCTO"}
                _nutri_col_names = [_rename.get(c,c) for c in _grp_cols]
                if "EXISTENCIA"  in _nutri_agg_cols: _nutri_col_names.append("INVENTARIO")
                if "SO_SEM_ANT"  in _nutri_agg_cols: _nutri_col_names.append("VTA SEM ANTERIOR ($)")
                if "SO_$"        in _nutri_agg_cols: _nutri_col_names.append("SELL OUT ($)")
                final_rank.columns = _nutri_col_names
        if final_rank is not None:
            sort_col = final_rank.columns[-1]
            final_rank = final_rank.sort_values(by=sort_col,ascending=False)
            fmt_dict = {c:"${:,.2f}" for c in final_rank.columns if "($)" in c or "$" in c}
            if "INVENTARIO" in final_rank.columns: fmt_dict["INVENTARIO"]="{:,.0f}"
            st.dataframe(final_rank.style.format(fmt_dict), width='stretch', hide_index=True, height=auto_height(final_rank))
            st.download_button("📥 DESCARGAR EXCEL", data=convert_df_to_excel(final_rank), file_name="Walmart_Ranking.xlsx", width='stretch')

def view_chedraui(df_c):
    df_c_cat = pd.read_json(StringIO(categorize_full_df(df_c.to_json(date_format='iso'), "CHEDRAUI")))  # @cache_data TTL 4h
    st.markdown(f"<div class='retailer-header' style='background-color:{RETAILER_COLORS['CHEDRAUI']}'>CHEDRAUI</div>", unsafe_allow_html=True)

    def tog_c(target):
        for v in ['c_neg_zero','c_dias_inv','c_transito']:
            st.session_state[v] = True if v==target and not st.session_state[v] else False
    def set_c_rank(mode):
        for v in ['c_rank_gen','c_rank_pas','c_rank_oli','c_rank_nut']: st.session_state[v]=False
        st.session_state[f'c_rank_{mode.lower()}']=True
        st.session_state['rank_btn_CHEDRAUI'] = mode.upper()

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

        def _clear_che():
            for _k in ["c_fil_no","c_fil_ti","c_fil_ed"]: st.session_state[_k]=[]
        if any([st.session_state.get("c_fil_no"),st.session_state.get("c_fil_ti"),st.session_state.get("c_fil_ed")]):
            st.button("🗑️ Borrar filtros", on_click=_clear_che, key="btn_cls_che", type="secondary")
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
        with b1: st.button("📉 NEGATIVOS",         on_click=tog_c, args=('c_neg_zero',), width='stretch', type="primary" if c_neg_zero   else "secondary")
        with b2: st.button("📅 DIAS INV",           on_click=tog_c, args=('c_dias_inv',), width='stretch', type="primary" if c_dias_inv   else "secondary")
        with b3: st.button("🚚 PEDIDOS EN TRANSITO",on_click=tog_c, args=('c_transito',), width='stretch', type="primary" if c_transito_c else "secondary")

        dff_cat = dff_graph.merge(df_c_cat[["Category","Category_PIE"]], left_index=True, right_index=True, how="left")
        c_kpi,c_chart = st.columns([1,2])
        with c_kpi:
            total_so = dff_cat['SELL_OUT'].sum()
            st.markdown(f"<div class='kpi-card' style='height:450px;'><div class='kpi-title'>Total Sell Out</div><div class='kpi-value' style='color:#FF6600;'>${total_so:,.2f}</div></div>", unsafe_allow_html=True)
        with c_chart:
            _hay_filtros_c = any([fil_no, fil_ti, fil_ed])
            if _hay_filtros_c:
                _cat_pie_c = "Category_PIE" if "Category_PIE" in dff_cat.columns else "Category"
                pie_df = dff_cat[[_cat_pie_c, 'SELL_OUT']].dropna(subset=[_cat_pie_c]).groupby(_cat_pie_c)['SELL_OUT'].sum().reset_index()
                pie_df = pie_df.rename(columns={_cat_pie_c: "Category"})
                pie_df = pie_df[pie_df['SELL_OUT']>0]
                if pie_df.empty:
                    _pie_json_c = st.session_state.get("pie_base_chedraui")
                else:
                    _pie_json_c = pie_df.to_json(date_format='iso')
            else:
                _pie_json_c = st.session_state.get("pie_base_chedraui")
            if not _pie_json_c:
                _cat_pie_c2 = "Category_PIE" if "Category_PIE" in df_c_cat.columns else "Category"
                _fb = df_c_cat[[_cat_pie_c2, "SELL_OUT"]].dropna(subset=[_cat_pie_c2]).groupby(_cat_pie_c2)["SELL_OUT"].sum().reset_index()
                _fb = _fb.rename(columns={_cat_pie_c2: "Category"})
                _fb = _fb[_fb["SELL_OUT"]>0]
                _pie_json_c = _fb.to_json(date_format='iso') if not _fb.empty else None
            if _pie_json_c:
                fig = build_pie_cached(_pie_json_c, "CHEDRAUI")
                _ann = _filter_badge({"No tienda": fil_no, "Tienda": fil_ti, "Estado": fil_ed}, RETAILER_COLORS["CHEDRAUI"])
                if _ann: fig.add_annotation(**_ann)
                st.plotly_chart(fig, width='stretch')
            else: st.info("Sin datos para gráfica.")

        if st.session_state.get('c_transito'):
            st.subheader("🚚 Pedidos en Tránsito — Cédis a Tiendas")
            if "TRANSITO_CEDIS" in dff.columns:
                dff_transito_c = dff[dff["TRANSITO_CEDIS"] > 0].copy()
                if not dff_transito_c.empty:
                    disp_tc = dff_transito_c[["ESTADO","NO_TIENDA","TIENDA","ARTICULO","INV_ULT_SEM","TRANSITO_CEDIS"]].copy()
                    disp_tc.columns = ["ESTADO","NO TIENDA","TIENDA","ARTÍCULO","INVENTARIO","TRÁNSITO CEDIS"]
                    st.dataframe(disp_tc.style.format({"INVENTARIO":"{:,.0f}","TRÁNSITO CEDIS":"{:,.0f}"}),
                                 width='stretch', hide_index=True, height=auto_height(disp_tc))
                else:
                    st.info("✅ No hay pedidos en tránsito para los filtros seleccionados.")
            else:
                log_error("view_chedraui", Exception("Columna transitos no encontrada"))

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
            
            # ── FIX 2: incluir columna CATEGORIA (con BORGES) en Excel exportado
            _dff_cat_merge = dff.merge(df_c_cat[["Category"]], left_index=True, right_index=True, how="left")
            disp=_dff_cat_merge[["NO_TIENDA","TIENDA","ARTICULO","Category","INV_ULT_SEM","VTA_PROM_DIARIA","DIAS_INV","SELL_OUT"]].copy()
            disp.columns=['NO_TIENDA','TIENDA','ARTICULO','CATEGORIA','INV_ULT_SEM','VTA_PROM_DIARIA','DIAS_INV','SELL_OUT']
            st.dataframe(disp.style.format({'INV_ULT_SEM':"{:,.0f}",'VTA_PROM_DIARIA':"{:,.2f}",'DIAS_INV':"{:,.1f}",'SELL_OUT':"${:,.2f}"}), width='stretch', hide_index=True, height=auto_height(disp))
            st.download_button("📥 DESCARGAR EXCEL", data=convert_df_to_excel(disp), file_name="Chedraui_Dias_Inventario.xlsx", width='stretch')

        elif st.session_state.c_neg_zero:
            dff_neg = dff[dff["INV_ULT_SEM"]<0].copy()
            st.subheader("📉 Vista: Inventarios Negativos")
            disp_neg = dff_neg[["CODIGO", "ARTICULO", "TIENDA", "INV_ULT_SEM", "SELL_OUT"]].copy()
            disp_neg.columns = ["CODIGO", "DESCRIPCION", "TIENDA", "INVENTARIO", "SELL OUT"]
            disp_neg = disp_neg.sort_values(by="INVENTARIO", ascending=True)
            st.dataframe(disp_neg.style.format({'INVENTARIO':"{:,.0f}", 'SELL OUT':'${:,.2f}'}), width='stretch', hide_index=True, height=auto_height(disp_neg))
            
            c_btn1, c_btn2 = st.columns(2)
            with c_btn1:
                st.download_button("📥 DESCARGAR EXCEL", data=convert_df_to_excel(disp_neg), file_name="Chedraui_Negativos.xlsx", width='stretch')
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
            pass  # vista completa
            # ── FIX 2: incluir columna CATEGORIA (con BORGES) en Excel exportado
            _dff_cat_merge2 = dff.merge(df_c_cat[["Category"]], left_index=True, right_index=True, how="left")
            disp=_dff_cat_merge2[["NO_TIENDA","TIENDA","ARTICULO","Category","INV_ULT_SEM","VTA_PROM_DIARIA","DIAS_INV","SELL_OUT"]].copy()
            disp.columns=['NO_TIENDA','TIENDA','ARTICULO','CATEGORIA','INV_ULT_SEM','VTA_PROM_DIARIA','DIAS_INV','SELL_OUT']
            st.dataframe(disp.style.format({'INV_ULT_SEM':"{:,.0f}",'VTA_PROM_DIARIA':"{:,.2f}",'DIAS_INV':"{:,.1f}",'SELL_OUT':"${:,.2f}"}), width='stretch', hide_index=True, height=auto_height(disp))
            st.download_button("📥 DESCARGAR EXCEL", data=convert_df_to_excel(disp), file_name="Chedraui_General.xlsx", width='stretch')

        st.divider()
        st.markdown("<h3 style='text-align:center;color:#444;'>🏆 RANKING DE VENTAS</h3>", unsafe_allow_html=True)
        sel_st_rank = st.selectbox("Filtrar Estado (Ranking)", ["Todos"]+_us(df_c["ESTADO"]), key="c_rnk_st")
        cr1,cr2,cr3,cr4 = st.columns(4,gap="small")
        with cr1: st.button("📊 GENERAL",  on_click=set_c_rank, args=('GEN',), width='stretch', type="primary" if c_rank_gen else "secondary")
        with cr2: st.button("🍝 PASTAS",   on_click=set_c_rank, args=('PAS',), width='stretch', type="primary" if c_rank_pas else "secondary")
        with cr3: st.button("🫒 OLIVAS",   on_click=set_c_rank, args=('OLI',), width='stretch', type="primary" if c_rank_oli else "secondary")
        with cr4: st.button("🍃 NUTRIOLI", on_click=set_c_rank, args=('NUT',), width='stretch', type="primary" if c_rank_nut else "secondary")

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
                st.dataframe(final_c_rank.style.format({rank_title:"${:,.2f}"}), width='stretch', hide_index=True, height=auto_height(final_c_rank))
                st.download_button("📥 DESCARGAR EXCEL", data=convert_df_to_excel(final_c_rank), file_name="Chedraui_Ranking.xlsx", width='stretch')
            


# ──────────────────────────────────────────────────────────────────────────────
# VISTA FRESKO
# ──────────────────────────────────────────────────────────────────────────────

def format_fresko_export(df):
    try:
        columnas_orden = [
            ("NOTIENDA",    "# Tda"),
            ("TIENDA",      "Tienda"),
            ("CODIGO",      "Sku"),
            ("DESCRIPCION", "Descripcion"),
            ("EXISTENCIA",  "INVENTARIO"),
            ("VTAMZO",      "VENTA MES ANTERIOR"),
            ("VTAABR",      "U VENTA AL CORTE"),
            ("IMPORTEABR",  "IMPORTE"),
            ("TRANSITO",    "Unidades tránsito"),
            ("VTAPROM",     "VTA PROM"),
            ("DIASINV",     "DI INV"),
        ]
        # Garantizar orden exacto; si falta columna se pone en 0
        for col, _ in columnas_orden:
            if col not in df.columns:
                df[col] = 0
        df = df[[c[0] for c in columnas_orden]].copy()
        rename_dict = {k: v for k, v in columnas_orden}
        df = df.rename(columns=rename_dict)
        return df
    except Exception as e:
        log_error("format_fresko_export", e)
        return df

def view_fresko(df_f):

    # ── 1. NORMALIZAR DATA ────────────────────────────────────────────────────
    df_f = df_f.copy()
    for _c in ["NOTIENDA","TIENDA","ESTADO","FORMATO","COORDINADOR","EJECUTIVO","PROMOTOR"]:
        if _c in df_f.columns:
            df_f[_c] = df_f[_c].astype(str).str.strip().str.upper()
    _desc_col = next((c for c in ["DESCRIPCION","ARTICULO"] if c in df_f.columns), None)
    if _desc_col:
        df_f[_desc_col] = df_f[_desc_col].astype(str).str.strip().str.upper()

    # ── 2. INICIALIZACIÓN DE SESSION STATE ────────────────────────────────────
    _FKEYS = ["f_fil_tda","f_fil_ti","f_fil_ed","f_fil_fmt",
              "f_fil_crd","f_fil_ej","f_fil_pr","f_fil_cat","f_fil_art"]
    for _k in _FKEYS:
        if _k not in st.session_state:
            st.session_state[_k] = []

    # ── 2b. AUTO-FILL: al cambiar #Tienda o Tienda rellena los demás filtros ──
    def _auto_fill_from(col_filter: str, col_key: str, fill_map: list):
        """Detecta si cambió col_key y rellena automáticamente los campos de fill_map."""
        _curr     = st.session_state.get(col_key, [])
        _prev_key = f"_prev_{col_key}"
        _prev     = st.session_state.get(_prev_key, [])
        if set(_curr) != set(_prev):
            st.session_state[_prev_key] = list(_curr)
            # Limpiar ejecutivo para evitar que un valor residual bloquee los datos
            st.session_state["f_fil_ej"] = []
            if _curr and col_filter in df_f.columns:
                _sub = df_f[df_f[col_filter].isin(set(_curr))]
                if not _sub.empty:
                    for _acol, _akey in fill_map:
                        if _acol in _sub.columns:
                            st.session_state[_akey] = sorted(
                                _sub[_acol].dropna().unique().tolist()
                            )

    # Auto-fill desde # Tienda (NOTIENDA) → rellena Estado, Tienda, Formato, Coordinador, Promotor
    # NOTA: EJECUTIVO se excluye del auto-fill porque puede variar por registro dentro
    # de una misma tienda; si se fuerza, el filtro posterior elimina datos válidos.
    _auto_fill_from("NOTIENDA", "f_fil_tda", [
        ("ESTADO",      "f_fil_ed"),
        ("TIENDA",      "f_fil_ti"),
        ("FORMATO",     "f_fil_fmt"),
        ("COORDINADOR", "f_fil_crd"),
        ("PROMOTOR",    "f_fil_pr"),
    ])

    # Auto-fill desde Tienda nombre → rellena #Tienda, Estado, Formato, Coordinador, Promotor
    # NOTA: EJECUTIVO se excluye del auto-fill — ver nota anterior.
    _auto_fill_from("TIENDA", "f_fil_ti", [
        ("NOTIENDA",    "f_fil_tda"),
        ("ESTADO",      "f_fil_ed"),
        ("FORMATO",     "f_fil_fmt"),
        ("COORDINADOR", "f_fil_crd"),
        ("PROMOTOR",    "f_fil_pr"),
    ])

    # ── 3. CASCADEO BIDIRECCIONAL ─────────────────────────────────────────────
    # Columnas que participan en el cascadeo (en orden de jerarquía natural)
    _CASCADE_PAIRS = [
        ("NOTIENDA",    "f_fil_tda"),
        ("ESTADO",      "f_fil_ed"),
        ("TIENDA",      "f_fil_ti"),
        ("FORMATO",     "f_fil_fmt"),
        ("COORDINADOR", "f_fil_crd"),
        ("EJECUTIVO",   "f_fil_ej"),
        ("PROMOTOR",    "f_fil_pr"),
    ]

    def get_scope_excluding(exclude_key: str) -> pd.DataFrame:
        """
        Devuelve el df filtrado por TODOS los filtros activos
        EXCEPTO el del filtro `exclude_key`.
        Esto permite calcular las opciones disponibles para ese filtro
        dado el resto de selecciones activas (cascadeo real bidireccional).
        """
        dff = df_f.copy()
        for col, key in _CASCADE_PAIRS:
            if key == exclude_key:
                continue
            vals = st.session_state.get(key, [])
            if vals and col in dff.columns:
                dff = dff[dff[col].isin(set(vals))]
        return dff

    def get_all_filtered() -> pd.DataFrame:
        """df filtrado por TODOS los filtros activos (para el scope de Artículo y datos)."""
        dff = df_f.copy()
        for col, key in _CASCADE_PAIRS:
            vals = st.session_state.get(key, [])
            if vals and col in dff.columns:
                dff = dff[dff[col].isin(set(vals))]
        return dff

    def cascade_default(options: list, key: str) -> list:
        """
        Lógica de default para cada multiselect con cascadeo:
        - Si hay exactamente 1 opción disponible → auto-seleccionar (Power BI style).
        - Si el usuario ya tenía selección manual con 2+ items → respetar sin forzar.
        - Si hay cascadeo que resulta en 2+ opciones → mostrar opciones disponibles
          pero NO forzar selección (el usuario elige). Los valores previos válidos
          se mantienen si aún están en las opciones.
        """
        current = st.session_state.get(key, [])
        valid_set = set(options)
        # Si hay exactamente 1 opción, auto-seleccionar siempre
        if len(options) == 1:
            return options
        # Mantener solo los valores actuales que siguen siendo válidos
        valid_current = [v for v in current if v in valid_set]
        return valid_current

    # ── 4. HEADER ─────────────────────────────────────────────────────────────
    st.markdown(
        "<div style='background:linear-gradient(135deg,#B3FF00,#8FCC00);"
        "border-radius:10px;padding:10px 18px;font-weight:700;color:#1a1a1a;"
        "font-size:1.1rem;margin-bottom:12px;'>🟢 FRESKO</div>",
        unsafe_allow_html=True
    )

    # ── 5. BOTÓN BORRAR — ANTES de widgets (evita StreamlitAPIException) ──────
    hay_filtros = any(st.session_state.get(k) for k in _FKEYS)
    if hay_filtros:
        if st.button("🗑️ Borrar filtros", key="btn_cls_fre", type="secondary"):
            for _k in _FKEYS:
                st.session_state[_k] = []
            # Limpiar claves de seguimiento para que el auto-fill se dispare en la siguiente selección
            for _pk in ["_prev_f_fil_tda", "_prev_f_fil_ti"]:
                if _pk in st.session_state:
                    del st.session_state[_pk]
            st.rerun()

    # ── 6. CALCULAR OPCIONES POR CASCADEO BIDIRECCIONAL ───────────────────────
    # Para cada filtro, las opciones se calculan excluyendo su propio filtro
    # pero aplicando todos los demás → cascadeo verdadero en cualquier dirección.
    tda_opts = sorted(get_scope_excluding("f_fil_tda")["NOTIENDA"].dropna().unique().tolist())    if "NOTIENDA"    in df_f.columns else []
    ed_opts  = sorted(get_scope_excluding("f_fil_ed")["ESTADO"].dropna().unique().tolist())       if "ESTADO"      in df_f.columns else []
    ti_opts  = sorted(get_scope_excluding("f_fil_ti")["TIENDA"].dropna().unique().tolist())       if "TIENDA"      in df_f.columns else []
    fmt_opts = sorted(get_scope_excluding("f_fil_fmt")["FORMATO"].dropna().unique().tolist())     if "FORMATO"     in df_f.columns else []
    crd_opts = sorted(get_scope_excluding("f_fil_crd")["COORDINADOR"].dropna().unique().tolist()) if "COORDINADOR" in df_f.columns else []
    ej_opts  = sorted(get_scope_excluding("f_fil_ej")["EJECUTIVO"].dropna().unique().tolist())    if "EJECUTIVO"   in df_f.columns else []
    pr_opts  = sorted(get_scope_excluding("f_fil_pr")["PROMOTOR"].dropna().unique().tolist())     if "PROMOTOR"    in df_f.columns else []
    # Categoría: siempre del dataset completo (filtro independiente)
    cat_opts = sorted(df_f["CATEGORIA"].dropna().unique().tolist())                               if "CATEGORIA"   in df_f.columns else []
    # Artículo: refinado por scope completo
    _scope_all = get_all_filtered()
    art_opts = sorted(_scope_all[_desc_col].dropna().unique().tolist()) if _desc_col and _desc_col in _scope_all.columns else []

    # ── 7. WIDGETS CON CASCADEO BIDIRECCIONAL ────────────────────────────────
    # El usuario puede seleccionar cualquier filtro libremente.
    # Si selecciona 1 item en cualquier filtro, los demás muestran solo opciones
    # relacionadas. Si hay 2+ opciones resultantes, el usuario elige manualmente.
    # Si el usuario pone múltiples items manualmente, se respetan sin forzar cascadeo.
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        fil_tda = st.multiselect(
            "# Tienda", tda_opts,
            default=cascade_default(tda_opts, "f_fil_tda"),
            key="f_fil_tda", placeholder="Buscar #..."
        )
        fil_ed = st.multiselect(
            "Estado", ed_opts,
            default=cascade_default(ed_opts, "f_fil_ed"),
            key="f_fil_ed", placeholder="Seleccionar..."
        )
    with c2:
        fil_ti = st.multiselect(
            "Tienda", ti_opts,
            default=cascade_default(ti_opts, "f_fil_ti"),
            key="f_fil_ti", placeholder="Buscar tienda..."
        )
        fil_fmt = st.multiselect(
            "Formato", fmt_opts,
            default=cascade_default(fmt_opts, "f_fil_fmt"),
            key="f_fil_fmt", placeholder="Seleccionar..."
        )
    with c3:
        fil_crd = st.multiselect(
            "Coordinador", crd_opts,
            default=cascade_default(crd_opts, "f_fil_crd"),
            key="f_fil_crd", placeholder="Seleccionar..."
        )
        fil_ej = st.multiselect(
            "Ejecutivo", ej_opts,
            default=cascade_default(ej_opts, "f_fil_ej"),
            key="f_fil_ej", placeholder="Seleccionar..."
        )
    with c4:
        fil_pr = st.multiselect(
            "Promotor", pr_opts,
            default=cascade_default(pr_opts, "f_fil_pr"),
            key="f_fil_pr", placeholder="Seleccionar..."
        )
        # Categoría: sin cascadeo — el usuario siempre elige manualmente
        fil_cat = st.multiselect(
            "🏷️ Categoría", cat_opts,
            key="f_fil_cat", placeholder="Todas las categorías..."
        )

    # Artículo — fila completa, sin cascadeo forzado
    fil_art = st.multiselect(
        "Artículo", art_opts,
        key="f_fil_art", placeholder="Buscar artículo..."
    )

    # ── 8. APLICAR FILTROS FINALES ────────────────────────────────────────────
    _fcols = ["NOTIENDA","TIENDA","ESTADO","FORMATO","COORDINADOR","EJECUTIVO","PROMOTOR","CATEGORIA"]
    if _desc_col:
        _fcols.append(_desc_col)
    _fvals = [fil_tda, fil_ti, fil_ed, fil_fmt, fil_crd, fil_ej, fil_pr, fil_cat]
    if _desc_col:
        _fvals.append(fil_art)
    _pairs  = [(c, v) for c, v in zip(_fcols, _fvals) if c in df_f.columns]
    dff = apply_filters(df_f, [p[0] for p in _pairs], [p[1] for p in _pairs])

    # ── 10. BOTONES DE VISTA ──────────────────────────────────────────────────
    def tog_fre_neg():
        st.session_state.fre_neg   = not st.session_state.get("fre_neg",   False)
        st.session_state.fre_dias  = False
        st.session_state.fre_trans = False
    def tog_fre_dias():
        st.session_state.fre_dias  = not st.session_state.get("fre_dias",  False)
        st.session_state.fre_neg   = False
        st.session_state.fre_trans = False
    def tog_fre_trans():
        st.session_state.fre_trans = not st.session_state.get("fre_trans", False)
        st.session_state.fre_neg   = False
        st.session_state.fre_dias  = False

    b1, b2, b3 = st.columns(3, gap="small")
    with b1:
        st.button("📉 NEGATIVOS", width='stretch',
                  type="primary" if st.session_state.get("fre_neg")   else "secondary",
                  key="btn_fre_neg",   on_click=tog_fre_neg)
    with b2:
        st.button("📅 DIAS INV",  width='stretch',
                  type="primary" if st.session_state.get("fre_dias")  else "secondary",
                  key="btn_fre_dias",  on_click=tog_fre_dias)
    with b3:
        st.button("🚚 PEDIDOS EN TRANSITO", width='stretch',
                  type="primary" if st.session_state.get("fre_trans") else "secondary",
                  key="btn_fre_trans", on_click=tog_fre_trans)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── 11. KPI + GRÁFICA ────────────────────────────────────────────────────
    c_kpi_f, c_chart_f = st.columns([1, 2])
    with c_kpi_f:
        total_so_f = float(dff["IMPORTEABR"].sum()) if "IMPORTEABR" in dff.columns else 0.0
        st.markdown(
            "<div class='kpi-card' style='height:450px;'>"
            "<div class='kpi-title'>Total Sell Out</div>"
            "<div class='kpi-value' style='color:#B3FF00;'>$" + f"{total_so_f:,.2f}" + "</div>"
            "</div>",
            unsafe_allow_html=True
        )
    with c_chart_f:
        val_col_pie = "IMPORTEABR" if "IMPORTEABR" in dff.columns else None
        cat_col_pie = "CATEGORIA"  if "CATEGORIA"  in dff.columns else None
        if val_col_pie and cat_col_pie and not dff.empty:
            pie_df_f = dff.groupby(cat_col_pie)[val_col_pie].sum().reset_index()
            pie_df_f.columns = ["Category", val_col_pie]
            pie_df_f = pie_df_f[pie_df_f[val_col_pie] > 0]
            if not pie_df_f.empty:
                _badge = {lbl: st.session_state.get(key, [])
                          for lbl, key in [("# Tienda","f_fil_tda"),("Tienda","f_fil_ti"),
                                           ("Estado","f_fil_ed"),("Coordinador","f_fil_crd"),
                                           ("Ejecutivo","f_fil_ej"),("Promotor","f_fil_pr")]
                          if st.session_state.get(key, [])}
                ann_f = _filter_badge(_badge, RETAILER_COLORS["FRESKO"]) if _badge else None
                fig_f = build_pie_cached(pie_df_f.to_json(date_format='iso'), "FRESKO")
                if ann_f:
                    fig_f.add_annotation(ann_f)
                st.plotly_chart(fig_f, width='stretch')
            else:
                st.info("Sin ventas con importe para los filtros seleccionados.")
        else:
            st.info("Sin datos para gráfica.")

    # ── 12. VISTAS CONDICIONALES ─────────────────────────────────────────────
    if st.session_state.get("fre_neg", False):
        st.subheader("📉 Inventarios Negativos y en Cero")

        # Columna de inventario mapeada por load_fre → EXISTENCIA
        # iloc 16 del Excel original = "Inventario 24 Abr 2026" → interno: EXISTENCIA
        _inv_col = next((c for c in ["EXISTENCIA","INV_CAJAS","INVENTARIO"] if c in dff.columns), None)

        if _inv_col:
            # Filtrar: negativos (<0) Y en cero (==0)
            dff_neg = dff[dff[_inv_col] <= 0].copy()
        else:
            dff_neg = pd.DataFrame()

        if not dff_neg.empty:
            # Columnas exactas solicitadas (por nombre interno tras mapeo de load_fre)
            # iloc → nombre header Excel          → columna interna
            #   7  → FORMATO                      → FORMATO
            #   8  → ESTATUS                      → ESTATUS
            #   9  → # Tda                        → NOTIENDA
            #  10  → Tienda                       → TIENDA
            #  11  → Sku                          → CODIGO
            #  12  → Descripcion                  → DESCRIPCION / ARTICULO
            #  15  → IMPORTE                      → IMPORTEABR
            #  16  → Inventario 24 Abr 2026       → EXISTENCIA  ← negativos y 0
            #  17  → Unidades tránsito            → TRANSITO
            #  18  → VTA PROM                     → VTAPROM
            #  19  → DI INV                       → DIASINV
            _desc = _desc_col or "DESCRIPCION"
            _cols_ordered = [
                "FORMATO",
                "ESTATUS",
                "NOTIENDA",
                "TIENDA",
                "CODIGO",
                _desc,
                "IMPORTEABR",
                _inv_col,
                "TRANSITO",
                "VTAPROM",
                "DIASINV",
            ]
            # Solo incluir columnas que existen en el df filtrado
            _show = [c for c in _cols_ordered if c and c in dff_neg.columns]

            # Renombrar para presentación amigable
            _rename = {
                "NOTIENDA":   "# Tda",
                "TIENDA":     "Tienda",
                "CODIGO":     "Sku",
                _desc:        "Descripcion",
                "IMPORTEABR": "IMPORTE",
                _inv_col:     "Inventario",
                "TRANSITO":   "Unidades tránsito",
                "VTAPROM":    "VTA PROM",
                "DIASINV":    "DI INV",
            }

            disp_neg = dff_neg[_show].rename(columns=_rename).sort_values("Inventario")

            # Formato numérico
            _fmt_neg = {}
            if "IMPORTE"          in disp_neg.columns: _fmt_neg["IMPORTE"]           = "${:,.2f}"
            if "Inventario"       in disp_neg.columns: _fmt_neg["Inventario"]        = "{:,.0f}"
            if "Unidades tránsito"in disp_neg.columns: _fmt_neg["Unidades tránsito"] = "{:,.0f}"
            if "VTA PROM"         in disp_neg.columns: _fmt_neg["VTA PROM"]          = "{:,.0f}"
            if "DI INV"           in disp_neg.columns: _fmt_neg["DI INV"]            = "{:.1f}"

            # Resumen rápido
            _total_neg  = int((disp_neg["Inventario"] < 0).sum())
            _total_zero = int((disp_neg["Inventario"] == 0).sum())
            _c1, _c2 = st.columns(2)
            with _c1:
                st.metric("🔴 Negativos", f"{_total_neg} SKUs")
            with _c2:
                st.metric("🟡 En Cero", f"{_total_zero} SKUs")

            def _color_negativos(v):
                if isinstance(v, (int, float)):
                    if v < 0:    return "color:#d32f2f;font-weight:700"
                    elif v == 0: return "color:#f57c00;font-weight:600"
                return ""

            _subset_inv = ["Inventario"] if "Inventario" in disp_neg.columns else []
            _styled = disp_neg.style.format(_fmt_neg).map(_color_negativos, subset=_subset_inv)
            st.dataframe(_styled, width='stretch', hide_index=True, height=auto_height(disp_neg))
            st.download_button(
                "📥 DESCARGAR EXCEL",
                data=convert_df_to_excel(disp_neg),
                file_name="Fresko_Negativos.xlsx",
                width='stretch'
            )
        else:
            st.success("✅ Sin inventarios negativos ni en cero con los filtros actuales.")

    elif st.session_state.get("fre_dias", False):
        st.subheader("📅 Reporte Días Inventario (Consolidado por SKU)")

        _FRE_NUTRIOLI = ["7501039121610"]
        _FRE_OLI = ["7501039122280","7501039127308","7501039127285","7501039122631",
                    "7501039122624","7501039122020","7501039127292","7501039122013"]
        _FRE_PASTAS  = ["7501039127025","7501039127124"]
        _FRE_BORGES  = [
            "8410179100043","8410179304144","8410179005935","8410179300825",
            "8410179100708","8410179100357","8410179100920","8410179005928",
            "8410179100036","8410179000640","8410179308142","8410179100050",
            "8410179510118","8410179301082","8410179800127","8410179900254",
            "8410179305141","8410179200811","8410179000084","8410179100821",
            "8410179200828","8410179000961","8410179000046","8410179306148",
            "8410179000077","8410179000053"
        ]

        def render_fre_card(title, skus, dff_context):
            mask    = dff_context["CODIGO"].astype(str).str.strip().isin(skus)
            subset  = dff_context[mask]
            val_dias = subset["DIASINV"].mean()    if not subset.empty else 0
            val_so   = subset["IMPORTEABR"].sum()  if not subset.empty else 0
            rows_html = ""
            if not subset.empty:
                desglose = (subset.groupby("DESCRIPCION")
                            .agg({"DIASINV": "mean", "IMPORTEABR": "sum"})
                            .reset_index())
                for _, row in desglose.head(8).iterrows():
                    desc = str(row["DESCRIPCION"])[:22]
                    rows_html += (
                        "<div style='display:flex;justify-content:space-between;"
                        "align-items:center;border-bottom:1px solid #f0f0f0;"
                        "padding:2px 0;gap:4px;'>"
                        f"<span style='font-size:0.6rem;color:#666;flex:1;"
                        f"white-space:nowrap;overflow:hidden;text-overflow:ellipsis;'>{desc}</span>"
                        f"<span style='font-size:0.7rem;font-weight:700;color:#64DD17;'>"
                        f"{row['DIASINV']:,.0f}</span>"
                        f"<span style='font-size:0.6rem;color:#888;margin-left:4px;'>"
                        f"${row['IMPORTEABR']:,.0f}</span>"
                        "</div>"
                    )
            return val_dias, val_so, rows_html

        d_nut, s_nut, _        = render_fre_card("NUTRIOLI", _FRE_NUTRIOLI, dff)
        d_oli, s_oli, _        = render_fre_card("OLI",      _FRE_OLI,     dff)
        d_bor, s_bor, _        = render_fre_card("BORGES",   _FRE_BORGES,  dff)
        d_pas, s_pas, rows_pas = render_fre_card("PASTAS",   _FRE_PASTAS,  dff)

        k1, k2, k3, k4 = st.columns(4)
        k1.markdown(
            f"<div class='kpi-card' style='height:100%;min-height:240px;justify-content:center;'>"
            f"<div class='kpi-title'>NUTRIOLI 850ML</div>"
            f"<div class='kpi-value' style='color:#28a745;'>{d_nut:,.1f}</div>"
            f"<div style='font-size:0.75rem;color:#555;margin-top:6px;font-weight:600;'>${s_nut:,.2f}</div>"
            f"</div>", unsafe_allow_html=True)
        k2.markdown(
            f"<div class='kpi-card' style='height:100%;min-height:240px;justify-content:center;'>"
            f"<div class='kpi-title'>OLI (TODOS)</div>"
            f"<div class='kpi-value' style='color:#E65100;'>{d_oli:,.1f}</div>"
            f"<div style='font-size:0.75rem;color:#555;margin-top:6px;font-weight:600;'>${s_oli:,.2f}</div>"
            f"</div>", unsafe_allow_html=True)
        k3.markdown(
            f"<div class='kpi-card' style='height:100%;min-height:240px;justify-content:center;'>"
            f"<div class='kpi-title'>BORGES</div>"
            f"<div class='kpi-value' style='color:#691D08;'>{d_bor:,.1f}</div>"
            f"<div style='font-size:0.75rem;color:#555;margin-top:6px;font-weight:600;'>${s_bor:,.2f}</div>"
            f"</div>", unsafe_allow_html=True)
        k4.markdown(
            f"<div class='kpi-card' style='height:100%;min-height:240px;padding:10px 12px;justify-content:flex-start;'>"
            f"<div class='kpi-title' style='margin-bottom:5px;'>PASTAS &nbsp;"
            f"<span style='color:#999;font-weight:400;font-size:0.65rem;'>${s_pas:,.2f}</span></div>"
            f"{rows_pas}</div>", unsafe_allow_html=True)

        # ── Tabla consolidada por SKU ──────────────────────────────────────
        all_skus  = _FRE_NUTRIOLI + _FRE_OLI + _FRE_PASTAS + _FRE_BORGES
        df_group  = dff[dff["CODIGO"].astype(str).str.strip().isin(all_skus)].copy()

        if not df_group.empty:
            df_consolidado = (
                df_group.groupby(["CODIGO", "DESCRIPCION"])
                .agg(EXISTENCIA=("EXISTENCIA", "sum"),
                     IMPORTEABR=("IMPORTEABR", "sum"),
                     DIASINV=("DIASINV", "mean"))
                .reset_index()
            )
            df_consolidado.columns = ["SKU", "ARTICULO", "INV PZS (TOTAL)", "SELL OUT (TOTAL)", "DIAS INV (PROM)"]
            df_consolidado = df_consolidado.sort_values("SELL OUT (TOTAL)", ascending=False)

            st.dataframe(
                df_consolidado.style.format({
                    "INV PZS (TOTAL)":  "{:,.0f}",
                    "SELL OUT (TOTAL)": "${:,.2f}",
                    "DIAS INV (PROM)":  "{:,.1f}"
                }),
                width='stretch', hide_index=True,
                height=auto_height(df_consolidado)
            )
            st.download_button(
                "📥 DESCARGAR REPORTE CONSOLIDADO",
                data=convert_df_to_excel(df_consolidado),
                file_name="Fresko_Dias_Inventario_Consolidado.xlsx",
                width='stretch'
            )
        else:
            st.warning("No se encontraron datos para los SKUs seleccionados en los filtros actuales.")
    elif st.session_state.get("fre_trans", False):
        st.subheader("🚚 Pedidos en Tránsito")
        trans_col = next((c for c in ["TRANSITO","TRANSITOCEDIS","TRANSITO_CEDIS"] if c in dff.columns), None)
        if trans_col:
            trans_df = dff[dff[trans_col] > 0].copy()
            show_t   = [c for c in ["NOTIENDA","TIENDA","CODIGO",_desc_col,
                                    "EXISTENCIA",trans_col,"VTAABR"] if c and c in trans_df.columns]
            trans_df = trans_df[show_t].sort_values(trans_col, ascending=False)
            num_t    = [c for c in ["EXISTENCIA",trans_col,"VTAABR"] if c in trans_df.columns]
            st.dataframe(trans_df.style.format({c:"{:,.0f}" for c in num_t}),
                         width='stretch', hide_index=True, height=auto_height(trans_df))
            st.download_button("📥 DESCARGAR EXCEL", data=convert_df_to_excel(trans_df),
                               file_name="Fresko_Transito.xlsx", width='stretch')
        else:
            st.info("Sin datos de tránsito disponibles.")

    else:
        st.subheader("📋 Detalle de Inventario")
        disp = format_fresko_export(dff)
        fmt_map = {k: v for k, v in {
            "INVENTARIO":         "{:,.0f}",
            "VENTA MES ANTERIOR": "{:,.0f}",
            "U VENTA AL CORTE":   "{:,.0f}",
            "IMPORTE":            "${:,.2f}",
            "Unidades tránsito":  "{:,.0f}",
            "VTA PROM":           "{:,.0f}",
            "DI INV":             "{:.1f}",
        }.items() if k in disp.columns}
        st.dataframe(
            disp.style.format(fmt_map),
            width='stretch', hide_index=True, height=auto_height(disp),
            column_config={col: st.column_config.Column(width="auto") for col in disp.columns}
        )
        st.download_button("📥 DESCARGAR EXCEL",
                           data=convert_df_to_excel(format_fresko_export(dff)),
                           file_name="Fresko_Inventario.xlsx", width='stretch')

    # ── 13. RANKING DE VENTAS FRESKO ──────────────────────────────────────────
    st.divider()
    st.markdown("<h3 style='text-align:center;color:#444;'>🏆 RANKING DE VENTAS FRESKO</h3>",
                unsafe_allow_html=True)

    # SKUs por categoría — filtrado por CODIGO (no por descripción)
    _RK_PASTAS   = ["7501039127025","7501039127124"]
    _RK_OLIVAS   = ["7501039127308","7501039127285","7501039122631","7501039122624",
                    "7501039122020","7501039127292","7501039122013"]
    _RK_NUTRIOLI = ["7501039121610"]
    _RK_BORGES   = [
        "8410179100043","8410179304144","8410179005935","8410179300825","8410179100708",
        "8410179100357","8410179100920","8410179005928","8410179100036","8410179000640",
        "8410179308142","8410179100050","8410179510118","8410179301082","8410179800127",
        "8410179900254","8410179305141","8410179200811","8410179000084","8410179100821",
        "8410179200828","8410179000961","8410179000046","8410179306148","8410179000077",
        "8410179000053"
    ]
    _RK_GENERAL  = _RK_PASTAS + _RK_OLIVAS + _RK_NUTRIOLI + _RK_BORGES

    def set_fre_rank(mode):
        for v in ["fre_rank_gen","fre_rank_pas","fre_rank_oli","fre_rank_nut","fre_rank_bor"]:
            st.session_state[v] = False
        st.session_state["fre_rank_" + mode.lower()] = True
        st.session_state["rank_btn_FRESKO"] = mode.upper()

    for _rv in ["fre_rank_gen","fre_rank_pas","fre_rank_oli","fre_rank_nut","fre_rank_bor"]:
        if _rv not in st.session_state:
            st.session_state[_rv] = False

    fre_rank_gen = st.session_state.get("fre_rank_gen", False)
    fre_rank_pas = st.session_state.get("fre_rank_pas", False)
    fre_rank_oli = st.session_state.get("fre_rank_oli", False)
    fre_rank_nut = st.session_state.get("fre_rank_nut", False)
    fre_rank_bor = st.session_state.get("fre_rank_bor", False)

    # Filtros que afectan el ranking
    c_rk1, c_rk2 = st.columns(2)
    with c_rk1:
        _edo_opts = sorted(df_f["ESTADO"].dropna().unique().tolist()) if "ESTADO" in df_f.columns else []
        sel_edo_rk = st.multiselect("Estado (Ranking)", _edo_opts,
                                    key="fre_rnk_st", placeholder="Seleccionar...")
    with c_rk2:
        _fmt_opts = sorted(df_f["FORMATO"].dropna().unique().tolist()) if "FORMATO" in df_f.columns else []
        sel_fmt_rk = st.multiselect("Formato (Ranking)", _fmt_opts,
                                    key="fre_rnk_fmt", placeholder="Seleccionar...")

    # Botones de categoría
    fr1, fr2, fr3, fr4, fr5 = st.columns(5, gap="small")
    with fr1: st.button("📊 GENERAL",  on_click=set_fre_rank, args=("GEN",), width='stretch',
                         type="primary" if fre_rank_gen else "secondary")
    with fr2: st.button("🍝 PASTAS",   on_click=set_fre_rank, args=("PAS",), width='stretch',
                         type="primary" if fre_rank_pas else "secondary")
    with fr3: st.button("🫒 OLIVAS",   on_click=set_fre_rank, args=("OLI",), width='stretch',
                         type="primary" if fre_rank_oli else "secondary")
    with fr4: st.button("🍃 NUTRIOLI", on_click=set_fre_rank, args=("NUT",), width='stretch',
                         type="primary" if fre_rank_nut else "secondary")
    with fr5: st.button("🍷 BORGES",   on_click=set_fre_rank, args=("BOR",), width='stretch',
                         type="primary" if fre_rank_bor else "secondary")

    # Determinar SKUs y etiqueta activos
    active_skus_fre   = []
    current_label_fre = ""
    if   fre_rank_gen: active_skus_fre = _RK_GENERAL;  current_label_fre = "GENERAL"
    elif fre_rank_pas: active_skus_fre = _RK_PASTAS;   current_label_fre = "PASTAS"
    elif fre_rank_oli: active_skus_fre = _RK_OLIVAS;   current_label_fre = "OLIVAS"
    elif fre_rank_nut: active_skus_fre = _RK_NUTRIOLI; current_label_fre = "NUTRIOLI"
    elif fre_rank_bor: active_skus_fre = _RK_BORGES;   current_label_fre = "BORGES"

    if active_skus_fre:
        # Aplicar filtros Estado y Formato sobre df_f (dataset completo de Fresko)
        dff_rk = df_f.copy()
        if sel_edo_rk and "ESTADO" in dff_rk.columns:
            dff_rk = dff_rk[dff_rk["ESTADO"].isin(sel_edo_rk)]
        if sel_fmt_rk and "FORMATO" in dff_rk.columns:
            dff_rk = dff_rk[dff_rk["FORMATO"].isin(sel_fmt_rk)]

        # Filtrar estrictamente por CODIGO
        dff_rk = dff_rk[dff_rk["CODIGO"].astype(str).str.strip().isin(active_skus_fre)]

        if not dff_rk.empty:
            # Agrupar por tienda y sumar IMPORTEABR
            group_cols_rk = [c for c in ["NOTIENDA", "TIENDA"] if c in dff_rk.columns]
            final_rank = (dff_rk.groupby(group_cols_rk)["IMPORTEABR"]
                          .sum()
                          .reset_index()
                          .sort_values("IMPORTEABR", ascending=False)
                          .reset_index(drop=True))
            final_rank.insert(0, "RANKING", final_rank.index + 1)
            final_rank.columns = (["RANKING"] +
                                   ["# Tda", "TIENDA"][:len(group_cols_rk)] +
                                   ["IMPORTE"])

            st.dataframe(
                final_rank.style.format({"IMPORTE": "${:,.2f}"}),
                width='stretch', hide_index=True,
                height=auto_height(final_rank)
            )
            st.download_button(
                f"📥 DESCARGAR RANKING {current_label_fre}",
                data=convert_df_to_excel(final_rank),
                file_name=f"Ranking_Fresko_{current_label_fre}.xlsx",
                width='stretch'
            )
        else:
            st.info("Sin datos para el ranking con los filtros seleccionados.")
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
    elif _act == 'FRESKO':
        df_f = get_cached_or_upload("FRESKO", "up_f", load_fre)
        if df_f is not None: view_fresko(df_f)

# --- 15. PIE DE PÁGINA ---
st.divider()
if st.button("🗑️ LIMPIAR MEMORIA / RESET", width='stretch', type="secondary", key="reset_btn"):
    if not st.session_state.confirm_reset:
        st.session_state.confirm_reset = True
        st.info("⚠️ ¡CONFIRMACIÓN REQUERIDA! Haz clic de nuevo para resetear todo.")
        st.rerun()
    else:
        st.cache_data.clear()
        for key in list(st.session_state.keys()): del st.session_state[key]
        st.success("✅ Memoria limpiada. Reiniciando...")
        time.sleep(1)
        st.rerun()