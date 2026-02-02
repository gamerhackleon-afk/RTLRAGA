import streamlit as st
import pandas as pd
import time
import urllib.parse 
import requests # Necesario para verificar internet
from PIL import Image
from io import BytesIO # Necesario para procesar el archivo descargado

# --- CONFIGURACIÓN DE PÁGINA ---
try:
    st.set_page_config(
        page_title="Inventarios Retail", 
        page_icon="ragasa_logo.png", 
        layout="wide", 
        initial_sidebar_state="collapsed"
    )
except:
    st.set_page_config(
        page_title="Inventarios Retail", 
        page_icon="📦", 
        layout="wide", 
        initial_sidebar_state="collapsed"
    )

# --- URLS DE LOS ARCHIVOS (GITHUB RAW) ---
# Convertimos 'blob' a 'raw' para descarga directa
URLS_DB = {
    "SORIANA": "https://github.com/gamerhackleon-afk/RTLRAGA/raw/main/SORIANA.xlsx",
    "WALMART": "https://github.com/gamerhackleon-afk/RTLRAGA/raw/main/WALMART.xlsx",
    "CHEDRAUI": "https://github.com/gamerhackleon-afk/RTLRAGA/raw/main/CHEDRAUI.xlsx"
}

# --- FUNCIÓN PARA DETECTAR INTERNET ---
def check_connection():
    try:
        # Intentamos conectar a GitHub con un timeout corto
        requests.get("https://github.com", timeout=3)
        return True
    except:
        return False

# Verificamos conexión al inicio
if 'is_online' not in st.session_state:
    st.session_state.is_online = check_connection()

# --- GESTIÓN DE ESTADO DE NAVEGACIÓN ---
if 'active_retailer' not in st.session_state:
    st.session_state.active_retailer = 'SORIANA'

def set_retailer(retailer_name):
    st.session_state.active_retailer = retailer_name

# --- ESTILOS CSS (METRO UI + BOTONES COLOREADOS) ---
st.markdown("""
<style>
    .block-container {
        padding-top: 1rem !important;
        padding-bottom: 2rem !important;
        max-width: 1200px;
    }

    /* ESTILO BASE TILE */
    div[data-testid="stHorizontalBlock"]:nth-of-type(2) button,
    div[data-testid="stHorizontalBlock"]:nth-of-type(3) button {
        width: 100% !important;
        height: 120px !important;
        border: none !important;
        border-radius: 0px !important;
        font-size: 1.5rem !important;
        font-weight: 800 !important;
        text-align: left !important;
        padding-left: 20px !important;
        padding-bottom: 10px !important;
        display: flex;
        align-items: flex-end;
        box-shadow: none !important;
        transition: transform 0.1s;
    }
    
    div[data-testid="stHorizontalBlock"]:nth-of-type(2) button:active,
    div[data-testid="stHorizontalBlock"]:nth-of-type(3) button:active {
        transform: scale(0.98);
        filter: brightness(90%);
    }

    /* COLORES ESPECIFICOS */
    /* SORIANA (Rojo) */
    div[data-testid="stHorizontalBlock"]:nth-of-type(2) [data-testid="stColumn"]:nth-of-type(1) button {
        background: #D32F2F !important; color: #FFFFFF !important;
    }
    div[data-testid="stHorizontalBlock"]:nth-of-type(2) [data-testid="stColumn"]:nth-of-type(1) button:hover {
        border: 3px solid white !important;
    }

    /* WALMART (Azul) */
    div[data-testid="stHorizontalBlock"]:nth-of-type(2) [data-testid="stColumn"]:nth-of-type(2) button {
        background: #0071DC !important; color: #FFC220 !important;
    }
    div[data-testid="stHorizontalBlock"]:nth-of-type(2) [data-testid="stColumn"]:nth-of-type(2) button:hover {
        border: 3px solid white !important;
    }

    /* CHEDRAUI (Naranja) */
    div[data-testid="stHorizontalBlock"]:nth-of-type(3) [data-testid="stColumn"]:nth-of-type(1) button {
        background: #FF6600 !important; color: #FFFFFF !important;
    }
    div[data-testid="stHorizontalBlock"]:nth-of-type(3) [data-testid="stColumn"]:nth-of-type(1) button:hover {
        border: 3px solid white !important;
    }

    /* FRESKO (Verde Limón) */
    div[data-testid="stHorizontalBlock"]:nth-of-type(3) [data-testid="stColumn"]:nth-of-type(2) button {
        background: #CCFF00 !important; color: #FF6600 !important; text-shadow: none !important;
    }
    div[data-testid="stHorizontalBlock"]:nth-of-type(3) [data-testid="stColumn"]:nth-of-type(2) button:hover {
        border: 3px solid #FF6600 !important;
    }

    .active-section-title {
        font-size: 2rem;
        font-weight: 900;
        margin-top: 20px;
        margin-bottom: 20px;
        padding: 10px;
        color: white;
        text-align: center;
        border-radius: 5px;
    }
    
    /* Botones grandes generales */
    div.stButton > button:first-child {
        height: 3.5em; font-weight: bold; border-radius: 10px;
    }
</style>
""", unsafe_allow_html=True)

