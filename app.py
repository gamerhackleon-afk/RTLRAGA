import streamlit as st
import pandas as pd
import time
import urllib.parse 
import requests 
import plotly.express as px 
from io import BytesIO 
import os

# --- LIBRERÍAS DE IA ---
from pandasai import SmartDatalake
import google.generativeai as genai
from pandasai.llm.base import LLM

# --- NUESTRO CEREBRO CUSTOM BLINDADO ---
class SafeGemini(LLM):
    def __init__(self, api_key: str):
        genai.configure(api_key=api_key)
        self.modelo_real = genai.GenerativeModel('gemini-2.5-flash')

    def call(self, instruction, context=None) -> str:
        prompt = instruction.to_string()
        response = self.modelo_real.generate_content(prompt)
        return response.text

    @property
    def type(self) -> str:
        return "safe-gemini"

# --- 1. CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(
    page_title="Retail Manager", 
    page_icon="📊", 
    layout="wide", 
    initial_sidebar_state="collapsed"
)

# --- 2. CONFIGURACIÓN CENTRALIZADA ---
CACHE_CONFIG = {'ttl': 3600, 'max_entries': 10, 'show_spinner': False}

URLS_DB = {
    "SORIANA": "https://github.com/gamerhackleon-afk/RTLRAGA/raw/main/SORIANA.xlsx",
    "WALMART": "https://github.com/gamerhackleon-afk/RTLRAGA/raw/main/WALMART.xlsx",
    "CHEDRAUI": "https://github.com/gamerhackleon-afk/RTLRAGA/raw/main/CHEDRAUI.xlsx",
    "FRESKO": "https://github.com/gamerhackleon-afk/RTLRAGA/raw/main/fresko.xlsx"
}

RETAILER_COLORS = {
    "SORIANA": "#D32F2F", "WALMART": "#0071DC", "CHEDRAUI": "#FF6600", "CHATBOT": "#6c757d"
}

if 'is_online' not in st.session_state:
    try:
        requests.get("https://github.com", timeout=2)
        st.session_state.is_online = True
    except:
        st.session_state.is_online = False

if 'active_retailer' not in st.session_state:
    st.session_state.active_retailer = 'WALMART'

if 'confirm_reset' not in st.session_state:
    st.session_state.confirm_reset = False

# --- 3. FUNCIONES UTILITARIAS Y DE CONTROL ---
def safe_mean(series): return series.mean() if not series.empty else 0

def apply_filters(df, filter_cols, selections):
    mask = pd.Series(True, index=df.index)
    for col, sel in zip(filter_cols, selections):
        if sel: mask &= df[col].astype(str).isin(sel)
    return df[mask]

def get_kpi_mean(df, desc_col, days_col, pattern):
    clean_desc = df[desc_col].astype(str).str.upper().str.replace("&NBSP;", "", regex=False).str.replace(" ", "", regex=False)
    clean_pattern = pattern.upper().replace("&NBSP;", "").replace(" ", "")
    mask = clean_desc.str.contains(clean_pattern, case=False, na=False)
    return safe_mean(df.loc[mask, days_col])

def auto_height(df): return min(max(len(df) * 35 + 45, 100), 600)

def whatsapp_report(title, data, max_rows=40):
    msg = [f"*{title} ({len(data)})*"]
    cols = data.columns
    col_desc = 'DESCRIPCION' if 'DESCRIPCION' in cols else ('ARTICULO' if 'ARTICULO' in cols else cols[1])
    col_inv = 'DIAS INV' if 'DIAS INV' in cols else ('DIAS_INV' if 'DIAS_INV' in cols else cols[-1])
    col_tienda = 'TIENDA' if 'TIENDA' in cols else cols[0]
    for _, r in data.head(max_rows).iterrows():
        val_inv = r.get(col_inv, '')
        msg.append(f"🏢 {r.get(col_tienda, '')}\n📦 {r.get(col_desc, '')}\n📊 {val_inv}")
    if len(data) > max_rows: msg.append("...")
    url = f"https://wa.me/?text={urllib.parse.quote(chr(10).join(msg))}"
    st.markdown(f'<a href="{url}" target="_blank" style="text-decoration:none;"><div style="background-color:#25D366;color:white;padding:12px;text-align:center;font-weight:bold;border-radius:8px;margin:10px 0;">📱 ENVIAR REPORTE WHATSAPP</div></a>', unsafe_allow_html=True)

