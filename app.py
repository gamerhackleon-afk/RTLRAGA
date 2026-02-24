import streamlit as st
import pandas as pd
import time
import urllib.parse 
import requests 
import altair as alt 
from io import BytesIO 

# --- 1. CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(
    page_title="Retail Manager", 
    page_icon="📊", 
    layout="wide", 
    initial_sidebar_state="collapsed"
)

# --- 2. CONFIGURACIÓN CENTRALIZADA ---
CACHE_CONFIG = {'ttl': 3600, 'max_entries': 10, 'show_spinner': False}

# URLs de Datos
URLS_DB = {
    "SORIANA": "https://github.com/gamerhackleon-afk/RTLRAGA/raw/main/SORIANA.xlsx",
    "WALMART": "https://github.com/gamerhackleon-afk/RTLRAGA/raw/main/WALMART.xlsx",
    "CHEDRAUI": "https://github.com/gamerhackleon-afk/RTLRAGA/raw/main/CHEDRAUI.xlsx"
}

# Colores por retailer
RETAILER_COLORS = {
    "SORIANA": "#D32F2F",
    "WALMART": "#0071DC", 
    "CHEDRAUI": "#FF6600",
    "FRESKO": "#CCFF00"
}

# Inicialización de estado
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

def safe_mean(series):
    return series.mean() if not series.empty else 0

def apply_filters(df, filter_cols, selections):
    mask = pd.Series(True, index=df.index)
    for col, sel in zip(filter_cols, selections):
        if sel:
            mask &= df[col].astype(str).isin(sel)
    return df[mask]

def get_kpi_mean(df, desc_col, days_col, pattern):
    # Limpiamos espacios y caracteres HTML extraños como &NBSP; para asegurar el match
    clean_desc = df[desc_col].astype(str).str.upper().str.replace("&NBSP;", "", regex=False).str.replace(" ", "", regex=False)
    clean_pattern = pattern.upper().replace("&NBSP;", "").replace(" ", "")
    mask = clean_desc.str.contains(clean_pattern, case=False, na=False)
    return safe_mean(df.loc[mask, days_col])

def whatsapp_report(title, data, max_rows=40):
    msg = [f"*{title} ({len(data)})*"]
    cols = data.columns
    col_desc = 'DESCRIPCION' if 'DESCRIPCION' in cols else ('ARTICULO' if 'ARTICULO' in cols else cols[1])
    col_inv = 'DIAS INV' if 'DIAS INV' in cols else ('DIAS_INV' if 'DIAS_INV' in cols else cols[-1])
    col_tienda = 'TIENDA' if 'TIENDA' in cols else cols[0]
    
    for _, r in data.head(max_rows).iterrows():
        val_inv = r.get(col_inv, '')
        msg.append(f"🏢 {r.get(col_tienda, '')}\n📦 {r.get(col_desc, '')}\n📊 {val_inv}")
    if len(data) > max_rows:
        msg.append("...")
    url = f"https://wa.me/?text={urllib.parse.quote(chr(10).join(msg))}"
    st.markdown(f'<a href="{url}" target="_blank" style="text-decoration:none;"><div style="background-color:#25D366;color:white;padding:12px;text-align:center;font-weight:bold;border-radius:8px;margin:10px 0;">📱 ENVIAR REPORTE WHATSAPP</div></a>', unsafe_allow_html=True)

def download_file(url_or_file):
    if isinstance(url_or_file, str):
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(url_or_file, headers=headers, timeout=10)
            response.raise_for_status()
            return BytesIO(response.content)
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
        if f: df = load_func(f)
    return df

def set_retailer(retailer_name):
    st.session_state.active_retailer = retailer_name
    logic_vars = [
        's_rojo', 's_dias_inv', 's_dias_prod',
        'w_neg', 'w_4w', 'w_dias_inv', 'w_dias_prod', 'w_rank_tiendas', 'w_rank_pastas', 'w_rank_olivas', 'w_nutri_top10', 
        'c_alt', 'c_neg', 'c_dias_inv', 'c_neg_zero', 'c_under_10', 'c_rank_gen', 'c_rank_pas', 'c_rank_oli', 'c_rank_nut'
    ]
    for var in logic_vars:
        if var in st.session_state: st.session_state[var] = False

# --- 4. FUNCIONES DE LECTURA DE EXCEL (CON PROTECCIÓN DE COLUMNAS) ---
def optimize_floats(df):
    for col in df.select_dtypes(include=['float64']).columns:
        df[col] = df[col].astype('float32')
    return df

@st.cache_data(**CACHE_CONFIG)
def load_sor(path):
    try:
        source = download_file(path)
        if source is None: return None
        
        df = pd.read_excel(source, engine='openpyxl')
        
        while df.shape[1] < 31:
            df[f"COL_AUTO_{df.shape[1]}"] = 0
            
        df.rename(columns={
            df.columns[2]: "CODIGO", df.columns[3]: "DESCRIPCION", df.columns[4]: "CATEGORIA",
            df.columns[5]: "NO_TIENDA", df.columns[6]: "TIENDA", df.columns[7]: "CIUDAD",
            df.columns[8]: "ESTADO", df.columns[9]: "FORMATO", 
            df.columns[30]: "DIAS_INV",  
            df.columns[28]: "INV_CAJAS", 
            df.columns[24]: "SO_$",      
            df.columns[0]: "RESURTIMIENTO"
        }, inplace=True)
        
        df["CODIGO"] = df["CODIGO"].astype(str).str.replace(r'\.0*$', '', regex=True)
        
        cols_num = ["DIAS_INV", "INV_CAJAS", "SO_$"]
        for c in cols_num:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
        
        cols_4sem = [df.columns[21], df.columns[22], df.columns[23], df.columns[24]]
        for c in cols_4sem:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
        
        df['SO_4SEM'] = df[cols_4sem].sum(axis=1) 
        df['SIN_VTA'] = (df['SO_4SEM'] == 0)
        df['VTA_PROM'] = df['SO_4SEM'] 
        return optimize_floats(df)
    except Exception as e: 
        st.error(f"Error Soriana: {e}")
        return None

@st.cache_data(**CACHE_CONFIG)
def load_wal(path):
    try:
        source = download_file(path)
        if source is None: return None

        df = pd.read_excel(source, engine='openpyxl')
        
        while df.shape[1] < 97:
            df[f"COL_AUTO_{df.shape[1]}"] = 0
            
        df.rename(columns={
            df.columns[0]: "CODIGO", df.columns[4]: "DESCRIPCION", df.columns[5]: "CATEGORIA",
            df.columns[7]: "ESTADO", df.columns[15]: "TIENDA", df.columns[16]: "FORMATO",
            df.columns[33]: "DIAS_INV", df.columns[42]: "EXISTENCIA"
        }, inplace=True)
        df["CODIGO"] = df["CODIGO"].astype(str).str.replace(r'\.0*$', '', regex=True)
        for col_idx in [33, 42, 73, 74, 75, 76, 96]:
            c_name = df.columns[col_idx]
            df[c_name] = pd.to_numeric(df[c_name], errors='coerce').fillna(0)
        df['PROM_PZS_MENSUAL'] = df.iloc[:,[73,74,75,76]].mean(axis=1)
        df['SO_$'] = df.iloc[:,96]
        return optimize_floats(df)
    except Exception as e: 
        st.error(f"Error Walmart: {e}")
        return None

@st.cache_data(**CACHE_CONFIG)
def load_che(path):
    try:
        source = download_file(path)
        if source is None: return None

        df = pd.read_excel(source, engine='openpyxl')
        
        while df.shape[1] < 20:
            df[f"COL_AUTO_{df.shape[1]}"] = 0
            
        df = df.dropna(subset=[df.columns[12]])
        df = df[pd.to_numeric(df.iloc[:,9], errors='coerce').notna()]
        
        df.rename(columns={
            df.columns[3]: "ESTADO", df.columns[8]: "CATEGORIA", df.columns[9]: "NO_TIENDA",
            df.columns[10]: "TIENDA", df.columns[12]: "ARTICULO", df.columns[13]: "INV_ULT_SEM",
            df.columns[17]: "VTA_PROM_DIARIA", df.columns[18]: "DIAS_INV", df.columns[19]: "SELL_OUT"
        }, inplace=True)

        for col in ["INV_ULT_SEM", "VTA_PROM_DIARIA", "DIAS_INV", "SELL_OUT"]:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            
        return optimize_floats(df)
    except Exception as e: 
        st.error(f"Error Chedraui: {e}")
        return None