# --- ENCABEZADO ---
c_logo, c_tit = st.columns([1, 4])
with c_logo:
    try:
        st.image("ragasa_logo.png", use_container_width=True)
    except:
        st.write("📦")
with c_tit:
    conn_status = "🟢 ONLINE" if st.session_state.is_online else "🔴 OFFLINE"
    st.markdown(f"<h3 style='margin-top:10px; font-weight:300;'>GESTOR INVENTARIOS <span style='font-size:0.6em; color:gray;'>({conn_status})</span></h3>", unsafe_allow_html=True)

st.write("") 

# --- LAYOUT METRO UI ---
col1, col2 = st.columns(2, gap="small")
with col1: st.button("SORIANA", on_click=set_retailer, args=("SORIANA",), use_container_width=True)
with col2: st.button("WALMART", on_click=set_retailer, args=("WALMART",), use_container_width=True)

col3, col4 = st.columns(2, gap="small")
with col3: st.button("CHEDRAUI", on_click=set_retailer, args=("CHEDRAUI",), use_container_width=True)
with col4: st.button("FRESKO", on_click=set_retailer, args=("FRESKO",), use_container_width=True)

st.divider()

# ==============================================================================
# LOGICA DE CARGA DE DATOS HIBRIDA (ONLINE/OFFLINE)
# ==============================================================================
def obtener_dataframe(retailer_key, file_uploader_key, func_limpieza):
    """
    Función maestra que decide si cargar de GitHub o del Uploader local.
    """
    df_result = None
    
    # 1. INTENTO CARGA ONLINE (Si hay internet y existe URL configurada)
    if st.session_state.is_online and retailer_key in URLS_DB:
        try:
            # Usamos st.spinner para indicar que está descargando
            with st.spinner(f"☁️ Descargando {retailer_key} de la nube..."):
                # Leemos directo con Pandas (soporta URLs)
                df_result = func_limpieza(URLS_DB[retailer_key])
                st.success(f"✅ Archivo {retailer_key} cargado desde la nube.")
        except Exception as e:
            st.error(f"⚠️ Error al descargar de la nube: {e}. Cambiando a modo manual.")
            # Si falla la descarga, df_result sigue siendo None, así que pasará al paso 2

    # 2. CARGA OFFLINE (Si no hay internet O falló la descarga O no hay URL)
    if df_result is None:
        if st.session_state.is_online:
            st.warning("No se pudo cargar automáticamente. Por favor sube el archivo manual.")
        else:
            st.info("📡 Modo Offline detectado: Carga tu archivo local.")
            
        uploaded_file = st.file_uploader(f"Cargar Excel {retailer_key}", type=["xlsx"], key=file_uploader_key)
        
        if uploaded_file:
            df_result = func_limpieza(uploaded_file)
            
    return df_result


