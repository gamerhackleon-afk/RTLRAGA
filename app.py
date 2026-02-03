import streamlit as st
import pandas as pd
import time
import urllib.parse 
import requests 
from io import BytesIO 

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

# --- OPTIMIZACIÓN DE MEMORIA (CACHE) ---
# ttl=None: La memoria NO expira mientras la app esté abierta.
# max_entries=5: Guarda hasta 5 archivos en memoria (suficiente para Soriana, Wal, Che, Fre).
CACHE_CONFIG = {'ttl': None, 'max_entries': 5, 'show_spinner': False}

# --- URLS (RAW) ---
URLS_DB = {
    "SORIANA": "https://github.com/gamerhackleon-afk/RTLRAGA/raw/main/SORIANA.xlsx",
    "WALMART": "https://github.com/gamerhackleon-afk/RTLRAGA/raw/main/WALMART.xlsx",
    "CHEDRAUI": "https://github.com/gamerhackleon-afk/RTLRAGA/raw/main/CHEDRAUI.xlsx"
}

# --- DETECCIÓN DE RED AL INICIO ---
if 'is_online' not in st.session_state:
    try:
        # Timeout rápido para no bloquear la app
        requests.get("https://github.com", timeout=1)
        st.session_state.is_online = True
    except:
        st.session_state.is_online = False

# --- NAVEGACIÓN ---
if 'active_retailer' not in st.session_state:
    st.session_state.active_retailer = 'WALMART'

def set_retailer(retailer_name):
    st.session_state.active_retailer = retailer_name

# --- CSS OPTIMIZADO ---
st.markdown("""
<style>
    .block-container { padding-top: 1rem !important; padding-bottom: 3rem !important; max-width: 1200px; }
    
    /* BOTONES TILE (CUADROS PRINCIPALES DE NAVEGACIÓN) */
    div[data-testid="stHorizontalBlock"]:nth-of-type(2) button,
    div[data-testid="stHorizontalBlock"]:nth-of-type(3) button {
        width: 100% !important; height: 110px !important;
        border: none !important; border-radius: 0px !important;
        font-size: 1.4rem !important; font-weight: 800 !important;
        text-align: left !important; padding-left: 15px !important;
        display: flex; align-items: flex-end; box-shadow: none !important;
        transition: transform 0.1s;
    }
    div[data-testid="stHorizontalBlock"] button:active { transform: scale(0.98); filter: brightness(90%); }

    /* COLORES TILES NAVEGACIÓN */
    /* Soriana */
    div[data-testid="stHorizontalBlock"]:nth-of-type(2) [data-testid="stColumn"]:nth-of-type(1) button {
        background: #D32F2F !important; color: #FFF !important;
    }
    /* Walmart */
    div[data-testid="stHorizontalBlock"]:nth-of-type(2) [data-testid="stColumn"]:nth-of-type(2) button {
        background: #0071DC !important; color: #FFC220 !important;
    }
    /* Chedraui */
    div[data-testid="stHorizontalBlock"]:nth-of-type(3) [data-testid="stColumn"]:nth-of-type(1) button {
        background: #FF6600 !important; color: #FFF !important;
    }
    /* Fresko */
    div[data-testid="stHorizontalBlock"]:nth-of-type(3) [data-testid="stColumn"]:nth-of-type(2) button {
        background: #CCFF00 !important; color: #FF6600 !important; text-shadow: none !important;
    }

    /* TITULOS DE SECCION */
    .active-title {
        font-size: 1.8rem; font-weight: 900; margin: 15px 0; padding: 8px;
        color: white; text-align: center; border-radius: 4px;
    }
    
    /* BOTONES GENERALES */
    div.stButton > button { min-height: 45px; border-radius: 8px; font-weight: bold; }

    /* --- ESTILOS BOTONES MODULO RANKING (VENTANA 2x2) --- */
    
    /* 1. Ranking Tiendas (AZUL) */
    .ranking-style > button {
        background-color: #0071DC !important;
        color: white !important;
        font-size: 1rem !important;
        text-transform: uppercase;
        border: 2px solid white !important;
        height: 80px !important; 
    }

    /* 2. Ranking Pastas (NARANJA) */
    .pastas-style > button {
        background-color: #FF8C00 !important; 
        color: white !important;
        font-size: 1rem !important;
        text-transform: uppercase;
        border: 2px solid white !important;
        height: 80px !important;
    }
    
    /* 3. Ranking Olivas (OLIVA/DORADO) */
    .olivas-style > button {
        background-color: #808000 !important; 
        color: white !important;
        font-size: 1rem !important;
        text-transform: uppercase;
        border: 2px solid white !important;
        height: 80px !important;
    }

    /* 4. Ranking Nutrioli (VERDE) */
    .nutrioli-style > button {
        background-color: #28a745 !important;
        color: #FFC220 !important; 
        border: 2px solid #FFC220 !important;
        font-size: 1rem !important;
        text-transform: uppercase;
        height: 80px !important;
    }
    
    .ranking-style > button:hover, .pastas-style > button:hover, .olivas-style > button:hover, .nutrioli-style > button:hover {
        filter: brightness(110%);
        transform: scale(1.02);
        z-index: 10;
    }

</style>
""", unsafe_allow_html=True)