@st.cache_data(**CACHE_CONFIG)
def load_fre(file):
    return pd.read_excel(file, engine='openpyxl')

# --- 5. CSS AVANZADO RESPONSIVO ---
act = st.session_state.active_retailer
style_on = "opacity: 1 !important; border: 3px solid #ffffff !important; transform: scale(1.02) !important; box-shadow: 0 8px 16px rgba(0,0,0,0.3) !important; z-index: 10 !important;"
style_off = "opacity: 0.6 !important; transform: scale(0.98) !important; filter: grayscale(40%) !important; border: 1px solid transparent !important;"

css_styles = {k: style_on if act == k else style_off for k in ['SORIANA', 'WALMART', 'CHEDRAUI', 'FRESKO']}

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap');
html, body {{ font-family: 'Inter', sans-serif; background-color: #f8f9fa; }}
.block-container {{ padding-top: 1rem !important; padding-bottom: 2rem !important; padding-left: 1rem !important; padding-right: 1rem !important; max-width: 100% !important; }}
.kpi-card {{ background: white; border: 1px solid #e0e0e0; border-radius: 12px; padding: 15px; text-align: center; box-shadow: 0 2px 6px rgba(0,0,0,0.05); margin-bottom: 15px; height: 100%; display: flex; flex-direction: column; justify-content: center; transition: transform 0.2s; }}
.kpi-card:active {{ transform: scale(0.98); }}
.kpi-title {{ font-size: 0.8rem; color: #666; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }}
.kpi-value {{ font-size: 2rem; font-weight: 800; margin-top: 5px; word-break: break-word; }}
.retailer-header {{ font-size: 1.2rem; font-weight: 800; color: white; padding: 10px 15px; border-radius: 8px; margin: 15px 0; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.1); text-shadow: 0 1px 2px rgba(0,0,0,0.2); }}
div[data-testid="stHorizontalBlock"] button {{ border-radius: 10px !important; font-weight: 700 !important; text-transform: uppercase; transition: all 0.15s ease-in-out !important; border: none !important; }}
div[data-testid="stHorizontalBlock"]:nth-of-type(2) [data-testid="stColumn"]:nth-of-type(1) button {{ background: linear-gradient(135deg, #D32F2F, #B71C1C) !important; color: white !important; {css_styles['SORIANA']} }}
div[data-testid="stHorizontalBlock"]:nth-of-type(2) [data-testid="stColumn"]:nth-of-type(2) button {{ background: linear-gradient(135deg, #0071DC, #005BB5) !important; color: white !important; {css_styles['WALMART']} }}
div[data-testid="stHorizontalBlock"]:nth-of-type(3) [data-testid="stColumn"]:nth-of-type(1) button {{ background: linear-gradient(135deg, #FF6600, #E65100) !important; color: white !important; {css_styles['CHEDRAUI']} }}
div[data-testid="stHorizontalBlock"]:nth-of-type(3) [data-testid="stColumn"]:nth-of-type(2) button {{ background: linear-gradient(135deg, #CCFF00, #AACC00) !important; color: #444 !important; {css_styles['FRESKO']} }}
.btn-ranking-blue {{ background-color: #0071DC !important; color: white !important; border: 2px solid white !important; }}
.btn-ranking-orange {{ background-color: #FF8C00 !important; color: white !important; border: 2px solid white !important; }}
.btn-ranking-olive {{ background-color: #808000 !important; color: white !important; border: 2px solid white !important; }}
.btn-ranking-green {{ background-color: #28a745 !important; color: #FFC220 !important; border: 2px solid #FFC220 !important; }}
.dias-inv-style > button {{ background-color: #28a745 !important; color: white !important; }}

@media (max-width: 768px) {{
    .block-container {{ padding-left: 0.5rem !important; padding-right: 0.5rem !important; }}
    div[data-testid="stHorizontalBlock"] button {{ height: 60px !important; font-size: 0.85rem !important; min-height: auto !important; }}
    .kpi-value {{ font-size: 1.5rem !important; }}
    .kpi-title {{ font-size: 0.7rem !important; }}
    .retailer-header {{ font-size: 1rem; padding: 8px; margin: 10px 0; }}
    section[data-testid="stSidebar"] {{ display: none; }}
    canvas {{ max-width: 100% !important; }}
}}
@media (min-width: 769px) {{
    div[data-testid="stHorizontalBlock"] button {{ height: 90px !important; font-size: 1.1rem !important; }}
}}
</style>
""", unsafe_allow_html=True)

# --- 6. HEADER ---
c_head1, c_head2 = st.columns([1, 5])
with c_head1:
    try: st.image("ragasa_logo.png", use_container_width=True)
    except: st.write("📦")
with c_head2:
    st.markdown("""
        <div style='display: flex; flex-direction: column; justify-content: center; height: 100%;'>
            <h2 style='margin:0; font-weight: 800; color: #333;'>RETAIL MANAGER</h2>
            <p style='margin:0; font-size: 0.9rem; color: #666;'>Control de Inventarios y Ventas</p>
        </div>
    """, unsafe_allow_html=True)

status_txt = 'CONECTADO' if st.session_state.is_online else 'OFFLINE'
status_color = "#28a745" if st.session_state.is_online else "#dc3545"
st.markdown(f"<div style='text-align:right; font-size:0.7rem; color:{status_color}; font-weight:bold; margin-bottom:5px;'>● {status_txt}</div>", unsafe_allow_html=True)

# --- 7. NAVEGACIÓN ---
col1, col2 = st.columns(2, gap="small")
with col1: st.button("SORIANA", on_click=set_retailer, args=("SORIANA",), use_container_width=True, key="nav_sor")
with col2: st.button("WALMART", on_click=set_retailer, args=("WALMART",), use_container_width=True, key="nav_wal")

col3, col4 = st.columns(2, gap="small")
with col3: st.button("CHEDRAUI", on_click=set_retailer, args=("CHEDRAUI",), use_container_width=True, key="nav_che")
with col4: st.button("FRESKO", on_click=set_retailer, args=("FRESKO",), use_container_width=True, key="nav_fre")

st.markdown("<hr style='margin: 15px 0; border: 0; border-top: 1px solid #eee;'>", unsafe_allow_html=True)

# --- 8. VISTAS POR RETAILER ---

def view_soriana(df_s):
    st.markdown(f"<div class='retailer-header' style='background-color: {RETAILER_COLORS['SORIANA']}'>SORIANA</div>", unsafe_allow_html=True)
    
    s_vars = ['s_rojo', 's_dias_inv', 's_dias_prod', 's_rank_gen', 's_rank_pas', 's_rank_oli', 's_rank_nut']
    for v in s_vars:
        if v not in st.session_state: st.session_state[v] = False
    
    def tog_s_rojo(): 
        st.session_state.s_rojo = not st.session_state.s_rojo
        st.session_state.s_dias_inv = False
        st.session_state.s_dias_prod = False
    def tog_s_dias_inv():
        st.session_state.s_dias_inv = not st.session_state.s_dias_inv
        st.session_state.s_rojo = False
        st.session_state.s_dias_prod = False
    def tog_s_dias_prod():
        st.session_state.s_dias_prod = not st.session_state.s_dias_prod
        st.session_state.s_rojo = False
        st.session_state.s_dias_inv = False

    def set_s_rank(mode):
        for v in ['s_rank_gen', 's_rank_pas', 's_rank_oli', 's_rank_nut']: st.session_state[v] = False
        if mode == 'GEN': st.session_state.s_rank_gen = True
        elif mode == 'PAS': st.session_state.s_rank_pas = True
        elif mode == 'OLI': st.session_state.s_rank_oli = True
        elif mode == 'NUT': st.session_state.s_rank_nut = True

    if df_s is not None:
        with st.expander("🔍 Filtros Avanzados", expanded=True):
            c1, c2 = st.columns(2)
            with c1:
                opts_res = ["Todos"] + sorted(df_s["RESURTIMIENTO"].astype(str).unique())
                def_res = ["1.0"] if "1.0" in opts_res else ["Todos"]
                fil_res = st.multiselect("Resurtible", opts_res, default=def_res)
                
                fil_nda = st.multiselect("No Tienda", sorted(df_s["NO_TIENDA"].astype(str).unique()))
                fil_nom = st.multiselect("Nombre", sorted(df_s["TIENDA"].astype(str).unique()))
                fil_cat = st.multiselect("Categoría", sorted(df_s["CATEGORIA"].astype(str).unique()))
            with c2:
                fil_cd = st.multiselect("Ciudad", sorted(df_s["CIUDAD"].astype(str).unique()))
                fil_edo = st.multiselect("Estado", sorted(df_s["ESTADO"].astype(str).unique()))
                fil_fmt = st.multiselect("Formato", sorted(df_s["FORMATO"].astype(str).unique()))
                fil_art = st.multiselect("Artículo", sorted(df_s["DESCRIPCION"].astype(str).unique()))

        dff = apply_filters(df_s, 
            ["RESURTIMIENTO", "NO_TIENDA", "TIENDA", "CATEGORIA", "CIUDAD", "ESTADO", "FORMATO", "DESCRIPCION"], 
            [fil_res if "Todos" not in fil_res else None, fil_nda, fil_nom, fil_cat, fil_cd, fil_edo, fil_fmt, fil_art]
        )

        b1, b2, b3 = st.columns(3, gap="small")
        with b1: st.button("🔴 INV SIN VENTA", on_click=tog_s_rojo, use_container_width=True, type="primary", key="btn_sor_rojo")
        with b2: 
            st.markdown(f'<div class="{"rank-green-on" if st.session_state.s_dias_inv else "dias-inv-style"}">', unsafe_allow_html=True)
            st.button("📅 DIAS INV", on_click=tog_s_dias_inv, use_container_width=True, key="btn_sor_dias")
            st.markdown('</div>', unsafe_allow_html=True)
        with b3:
            st.markdown(f'<div class="{"rank-green-on" if st.session_state.s_dias_prod else "dias-inv-style"}">', unsafe_allow_html=True)
            st.button("📋 DIAS X PROD", on_click=tog_s_dias_prod, use_container_width=True, key="btn_sor_prod")
            st.markdown('</div>', unsafe_allow_html=True)

        if st.session_state.s_dias_prod:
            st.subheader("📋 Días Inventario x Producto")
            target_list = [
                "ACEITE DE SOYA NUTRIOLI BOT 850 ML", "ACEITE COMESTIBLE NUTRIOLI 400 ML",
                "ACEITE COMESTIBLE SABROSANO 850 ML", "ACEITE COMESTIBLE GRAN TRADICION 800 ML",
                "ACEITE NUTRIOLI PROTECT DEFENSAS 850ML", "ACEITE NUTRIOLI PROTECT MENTE 850 ML",
                "ACEITE COMESTIBLE NUTRIOLI AEROSOL 180ML", "ACEITE COMESTIBLE NUTRIOLI ANTIGOTEO 700",
                "ACEITE OLI OLIVA EXTRA VIRGEN PZ 250ML", "ACEITE OLI OLIVA EXTRA VIRGEN PZ 500ML",
                "ACEITE OLI OLIVA EXTRA VIRGEN PZ 750ML", "ADERE OLI OLIVA PARA COCINAR 500 ML OLI",
                "ADERE OLI OLIVA PARA COCINAR 750 ML OLI", "ADEREZO OLI 250 ML PZ",
                "ADEREZO OLI 500 ML BOT", "ACEITE COMESTIBLE AVE 850 ML",
                "ACEITE COMESTIBLE AEROSOL 170GR", "ACEITE COMESTIBLE NUTRIOLI AEROSOL 180ML",
                "ACEITE OLIVA OLI PURO SPRAY 145 ML", "ACEITE OLIVA OLI EV SPRAY 145 ML",
                "PASTA FIDEO NUTRIOLI 200GR", "PASTA SPAGHETTI NUTRIOLI INTEGRAL 200GR",
                "PASTA FUSILLI INTEGRAL NUTRIOLI 200GR", "PASTA CODO NUTRIOLI VERDURAS 200GR",
                "PASTA FUSILLI VERDURAS NUTRIOLI 450GR", "PASTA SPAGHETTI NUTRIOLI 200GR",
                "PASTA CODO NUTRIOLI 200GR", "VINAGRE BALSAMICO 250ML"
            ]
            res_rows = []
            dff['DESC_CLEAN'] = dff["DESCRIPCION"].astype(str).str.upper().str.replace(r'&NBSP;', ' ', regex=True).str.strip()
            
            for item in target_list:
                clean_item = item.strip()
                mask = dff['DESC_CLEAN'].str.contains(clean_item, case=False, regex=False)
                if mask.any():
                    subset = dff[mask]
                    avg_days = subset["DIAS_INV"].mean()
                    code = subset["CODIGO"].iloc[0]
                    res_rows.append({"CODIGO": code, "ARTICULO": item, "DIAS INV": avg_days})
                else:
                    res_rows.append({"CODIGO": "-", "ARTICULO": item, "DIAS INV": 0})
            st.dataframe(pd.DataFrame(res_rows).style.format({'DIAS INV': "{:,.1f}"}), use_container_width=True, hide_index=True)

        elif st.session_state.s_dias_inv:
            st.subheader("📅 Reporte Días Inventario")
            val_nut = get_kpi_mean(dff, "DESCRIPCION", "DIAS_INV", "ACEITE DE SOYA NUTRIOLI BOT 850 ML")
            val_sab = get_kpi_mean(dff, "DESCRIPCION", "DIAS_INV", "ACEITE COMESTIBLE SABROSANO 850 ML")
            mask_pastas = dff["DESCRIPCION"].astype(str).str.contains("PASTA", case=False, na=False)
            val_pas = dff.loc[mask_pastas, "DIAS_INV"].mean() if mask_pastas.any() else 0
            
            k1, k2, k3 = st.columns(3)
            k1.markdown(f"<div class='kpi-card'><div class='kpi-title'>NUTRIOLI 850ML</div><div class='kpi-value' style='color:#28a745;'>{val_nut:,.1f}</div></div>", unsafe_allow_html=True)
            k2.markdown(f"<div class='kpi-card'><div class='kpi-title'>SABROSANO 850ML</div><div class='kpi-value' style='color:#E4007C;'>{val_sab:,.1f}</div></div>", unsafe_allow_html=True)
            k3.markdown(f"<div class='kpi-card'><div class='kpi-title'>PASTAS</div><div class='kpi-value' style='color:#64DD17;'>{val_pas:,.1f}</div></div>", unsafe_allow_html=True)
            
            disp_sor_dias = dff[["NO_TIENDA", "TIENDA", "CODIGO", "DESCRIPCION", "INV_CAJAS", "SO_$", "SO_4SEM", "DIAS_INV"]].copy()
            disp_sor_dias.columns = ['No.', 'TIENDA', 'CODIGO', 'ARTICULO', 'INV CAJAS', 'SELL OUT SEM', 'SELL OUT ULT 4 SEM', 'DIAS INV']
            st.dataframe(disp_sor_dias.style.format({'INV CAJAS': "{:,.0f}", 'SELL OUT SEM': '${:,.2f}', 'SELL OUT ULT 4 SEM': '${:,.2f}', 'DIAS INV': "{:,.1f}"}), use_container_width=True, hide_index=True)
            
        else:
            # --- VISTA PRINCIPAL SORIANA: SELL OUT ---
            def get_soriana_category(desc):
                desc = str(desc).upper().replace(" ", "")
                if "SABROSANO" in desc: return "SABROSANO"
                if "GRANTRADICION" in desc: return "GT"
                if "BALSAMICO" in desc: return "BALSAMICO"
                if "MISAZON" in desc or "MISAZÓN" in desc: return "MI SAZON"
                if "AVE" in desc: return "AVE"
                if "NUTRIOLI" in desc and any(k in desc for k in ["FUSILLI", "SPAGUETTI", "FIDEO", "CODO", "PASTA"]): return "PASTAS"
                if "OLI" in desc and ("OLIVA" in desc or "EV" in desc or "AEROSOL" in desc or "ADEREZO" in desc): return "OLIVAS"
                if "NUTRIOLI" in desc and ("400ML" in desc or "850ML" in desc) and "PROTECT" not in desc and "DEFENSAS" not in desc: return "NUTRIOLI"
                if "NUTRIOLI" in desc: return "REST NUTRIOLI"
                return None

            c_kpi, c_chart = st.columns([1, 2])
            with c_kpi:
                total_so = dff['SO_$'].sum()
                st.markdown(f"<div class='kpi-card' style='height: 300px;'><div class='kpi-title'>Total Sell Out Semanal</div><div class='kpi-value' style='color:#D32F2F;'>${total_so:,.2f}</div></div>", unsafe_allow_html=True)
            
            with c_chart:
                chart_data = dff.copy()
                chart_data['Category'] = chart_data['DESCRIPCION'].apply(get_soriana_category)
                pie_df = chart_data.dropna(subset=['Category']).groupby('Category')['SO_$'].sum().reset_index()
                pie_df = pie_df[pie_df['SO_$'] > 0]
                total_pie = pie_df['SO_$'].sum()
                
                if not pie_df.empty:
                    domain = ["BALSAMICO", "SABROSANO", "PASTAS", "OLIVAS", "GT", "NUTRIOLI", "MI SAZON", "AVE", "REST NUTRIOLI"]
                    range_ = ["#e012a9", "#f705ab", "#4c915d", "#97ad6a", "#7d6010", "#02c705", "#e89015", "#ff0000", "#00ff04"]
                    
                    base = alt.Chart(pie_df).encode(theta=alt.Theta(field="SO_$", type="quantitative", stack=True)).properties(height=300)
                    pie = base.mark_arc(innerRadius=60, outerRadius=100).encode(
                        color=alt.Color(field="Category", type="nominal", scale=alt.Scale(domain=domain, range=range_), legend=None),
                        order=alt.Order("SO_$", sort="descending"),
                        tooltip=['Category', alt.Tooltip('SO_$', format='$,.2f')]
                    )
                    text = base.mark_text(radius=130, fontSize=11).encode(
                        text=alt.Text("label_text:N"), order=alt.Order("SO_$", sort="descending"), color=alt.value("black")
                    ).transform_calculate(label_text="datum.Category + ': $' + format(datum['SO_$'], ',.0f')").transform_filter(alt.datum['SO_$'] > (total_pie * 0.02))
                    st.altair_chart(pie + text, use_container_width=True)
                else: st.info("Sin datos para gráfica.")

            if st.session_state.s_rojo: 
                dff = dff[dff['SIN_VTA']]
                st.caption("📋 Vista: Sin Venta")
            
            # Tabla Unificada Soriana
            disp = dff[["NO_TIENDA", "TIENDA", "CODIGO", "DESCRIPCION", "INV_CAJAS", "SO_$", "SO_4SEM", "DIAS_INV"]].copy()
            disp.columns = ['No.', 'TIENDA', 'CODIGO', 'ARTICULO', 'INV CAJAS', 'SELL OUT SEM', 'SELL OUT ULT 4 SEM', 'DIAS INV']
            
            # Ordenamos por Venta 
            disp = disp.sort_values(by='SELL OUT ULT 4 SEM', ascending=False)
            
            whatsapp_report("SORIANA Reporte", disp)
            st.dataframe(disp.style.format({'INV CAJAS': "{:,.0f}", 'SELL OUT SEM': '${:,.2f}', 'SELL OUT ULT 4 SEM': '${:,.2f}', 'DIAS INV': "{:,.1f}"}), use_container_width=True, hide_index=True)

        # --- RANKING SORIANA ---
        st.divider()
        st.markdown("<h3 style='text-align: center; color: #444;'>🏆 RANKING DE VENTAS</h3>", unsafe_allow_html=True)
        
        s_mod1, s_mod2 = st.columns(2)
        with s_mod1: sel_s_rank_st = st.multiselect("Estado (Ranking)", sorted(df_s["ESTADO"].astype(str).unique()), key="s_rnk_st")
        with s_mod2: sel_s_rank_fmt = st.multiselect("Formato (Ranking)", sorted(df_s["FORMATO"].astype(str).unique()), key="s_rnk_fmt")

        sr1, sr2 = st.columns(2, gap="small")
        with sr1:
            st.markdown('<div class="btn-ranking-blue">', unsafe_allow_html=True)
            if st.button("📊 GENERAL", key="s_rk_gen", use_container_width=True): set_s_rank('GEN')
            st.markdown('</div>', unsafe_allow_html=True)
        with sr2:
            st.markdown('<div class="btn-ranking-orange">', unsafe_allow_html=True)
            if st.button("🍝 PASTAS", key="s_rk_pas", use_container_width=True): set_s_rank('PAS')
            st.markdown('</div>', unsafe_allow_html=True)
        
        sr3, sr4 = st.columns(2, gap="small")
        with sr3:
            st.markdown('<div class="btn-ranking-olive">', unsafe_allow_html=True)
            if st.button("🫒 OLIVAS", key="s_rk_oli", use_container_width=True): set_s_rank('OLI')
            st.markdown('</div>', unsafe_allow_html=True)
        with sr4:
            st.markdown('<div class="btn-ranking-green">', unsafe_allow_html=True)
            if st.button("🍃 NUTRIOLI", key="s_rk_nut", use_container_width=True): set_s_rank('NUT')
            st.markdown('</div>', unsafe_allow_html=True)
            
        dff_s_rank = apply_filters(df_s, ["ESTADO", "FORMATO"], [sel_s_rank_st, sel_s_rank_fmt])

        list_s_gen = [
            "ACEITE COMESTIBLE NUTRIOLI ANTIGOTEO 700", "ACEITE COMESTIBLE GRAN TRADICION 900 ML", "ACEITE COMESTIBLE SABROSANO +30 850 ML", 
            "ACEITE OLIVA OLI PURO SPRAY 145 ML", "JUSTO 850 ML", "ACEITE COMESTIBLE AEROSOL 170GR", "ACEITE COMESTIBLE AVE 850 ML", 
            "ACEITE COMESTIBLE NUTRIOLI 400 ML", "ACEITE COMESTIBLE NUTRIOLI AEROSOL 180ML", "ACEITE COMESTIBLE NUTRIOLI DHA 850 ML", 
            "ACEITE COMESTIBLE SABROSANO 850 ML", "SABROSANO RINDE+ 850 ML", "ACEITE OLI OLIVA EXTRA VIRGEN PZ 250ML", 
            "ACEITE OLI OLIVA EXTRA VIRGEN PZ 500ML", "ACEITE OLI OLIVA EXTRA VIRGEN PZ 750ML", "ADERE OLI OLIVA PARA COCINAR 500 ML OLI", 
            "ADERE OLI OLIVA PARA COCINAR 750 ML OLI", "ADEREZO OLI 250 ML PZ", "ADEREZO OLI 500 ML BOT", "ACEITE COMESTIBLE GRAN TRADICION 800 ML", 
            "ACEITE DE SOYA NUTRIOLI BOT 850 ML", "VINAGRE BALSAMICO 250ML", "ACEITE NUTRIOLI PROTECT DEFENSAS 850ML", 
            "ACEITE NUTRIOLI PROTECT MENTE 850 ML", "PASTA FIDEO NUTRIOLI 200GR", "PASTA SPAGHETTI NUTRIOLI INTEGRAL 200GR", 
            "PASTA FUSILLI INTEGRAL NUTRIOLI 200GR", "PASTA CODO NUTRIOLI VERDURAS 200GR", "PASTA FUSILLI VERDURAS NUTRIOLI 450GR", 
            "PASTA SPAGHETTI NUTRIOLI 200GR", "PASTA CODO NUTRIOLI 200GR"
        ]
        list_s_pas = [
            "PASTA FIDEO NUTRIOLI 200GR", "PASTA SPAGHETTI NUTRIOLI INTEGRAL 200GR", "PASTA FUSILLI INTEGRAL NUTRIOLI 200GR", 
            "PASTA CODO NUTRIOLI VERDURAS 200GR", "PASTA FUSILLI VERDURAS NUTRIOLI 450GR", "PASTA SPAGHETTI NUTRIOLI 200GR", 
            "PASTA CODO NUTRIOLI 200GR"
        ]
        list_s_oli = [
            "ACEITE OLI OLIVA EXTRA VIRGEN PZ 250ML", "ACEITE OLI OLIVA EXTRA VIRGEN PZ 500ML", "ACEITE OLI OLIVA EXTRA VIRGEN PZ 750ML", 
            "ADERE OLI OLIVA PARA COCINAR 500 ML OLI", "ADERE OLI OLIVA PARA COCINAR 750 ML OLI", "ADEREZO OLI 250 ML PZ", 
            "ADEREZO OLI 500 ML BOT", "ACEITE OLIVA OLI PURO SPRAY 145 ML"
        ]
        list_s_nut = ["ACEITE DE SOYA NUTRIOLI BOT 850 ML"]

        target_list_s = []
        rank_title_s = ""
        if st.session_state.s_rank_gen: target_list_s = list_s_gen; rank_title_s = "VENTA GENERAL ($)"
        elif st.session_state.s_rank_pas: target_list_s = list_s_pas; rank_title_s = "VENTA PASTAS ($)"
        elif st.session_state.s_rank_oli: target_list_s = list_s_oli; rank_title_s = "VENTA OLIVAS ($)"
        elif st.session_state.s_rank_nut: target_list_s = list_s_nut; rank_title_s = "VENTA NUTRIOLI ($)"

        if target_list_s:
            dff_s_rank['DESC_CLEAN'] = dff_s_rank['DESCRIPCION'].astype(str).str.strip()
            target_list_s_clean = [t.strip() for t in target_list_s]
            
            dff_sub = dff_s_rank[dff_s_rank["DESC_CLEAN"].isin(target_list_s_clean)]
            if not dff_sub.empty:
                final_s_rank = dff_sub.groupby(["NO_TIENDA", "TIENDA"])['SO_$'].sum().reset_index()
                final_s_rank.columns = ['No Tienda', 'TIENDA', rank_title_s]
                st.dataframe(final_s_rank.sort_values(by=rank_title_s, ascending=False).style.format({rank_title_s: "${:,.2f}"}), use_container_width=True, hide_index=True)
            else:
                st.warning("⚠️ No se encontraron ventas para los productos seleccionados.")

def view_walmart(df_w):
    st.markdown(f"<div class='retailer-header' style='background-color: {RETAILER_COLORS['WALMART']}'>WALMART</div>", unsafe_allow_html=True)
    w_vars = ['w_neg', 'w_4w', 'w_dias_inv', 'w_dias_prod', 'w_rank_tiendas', 'w_rank_pastas', 'w_rank_olivas', 'w_nutri_top10']
    for v in w_vars: 
        if v not in st.session_state: st.session_state[v] = False
    
    def tog_w(target):
        for v in ['w_neg', 'w_4w', 'w_dias_inv', 'w_dias_prod']:
            st.session_state[v] = True if v == target and not st.session_state[v] else False

    def set_rank(mode):
        for v in ['w_rank_tiendas', 'w_rank_pastas', 'w_rank_olivas', 'w_nutri_top10']: st.session_state[v] = False
        if mode == 'tiendas': st.session_state.w_rank_tiendas = True
        elif mode == 'pastas': st.session_state.w_rank_pastas = True
        elif mode == 'olivas': st.session_state.w_rank_olivas = True
        elif mode == 'nutrioli': st.session_state.w_nutri_top10 = True

    if df_w is not None:
        df_w = df_w[~df_w["FORMATO"].isin(['BAE','MB'])]
        with st.expander("🔍 Filtros Avanzados", expanded=True):
            c1, c2 = st.columns(2)
            with c1:
                sel_state = st.multiselect("Estado", sorted(df_w["ESTADO"].astype(str).unique()))
                unique_stores = sorted(df_w[df_w["ESTADO"].isin(sel_state)]["TIENDA"].astype(str).unique()) if sel_state else sorted(df_w["TIENDA"].astype(str).unique())
                sel_store = st.multiselect("Tienda", unique_stores)
            with c2:
                sel_fmt = st.multiselect("Formato", sorted(df_w["FORMATO"].astype(str).unique()))
                sel_prod = st.multiselect("Producto", sorted(df_w["DESCRIPCION"].astype(str).unique()))

        dff_kpi = apply_filters(df_w, ["ESTADO", "TIENDA", "FORMATO"], [sel_state, sel_store, sel_fmt])
        dff = apply_filters(dff_kpi, ["DESCRIPCION"], [sel_prod])

        b1, b2, b3 = st.columns(3, gap="small")
        with b1: st.button("📉 NEGATIVOS", on_click=tog_w, args=('w_neg',), key="btn_w_neg", use_container_width=True)
        with b2: st.button("🔴 SIN VTA 4SEM", on_click=tog_w, args=('w_4w',), key="btn_w_4w", use_container_width=True)
        with b3: 
            st.markdown(f'<div class="{"rank-green-on" if st.session_state.w_dias_inv else "dias-inv-style"}">', unsafe_allow_html=True)
            st.button("📅 DIAS INV", on_click=tog_w, args=('w_dias_inv',), key="btn_w_dias", use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
        
        br1, br2 = st.columns(2, gap="small")
        with br1:
            st.markdown(f'<div class="{"rank-green-on" if st.session_state.w_dias_prod else "dias-inv-style"}">', unsafe_allow_html=True)
            st.button("📋 DIAS X PROD", on_click=tog_w, args=('w_dias_prod',), key="btn_w_dias_prod", use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)

        if st.session_state.w_neg: dff = dff[dff["EXISTENCIA"] < 0]; st.warning("VISTA: NEGATIVOS")
        if st.session_state.w_4w: dff = dff[(dff.iloc[:,73]==0)&(dff.iloc[:,74]==0)&(dff.iloc[:,75]==0)&(dff.iloc[:,76]==0)]; st.warning("VISTA: SIN VENTA 4 SEMANAS")

        def get_walmart_category(desc):
            desc = str(desc).upper().replace(" ", "")
            if "NUTRIOLI946M" in desc: return "NUTRIOLI"
            if "SABROSANO" in desc: return "SABROSANO"
            if "GRANTRADICION" in desc: return "GT"
            if "BALSAMICO" in desc: return "BALSAMICO"
            if any(k in desc for k in ["OLISPRAY", "OLICOCINA", "OLIDENUTEV", "ACEITEOLIDEOLIVA", "OLIDENUT"]) and "BALSAMICO" not in desc: return "OLIVAS"
            if "NUTRIOLI" in desc and any(x in desc for x in ["SPAGUETTI", "FIDEO", "CODO", "PASTA"]): return "PASTAS"
            if "NUTRIOLI" in desc: return "REST NUTRIOLI"
            return None

        if st.session_state.w_dias_prod:
            st.subheader("📋 Días Inventario x Producto")
            target_list = ["ACEITE NUTRIOLI 946M", "GRANTRADICION 850ML", "SABROSANO 850ML", "ACEITE AVE 850", "NUTRIOLI ACEITE PURO DE SOYA 400 ML", "NUTRIOLI ACEITE PROTECT MENTE 850 ML", "ACEITE NUTRIOLI DEFENSAS 850 ML", "NUTRIOLI ACEITE SOYA (Antigoteo)", "OLI DE NUT EV 250ML", "OLI DE NUT EV 500ML", "OLI DE NUT EV 750ML", "OLI COCINA 250ML", "OLI COCINA 500ML", "OLI COCINA 750ML", "ACEITE OLI DE OLIVA EX VIRGEN ORGANICO", "SPRAY NUTRIOLI 180ML", "AVE AEROSOL", "OLI SPRAY ACEITE DE OLIVA 145ML", "OLI VINAGRE BALSAMICO 250ML"]
            res_rows = []
            dff_kpi['DESC_CLEAN'] = dff_kpi["DESCRIPCION"].astype(str).str.upper().str.replace(r'&NBSP;', ' ', regex=True)
            for item in target_list:
                clean_item = item.replace(" ", "")
                mask = dff_kpi['DESC_CLEAN'].str.replace(" ", "").str.contains(clean_item, case=False, regex=False)
                if mask.any():
                    subset = dff_kpi[mask]
                    avg_days = subset["DIAS_INV"].mean()
                    code = subset["CODIGO"].iloc[0]
                    res_rows.append({"CODIGO": code, "ARTICULO": item, "DIAS INV": avg_days})
                else:
                    res_rows.append({"CODIGO": "-", "ARTICULO": item, "DIAS INV": 0})
            st.dataframe(pd.DataFrame(res_rows).style.format({'DIAS INV': "{:,.1f}"}), use_container_width=True, hide_index=True)

        elif st.session_state.w_dias_inv:
            st.subheader("📅 Reporte Días Inventario")
            val_nutri = get_kpi_mean(dff_kpi, "DESCRIPCION", "DIAS_INV", "NUTRIOLI 946M")
            val_sabro = get_kpi_mean(dff_kpi, "DESCRIPCION", "DIAS_INV", "SABROSANO 850ML")
            val_ave = get_kpi_mean(dff_kpi, "DESCRIPCION", "DIAS_INV", "ACEITE AVE 850")
            val_gran = get_kpi_mean(dff_kpi, "DESCRIPCION", "DIAS_INV", "GRANTRADICION")
            
            m1, m2, m3, m4 = st.columns(4)
            m1.markdown(f"<div class='kpi-card'><div class='kpi-title'>NUTRIOLI 946M</div><div class='kpi-value' style='color:#28a745;'>{val_nutri:,.1f}</div></div>", unsafe_allow_html=True)
            m2.markdown(f"<div class='kpi-card'><div class='kpi-title'>SABROSANO 850ML</div><div class='kpi-value' style='color:#E4007C;'>{val_sabro:,.1f}</div></div>", unsafe_allow_html=True)
            m3.markdown(f"<div class='kpi-card'><div class='kpi-title'>AVE 850ML</div><div class='kpi-value' style='color:#D32F2F;'>{val_ave:,.1f}</div></div>", unsafe_allow_html=True)
            m4.markdown(f"<div class='kpi-card'><div class='kpi-title'>GRAN TRADICION</div><div class='kpi-value' style='color:#8B4513;'>{val_gran:,.1f}</div></div>", unsafe_allow_html=True)
            st.dataframe(dff[["TIENDA", "CODIGO", "DESCRIPCION", "DIAS_INV"]].rename(columns={"DIAS_INV":"DIAS INVENTARIO"}).style.format({'DIAS INVENTARIO': "{:,.1f}"}), use_container_width=True, hide_index=True)
            
        else:
            c_kpi, c_chart = st.columns([1, 2])
            with c_kpi:
                total_so = dff['SO_$'].sum()
                st.markdown(f"<div class='kpi-card' style='height: 300px;'><div class='kpi-title'>Total Sell Out</div><div class='kpi-value' style='color:#28a745;'>${total_so:,.2f}</div></div>", unsafe_allow_html=True)
            with c_chart:
                chart_data = dff.copy()
                chart_data['Category'] = chart_data['DESCRIPCION'].apply(get_walmart_category)
                pie_df = chart_data.dropna(subset=['Category']).groupby('Category')['SO_$'].sum().reset_index()
                pie_df = pie_df[pie_df['SO_$'] > 0]
                total_pie = pie_df['SO_$'].sum()
                
                if not pie_df.empty:
                    domain = ["SABROSANO", "GT", "OLIVAS", "BALSAMICO", "PASTAS", "REST NUTRIOLI", "NUTRIOLI"]
                    range_ = ["#E4007C", "#a18262", "#6B8E23", "#9f4576", "#426045", "#bfff00", "#008f39"]
                    base = alt.Chart(pie_df).encode(theta=alt.Theta(field="SO_$", type="quantitative", stack=True)).properties(height=300)
                    pie = base.mark_arc(innerRadius=60, outerRadius=100).encode(
                        color=alt.Color(field="Category", type="nominal", scale=alt.Scale(domain=domain, range=range_), legend=None),
                        order=alt.Order("SO_$", sort="descending"),
                        tooltip=['Category', alt.Tooltip('SO_$', format='$,.2f')]
                    )
                    text = base.mark_text(radius=130, fontSize=11).encode(
                        text=alt.Text("label_text:N"), order=alt.Order("SO_$", sort="descending"), color=alt.value("black")
                    ).transform_calculate(label_text="datum.Category + ': $' + format(datum['SO_$'], ',.0f')").transform_filter(alt.datum['SO_$'] > (total_pie * 0.02))
                    st.altair_chart(pie + text, use_container_width=True)
                else: st.info("Sin datos para gráfica.")

            disp = dff[["CODIGO", "DESCRIPCION", "TIENDA", "EXISTENCIA", "SO_$", "PROM_PZS_MENSUAL"]].copy()
            disp.columns = ['CODIGO', 'DESCRIPCION', 'TIENDA', 'EXISTENCIA', 'SELL OUT', 'PROM PZS MENSUAL']
            whatsapp_report("WALMART Reporte", disp)
            st.dataframe(disp.style.format({'SELL OUT': '${:,.2f}', 'PROM PZS MENSUAL': '{:,.2f}'}), use_container_width=True, hide_index=True)

        st.divider()
        st.markdown("<h3 style='text-align: center; color: #444;'>🏆 RANKING DE VENTAS</h3>", unsafe_allow_html=True)
        c_mod1, c_mod2 = st.columns(2)
        with c_mod1: sel_st_rank = st.multiselect("Estado (Ranking)", sorted(df_w["ESTADO"].astype(str).unique()), key="rnk_st")
        with c_mod2: sel_fmt_rank = st.multiselect("Formato (Ranking)", sorted(df_w["FORMATO"].astype(str).unique()), key="rnk_fmt")
        
        r1, r2 = st.columns(2, gap="small")
        with r1:
            st.markdown('<div class="btn-ranking-blue">', unsafe_allow_html=True)
            if st.button("📊 GENERAL", key="rk_gen", use_container_width=True): set_rank('tiendas')
            st.markdown('</div>', unsafe_allow_html=True)
        with r2:
            st.markdown('<div class="btn-ranking-orange">', unsafe_allow_html=True)
            if st.button("🍝 PASTAS", key="rk_pas", use_container_width=True): set_rank('pastas')
            st.markdown('</div>', unsafe_allow_html=True)
        r3, r4 = st.columns(2, gap="small")
        with r3:
            st.markdown('<div class="btn-ranking-olive">', unsafe_allow_html=True)
            if st.button("🫒 OLIVAS", key="rk_oli", use_container_width=True): set_rank('olivas')
            st.markdown('</div>', unsafe_allow_html=True)
        with r4:
            st.markdown('<div class="btn-ranking-green">', unsafe_allow_html=True)
            if st.button("🏆 NUTRIOLI", key="rk_nut", use_container_width=True): set_rank('nutrioli')
            st.markdown('</div>', unsafe_allow_html=True)
            
        dff_rank = apply_filters(df_w, ["ESTADO", "FORMATO"], [sel_st_rank, sel_fmt_rank])
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
            df_sub = dff_rank[dff_rank["DESCRIPCION"].str.contains("NUTRIOLI 946M", case=False, na=False)]
            if not df_sub.empty: final_rank = df_sub.groupby("TIENDA")['SO_$'].sum().reset_index().rename(columns={'SO_$':'VENTA NUTRIOLI ($)'}).sort_values(by='VENTA NUTRIOLI ($)', ascending=False).head(10)
        
        if final_rank is not None:
            st.dataframe(final_rank.sort_values(by=final_rank.columns[1], ascending=False).style.format({final_rank.columns[1]: "${:,.2f}"}), use_container_width=True, hide_index=True)

def view_chedraui(df_c):
    st.markdown(f"<div class='retailer-header' style='background-color: {RETAILER_COLORS['CHEDRAUI']}'>CHEDRAUI</div>", unsafe_allow_html=True)
    c_vars = ['c_neg_zero', 'c_under_10', 'c_dias_inv', 'c_rank_gen', 'c_rank_pas', 'c_rank_oli', 'c_rank_nut']
    for v in c_vars:
        if v not in st.session_state: st.session_state[v] = False
    
    def tog_c(target):
        for v in ['c_neg_zero', 'c_under_10', 'c_dias_inv']:
            st.session_state[v] = True if v == target and not st.session_state[v] else False

    def set_c_rank(mode):
        for v in ['c_rank_gen', 'c_rank_pas', 'c_rank_oli', 'c_rank_nut']: st.session_state[v] = False
        if mode == 'GEN': st.session_state.c_rank_gen = True
        elif mode == 'PAS': st.session_state.c_rank_pas = True
        elif mode == 'OLI': st.session_state.c_rank_oli = True
        elif mode == 'NUT': st.session_state.c_rank_nut = True

    if df_c is not None:
        with st.expander("🔍 Filtros Avanzados", expanded=True):
            c1, c2 = st.columns(2)
            with c1:
                fil_no = st.multiselect("No Tienda", sorted(df_c["NO_TIENDA"].astype(str).unique()))
                fil_ti = st.multiselect("Tienda", sorted(df_c["TIENDA"].astype(str).unique()))
            with c2:
                fil_ed = st.multiselect("Estado", sorted(df_c["ESTADO"].astype(str).unique()))
                fil_art = st.multiselect("Artículo", sorted(df_c["ARTICULO"].astype(str).unique()))
                fil_cat = st.multiselect("Categoría", sorted(df_c["CATEGORIA"].astype(str).unique()))

        dff_base = apply_filters(df_c, ["NO_TIENDA", "TIENDA", "ESTADO", "CATEGORIA"], [fil_no, fil_ti, fil_ed, fil_cat])
        dff = apply_filters(dff_base, ["ARTICULO"], [fil_art])

        b1, b2, b3 = st.columns(3, gap="small")
        with b1: st.button("📉 NEGATIVO / 0", on_click=tog_c, args=('c_neg_zero',), key="btn_che_nz", use_container_width=True, type="primary")
        with b2: st.button("⚠️ DIAS INV < 10", on_click=tog_c, args=('c_under_10',), key="btn_che_u10", use_container_width=True, type="primary")
        with b3: 
            st.markdown(f'<div class="{"rank-green-on" if st.session_state.c_dias_inv else "dias-inv-style"}">', unsafe_allow_html=True)
            st.button("📅 DIAS INV", on_click=tog_c, args=('c_dias_inv',), key="btn_che_dias", use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)

        if st.session_state.c_dias_inv:
            st.subheader("📅 Reporte Días Inventario")
            val_nut = get_kpi_mean(dff_base, "ARTICULO", "DIAS_INV", "Nutrioli Bot 850")
            val_sab = get_kpi_mean(dff_base, "ARTICULO", "DIAS_INV", "Sabrosano Mixto 850")
            val_ave = get_kpi_mean(dff_base, "ARTICULO", "DIAS_INV", "Ave Soya-Canola 850")
            k1, k2, k3 = st.columns(3)
            k1.markdown(f"<div class='kpi-card'><div class='kpi-title'>NUTRIOLI 850ML</div><div class='kpi-value' style='color:#28a745;'>{val_nut:,.1f}</div></div>", unsafe_allow_html=True)
            k2.markdown(f"<div class='kpi-card'><div class='kpi-title'>SABROSANO 850ML</div><div class='kpi-value' style='color:#E4007C;'>{val_sab:,.1f}</div></div>", unsafe_allow_html=True)
            k3.markdown(f"<div class='kpi-card'><div class='kpi-title'>AVE 850ML</div><div class='kpi-value' style='color:#D32F2F;'>{val_ave:,.1f}</div></div>", unsafe_allow_html=True)
            st.dataframe(dff[["NO_TIENDA", "TIENDA", "ARTICULO", "INV_ULT_SEM", "VTA_PROM_DIARIA", "DIAS_INV", "SELL_OUT"]].style.format({'INV_ULT_SEM': "{:,.0f}", 'VTA_PROM_DIARIA': "{:,.2f}", 'DIAS_INV': "{:,.1f}", 'SELL_OUT': "${:,.2f}"}), use_container_width=True, hide_index=True)
            
        else:
            def get_chedraui_category(desc):
                desc = str(desc).upper().replace(" ", "")
                if "BALSAMICO" in desc: return "BALSAMICO"
                if "SABROSANO" in desc: return "SABROSANO"
                if "GRANTRADICION" in desc: return "GT"
                if "MISAZON" in desc or "MISAZÓN" in desc: return "MI SAZON"
                if "AVE" in desc and ("SOYA-CANOLA" in desc or "AEROSOL" in desc): return "AVE"
                if "NUTRIOLI" in desc and any(k in desc for k in ["FUSILLI", "SPAGUETTI", "FIDEO", "CODO"]): return "PASTAS"
                if "OLI" in desc and ("OLIVA" in desc or "EV" in desc or "AEROSOL" in desc): return "OLIVAS"
                if "NUTRIOLI" in desc and ("400ML" in desc or "850ML" in desc) and "PROTECT" not in desc and "DEFENSAS" not in desc: return "NUTRIOLI"
                if "NUTRIOLI" in desc: return "REST NUTRIOLI"
                return None

            c_kpi, c_chart = st.columns([1, 2])
            with c_kpi:
                total_so = dff['SELL_OUT'].sum()
                st.markdown(f"<div class='kpi-card' style='height: 300px;'><div class='kpi-title'>Total Sell Out</div><div class='kpi-value' style='color:#FF6600;'>${total_so:,.2f}</div></div>", unsafe_allow_html=True)
            with c_chart:
                chart_data = dff.copy()
                chart_data['Category'] = chart_data['ARTICULO'].apply(get_chedraui_category)
                pie_df = chart_data.dropna(subset=['Category']).groupby('Category')['SELL_OUT'].sum().reset_index()
                pie_df = pie_df[pie_df['SELL_OUT'] > 0]
                total_pie = pie_df['SELL_OUT'].sum()
                
                if not pie_df.empty:
                    domain = ["BALSAMICO", "SABROSANO", "PASTAS", "OLIVAS", "GT", "NUTRIOLI", "MI SAZON", "AVE", "REST NUTRIOLI"]
                    range_ = ["#e012a9", "#f705ab", "#4c915d", "#97ad6a", "#7d6010", "#02c705", "#e89015", "#ff0000", "#00ff04"]
                    base = alt.Chart(pie_df).encode(theta=alt.Theta(field="SELL_OUT", type="quantitative", stack=True)).properties(height=300)
                    pie = base.mark_arc(innerRadius=60, outerRadius=100).encode(
                        color=alt.Color(field="Category", type="nominal", scale=alt.Scale(domain=domain, range=range_), legend=None),
                        order=alt.Order("SELL_OUT", sort="descending"),
                        tooltip=['Category', alt.Tooltip('SELL_OUT', format='$,.2f')]
                    )
                    text = base.mark_text(radius=130, fontSize=11).encode(
                        text=alt.Text("label_text:N"), order=alt.Order("SELL_OUT", sort="descending"), color=alt.value("black")
                    ).transform_calculate(label_text="datum.Category + ': $' + format(datum['SELL_OUT'], ',.0f')").transform_filter(alt.datum['SELL_OUT'] > (total_pie * 0.02))
                    st.altair_chart(pie + text, use_container_width=True)
                else: st.info("Sin datos para gráfica.")

            view_mode = ""
            if st.session_state.c_neg_zero: dff = dff[dff["DIAS_INV"] <= 0]; view_mode = "Negativos o Cero"
            if st.session_state.c_under_10: dff = dff[dff["DIAS_INV"] < 10]; view_mode = "Menor a 10 Días"
            
            st.caption(f"📋 Vista: {view_mode or 'Completa'}")
            st.dataframe(dff[["NO_TIENDA", "TIENDA", "ARTICULO", "INV_ULT_SEM", "VTA_PROM_DIARIA", "DIAS_INV", "SELL_OUT"]].style.format({'INV_ULT_SEM': "{:,.0f}", 'VTA_PROM_DIARIA': "{:,.2f}", 'DIAS_INV': "{:,.1f}", 'SELL_OUT': "${:,.2f}"}), use_container_width=True, hide_index=True)

        st.divider()
        st.markdown("<h3 style='text-align: center; color: #444;'>🏆 RANKING DE VENTAS</h3>", unsafe_allow_html=True)
        
        sel_st_rank = st.selectbox("Filtrar Estado (Ranking)", ["Todos"] + sorted(df_c["ESTADO"].astype(str).unique()), key="c_rnk_st")
        
        cr1, cr2 = st.columns(2, gap="small")
        with cr1:
            st.markdown('<div class="btn-ranking-blue">', unsafe_allow_html=True)
            if st.button("📊 GENERAL", key="c_rk_gen", use_container_width=True): set_c_rank('GEN')
            st.markdown('</div>', unsafe_allow_html=True)
        with cr2:
            st.markdown('<div class="btn-ranking-orange">', unsafe_allow_html=True)
            if st.button("🍝 PASTAS", key="c_rk_pas", use_container_width=True): set_c_rank('PAS')
            st.markdown('</div>', unsafe_allow_html=True)
        cr3, cr4 = st.columns(2, gap="small")
        with cr3:
            st.markdown('<div class="btn-ranking-olive">', unsafe_allow_html=True)
            if st.button("🫒 OLIVAS", key="c_rk_oli", use_container_width=True): set_c_rank('OLI')
            st.markdown('</div>', unsafe_allow_html=True)
        with cr4:
            st.markdown('<div class="btn-ranking-green">', unsafe_allow_html=True)
            if st.button("🍃 NUTRIOLI", key="c_rk_nut", use_container_width=True): set_c_rank('NUT')
            st.markdown('</div>', unsafe_allow_html=True)

        dff_rank = df_c.copy()
        if sel_st_rank != "Todos": dff_rank = dff_rank[dff_rank["ESTADO"].astype(str) == sel_st_rank]

        list_gen = ["Vinagre Oli Nutrioli Balsámico 250 ml (3795515)", "Aceite Sabrosano Mixto 850 ML (3691244)", "Aceite Mi Sazón Vegetal 800 ML (3775895)", "Pps Nutrioli Fusilli Integral (3878678)", "Aceite Ave Soya-Canola 850 ML (3696190)", "Pps Nutrioli Spaguetti 200 (3878673)", "Pps Nutrioli Fusilli Verduras (3878676)", "Pps Nutrioli Fideo 200 Gr (3878671)", "Aceite Nutrioli Antigoteo 700 ML (3738492)", "Pps Nutrioli Spaguetti Integra (3878677)", "Pps Nutrioli Codo Verduras 200 (3878675)", "Pps Nutrioli Codo 200 Gr (3878674)", "Aceite Nutrioli Protect Defensas 850 ml (3828176)", "Pps Nutrioli Fusilli 450 (3878672)", "Ace Oliva EV Oli BOT 750 Ml (3284693)", "Aceite Oliva Puro Oli Bote 750 Ml (3570620)", "Ace Oliva EV Oli BOT 500 Ml (3368446)", "Aceite Gran Tradición Soya-Canola 800 ML (3009894)", "Aceite Nutrioli Protect Mente 850 Ml (3009960)", "Aceite De Soya Nutrioli Bot 850 Ml (3132396)", "Ace Oliva Puro Oli BOT 500 Ml (3570614)", "Ace Oliva EV Oli BOT 250 Ml (3284690)", "Aceite De Soya Nutrioli Bot 400 Ml (3590824)", "Aceite Mi Sazón Mixto 400 ML", "Aceite Aerosol Nutrioli Soya Lata 180 Gr (3317342)", "Aceite Oli Extra Virgen 500 Ml (3646332)", "Aceite Aerosol Ave Mixto 170 Gr (3693814)", "Aceite de Oliva Oli Nutrioli 250 Ml (3679970)", "Aceite Nutrioli Soya 850 ML (3676715)", "Aceite Sabrosano Rinde + 850 ML (3782858)", "Aceite Aerosol Oli Oliva 145 Ml (3679971)", "Ace Oliva EV Oli BOT 500 Ml (3428657)", "Aceite Nutrioli 850+Pps Fusill (3880416)", "Aceite Nutrioli 850+Pps Codo 2 (3880415)"]
        list_pas = ["Pps Nutrioli Fusilli Integral (3878678)", "Pps Nutrioli Spaguetti 200 (3878673)", "Pps Nutrioli Fusilli Verduras (3878676)", "Pps Nutrioli Fideo 200 Gr (3878671)", "Pps Nutrioli Spaguetti Integra (3878677)", "Pps Nutrioli Codo Verduras 200 (3878675)", "Pps Nutrioli Codo 200 Gr (3878674)", "Pps Nutrioli Fusilli 450 (3878672)", "Aceite Nutrioli 850+Pps Fusill (3880416)", "Aceite Nutrioli 850+Pps Codo 2 (3880415)"]
        list_oli = ["Ace Oliva EV Oli BOT 750 Ml (3284693)", "Aceite Oliva Puro Oli Bote 750 Ml (3570620)", "Ace Oliva EV Oli BOT 500 Ml (3368446)", "Ace Oliva Puro Oli BOT 500 Ml (3570614)", "Ace Oliva EV Oli BOT 250 Ml (3284690)", "Aceite Oli Extra Virgen 500 Ml (3646332)", "Aceite de Oliva Oli Nutrioli 250 Ml (3679970)", "Aceite Aerosol Oli Oliva 145 Ml (3679971)", "Ace Oliva EV Oli BOT 500 Ml (3428657)"]
        list_nut = ["Aceite De Soya Nutrioli Bot 850 Ml (3132396)"]

        target_list = []
        rank_title = ""
        if st.session_state.c_rank_gen: target_list = list_gen; rank_title = "VENTA GENERAL ($)"
        elif st.session_state.c_rank_pas: target_list = list_pas; rank_title = "VENTA PASTAS ($)"
        elif st.session_state.c_rank_oli: target_list = list_oli; rank_title = "VENTA OLIVAS ($)"
        elif st.session_state.c_rank_nut: target_list = list_nut; rank_title = "VENTA NUTRIOLI ($)"

        if target_list:
            dff_rank = dff_rank[dff_rank["ARTICULO"].isin(target_list)]
            if not dff_rank.empty:
                final_c_rank = dff_rank.groupby(["NO_TIENDA", "TIENDA"])['SELL_OUT'].sum().reset_index()
                final_c_rank.columns = ['No Tienda', 'TIENDA', rank_title]
                st.dataframe(final_c_rank.sort_values(by=rank_title, ascending=False).style.format({rank_title: "${:,.2f}"}), use_container_width=True, hide_index=True)
            else: st.warning("⚠️ No se encontraron ventas para los productos seleccionados en este estado.")

def view_fresko():
    st.markdown(f"<div class='retailer-header' style='background-color: {RETAILER_COLORS['FRESKO']}; color: #444;'>FRESKO</div>", unsafe_allow_html=True)
    f_fre = st.file_uploader("📂 Cargar Excel FRESKO", type=["xlsx"], key="up_fre")
    if f_fre:
        df_fre = load_fre(f_fre)
        st.dataframe(df_fre, use_container_width=True)

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

elif st.session_state.active_retailer == 'FRESKO':
    view_fresko()

# --- 10. PIE DE PÁGINA ---
st.divider()
if st.button("🗑️ LIMPIAR MEMORIA / RESET", use_container_width=True):
    if not st.session_state.confirm_reset:
        st.session_state.confirm_reset = True
        st.error("⚠️ ¡CONFIRMACIÓN REQUERIDA! Haz clic de nuevo para resetear todo.")
        st.rerun()
    else:
        st.cache_data.clear()
        for key in list(st.session_state.keys()): del st.session_state[key]
        st.success("✅ Memoria limpiada. Reiniciando...")
        st.rerun()