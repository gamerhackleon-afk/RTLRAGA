import streamlit as st
import pandas as pd
import time
import urllib.parse 
import requests 
from io import BytesIO 

# --- 1. CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(
    page_title="Retail Manager", 
    page_icon="📊", 
    layout="wide", 
    initial_sidebar_state="collapsed"
)

# --- 2. GESTIÓN DE ESTADO Y MEMORIA ---
CACHE_CONFIG = {'ttl': None, 'max_entries': 5, 'show_spinner': False}

# URLs de Datos
URLS_DB = {
    "SORIANA": "https://github.com/gamerhackleon-afk/RTLRAGA/raw/main/SORIANA.xlsx",
    "WALMART": "https://github.com/gamerhackleon-afk/RTLRAGA/raw/main/WALMART.xlsx",
    "CHEDRAUI": "https://github.com/gamerhackleon-afk/RTLRAGA/raw/main/CHEDRAUI.xlsx"
}

# Inicialización
if 'is_online' not in st.session_state:
    try:
        requests.get("https://github.com", timeout=1)
        st.session_state.is_online = True
    except:
        st.session_state.is_online = False

if 'active_retailer' not in st.session_state:
    st.session_state.active_retailer = 'WALMART'

# Funciones de control
def set_retailer(retailer_name):
    st.session_state.active_retailer = retailer_name
    st.session_state.w_rank_tiendas = False
    st.session_state.w_rank_pastas = False
    st.session_state.w_rank_olivas = False
    st.session_state.w_nutri_top10 = False
    st.session_state.s_dias_inv = False
    st.session_state.w_dias_inv = False 

# --- 3. GENERACIÓN DINÁMICA DE CSS ---
act = st.session_state.active_retailer
style_on = "opacity: 1 !important; border: 3px solid #ffffff !important; transform: scale(1.02) !important; box-shadow: 0 8px 16px rgba(0,0,0,0.3) !important; z-index: 10 !important;"
style_off = "opacity: 0.5 !important; transform: scale(0.98) !important; filter: grayscale(60%) !important; border: 1px solid transparent !important;"

css_sor = style_on if act == 'SORIANA' else style_off
css_wal = style_on if act == 'WALMART' else style_off
css_che = style_on if act == 'CHEDRAUI' else style_off
css_fre = style_on if act == 'FRESKO' else style_off

st.markdown(f"""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap');
    
    html, body, [class*="css"] {{
        font-family: 'Inter', sans-serif;
    }}

    .block-container {{
        padding-top: 1.5rem !important;
        padding-bottom: 3rem !important;
        max-width: 1200px;
    }}

    /* BOTONES TILE */
    div[data-testid="stHorizontalBlock"] button {{
        border-radius: 12px !important;
        height: 90px !important;
        font-size: 1.1rem !important;
        font-weight: 800 !important;
        text-transform: uppercase;
        display: flex; align-items: center; justify-content: center;
        transition: all 0.2s ease-in-out !important;
    }}

    /* 1. SORIANA (ROJO) */
    div[data-testid="stHorizontalBlock"]:nth-of-type(2) [data-testid="stColumn"]:nth-of-type(1) button {{
        background: linear-gradient(135deg, #D32F2F, #B71C1C) !important; 
        color: white !important;
        {css_sor}
    }}

    /* 2. WALMART (AZUL) */
    div[data-testid="stHorizontalBlock"]:nth-of-type(2) [data-testid="stColumn"]:nth-of-type(2) button {{
        background: linear-gradient(135deg, #0071DC, #005BB5) !important; 
        color: white !important;
        {css_wal}
    }}

    /* 3. CHEDRAUI (NARANJA) */
    div[data-testid="stHorizontalBlock"]:nth-of-type(3) [data-testid="stColumn"]:nth-of-type(1) button {{
        background: linear-gradient(135deg, #FF6600, #E65100) !important; 
        color: white !important;
        {css_che}
    }}

    /* 4. FRESKO (VERDE/GRIS) */
    div[data-testid="stHorizontalBlock"]:nth-of-type(3) [data-testid="stColumn"]:nth-of-type(2) button {{
        background: linear-gradient(135deg, #CCFF00, #AACC00) !important; 
        color: #444 !important; text-shadow: none !important;
        {css_fre}
    }}

    /* ESTILOS DE APP */
    .kpi-card {{
        background-color: white; border: 1px solid #e0e0e0; border-radius: 12px;
        padding: 20px; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.05); margin-bottom: 20px;
    }}
    .kpi-title {{ font-size: 0.9rem; color: #666; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; }}
    .kpi-value {{ font-size: 2.5rem; color: #28a745; font-weight: 800; margin-top: 5px; }}

    .retailer-header {{
        font-size: 1.5rem; font-weight: 800; color: white; padding: 12px 20px;
        border-radius: 8px; margin-top: 20px; margin-bottom: 15px; text-align: center;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }}

    div.stButton > button {{ min-height: 50px !important; border-radius: 8px; font-weight: 600; }}

    /* RANKING STYLES */
    .ranking-style > button {{ background-color: #0071DC !important; color: white !important; border: 2px solid white !important; height: 80px !important; font-size: 1rem !important; text-transform: uppercase; }}
    .pastas-style > button {{ background-color: #FF8C00 !important; color: white !important; border: 2px solid white !important; height: 80px !important; font-size: 1rem !important; text-transform: uppercase; }}
    .olivas-style > button {{ background-color: #808000 !important; color: white !important; border: 2px solid white !important; height: 80px !important; font-size: 1rem !important; text-transform: uppercase; }}
    .nutrioli-style > button {{ background-color: #28a745 !important; color: #FFC220 !important; border: 2px solid #FFC220 !important; height: 80px !important; font-size: 1rem !important; text-transform: uppercase; }}
    
    .dias-inv-style > button {{
        background-color: #28a745 !important; color: white !important; border: 1px solid rgba(0,0,0,0.1) !important;
        font-size: 1rem !important; text-transform: uppercase; min-height: 50px !important; margin-top: 0px !important;
    }}
    
    .ranking-style > button:hover, .pastas-style > button:hover, .olivas-style > button:hover, .nutrioli-style > button:hover, .dias-inv-style > button:hover {{
        filter: brightness(110%); transform: scale(1.02); z-index: 10;
    }}
</style>
""", unsafe_allow_html=True)