# ==============================================================================
# VISTA: SORIANA
# ==============================================================================
if st.session_state.active_retailer == 'SORIANA':
    st.markdown(f"<div class='active-section-title' style='background-color: #D32F2F;'>SORIANA</div>", unsafe_allow_html=True)
    
    if 's_rojo' not in st.session_state: st.session_state.s_rojo = False
    def tog_s_rojo(): st.session_state.s_rojo = not st.session_state.s_rojo

    @st.cache_data(ttl=3600)
    def load_sor(file_path_or_buffer):
        try:
            df = pd.read_excel(file_path_or_buffer)
            if df.shape[1] < 22: return None
            for c in df.iloc[:, 15:20].columns:
                df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
            df['VTA_PROM'] = df.iloc[:, 15:19].sum(axis=1)
            df['SIN_VTA'] = ((df.iloc[:,15]==0)&(df.iloc[:,16]==0)&(df.iloc[:,17]==0)&(df.iloc[:,18]==0))
            return df
        except:
            return None

    # LLAMADA A LA LOGICA HIBRIDA
    df_s = obtener_dataframe("SORIANA", "up_s", load_sor)

    if df_s is not None:
        with st.expander("🔍 Filtros Soriana", expanded=False):
            col1, col2 = st.columns(2)
            with col1:
                c_res = df_s.columns[0]
                u_res = sorted(df_s[c_res].astype(str).unique())
                def_res = [x for x in u_res if x in ["1","1.0","2","2.0"]] or None
                fil_res = st.multiselect("Resurtible", ["Todos"]+u_res, default=def_res)
                c_nda = df_s.columns[5]
                fil_nda = st.multiselect("No Tienda", sorted(df_s[c_nda].astype(str).unique()))
                c_nom = df_s.columns[6]
                fil_nom = st.multiselect("Nombre", sorted(df_s[c_nom].astype(str).unique()))
                c_cat = df_s.columns[4]
                fil_cat = st.multiselect("Categoría", sorted(df_s[c_cat].astype(str).unique()))
            with col2:
                c_cd = df_s.columns[7]
                fil_cd = st.multiselect("Ciudad", sorted(df_s[c_cd].astype(str).unique()))
                c_edo = df_s.columns[8]
                fil_edo = st.multiselect("Estado", sorted(df_s[c_edo].astype(str).unique()))
                c_fmt = df_s.columns[9]
                fil_fmt = st.multiselect("Formato", sorted(df_s[c_fmt].astype(str).unique()))

        dff = df_s.copy()
        if st.session_state.s_rojo: dff = dff[dff['SIN_VTA']]
        
        if "Todos" not in fil_res and fil_res: dff = dff[dff[c_res].astype(str).isin(fil_res)]
        if fil_nda: dff = dff[dff[c_nda].astype(str).isin(fil_nda)]
        if fil_nom: dff = dff[dff[c_nom].astype(str).isin(fil_nom)]
        if fil_cat: dff = dff[dff[c_cat].astype(str).isin(fil_cat)]
        if fil_cd: dff = dff[dff[c_cd].astype(str).isin(fil_cd)]
        if fil_edo: dff = dff[dff[c_edo].astype(str).isin(fil_edo)]
        if fil_fmt: dff = dff[dff[c_fmt].astype(str).isin(fil_fmt)]

        dff = dff.sort_values('VTA_PROM', ascending=False)
        
        cols_fin = [df_s.columns[6], df_s.columns[2], df_s.columns[3], df_s.columns[4], 'VTA_PROM', df_s.columns[21], df_s.columns[19]]
        disp = dff[cols_fin].copy()
        disp.columns = ['TIENDA', 'COD', 'DESC', 'CAT', 'VTA PROM', 'DIAS', 'CAJAS']

        st.write("")
        lbl = "🔴 APAGAR SIN VENTA" if st.session_state.s_rojo else "🔴 INV SIN VENTA"
        st.button(lbl, on_click=tog_s_rojo, use_container_width=True, type="primary")

        msg = [f"*SORIANA ({len(disp)})*"]
        for _, r in disp.head(40).iterrows():
            msg.append(f"🏢 {r['TIENDA']}\n📦 {r['DESC']}\n📊 Inv:{r['CAJAS']} | Dias:{r['DIAS']}\n-")
        if len(disp)>40: msg.append(f"... +{len(disp)-40}")
        url = f"https://wa.me/?text={urllib.parse.quote(chr(10).join(msg))}"
        st.markdown(f'<a href="{url}" target="_blank" style="text-decoration:none;"><div style="background-color:#25D366;color:fff;padding:12px;border-radius:0px;text-align:center;font-weight:bold;margin:10px 0;box-shadow:0 2px 4px rgba(0,0,0,0.2);">📱 WHATSAPP</div></a>', unsafe_allow_html=True)

        def sty(r): return ['background-color:#ffcccc;color:#000']*len(r) if st.session_state.s_rojo else ['']*len(r)
        st.dataframe(disp.style.apply(sty, axis=1).format(precision=2), use_container_width=True, hide_index=True)