# --- HEADER ---
c1, c2 = st.columns([1, 4])
with c1:
    try: st.image("ragasa_logo.png", use_container_width=True)
    except: st.write("📦")
with c2:
    status = "🟢 ONLINE" if st.session_state.is_online else "🔴 OFFLINE"
    st.markdown(f"<h3 style='margin-top:10px;'>GESTOR INVENTARIOS <span style='font-size:0.5em;color:#888;'>{status}</span></h3>", unsafe_allow_html=True)

st.write("")

# --- MENU TILES ---
col1, col2 = st.columns(2, gap="small")
with col1: st.button("SORIANA", on_click=set_retailer, args=("SORIANA",), use_container_width=True)
with col2: st.button("WALMART", on_click=set_retailer, args=("WALMART",), use_container_width=True)

col3, col4 = st.columns(2, gap="small")
with col3: st.button("CHEDRAUI", on_click=set_retailer, args=("CHEDRAUI",), use_container_width=True)
with col4: st.button("FRESKO", on_click=set_retailer, args=("FRESKO",), use_container_width=True)

st.divider()

# --- FUNCIÓN DE CARGA MAESTRA (CLAVE PARA OFFLINE) ---
def get_data(key, uploader_key, func_load):
    """
    Intenta cargar datos. Si ya están en caché (RAM), los devuelve sin usar internet.
    Si no están en caché, intenta descargar.
    """
    df = None
    
    # 1. Intentamos cargar usando la función cacheada.
    # Si ya se descargó antes, Streamlit NO ejecutará el código de red y devolverá el dato de RAM.
    if st.session_state.is_online and key in URLS_DB:
        try:
            # Spinner solo visible si realmente está descargando
            with st.spinner(f"☁️ Sincronizando {key}..."):
                df = func_load(URLS_DB[key]) 
        except:
            # Si falla la descarga, no pasa nada, df sigue siendo None
            pass
    
    # 2. Si no tenemos datos (porque es la primera vez y no hay red, o falló la descarga)
    if df is None:
        if not st.session_state.is_online: 
            st.info("📡 Estás Offline. Si ya cargaste los datos antes, intenta recargar la página. Si no, usa carga manual.")
        
        f = st.file_uploader(f"📂 Cargar Excel {key}", type=["xlsx"], key=uploader_key)
        if f: df = func_load(f)
    
    return df