# --- 4. HEADER ---
c_head1, c_head2 = st.columns([1, 5])
with c_head1:
    try: st.image("ragasa_logo.png", use_container_width=True)
    except: st.write("📦")
with c_head2:
    st.markdown("""
        <div style='display: flex; flex-direction: column; justify-content: center; height: 100%;'>
            <h2 style='margin:0; font-weight: 800; color: #333;'>RETAIL MANAGER</h2>
            <p style='margin:0; font-size: 0.9rem; color: #666;'>Panel de Control de Inventarios y Ventas</p>
        </div>
    """, unsafe_allow_html=True)

status_color = "#28a745" if st.session_state.is_online else "#dc3545"
st.markdown(f"<div style='text-align:right; font-size:0.75rem; color:{status_color}; font-weight:bold; margin-bottom:10px;'>● {'CONECTADO' if st.session_state.is_online else 'OFFLINE'}</div>", unsafe_allow_html=True)

# --- 5. NAVEGACIÓN ---
col1, col2 = st.columns(2, gap="medium")
with col1: st.button("SORIANA", on_click=set_retailer, args=("SORIANA",), use_container_width=True)
with col2: st.button("WALMART", on_click=set_retailer, args=("WALMART",), use_container_width=True)

col3, col4 = st.columns(2, gap="medium")
with col3: st.button("CHEDRAUI", on_click=set_retailer, args=("CHEDRAUI",), use_container_width=True)
with col4: st.button("FRESKO", on_click=set_retailer, args=("FRESKO",), use_container_width=True)

st.markdown("<hr style='margin: 20px 0; border: 0; border-top: 1px solid #eee;'>", unsafe_allow_html=True)

# --- 6. CARGA MAESTRA ---
def get_data(key, uploader_key, func_load):
    df = None
    if st.session_state.is_online and key in URLS_DB:
        try:
            with st.spinner(f"Sincronizando {key}..."):
                df = func_load(URLS_DB[key])
        except: pass
    
    if df is None:
        if not st.session_state.is_online:
            st.warning("⚠️ Sin conexión. Cargue el archivo localmente.")
        f = st.file_uploader(f"📂 Cargar Excel {key}", type=["xlsx"], key=uploader_key)
        if f: df = func_load(f)
    return df