# ==============================================================================
# VISTA: WALMART
# ==============================================================================
elif st.session_state.active_retailer == 'WALMART':
    st.markdown(f"<div class='active-section-title' style='background-color: #0071DC; color: #FFC220;'>WALMART</div>", unsafe_allow_html=True)

    if 'w_neg' not in st.session_state: st.session_state.w_neg = False
    if 'w_4w' not in st.session_state: st.session_state.w_4w = False

    def tog_w_neg():
        st.session_state.w_neg = not st.session_state.w_neg
        if st.session_state.w_neg: st.session_state.w_4w = False

    def tog_w_4w():
        st.session_state.w_4w = not st.session_state.w_4w
        if st.session_state.w_4w: st.session_state.w_neg = False

    @st.cache_data(ttl=3600)
    def load_wal(file_path_or_buffer):
        try:
            df = pd.read_excel(file_path_or_buffer)
            if df.shape[1] < 97: return None
            for c in df.iloc[:, 92:97].columns: df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
            for c in df.iloc[:, 73:77].columns: df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
            c42 = df.columns[42]
            df[c42] = pd.to_numeric(df[c42], errors='coerce').fillna(0)
            df['SO_$'] = df.iloc[:, 92:96].sum(axis=1)
            return df
        except:
            return None

    # LLAMADA A LA LOGICA HIBRIDA
    df_w = obtener_dataframe("WALMART", "up_w", load_wal)

    if df_w is not None:
        cq = df_w.columns[16]
        df_w = df_w[~df_w[cq].isin(['BAE','MB'])]

        with st.expander("🔍 Filtros Walmart", expanded=False):
            c1, c2 = st.columns(2)
            with c1:
                cp = df_w.columns[15] # Tienda
                fil_t = st.multiselect("Tienda", sorted(df_w[cp].astype(str).unique()))
                fil_f = st.multiselect("Formato", sorted(df_w[cq].astype(str).unique()))
            with c2:
                cf = df_w.columns[5] # Cat
                fil_c = st.multiselect("Categoría", sorted(df_w[cf].astype(str).unique()))
                ch = df_w.columns[7] # Edo
                fil_e = st.multiselect("Estado", sorted(df_w[ch].astype(str).unique()))

        st.write("")
        b1, b2 = st.columns(2)
        with b1: st.button("📉 NEGATIVOS" if not st.session_state.w_neg else "📉 QUITAR NEG", on_click=tog_w_neg, use_container_width=True, type="primary")
        with b2: st.button("🔴 SIN VTA 4SEM" if not st.session_state.w_4w else "🔴 QUITAR 4SEM", on_click=tog_w_4w, use_container_width=True, type="primary")

        dff = df_w.copy()
        if fil_t: dff = dff[dff[cp].astype(str).isin(fil_t)]
        if fil_f: dff = dff[dff[cq].astype(str).isin(fil_f)]
        if fil_c: dff = dff[dff[cf].astype(str).isin(fil_c)]
        if fil_e: dff = dff[dff[ch].astype(str).isin(fil_e)]

        caq = df_w.columns[42]
        if st.session_state.w_neg:
            dff = dff[dff[caq] < 0]
            st.warning("VISTA: NEGATIVOS")
        
        cbv, cbw, cbx, cby = df_w.columns[73], df_w.columns[74], df_w.columns[75], df_w.columns[76]
        if st.session_state.w_4w:
            dff = dff[(dff[cbv]==0)&(dff[cbw]==0)&(dff[cbx]==0)&(dff[cby]==0)]
            st.warning("VISTA: SIN VENTA 4 SEMANAS")

        st.metric("TOTAL SELL OUT $", f"${dff[df_w.columns[96]].sum():,.2f}")

        cols = [df_w.columns[0], df_w.columns[4], df_w.columns[15], df_w.columns[33], df_w.columns[42], 'SO_$', df_w.columns[38]]
        disp = dff[cols].copy()
        disp.columns = ['COD', 'DESC', 'TIENDA', 'DDI', 'EXIST', 'SO $', 'PROM PZAS']

        msg = [f"*WALMART ({len(disp)})*"]
        for _, r in disp.head(40).iterrows():
            msg.append(f"🏢 {r['TIENDA']}\n📦 {r['DESC']}\n📊 Ext:{r['EXIST']} | SO$:{r['SO $']:,.2f}\n-")
        if len(disp)>40: msg.append("...")
        url = f"https://wa.me/?text={urllib.parse.quote(chr(10).join(msg))}"
        st.markdown(f'<a href="{url}" target="_blank" style="text-decoration:none;"><div style="background-color:#25D366;color:fff;padding:12px;border-radius:0px;text-align:center;font-weight:bold;margin:10px 0;box-shadow:0 2px 4px rgba(0,0,0,0.2);">📱 WHATSAPP</div></a>', unsafe_allow_html=True)

        def sty(r): return ['background-color:#ffcccc;color:#000']*len(r) if st.session_state.w_4w else ['']*len(r)
        st.dataframe(disp.style.apply(sty, axis=1).format({'SO $':"${:,.2f}", 'PROM PZAS':"{:,.2f}"}), use_container_width=True, hide_index=True)