# ==============================================================================
# VISTA: SORIANA
# ==============================================================================
if st.session_state.active_retailer == 'SORIANA':
    st.markdown(f"<div class='active-title' style='background-color: #D32F2F;'>SORIANA</div>", unsafe_allow_html=True)
    
    if 's_rojo' not in st.session_state: st.session_state.s_rojo = False
    def tog_s_rojo(): st.session_state.s_rojo = not st.session_state.s_rojo

    # TTL=None -> PERSISTENCIA TOTAL EN RAM
    @st.cache_data(**CACHE_CONFIG)
    def load_sor(path):
        try:
            df = pd.read_excel(path)
            if df.shape[1] < 22: return None
            for c in df.iloc[:, 15:20].columns: df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
            df['VTA_PROM'] = df.iloc[:, 15:19].sum(axis=1)
            df['SIN_VTA'] = ((df.iloc[:,15]==0)&(df.iloc[:,16]==0)&(df.iloc[:,17]==0)&(df.iloc[:,18]==0))
            return df
        except: return None

    df_s = get_data("SORIANA", "up_s", load_sor)

    if df_s is not None:
        # FILTROS VISIBLES
        c1, c2 = st.columns(2)
        with c1:
            fil_res = st.multiselect("Resurtible", ["Todos"]+sorted(df_s[df_s.columns[0]].astype(str).unique()), default=None)
            fil_nda = st.multiselect("No Tienda", sorted(df_s[df_s.columns[5]].astype(str).unique()))
            fil_nom = st.multiselect("Nombre", sorted(df_s[df_s.columns[6]].astype(str).unique()))
            fil_cat = st.multiselect("Categoría", sorted(df_s[df_s.columns[4]].astype(str).unique()))
        with c2:
            fil_cd = st.multiselect("Ciudad", sorted(df_s[df_s.columns[7]].astype(str).unique()))
            fil_edo = st.multiselect("Estado", sorted(df_s[df_s.columns[8]].astype(str).unique()))
            fil_fmt = st.multiselect("Formato", sorted(df_s[df_s.columns[9]].astype(str).unique()))

        dff = df_s.copy()
        if st.session_state.s_rojo: dff = dff[dff['SIN_VTA']]
        if "Todos" not in fil_res and fil_res: dff = dff[dff[df_s.columns[0]].astype(str).isin(fil_res)]
        if fil_nda: dff = dff[dff[df_s.columns[5]].astype(str).isin(fil_nda)]
        if fil_nom: dff = dff[dff[df_s.columns[6]].astype(str).isin(fil_nom)]
        if fil_cat: dff = dff[dff[df_s.columns[4]].astype(str).isin(fil_cat)]
        if fil_cd: dff = dff[dff[df_s.columns[7]].astype(str).isin(fil_cd)]
        if fil_edo: dff = dff[dff[df_s.columns[8]].astype(str).isin(fil_edo)]
        if fil_fmt: dff = dff[dff[df_s.columns[9]].astype(str).isin(fil_fmt)]

        dff = dff.sort_values('VTA_PROM', ascending=False)
        cols_fin = [df_s.columns[6], df_s.columns[2], df_s.columns[3], df_s.columns[4], 'VTA_PROM', df_s.columns[21], df_s.columns[19]]
        disp = dff[cols_fin].copy()
        disp.columns = ['TIENDA', 'COD', 'DESC', 'CAT', 'VTA PROM', 'DIAS', 'CAJAS']

        st.write("")
        st.button("🔴 APAGAR SIN VENTA" if st.session_state.s_rojo else "🔴 INV SIN VENTA", on_click=tog_s_rojo, use_container_width=True, type="primary")

        msg = [f"*SORIANA ({len(disp)})*"]
        for _, r in disp.head(40).iterrows(): msg.append(f"🏢 {r['TIENDA']}\n📦 {r['DESC']}\n📊 Inv:{r['CAJAS']} | Dias:{r['DIAS']}\n-")
        if len(disp)>40: msg.append("...")
        url = f"https://wa.me/?text={urllib.parse.quote(chr(10).join(msg))}"
        st.markdown(f'<a href="{url}" target="_blank" style="text-decoration:none;"><div style="background-color:#25D366;color:fff;padding:12px;text-align:center;font-weight:bold;margin:10px 0;">📱 ENVIAR POR WHATS</div></a>', unsafe_allow_html=True)

        def sty(r): return ['background-color:#ffcccc;color:#000']*len(r) if st.session_state.s_rojo else ['']*len(r)
        st.dataframe(disp.style.apply(sty, axis=1).format(precision=2), use_container_width=True, hide_index=True)