# ==============================================================================
# VISTA: SORIANA
# ==============================================================================
if st.session_state.active_retailer == 'SORIANA':
    st.markdown(f"<div class='retailer-header' style='background-color: #D32F2F;'>SORIANA</div>", unsafe_allow_html=True)
    
    if 's_rojo' not in st.session_state: st.session_state.s_rojo = False
    if 's_dias_inv' not in st.session_state: st.session_state.s_dias_inv = False

    def tog_s_rojo(): 
        st.session_state.s_rojo = not st.session_state.s_rojo
        if st.session_state.s_rojo: st.session_state.s_dias_inv = False

    def tog_s_dias_inv():
        st.session_state.s_dias_inv = not st.session_state.s_dias_inv
        if st.session_state.s_dias_inv: st.session_state.s_rojo = False

    @st.cache_data(**CACHE_CONFIG)
    def load_sor(path):
        try:
            df = pd.read_excel(path)
            if df.shape[1] < 22: return None
            c_code = df.columns[2]
            df[c_code] = df[c_code].astype(str).str.replace(r'\.0*$', '', regex=True)
            c21 = df.columns[21]
            df[c21] = pd.to_numeric(df[c21], errors='coerce').fillna(0)
            for c in df.iloc[:, 15:20].columns: df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
            df['VTA_PROM'] = df.iloc[:, 15:19].sum(axis=1)
            df['SIN_VTA'] = ((df.iloc[:,15]==0)&(df.iloc[:,16]==0)&(df.iloc[:,17]==0)&(df.iloc[:,18]==0))
            return df
        except: return None

    df_s = get_data("SORIANA", "up_s", load_sor)

    if df_s is not None:
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
        if "Todos" not in fil_res and fil_res: dff = dff[dff[df_s.columns[0]].astype(str).isin(fil_res)]
        if fil_nda: dff = dff[dff[df_s.columns[5]].astype(str).isin(fil_nda)]
        if fil_nom: dff = dff[dff[df_s.columns[6]].astype(str).isin(fil_nom)]
        if fil_cat: dff = dff[dff[df_s.columns[4]].astype(str).isin(fil_cat)]
        if fil_cd: dff = dff[dff[df_s.columns[7]].astype(str).isin(fil_cd)]
        if fil_edo: dff = dff[dff[df_s.columns[8]].astype(str).isin(fil_edo)]
        if fil_fmt: dff = dff[dff[df_s.columns[9]].astype(str).isin(fil_fmt)]

        st.write("")
        b1, b2 = st.columns(2, gap="small")
        with b1:
            st.button("🔴 APAGAR SIN VENTA" if st.session_state.s_rojo else "🔴 INV SIN VENTA", on_click=tog_s_rojo, use_container_width=True, type="primary")
        with b2:
            cls_dias = "rank-green-on" if st.session_state.s_dias_inv else "dias-inv-style"
            st.markdown(f'<div class="{cls_dias}">', unsafe_allow_html=True)
            if st.button("📅 DIAS INV", use_container_width=True): tog_s_dias_inv()
            st.markdown('</div>', unsafe_allow_html=True)

        if st.session_state.s_dias_inv:
            st.subheader("📅 Reporte Días Inventario")
            
            # --- KPI Calculations ---
            # 1. Nutrioli 850
            col_desc_s = dff.columns[3] # Col D
            col_dias_s = dff.columns[21] # Col V
            
            mask_nut = dff[col_desc_s].astype(str).str.contains("ACEITE DE SOYA NUTRIOLI BOT 850 ML", case=False, na=False)
            val_nut = dff.loc[mask_nut, col_dias_s].mean()
            
            # 2. Sabrosano
            mask_sab = dff[col_desc_s].astype(str).str.contains("ACEITE COMESTIBLE SABROSANO 850 ML", case=False, na=False)
            val_sab = dff.loc[mask_sab, col_dias_s].mean()
            
            # 3. Pastas (Grupo)
            target_pastas = [
                "PASTA FIDEO NUTRIOLI 200GR", "PASTA SPAGHETTI NUTRIOLI INTEGRAL 200GR",
                "PASTA FUSILLI INTEGRAL NUTRIOLI 200GR", "PASTA CODO NUTRIOLI VERDURAS 200GR",
                "PASTA FUSILLI VERDURAS NUTRIOLI 450GR", "PASTA SPAGHETTI NUTRIOLI 200GR",
                "PASTA CODO NUTRIOLI 200GR"
            ]
            clean_target = [p.strip() for p in target_pastas]
            mask_pas = dff[col_desc_s].astype(str).str.strip().isin(clean_target)
            val_pas = dff.loc[mask_pas, col_dias_s].mean()
            
            val_nut = val_nut if pd.notna(val_nut) else 0
            val_sab = val_sab if pd.notna(val_sab) else 0
            val_pas = val_pas if pd.notna(val_pas) else 0

            # Mostrar Cards
            k1, k2, k3 = st.columns(3)
            k1.markdown(f"<div class='kpi-card'><div class='kpi-title'>NUTRIOLI 850ML</div><div class='kpi-value' style='color:#0071DC;'>{val_nut:,.1f}</div></div>", unsafe_allow_html=True)
            k2.markdown(f"<div class='kpi-card'><div class='kpi-title'>SABROSANO 850ML</div><div class='kpi-value' style='color:#0071DC;'>{val_sab:,.1f}</div></div>", unsafe_allow_html=True)
            k3.markdown(f"<div class='kpi-card'><div class='kpi-title'>PASTAS (Promedio)</div><div class='kpi-value' style='color:#0071DC;'>{val_pas:,.1f}</div></div>", unsafe_allow_html=True)

            # --- Tabla Detallada ---
            lista_ordenada = [
                "ACEITE DE SOYA NUTRIOLI BOT 850 ML", "ACEITE COMESTIBLE NUTRIOLI 400 ML",
                "ACEITE COMESTIBLE NUTRIOLI ANTIGOTEO 700", "ACEITE NUTRIOLI PROTECT DEFENSAS 850ML",
                "ACEITE NUTRIOLI PROTECT MENTE 850 ML", "ACEITE COMESTIBLE GRAN TRADICION 800 ML",
                "ACEITE COMESTIBLE SABROSANO 850 ML", "ACEITE COMESTIBLE NUTRIOLI AEROSOL 180ML",
                "ACEITE OLIVA OLI EV SPRAY 145 ML", "ACEITE OLIVA OLI PURO SPRAY 145 ML",
                "ACEITE OLI OLIVA EXTRA VIRGEN PZ 250ML", "ACEITE OLI OLIVA EXTRA VIRGEN PZ 500ML",
                "ACEITE OLI OLIVA EXTRA VIRGEN PZ 750ML", "ADEREZO OLI 250 ML PZ",
                "ADERE OLI OLIVA PARA COCINAR 500 ML OLI", "ADERE OLI OLIVA PARA COCINAR 750 ML OLI",
                "ADEREZO OLI 500 ML BOT", "PASTA CODO NUTRIOLI 200GR", "PASTA CODO NUTRIOLI VERDURAS 200GR",
                "PASTA FIDEO NUTRIOLI 200GR", "PASTA FUSILLI INTEGRAL NUTRIOLI 200GR",
                "PASTA FUSILLI VERDURAS NUTRIOLI 450GR", "PASTA SPAGHETTI NUTRIOLI 200GR",
                "PASTA SPAGHETTI NUTRIOLI INTEGRAL 200GR", "VINAGRE BALSAMICO 250ML",
                "ACEITE COMESTIBLE AEROSOL 170GR", "ACEITE COMESTIBLE AVE 850 ML"
            ]
            df_template = pd.DataFrame({'TARGET_DESC': lista_ordenada})
            df_agg = dff.groupby(dff.iloc[:, 3]).agg({dff.columns[2]: 'first', dff.columns[21]: 'mean'}).reset_index()
            df_agg.columns = ['DESC_ORIGINAL', 'CODIGO', 'DIAS_INV_PROM']
            
            df_template['TARGET_DESC'] = df_template['TARGET_DESC'].str.strip()
            df_agg['DESC_ORIGINAL'] = df_agg['DESC_ORIGINAL'].astype(str).str.strip()
            
            df_final = pd.merge(df_template, df_agg, left_on='TARGET_DESC', right_on='DESC_ORIGINAL', how='left')
            df_display = df_final[['CODIGO', 'TARGET_DESC', 'DIAS_INV_PROM']].copy()
            df_display.columns = ["Código", "Descripción", "DIAS INV"]
            fix_mask = df_display['Descripción'] == "ACEITE OLIVA OLI EV SPRAY 145 ML"
            df_display.loc[fix_mask & (df_display['Código'].isna()), 'Código'] = "7501039122624"
            df_display = df_display.fillna({'DIAS INV': 0, 'Código': '-'})
            st.dataframe(df_display.style.format({'DIAS INV': "{:,.1f}"}), use_container_width=True, hide_index=True)
        else:
            dff_view = dff.copy()
            if st.session_state.s_rojo: dff_view = dff_view[dff_view['SIN_VTA']]
            dff_view = dff_view.sort_values('VTA_PROM', ascending=False)
            cols_fin = [df_s.columns[6], df_s.columns[2], df_s.columns[3], df_s.columns[4], 'VTA_PROM', df_s.columns[21], df_s.columns[19]]
            disp = dff_view[cols_fin].copy()
            disp.columns = ['TIENDA', 'COD', 'DESC', 'CAT', 'VTA PROM', 'DIAS', 'CAJAS']
            msg = [f"*SORIANA ({len(disp)})*"]
            for _, r in disp.head(40).iterrows(): msg.append(f"🏢 {r['TIENDA']}\n📦 {r['DESC']}\n📊 Inv:{r['CAJAS']} | Dias:{r['DIAS']}\n-")
            if len(disp)>40: msg.append("...")
            url = f"https://wa.me/?text={urllib.parse.quote(chr(10).join(msg))}"
            st.markdown(f'<a href="{url}" target="_blank" style="text-decoration:none;"><div style="background-color:#25D366;color:fff;padding:12px;text-align:center;font-weight:bold;border-radius:8px;margin:10px 0;">📱 ENVIAR REPORTE WHATSAPP</div></a>', unsafe_allow_html=True)
            def sty(r): return ['background-color:#ffcccc;color:#000']*len(r) if st.session_state.s_rojo else ['']*len(r)
            st.dataframe(disp.style.apply(sty, axis=1).format(precision=2), use_container_width=True, hide_index=True)