# ==============================================================================
# VISTA: CHEDRAUI
# ==============================================================================
elif st.session_state.active_retailer == 'CHEDRAUI':
    st.markdown(f"<div class='active-section-title' style='background-color: #FF6600;'>CHEDRAUI</div>", unsafe_allow_html=True)

    if 'c_alt' not in st.session_state: st.session_state.c_alt = False
    if 'c_neg' not in st.session_state: st.session_state.c_neg = False

    def tog_c_alt():
        st.session_state.c_alt = not st.session_state.c_alt
        if st.session_state.c_alt: st.session_state.c_neg = False

    def tog_c_neg():
        st.session_state.c_neg = not st.session_state.c_neg
        if st.session_state.c_neg: st.session_state.c_alt = False

    @st.cache_data(ttl=3600)
    def load_che(file_path_or_buffer):
        try:
            df = pd.read_excel(file_path_or_buffer)
            if df.shape[1] < 18: return None
            for c in df.iloc[:, [12,14,16,17]].columns: df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
            return df
        except:
            return None

    # LLAMADA A LA LOGICA HIBRIDA
    df_c = obtener_dataframe("CHEDRAUI", "up_c", load_che)

    if df_c is not None:
        with st.expander("🔍 Filtros Chedraui", expanded=False):
            c1, c2 = st.columns(2)
            with c1:
                ci = df_c.columns[8] 
                fil_no = st.multiselect("No (#)", sorted(df_c[ci].astype(str).unique()))
                cj = df_c.columns[9] 
                fil_ti = st.multiselect("Tienda", sorted(df_c[cj].astype(str).unique()))
            with c2:
                cd = df_c.columns[3] 
                fil_ed = st.multiselect("Estado", sorted(df_c[cd].astype(str).unique()))

        st.write("")
        b1, b2 = st.columns(2)
        with b1: st.button("📈 DDI > 30" if not st.session_state.c_alt else "📈 QUITAR FILTRO", on_click=tog_c_alt, use_container_width=True, type="primary")
        with b2: st.button("📉 DDI < 0" if not st.session_state.c_neg else "📉 QUITAR FILTRO", on_click=tog_c_neg, use_container_width=True, type="primary")

        dff = df_c.copy()
        if fil_no: dff = dff[dff[ci].astype(str).isin(fil_no)]
        if fil_ti: dff = dff[dff[cj].astype(str).isin(fil_ti)]
        if fil_ed: dff = dff[dff[cd].astype(str).isin(fil_ed)]

        cr = df_c.columns[17] # DDI
        if st.session_state.c_alt:
            dff = dff[dff[cr] > 30]
            st.warning("VISTA: DDI ALTOS")
        if st.session_state.c_neg:
            dff = dff[dff[cr] < 0]
            st.warning("VISTA: DDI NEGATIVOS")

        cols = [df_c.columns[11], df_c.columns[12], df_c.columns[14], df_c.columns[16], df_c.columns[17]]
        disp = dff[cols].copy()
        disp.columns = ['DESC', 'INV ULT SEM', 'VTA ULT SEM', 'VTA PROM', 'DDI']
        
        st.dataframe(disp.style.format(precision=2), use_container_width=True, hide_index=True)


# ==============================================================================
# VISTA: FRESKO (SOLO MANUAL, SIN URL DEFINIDA)
# ==============================================================================
elif st.session_state.active_retailer == 'FRESKO':
    st.markdown(f"<div class='active-section-title' style='background-color: #CCFF00; color: #FF6600;'>FRESKO</div>", unsafe_allow_html=True)
    
    @st.cache_data(ttl=3600)
    def load_fre(file):
        df = pd.read_excel(file)
        return df

    # Fresko solo tiene carga manual por ahora
    f_fre = st.file_uploader("Cargar Excel FRESKO", type=["xlsx"], key="up_fre")

    if f_fre:
        df_fre = load_fre(f_fre)
        st.write("Datos cargados:")
        st.dataframe(df_fre, use_container_width=True)