# ==============================================================================
# VISTA: WALMART
# ==============================================================================
elif st.session_state.active_retailer == 'WALMART':
    st.markdown(f"<div class='active-title' style='background-color: #0071DC; color: #FFC220;'>WALMART</div>", unsafe_allow_html=True)

    # Estado botones principales
    if 'w_neg' not in st.session_state: st.session_state.w_neg = False
    if 'w_4w' not in st.session_state: st.session_state.w_4w = False
    
    # Estados Módulo Rankings
    if 'w_rank_tiendas' not in st.session_state: st.session_state.w_rank_tiendas = False
    if 'w_rank_pastas' not in st.session_state: st.session_state.w_rank_pastas = False
    if 'w_rank_olivas' not in st.session_state: st.session_state.w_rank_olivas = False
    if 'w_nutri_top10' not in st.session_state: st.session_state.w_nutri_top10 = False

    def tog_w_neg():
        st.session_state.w_neg = not st.session_state.w_neg
        if st.session_state.w_neg: st.session_state.w_4w = False
    def tog_w_4w():
        st.session_state.w_4w = not st.session_state.w_4w
        if st.session_state.w_4w: st.session_state.w_neg = False
    
    # Toggles Rankings (Mutuamente exclusivos)
    def tog_rank_tiendas():
        st.session_state.w_rank_tiendas = not st.session_state.w_rank_tiendas
        if st.session_state.w_rank_tiendas: 
            st.session_state.w_nutri_top10 = False
            st.session_state.w_rank_pastas = False
            st.session_state.w_rank_olivas = False
            
    def tog_rank_pastas():
        st.session_state.w_rank_pastas = not st.session_state.w_rank_pastas
        if st.session_state.w_rank_pastas:
            st.session_state.w_rank_tiendas = False
            st.session_state.w_nutri_top10 = False
            st.session_state.w_rank_olivas = False

    def tog_rank_olivas():
        st.session_state.w_rank_olivas = not st.session_state.w_rank_olivas
        if st.session_state.w_rank_olivas:
            st.session_state.w_rank_tiendas = False
            st.session_state.w_nutri_top10 = False
            st.session_state.w_rank_pastas = False

    def tog_nutri_top10():
        st.session_state.w_nutri_top10 = not st.session_state.w_nutri_top10
        if st.session_state.w_nutri_top10: 
            st.session_state.w_rank_tiendas = False
            st.session_state.w_rank_pastas = False
            st.session_state.w_rank_olivas = False

    @st.cache_data(**CACHE_CONFIG)
    def load_wal(path):
        try:
            df = pd.read_excel(path)
            if df.shape[1] < 97: return None
            # Limpiezas
            for c in df.iloc[:, 92:97].columns: df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
            for c in df.iloc[:, 73:77].columns: df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
            c42 = df.columns[42]
            df[c42] = pd.to_numeric(df[c42], errors='coerce').fillna(0)
            df['SO_$'] = df.iloc[:, 92:96].sum(axis=1)
            return df
        except: return None

    df_w = get_data("WALMART", "up_w", load_wal)

    if df_w is not None:
        cq = df_w.columns[16] # Formato
        # FILTRO GLOBAL DE FORMATO
        df_w = df_w[~df_w[cq].isin(['BAE','MB'])]

        # --- FILTROS PRINCIPALES ---
        c1, c2 = st.columns(2)
        with c1:
            fil_t = st.multiselect("Tienda", sorted(df_w[df_w.columns[15]].astype(str).unique()))
            fil_f = st.multiselect("Formato", sorted(df_w[cq].astype(str).unique()))
        with c2:
            fil_c = st.multiselect("Categoría", sorted(df_w[df_w.columns[5]].astype(str).unique()))
            fil_e = st.multiselect("Estado", sorted(df_w[df_w.columns[7]].astype(str).unique()))

        st.write("")
        b1, b2 = st.columns(2)
        with b1: st.button("📉 NEGATIVOS" if not st.session_state.w_neg else "📉 QUITAR NEG", on_click=tog_w_neg, use_container_width=True, type="primary")
        with b2: st.button("🔴 SIN VTA 4SEM" if not st.session_state.w_4w else "🔴 QUITAR 4SEM", on_click=tog_w_4w, use_container_width=True, type="primary")

        # --- APLICACIÓN FILTROS ---
        dff = df_w.copy()
        if fil_t: dff = dff[dff[df_w.columns[15]].astype(str).isin(fil_t)]
        if fil_f: dff = dff[dff[cq].astype(str).isin(fil_f)]
        if fil_c: dff = dff[dff[df_w.columns[5]].astype(str).isin(fil_c)]
        if fil_e: dff = dff[dff[df_w.columns[7]].astype(str).isin(fil_e)]

        if st.session_state.w_neg: dff = dff[dff[df_w.columns[42]] < 0]; st.warning("VISTA: NEGATIVOS")
        
        cbv, cbw, cbx, cby = df_w.columns[73], df_w.columns[74], df_w.columns[75], df_w.columns[76]
        if st.session_state.w_4w:
            dff = dff[(dff[cbv]==0)&(dff[cbw]==0)&(dff[cbx]==0)&(dff[cby]==0)]
            st.warning("VISTA: SIN VENTA 4 SEMANAS")

        # --- METRIC CENTERED GREEN ---
        total_kpi = dff[df_w.columns[96]].sum() # Suma de CS
        st.markdown(f"""
            <div style="text-align: center; padding: 10px; background-color: #f9f9f9; border-radius: 10px; margin-bottom: 20px; border: 1px solid #ddd;">
                <h4 style="color: #555; margin:0; font-size: 1rem;">TOTAL SELL OUT $</h4>
                <h2 style="color: #28a745; margin:0; font-size: 2.2rem; font-weight: bold;">${total_kpi:,.2f}</h2>
            </div>
        """, unsafe_allow_html=True)

        # Tabla Principal
        cols = [df_w.columns[0], df_w.columns[4], df_w.columns[15], df_w.columns[33], df_w.columns[42], 'SO_$', df_w.columns[38]]
        disp = dff[cols].copy()
        disp.columns = ['COD', 'DESC', 'TIENDA', 'DDI', 'EXIST', 'SO $', 'PROM PZAS']

        # WhatsApp Principal
        msg = [f"*WALMART ({len(disp)})*"]
        for _, r in disp.head(40).iterrows(): msg.append(f"🏢 {r['TIENDA']}\n📦 {r['DESC']}\n📊 Ext:{r['EXIST']} | SO$:{r['SO $']:,.2f}\n-")
        if len(disp)>40: msg.append("...")
        url = f"https://wa.me/?text={urllib.parse.quote(chr(10).join(msg))}"
        st.markdown(f'<a href="{url}" target="_blank" style="text-decoration:none;"><div style="background-color:#25D366;color:fff;padding:12px;text-align:center;font-weight:bold;margin:10px 0;">📱 ENVIAR POR WHATS</div></a>', unsafe_allow_html=True)

        def sty(r): return ['background-color:#ffcccc;color:#000']*len(r) if st.session_state.w_4w else ['']*len(r)
        st.dataframe(disp.style.apply(sty, axis=1).format({'SO $':"${:,.2f}", 'PROM PZAS':"{:,.2f}"}), use_container_width=True, hide_index=True)

        # ----------------------------------------------------------------------
        #  🏆 SEGUNDO MÓDULO: RANKING DE VENTAS (VENTANA 2x2)
        # ----------------------------------------------------------------------
        st.divider()
        st.markdown("<h3 style='text-align: center;'>🏆 RANKING DE VENTAS</h3>", unsafe_allow_html=True)

        # Filtros del Módulo (Compartidos)
        c_mod1, c_mod2 = st.columns(2)
        with c_mod1:
            col_h_idx = 7 # Estado
            unique_states = sorted(df_w.iloc[:, col_h_idx].astype(str).unique())
            sel_state_rank = st.multiselect("Filtrar Estado (Ranking)", unique_states)
        with c_mod2:
            col_q_idx = 16 # Formato
            unique_formats = sorted(df_w.iloc[:, col_q_idx].astype(str).unique())
            sel_fmt_rank = st.multiselect("Filtrar Formato (Ranking)", unique_formats)

        # LAYOUT VENTANA 2x2 PARA BOTONES
        r1_c1, r1_c2 = st.columns(2, gap="small")
        with r1_c1:
            st.markdown('<div class="ranking-style">', unsafe_allow_html=True)
            if st.button("📊 GENERAL", use_container_width=True, key="btn_rank_tiendas"):
                tog_rank_tiendas()
            st.markdown('</div>', unsafe_allow_html=True)
        
        with r1_c2:
            st.markdown('<div class="pastas-style">', unsafe_allow_html=True)
            if st.button("🍝 PASTAS", use_container_width=True, key="btn_rank_pastas"):
                tog_rank_pastas()
            st.markdown('</div>', unsafe_allow_html=True)

        r2_c1, r2_c2 = st.columns(2, gap="small")
        with r2_c1:
            st.markdown('<div class="olivas-style">', unsafe_allow_html=True)
            if st.button("🫒 OLIVAS", use_container_width=True, key="btn_rank_olivas"):
                tog_rank_olivas()
            st.markdown('</div>', unsafe_allow_html=True)
            
        with r2_c2:
            st.markdown('<div class="nutrioli-style">', unsafe_allow_html=True)
            if st.button("🏆 NUTRIOLI", use_container_width=True, key="btn_nutrioli"):
                tog_nutri_top10()
            st.markdown('</div>', unsafe_allow_html=True)

        # --- LOGICA VISUALIZACION RANKINGS ---
        df_rank_base = df_w.copy()
        if sel_state_rank:
            df_rank_base = df_rank_base[df_rank_base.iloc[:, col_h_idx].astype(str).isin(sel_state_rank)]
        if sel_fmt_rank:
            df_rank_base = df_rank_base[df_rank_base.iloc[:, col_q_idx].astype(str).isin(sel_fmt_rank)]

        # CASO 1: GENERAL
        if st.session_state.w_rank_tiendas:
            col_store_idx = 15
            col_sales_idx = 96
            rank_gen = df_rank_base.groupby(df_rank_base.iloc[:, col_store_idx])[df_rank_base.columns[col_sales_idx]].sum().reset_index()
            rank_gen.columns = ['TIENDA', 'VENTA TOTAL ($)']
            rank_gen = rank_gen.sort_values(by='VENTA TOTAL ($)', ascending=False)
            st.dataframe(rank_gen.style.format({'VENTA TOTAL ($)': "${:,.2f}"}), use_container_width=True, hide_index=True)

        # CASO 2: PASTAS
        if st.session_state.w_rank_pastas:
            df_pastas = df_rank_base[df_rank_base.iloc[:, 5].astype(str).str.contains("PASTAS", case=False, na=False)]
            if df_pastas.empty:
                 st.warning("⚠️ No se encontraron ventas para la categoría PASTAS.")
            else:
                col_store_idx = 15
                col_sales_idx = 96
                rank_pst = df_pastas.groupby(df_pastas.iloc[:, col_store_idx])[df_pastas.columns[col_sales_idx]].sum().reset_index()
                rank_pst.columns = ['TIENDA', 'VENTA PASTAS ($)']
                rank_pst = rank_pst.sort_values(by='VENTA PASTAS ($)', ascending=False)
                st.dataframe(rank_pst.style.format({'VENTA PASTAS ($)': "${:,.2f}"}), use_container_width=True, hide_index=True)

        # CASO 3: OLIVAS
        if st.session_state.w_rank_olivas:
            target_olivas = [
                "OLI SPRAY ACEITE DE OLIVA 145ML", "OLI COCINA 500ML", "OLI COCINA 250ML",
                "OLI DE NUT EV 500ML", "OLI COCINA 750ML", "OLI DE NUT EV 250ML",
                "OLI DE NUT EV 750ML", "OLI VINAGRE BALSAMICO 250ML"
            ]
            df_olivas = df_rank_base[df_rank_base.iloc[:, 4].isin(target_olivas)]
            if df_olivas.empty:
                st.warning("⚠️ No se encontraron ventas para la lista de Olivas.")
            else:
                col_store_idx = 15
                col_sales_idx = 96
                rank_oli = df_olivas.groupby(df_olivas.iloc[:, col_store_idx])[df_olivas.columns[col_sales_idx]].sum().reset_index()
                rank_oli.columns = ['TIENDA', 'VENTA OLIVAS ($)']
                rank_oli = rank_oli.sort_values(by='VENTA OLIVAS ($)', ascending=False)
                st.dataframe(rank_oli.style.format({'VENTA OLIVAS ($)': "${:,.2f}"}), use_container_width=True, hide_index=True)

        # CASO 4: NUTRIOLI
        if st.session_state.w_nutri_top10:
            df_nutri = df_rank_base[df_rank_base.iloc[:, 4].astype(str).str.contains("ACEITE NUTRIOLI 946M", case=False, na=False)]
            if df_nutri.empty:
                st.warning("⚠️ No se encontraron ventas para 'ACEITE NUTRIOLI 946M'.")
            else:
                col_store_idx = 15
                col_sales_idx = 96
                rank_nut = df_nutri.groupby(df_nutri.iloc[:, col_store_idx])[df_nutri.columns[col_sales_idx]].sum().reset_index()
                rank_nut.columns = ['TIENDA', 'VENTA NUTRIOLI ($)']
                rank_nut = rank_nut.sort_values(by='VENTA NUTRIOLI ($)', ascending=False).head(10)
                st.success("✅ Top 10 Tiendas Nutrioli Generado")
                st.dataframe(rank_nut.style.format({'VENTA NUTRIOLI ($)': "${:,.2f}"}), use_container_width=True, hide_index=True)