# ==============================================================================
# VISTA: WALMART
# ==============================================================================
elif st.session_state.active_retailer == 'WALMART':
    st.markdown(f"<div class='retailer-header' style='background-color: #0071DC;'>WALMART</div>", unsafe_allow_html=True)

    if 'w_neg' not in st.session_state: st.session_state.w_neg = False
    if 'w_4w' not in st.session_state: st.session_state.w_4w = False
    if 'w_rank_tiendas' not in st.session_state: st.session_state.w_rank_tiendas = False
    if 'w_rank_pastas' not in st.session_state: st.session_state.w_rank_pastas = False
    if 'w_rank_olivas' not in st.session_state: st.session_state.w_rank_olivas = False
    if 'w_nutri_top10' not in st.session_state: st.session_state.w_nutri_top10 = False
    if 'w_dias_inv' not in st.session_state: st.session_state.w_dias_inv = False 

    def reset_ranks():
        st.session_state.w_rank_tiendas = False
        st.session_state.w_rank_pastas = False
        st.session_state.w_rank_olivas = False
        st.session_state.w_nutri_top10 = False

    def tog_w_neg(): 
        st.session_state.w_neg = not st.session_state.w_neg
        st.session_state.w_4w = False
        st.session_state.w_dias_inv = False
        
    def tog_w_4w(): 
        st.session_state.w_4w = not st.session_state.w_4w
        st.session_state.w_neg = False
        st.session_state.w_dias_inv = False

    def tog_w_dias_inv():
        st.session_state.w_dias_inv = not st.session_state.w_dias_inv
        if st.session_state.w_dias_inv:
            st.session_state.w_neg = False
            st.session_state.w_4w = False
    
    def set_rank(mode):
        if mode == 'tiendas' and st.session_state.w_rank_tiendas: reset_ranks()
        elif mode == 'pastas' and st.session_state.w_rank_pastas: reset_ranks()
        elif mode == 'olivas' and st.session_state.w_rank_olivas: reset_ranks()
        elif mode == 'nutrioli' and st.session_state.w_nutri_top10: reset_ranks()
        else:
            reset_ranks()
            if mode == 'tiendas': st.session_state.w_rank_tiendas = True
            elif mode == 'pastas': st.session_state.w_rank_pastas = True
            elif mode == 'olivas': st.session_state.w_rank_olivas = True
            elif mode == 'nutrioli': st.session_state.w_nutri_top10 = True

    @st.cache_data(**CACHE_CONFIG)
    def load_wal(path):
        try:
            df = pd.read_excel(path)
            if df.shape[1] < 97: return None
            df = df.drop_duplicates()
            c_code = df.columns[0]
            df[c_code] = df[c_code].astype(str).str.replace(r'\.0*$', '', regex=True)
            for c in df.iloc[:, 92:97].columns: df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
            for c in df.iloc[:, 73:77].columns: df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
            df['PROM_PZS_MENSUAL'] = df.iloc[:, [73,74,75,76]].mean(axis=1)
            c42 = df.columns[42]
            df[c42] = pd.to_numeric(df[c42], errors='coerce').fillna(0)
            c_cs = df.columns[96]
            df['SO_$'] = pd.to_numeric(df[c_cs], errors='coerce').fillna(0)
            
            # Col 33 = AH = Días Inv
            c_ah = df.columns[33]
            df[c_ah] = pd.to_numeric(df[c_ah], errors='coerce').fillna(0)
            
            return df
        except: return None

    df_w = get_data("WALMART", "up_w", load_wal)

    if df_w is not None:
        cq = df_w.columns[16]
        df_w = df_w[~df_w[cq].isin(['BAE','MB'])]

        # --- FILTROS ---
        c1, c2 = st.columns(2)
        with c1:
            c_state = df_w.columns[7]
            unique_states = sorted(df_w[c_state].astype(str).unique())
            sel_state = st.multiselect("Estado", unique_states)
            
            c_store = df_w.columns[15] 
            if sel_state:
                subset_stores = df_w[df_w[c_state].isin(sel_state)]
                unique_stores = sorted(subset_stores[c_store].astype(str).unique())
            else:
                unique_stores = sorted(df_w[c_store].astype(str).unique())
            sel_store = st.multiselect("Tienda", unique_stores)

        with c2:
            sel_fmt = st.multiselect("Formato", sorted(df_w[cq].astype(str).unique()))
            # Nuevo Filtro Producto (Col E - 4)
            c_prod = df_w.columns[4]
            sel_prod = st.multiselect("Producto", sorted(df_w[c_prod].astype(str).unique()))

        st.write("")
        b1, b2, b3 = st.columns(3, gap="small")
        with b1: st.button("📉 NEGATIVOS" if not st.session_state.w_neg else "📉 QUITAR NEG", on_click=tog_w_neg, use_container_width=True, type="primary")
        with b2: st.button("🔴 SIN VTA 4SEM" if not st.session_state.w_4w else "🔴 QUITAR 4SEM", on_click=tog_w_4w, use_container_width=True, type="primary")
        with b3:
            cls_dias = "rank-green-on" if st.session_state.w_dias_inv else "dias-inv-style"
            st.markdown(f'<div class="{cls_dias}">', unsafe_allow_html=True)
            if st.button("📅 DIAS INV", use_container_width=True): tog_w_dias_inv()
            st.markdown('</div>', unsafe_allow_html=True)

        # Base Global Filtrada (Menos Producto) para los KPIs
        dff_kpi = df_w.copy()
        if sel_state: dff_kpi = dff_kpi[dff_kpi[c_state].astype(str).isin(sel_state)]
        if sel_store: dff_kpi = dff_kpi[dff_kpi[c_store].astype(str).isin(sel_store)]
        if sel_fmt: dff_kpi = dff_kpi[dff_kpi[cq].astype(str).isin(sel_fmt)]

        # Base para Tabla (Aplica Todo)
        dff = dff_kpi.copy()
        if sel_prod: dff = dff[dff[c_prod].astype(str).isin(sel_prod)]

        if st.session_state.w_neg: dff = dff[dff[df_w.columns[42]] < 0]; st.warning("VISTA: NEGATIVOS")
        if st.session_state.w_4w:
            dff = dff[(dff[df_w.columns[73]]==0)&(dff[df_w.columns[74]]==0)&(dff[df_w.columns[75]]==0)&(dff[df_w.columns[76]]==0)]
            st.warning("VISTA: SIN VENTA 4 SEMANAS")

        # --- VISTA CONDICIONAL: DIAS INV VS NORMAL ---
        
        if st.session_state.w_dias_inv:
            st.subheader("📅 Reporte Días Inventario")
            
            # KPI Cards (Usando dff_kpi para que no desaparezcan al filtrar producto)
            col_ah = df_w.columns[33]
            col_desc = df_w.columns[4]
            
            # SEARCH 1: NUTRIOLI 946M
            val_nutri = dff_kpi[dff_kpi[col_desc].astype(str).str.contains("NUTRIOLI 946M", case=False, na=False)][col_ah].mean()
            
            # SEARCH 2: GRAN TRADICION (CORREGIDO: Elimina espacios antes de buscar "GRANTRADICION")
            # Esto encontrará "GRANTRADICION", "GRAN TRADICION", "  GRANTRADICION  "
            mask_gran = dff_kpi[col_desc].astype(str).str.replace(" ", "").str.contains("GRANTRADICION", case=False, na=False)
            val_gran = dff_kpi[mask_gran][col_ah].mean()
            
            # SEARCH 3: SABROSANO 850ML
            val_sabro = dff_kpi[dff_kpi[col_desc].astype(str).str.contains("SABROSANO 850ML", case=False, na=False)][col_ah].mean()
            
            val_nutri = val_nutri if pd.notna(val_nutri) else 0
            val_gran = val_gran if pd.notna(val_gran) else 0
            val_sabro = val_sabro if pd.notna(val_sabro) else 0

            m1, m2, m3 = st.columns(3)
            m1.markdown(f"<div class='kpi-card'><div class='kpi-title'>NUTRIOLI 946M</div><div class='kpi-value' style='color:#0071DC;'>{val_nutri:,.1f}</div></div>", unsafe_allow_html=True)
            m2.markdown(f"<div class='kpi-card'><div class='kpi-title'>GRAN TRADICION</div><div class='kpi-value' style='color:#0071DC;'>{val_gran:,.1f}</div></div>", unsafe_allow_html=True)
            m3.markdown(f"<div class='kpi-card'><div class='kpi-title'>SABROSANO 850ML</div><div class='kpi-value' style='color:#0071DC;'>{val_sabro:,.1f}</div></div>", unsafe_allow_html=True)

            cols_dias = [df_w.columns[15], df_w.columns[0], df_w.columns[4], df_w.columns[33]]
            disp_dias = dff[cols_dias].copy()
            disp_dias.columns = ['TIENDA', 'CODIGO', 'DESCRIPCION', 'DIAS INVENTARIO']
            st.dataframe(disp_dias.style.format({'DIAS INVENTARIO': "{:,.1f}"}), use_container_width=True, hide_index=True)

        else:
            total_kpi = dff['SO_$'].sum() 
            st.markdown(f"""
                <div class='kpi-card'>
                    <div class='kpi-title'>Total Sell Out</div>
                    <div class='kpi-value'>${total_kpi:,.2f}</div>
                </div>
            """, unsafe_allow_html=True)

            cols = [df_w.columns[0], df_w.columns[4], df_w.columns[15], df_w.columns[42], 'SO_$', 'PROM_PZS_MENSUAL']
            disp = dff[cols].copy()
            disp.columns = ['CODIGO', 'DESCRIPCION', 'TIENDA', 'EXISTENCIA', 'SELL OUT', 'PROM PZS MENSUAL']

            msg = [f"*WALMART ({len(disp)})*"]
            for _, r in disp.head(40).iterrows(): msg.append(f"🏢 {r['TIENDA']}\n📦 {r['DESCRIPCION']}\n📊 Ext:{r['EXISTENCIA']} | SO$:{r['SELL OUT']:,.2f}\n-")
            if len(disp)>40: msg.append("...")
            url = f"https://wa.me/?text={urllib.parse.quote(chr(10).join(msg))}"
            st.markdown(f'<a href="{url}" target="_blank" style="text-decoration:none;"><div style="background-color:#25D366;color:fff;padding:12px;text-align:center;font-weight:bold;border-radius:8px;margin:10px 0;">📱 ENVIAR REPORTE WHATSAPP</div></a>', unsafe_allow_html=True)

            def sty(r): return ['background-color:#ffcccc;color:#000']*len(r) if st.session_state.w_4w else ['']*len(r)
            st.dataframe(disp.style.apply(sty, axis=1).format({'SELL OUT':"${:,.2f}", 'PROM PZS MENSUAL':"{:,.2f}"}), use_container_width=True, hide_index=True)

        st.divider()
        st.markdown("<h3 style='text-align: center; color: #444;'>🏆 RANKING DE VENTAS</h3>", unsafe_allow_html=True)

        c_mod1, c_mod2 = st.columns(2)
        with c_mod1:
            sel_state_rank = st.multiselect("Filtrar Estado (Ranking)", unique_states)
        with c_mod2:
            unique_formats = sorted(df_w.iloc[:, 16].astype(str).unique())
            sel_fmt_rank = st.multiselect("Filtrar Formato (Ranking)", unique_formats)

        r1_c1, r1_c2 = st.columns(2, gap="small")
        with r1_c1:
            st.markdown('<div class="btn-ranking-blue">', unsafe_allow_html=True)
            if st.button("📊 GENERAL", use_container_width=True): set_rank('tiendas')
            st.markdown('</div>', unsafe_allow_html=True)
        with r1_c2:
            st.markdown('<div class="btn-ranking-orange">', unsafe_allow_html=True)
            if st.button("🍝 PASTAS", use_container_width=True): set_rank('pastas')
            st.markdown('</div>', unsafe_allow_html=True)

        r2_c1, r2_c2 = st.columns(2, gap="small")
        with r2_c1:
            st.markdown('<div class="btn-ranking-olive">', unsafe_allow_html=True)
            if st.button("🫒 OLIVAS", use_container_width=True): set_rank('olivas')
            st.markdown('</div>', unsafe_allow_html=True)
        with r2_c2:
            st.markdown('<div class="btn-ranking-green">', unsafe_allow_html=True)
            if st.button("🏆 NUTRIOLI", use_container_width=True): set_rank('nutrioli')
            st.markdown('</div>', unsafe_allow_html=True)

        df_rank = df_w.copy()
        col_h_idx = 7; col_q_idx = 16
        if sel_state_rank: df_rank = df_rank[df_rank.iloc[:, col_h_idx].astype(str).isin(sel_state_rank)]
        if sel_fmt_rank: df_rank = df_rank[df_rank.iloc[:, col_q_idx].astype(str).isin(sel_fmt_rank)]

        final_df = None
        if st.session_state.w_rank_tiendas:
            final_df = df_rank.groupby(df_rank.iloc[:, 15])['SO_$'].sum().reset_index()
            final_df.columns = ['TIENDA', 'VENTA TOTAL ($)']
        elif st.session_state.w_rank_pastas:
            df_f = df_rank[df_rank.iloc[:, 5].astype(str).str.contains("PASTAS", case=False, na=False)]
            if not df_f.empty:
                final_df = df_f.groupby(df_f.iloc[:, 15])['SO_$'].sum().reset_index()
                final_df.columns = ['TIENDA', 'VENTA PASTAS ($)']
        elif st.session_state.w_rank_olivas:
            target = ["OLI SPRAY ACEITE DE OLIVA 145ML", "OLI COCINA 500ML", "OLI COCINA 250ML",
                      "OLI DE NUT EV 500ML", "OLI COCINA 750ML", "OLI DE NUT EV 250ML",
                      "OLI DE NUT EV 750ML", "OLI VINAGRE BALSAMICO 250ML"]
            df_f = df_rank[df_rank.iloc[:, 4].isin(target)]
            if not df_f.empty:
                final_df = df_f.groupby(df_f.iloc[:, 15])['SO_$'].sum().reset_index()
                final_df.columns = ['TIENDA', 'VENTA OLIVAS ($)']
        elif st.session_state.w_nutri_top10:
            df_f = df_rank[df_rank.iloc[:, 4].astype(str).str.contains("ACEITE NUTRIOLI 946M", case=False, na=False)]
            if not df_f.empty:
                final_df = df_f.groupby(df_f.iloc[:, 15])['SO_$'].sum().reset_index()
                final_df.columns = ['TIENDA', 'VENTA NUTRIOLI ($)']
                final_df = final_df.sort_values(by='VENTA NUTRIOLI ($)', ascending=False).head(10)

        if final_df is not None:
            col_val = final_df.columns[1]
            final_df = final_df.sort_values(by=col_val, ascending=False)
            st.dataframe(final_df.style.format({col_val: "${:,.2f}"}), use_container_width=True, hide_index=True)
        else:
            if any([st.session_state.w_rank_tiendas, st.session_state.w_rank_pastas, st.session_state.w_rank_olivas, st.session_state.w_nutri_top10]):
                st.warning("⚠️ No se encontraron datos con los filtros seleccionados.")

# ==============================================================================
# VISTA: CHEDRAUI
# ==============================================================================
elif st.session_state.active_retailer == 'CHEDRAUI':
    st.markdown(f"<div class='retailer-header' style='background-color: #FF6600;'>CHEDRAUI</div>", unsafe_allow_html=True)

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
    st.markdown(f"<div class='retailer-header' style='background-color: #CCFF00; color: #444;'>FRESKO</div>", unsafe_allow_html=True)
    
    @st.cache_data(**CACHE_CONFIG)
    def load_fre(file):
        df = pd.read_excel(file)
        return df

    f_fre = st.file_uploader("📂 Cargar Excel FRESKO", type=["xlsx"], key="up_fre")
    if f_fre:
        df_fre = load_fre(f_fre)
        st.dataframe(df_fre, use_container_width=True)

# --- 7. PIE DE PÁGINA ---
st.divider()
if st.button("🗑️ LIMPIAR MEMORIA / RESET", use_container_width=True):
    st.cache_data.clear()
    st.session_state.clear()
    st.rerun()