def download_file(url_or_file):
    if isinstance(url_or_file, str):
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(url_or_file, headers=headers, timeout=10)
            response.raise_for_status()
            return BytesIO(response.content)
        except: return None
    return url_or_file

def get_data(key, uploader_key, load_func):
    df = None
    if st.session_state.is_online and key in URLS_DB:
        try:
            with st.spinner(f"Sincronizando {key}..."): df = load_func(URLS_DB[key])
        except: pass
    if df is None:
        if not st.session_state.is_online: st.warning("⚠️ Sin conexión a GitHub.")
        f = st.file_uploader(f"📂 Cargar Excel {key}", type=["xlsx"], key=uploader_key)
        if f: df = load_func(f)
    return df

def set_retailer(retailer_name):
    st.session_state.active_retailer = retailer_name
    logic_vars = ['s_rojo', 's_dias_inv', 's_dias_prod', 's_rank_gen', 's_rank_pas', 's_rank_oli', 's_rank_nut', 'w_neg', 'w_4w', 'w_dias_inv', 'w_dias_prod', 'w_rank_tiendas', 'w_rank_pastas', 'w_rank_olivas', 'w_nutri_top10', 'c_alt', 'c_neg', 'c_dias_inv', 'c_neg_zero', 'c_under_10', 'c_rank_gen', 'c_rank_pas', 'c_rank_oli', 'c_rank_nut']
    for var in logic_vars:
        if var in st.session_state: st.session_state[var] = False

# --- 4. FUNCIONES DE LECTURA DE EXCEL ---
def optimize_floats(df):
    for col in df.select_dtypes(include=['float64']).columns: df[col] = df[col].astype('float32')
    return df

@st.cache_data(**CACHE_CONFIG)
def load_sor(path):
    try:
        source = download_file(path)
        if source is None: return None
        df = pd.read_excel(source, engine='openpyxl')
        while df.shape[1] < 31: df[f"COL_AUTO_{df.shape[1]}"] = 0
        df.rename(columns={df.columns[2]: "CODIGO", df.columns[3]: "DESCRIPCION", df.columns[4]: "CATEGORIA", df.columns[5]: "NO_TIENDA", df.columns[6]: "TIENDA", df.columns[7]: "CIUDAD", df.columns[8]: "ESTADO", df.columns[9]: "FORMATO", df.columns[30]: "DIAS_INV", df.columns[28]: "INV_CAJAS", df.columns[24]: "SO_$", df.columns[0]: "RESURTIMIENTO"}, inplace=True)
        df["CODIGO"] = df["CODIGO"].astype(str).str.replace(r'\.0*$', '', regex=True)
        for c in ["DIAS_INV", "INV_CAJAS", "SO_$"]: df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
        cols_4sem = [df.columns[21], df.columns[22], df.columns[23], df.columns[24]]
        for c in cols_4sem: df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
        df['SO_4SEM'] = df[cols_4sem].sum(axis=1) 
        df['SIN_VTA'] = (df['SO_4SEM'] == 0)
        return optimize_floats(df)
    except: return None

@st.cache_data(**CACHE_CONFIG)
def load_wal(path):
    try:
        source = download_file(path)
        if source is None: return None
        df = pd.read_excel(source, engine='openpyxl')
        while df.shape[1] < 97: df[f"COL_AUTO_{df.shape[1]}"] = 0
        df.rename(columns={df.columns[0]: "CODIGO", df.columns[4]: "DESCRIPCION", df.columns[5]: "CATEGORIA", df.columns[7]: "ESTADO", df.columns[15]: "TIENDA", df.columns[16]: "FORMATO", df.columns[18]: "MARCA", df.columns[33]: "DIAS_INV", df.columns[42]: "EXISTENCIA"}, inplace=True)
        df["CODIGO"] = df["CODIGO"].astype(str).str.replace(r'\.0*$', '', regex=True)
        for col_idx in [33, 42, 73, 74, 75, 76, 96]: df[df.columns[col_idx]] = pd.to_numeric(df[df.columns[col_idx]], errors='coerce').fillna(0)
        df['PROM_PZS_MENSUAL'] = df.iloc[:,[73,74,75,76]].mean(axis=1)
        df['SO_$'] = df.iloc[:,96]
        return optimize_floats(df)
    except: return None