# ==============================================================================
# VISTA: CHEDRAUI
# ==============================================================================
elif st.session_state.active_retailer == 'CHEDRAUI':
    st.markdown(f"<div class='active-title' style='background-color: #FF6600;'>CHEDRAUI</div>", unsafe_allow_html=True)

    if 'c_alt' not in st.session_state: st.session_state.c_alt = False
    if 'c_neg' not in st.session_state: st.session_state.c_neg = False
    def tog_c_alt(): st.session_state.c_alt = not st.session_state.c_alt; st.session_state.c_neg=False
    def tog_c_neg(): st.session_state.c_neg = not st.session_state.c_neg; st.session_state.c_alt=False

    @st.cache_data(**CACHE_CONFIG)
    def load_che(path):
        try:
            df = pd.read_excel(path)
            if df.shape[1] < 18: return None
            for c in df.iloc[:, [12,14,16,17]].columns: df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
            return df
        except: return None

    df_c = get_data("CHEDRAUI", "up_c", load_che)

    if df_c is not None:
        # FILTROS VISIBLES
        c1, c2 = st.columns(2)
        with c1:
            fil_no = st.multiselect("No (#)", sorted(df_c[df_c.columns[8]].astype(str).unique()))
            fil_ti = st.multiselect("Tienda", sorted(df_c[df_c.columns[9]].astype(str).unique()))
        with c2:
            fil_ed = st.multiselect("Estado", sorted(df_c[df_c.columns[3]].astype(str).unique()))

        st.write("")
        b1, b2 = st.columns(2)
        with b1: st.button("📈 DDI > 30" if not st.session_state.c_alt else "📈 QUITAR FILTRO", on_click=tog_c_alt, use_container_width=True, type="primary")
        with b2: st.button("📉 DDI < 0" if not st.session_state.c_neg else "📉 QUITAR FILTRO", on_click=tog_c_neg, use_container_width=True, type="primary")

        dff = df_c.copy()
        if fil_no: dff = dff[dff[df_c.columns[8]].astype(str).isin(fil_no)]
        if fil_ti: dff = dff[dff[df_c.columns[9]].astype(str).isin(fil_ti)]
        if fil_ed: dff = dff[dff[df_c.columns[3]].astype(str).isin(fil_ed)]

        cr = df_c.columns[17]
        if st.session_state.c_alt: dff = dff[dff[cr] > 30]; st.warning("VISTA: DDI ALTOS")
        if st.session_state.c_neg: dff = dff[dff[cr] < 0]; st.warning("VISTA: DDI NEGATIVOS")

        cols = [df_c.columns[11], df_c.columns[12], df_c.columns[14], df_c.columns[16], df_c.columns[17]]
        disp = dff[cols].copy()
        disp.columns = ['DESC', 'INV ULT SEM', 'VTA ULT SEM', 'VTA PROM', 'DDI']
        st.dataframe(disp.style.format(precision=2), use_container_width=True, hide_index=True)

# ==============================================================================
# VISTA: FRESKO (SOLO MANUAL)
# ==============================================================================
elif st.session_state.active_retailer == 'FRESKO':
    st.markdown(f"<div class='active-title' style='background-color: #CCFF00; color: #FF6600;'>FRESKO</div>", unsafe_allow_html=True)
    
    @st.cache_data(**CACHE_CONFIG)
    def load_fre(file):
        df = pd.read_excel(file)
        return df

    f_fre = st.file_uploader("📂 Cargar Excel FRESKO", type=["xlsx"], key="up_fre")
    if f_fre:
        df_fre = load_fre(f_fre)
        st.dataframe(df_fre, use_container_width=True)

# --- PIE DE PÁGINA (LIMPIEZA) ---
st.divider()
if st.button("🗑️ LIMPIAR MEMORIA / RESET", use_container_width=True):
    st.cache_data.clear()
    st.session_state.clear()
    st.rerun()