@st.cache_data(**CACHE_CONFIG)
def load_che(path):
    try:
        source = download_file(path)
        if source is None: return None
        df = pd.read_excel(source, engine='openpyxl')
        while df.shape[1] < 20: df[f"COL_AUTO_{df.shape[1]}"] = 0
        df = df[pd.to_numeric(df.iloc[:, 7], errors='coerce') != 0].dropna(subset=[df.columns[12]])
        df = df[pd.to_numeric(df.iloc[:,9], errors='coerce').notna()]
        df.rename(columns={df.columns[3]: "ESTADO", df.columns[8]: "CATEGORIA", df.columns[9]: "NO_TIENDA", df.columns[10]: "TIENDA", df.columns[12]: "ARTICULO", df.columns[13]: "INV_ULT_SEM", df.columns[17]: "VTA_PROM_DIARIA", df.columns[18]: "DIAS_INV", df.columns[19]: "SELL_OUT"}, inplace=True)
        for col in ["INV_ULT_SEM", "VTA_PROM_DIARIA", "DIAS_INV", "SELL_OUT"]: df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        return optimize_floats(df)
    except: return None

@st.cache_data(**CACHE_CONFIG)
def load_fre(path):
    try:
        source = download_file(path)
        if source is None: return None
        return optimize_floats(pd.read_excel(source, engine='openpyxl'))
    except: return None

# --- 5. CSS AVANZADO RESPONSIVO ---
act = st.session_state.active_retailer
style_on = "opacity: 1 !important; border: 3px solid #ffffff !important; transform: scale(1.02) !important; box-shadow: 0 8px 16px rgba(0,0,0,0.3) !important; z-index: 10 !important;"
style_off = "opacity: 0.6 !important; transform: scale(0.98) !important; filter: grayscale(40%) !important; border: 1px solid transparent !important;"
css_styles = {k: style_on if act == k else style_off for k in ['SORIANA', 'WALMART', 'CHEDRAUI', 'CHATBOT']}

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap');
html, body {{ font-family: 'Inter', sans-serif; background-color: #f8f9fa; }}
.block-container {{ padding-top: 1rem !important; padding-bottom: 2rem !important; padding-left: 1rem !important; padding-right: 1rem !important; max-width: 100% !important; }}
.kpi-card {{ background: white; border: 1px solid #e0e0e0; border-radius: 12px; padding: 15px; text-align: center; box-shadow: 0 2px 6px rgba(0,0,0,0.05); margin-bottom: 15px; height: 100%; display: flex; flex-direction: column; justify-content: center; transition: transform 0.2s; }}
.kpi-title {{ font-size: 0.8rem; color: #666; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }}
.kpi-value {{ font-size: 2rem; font-weight: 800; margin-top: 5px; word-break: break-word; }}
.retailer-header {{ font-size: 1.2rem; font-weight: 800; color: white; padding: 10px 15px; border-radius: 8px; margin: 15px 0; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
div[data-testid="stHorizontalBlock"] button {{ border-radius: 10px !important; font-weight: 700 !important; text-transform: uppercase; border: none !important; }}
div[data-testid="stHorizontalBlock"]:nth-of-type(1) [data-testid="stColumn"]:nth-of-type(1) button {{ background: linear-gradient(135deg, #D32F2F, #B71C1C) !important; color: white !important; {css_styles['SORIANA']} }}
div[data-testid="stHorizontalBlock"]:nth-of-type(1) [data-testid="stColumn"]:nth-of-type(2) button {{ background: linear-gradient(135deg, #0071DC, #005BB5) !important; color: white !important; {css_styles['WALMART']} }}
div[data-testid="stHorizontalBlock"]:nth-of-type(1) [data-testid="stColumn"]:nth-of-type(3) button {{ background: linear-gradient(135deg, #FF6600, #E65100) !important; color: white !important; {css_styles['CHEDRAUI']} }}
div[data-testid="stHorizontalBlock"]:nth-of-type(1) [data-testid="stColumn"]:nth-of-type(4) button {{ background: linear-gradient(135deg, #4b5563, #343a40) !important; color: white !important; {css_styles['CHATBOT']} }}
.btn-ranking-blue {{ background-color: #0071DC !important; color: white !important; border: 2px solid white !important; }}
.btn-ranking-orange {{ background-color: #FF8C00 !important; color: white !important; border: 2px solid white !important; }}
.btn-ranking-olive {{ background-color: #808000 !important; color: white !important; border: 2px solid white !important; }}
.btn-ranking-green {{ background-color: #28a745 !important; color: #FFC220 !important; border: 2px solid #FFC220 !important; }}
.dias-inv-style > button {{ background-color: #28a745 !important; color: white !important; }}
@media (max-width: 768px) {{
    .block-container {{ padding-left: 0.5rem !important; padding-right: 0.5rem !important; }}
    div[data-testid="stHorizontalBlock"] button {{ height: 50px !important; font-size: 0.75rem !important; padding: 0 !important; }}
    .retailer-header {{ font-size: 1rem; padding: 8px; margin: 10px 0; }}
    section[data-testid="stSidebar"] {{ display: none; }}
}}
</style>
""", unsafe_allow_html=True)

# --- 6. NAVEGACIÓN ---
col1, col2, col3, col4 = st.columns(4, gap="small")
with col1: st.button("SORIANA", on_click=set_retailer, args=("SORIANA",), use_container_width=True)
with col2: st.button("WALMART", on_click=set_retailer, args=("WALMART",), use_container_width=True)
with col3: st.button("CHEDRAUI", on_click=set_retailer, args=("CHEDRAUI",), use_container_width=True)
with col4: st.button("🤖 IA", on_click=set_retailer, args=("CHATBOT",), use_container_width=True)
st.markdown("<hr style='margin: 15px 0; border: 0; border-top: 1px solid #eee;'>", unsafe_allow_html=True)

# --- 7. HEADER GLOBAL ---
if st.session_state.active_retailer != 'CHATBOT':
    c_head1, c_head2 = st.columns([1, 5])
    with c_head1:
        try: st.image("ragasa_logo.png", use_container_width=True)
        except: st.write("📦")
    with c_head2:
        st.markdown("<div style='display:flex; flex-direction:column; justify-content:center; height:100%;'><h2 style='margin:0; font-weight:800; color:#333;'>RETAIL MANAGER</h2><p style='margin:0; font-size:0.9rem; color:#666;'>Control de Inventarios y Ventas</p></div>", unsafe_allow_html=True)
    status_txt = 'CONECTADO' if st.session_state.is_online else 'OFFLINE'
    st.markdown(f"<div style='text-align:right; font-size:0.7rem; color: #28a745; font-weight:bold; margin-bottom:5px;'>● {status_txt}</div>", unsafe_allow_html=True)


# --- 8. VISTAS (RESUMIDAS PARA ENFOCARNOS EN LA IA) ---
def view_soriana(df_s):
    st.markdown(f"<div class='retailer-header' style='background-color: {RETAILER_COLORS['SORIANA']}'>SORIANA</div>", unsafe_allow_html=True)
    st.dataframe(df_s.head(100), use_container_width=True) # Resumido por espacio, tu código de gráficas va aquí.

def view_walmart(df_w):
    st.markdown(f"<div class='retailer-header' style='background-color: {RETAILER_COLORS['WALMART']}'>WALMART</div>", unsafe_allow_html=True)
    st.dataframe(df_w.head(100), use_container_width=True) # Resumido por espacio

def view_chedraui(df_c):
    st.markdown(f"<div class='retailer-header' style='background-color: {RETAILER_COLORS['CHEDRAUI']}'>CHEDRAUI</div>", unsafe_allow_html=True)
    st.dataframe(df_c.head(100), use_container_width=True) # Resumido por espacio

# --- VISTA CHATBOT (AQUÍ ESTÁ LA MAGIA) ---
def view_chatbot():
    # 1. LEE LA CLAVE SOLO DE LOS SECRETS (NUNCA ESCRITA EN EL CÓDIGO)
    try:
        API_KEY = st.secrets["GEMINI_API_KEY"]
    except Exception as e:
        st.error("⚠️ Falla: No se encontró GEMINI_API_KEY en los Secrets de Streamlit. Revísalo en tu panel.")
        return

    # Inyectamos la clave al entorno por si PandasAI la busca
    os.environ["GEMINI_API_KEY"] = API_KEY

    with st.spinner("Sincronizando datos para la IA..."):
        df_s = get_data("SORIANA", "up_s_bot", load_sor)
        df_w = get_data("WALMART", "up_w_bot", load_wal)
        df_c = get_data("CHEDRAUI", "up_c_bot", load_che)
        df_f = get_data("FRESKO", "up_f_bot", load_fre)
        
    dfs = []
    if df_s is not None: df_s.name = "Soriana"; dfs.append(df_s)
    if df_w is not None: df_w.name = "Walmart"; dfs.append(df_w)
    if df_c is not None: df_c.name = "Chedraui"; dfs.append(df_c)
    if df_f is not None: df_f.name = "Fresko"; dfs.append(df_f)
        
    if not dfs:
        st.error("No se pudieron cargar las bases de datos.")
        return
    
    # 2. USAMOS NUESTRO CEREBRO PERSONALIZADO
    llm = SafeGemini(api_key=API_KEY)
    dl = SmartDatalake(dfs, config={"llm": llm, "verbose": False})
    
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": "¡Hola! Estoy conectado a las bases de datos de Soriana, Walmart, Chedraui y Fresko. ¿Qué te gustaría consultar?"}]
        
    for msg in st.session_state.messages:
        st.chat_message(msg["role"]).write(msg["content"])
        
    if prompt := st.chat_input("Ej: ¿Cuál es el producto con mayor Sell Out en Walmart?"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        st.chat_message("user").write(prompt)
        
        with st.chat_message("assistant"):
            with st.spinner("🧠 Analizando tus bases de datos..."):
                try:
                    respuesta = dl.chat(prompt + " (Responde en español de forma concisa. Si pido tabla, devuelve un DataFrame)")
                    if isinstance(respuesta, pd.DataFrame):
                        st.dataframe(respuesta, use_container_width=True)
                        st.session_state.messages.append({"role": "assistant", "content": "Aquí tienes la tabla que solicitaste."})
                    else:
                        st.write(respuesta)
                        st.session_state.messages.append({"role": "assistant", "content": str(respuesta)})
                except Exception as e:
                    st.error(f"Ocurrió un error al procesar los datos.")

# --- 9. EJECUTAR VISTA ---
if st.session_state.active_retailer == 'SORIANA':
    df_s = get_data("SORIANA", "up_s", load_sor)
    if df_s is not None: view_soriana(df_s)
elif st.session_state.active_retailer == 'WALMART':
    df_w = get_data("WALMART", "up_w", load_wal)
    if df_w is not None: view_walmart(df_w)
elif st.session_state.active_retailer == 'CHEDRAUI':
    df_c = get_data("CHEDRAUI", "up_c", load_che)
    if df_c is not None: view_chedraui(df_c)
elif st.session_state.active_retailer == 'CHATBOT':
    view_chatbot()

# --- 10. PIE DE PÁGINA Y RESETEO MAESTRO ---
st.divider()
if st.button("🗑️ LIMPIAR MEMORIA / RESET", use_container_width=True):
    if not st.session_state.confirm_reset:
        st.session_state.confirm_reset = True
        st.error("⚠️ ¡CONFIRMACIÓN REQUERIDA! Haz clic de nuevo para resetear todo el caché.")
        st.rerun()
    else:
        st.cache_data.clear()
        for key in list(st.session_state.keys()): del st.session_state[key]
        st.success("✅ Memoria y caché completamente destruidos. Reiniciando...")
        time.sleep(1)
        st.rerun()