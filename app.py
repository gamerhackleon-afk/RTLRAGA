import streamlit as st
import pandas as pd
import time
import urllib.parse 
from PIL import Image

# --- CONFIGURACIÓN DE PÁGINA (OFFLINE MODE) ---
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

# --- ESTILOS CSS OPTIMIZADOS PARA MÓVIL Y OFFLINE ---
st.markdown("""
<style>
    /* 1. MAXIMIZAR ESPACIO EN PANTALLA MÓVIL */
    .block-container {
        padding-top: 0.5rem !important;
        padding-bottom: 2rem !important;
        padding-left: 0.5rem !important;
        padding-right: 0.5rem !important;
    }
    
    /* 2. BOTONES GRANDES (FÁCILES DE TOCAR) */
    div.stButton > button:first-child {
        background-color: #ff4b4b;
        color: white;
        height: 3.5em !important; /* Más altos para el dedo */
        font-weight: bold;
        border-radius: 10px;
        font-size: 16px !important;
        box-shadow: 0px 4px 6px rgba(0,0,0,0.2);
    }
    
    /* 3. PESTAÑAS MÁS GRANDES Y LEGIBLES */
    .stTabs [data-baseweb="tab-list"] {
        gap: 5px;
        overflow-x: auto; /* Permite scroll horizontal en pestañas si no caben */
        white-space: nowrap;
    }
    .stTabs [data-baseweb="tab"] {
        height: 60px; /* Más altas */
        padding: 10px 20px;
        background-color: #f0f2f6;
        border-radius: 8px 8px 0px 0px;
        font-size: 1rem;
        flex-grow: 1; /* Ocupar espacio disponible */
        text-align: center;
    }

    /* 4. COLORES ESPECÍFICOS DE PESTAÑAS (SORIANA, WALMART, CHEDRAUI) */
    /* Soriana (Rojo) */
    div[data-baseweb="tab-list"] button:nth-child(1)[aria-selected="true"] {
        border-bottom: 5px solid #E31C23 !important;
        color: #E31C23 !important;
        background-color: #fff !important;
    }
    /* Walmart (Azul) */
    div[data-baseweb="tab-list"] button:nth-child(2)[aria-selected="true"] {
        border-bottom: 5px solid #0071DC !important;
        color: #0071DC !important;
        background-color: #fff !important;
    }
    /* Chedraui (Naranja) */
    div[data-baseweb="tab-list"] button:nth-child(3)[aria-selected="true"] {
        border-bottom: 5px solid #FF6600 !important;
        color: #FF6600 !important;
        background-color: #fff !important;
    }

    /* 5. MENSAJES Y MÉTRICAS COMPACTOS */
    div[data-testid="stMetric"] {
        background-color: #f1f3f4;
        padding: 10px;
        border-radius: 10px;
        border: 1px solid #ddd;
        text-align: center;
    }
    
    /* Alineación vertical del logo y título */
    [data-testid="stVerticalBlock"] > [style*="flex-direction: column;"] > [data-testid="stVerticalBlock"] {
        align-items: center;
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
    st.markdown("<h3 style='margin-top:10px;'>GESTOR INVENTARIOS</h3>", unsafe_allow_html=True)

# --- TABS ---
tab_sor, tab_wal, tab_che = st.tabs(["SORIANA", "WALMART", "CHEDRAUI"])

# ==============================================================================
#                               PESTAÑA 1: SORIANA
# ==============================================================================
with tab_sor:
    if 's_rojo' not in st.session_state: st.session_state.s_rojo = False
    
    def tog_s_rojo(): st.session_state.s_rojo = not st.session_state.s_rojo

    @st.cache_data(ttl=3600)
    def load_sor(file):
        df = pd.read_excel(file)
        if df.shape[1] < 22: return None
        # Limpieza P..T
        for c in df.iloc[:, 15:20].columns:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
        # Suma P..S
        df['VTA_PROM'] = df.iloc[:, 15:19].sum(axis=1)
        # Flag Sin Venta
        df['SIN_VTA'] = ((df.iloc[:,15]==0)&(df.iloc[:,16]==0)&(df.iloc[:,17]==0)&(df.iloc[:,18]==0))
        return df

    f_s = st.file_uploader("Cargar Excel SORIANA", type=["xlsx"], key="up_s")

    if f_s:
        df_s = load_sor(f_s)
        if df_s is None:
            st.error("Formato incorrecto")
        else:
            with st.expander("🔍 Filtros Soriana", expanded=False):
                col1, col2 = st.columns(2)
                with col1:
                    c_res = df_s.columns[0]
                    u_res = sorted(df_s[c_res].astype(str).unique())
                    def_res = [x for x in u_res if x in ["1","1.0","2","2.0"]] or None
                    fil_res = st.multiselect("Resurtible", ["Todos"]+u_res, default=def_res)
                    
                    c_nda = df_s.columns[5] # No Tienda
                    fil_nda = st.multiselect("No Tienda", sorted(df_s[c_nda].astype(str).unique()))
                    
                    c_nom = df_s.columns[6] # Nombre
                    fil_nom = st.multiselect("Nombre", sorted(df_s[c_nom].astype(str).unique()))
                    
                    c_cat = df_s.columns[4] # Categoria
                    fil_cat = st.multiselect("Categoría", sorted(df_s[c_cat].astype(str).unique()))
                with col2:
                    c_cd = df_s.columns[7]
                    fil_cd = st.multiselect("Ciudad", sorted(df_s[c_cd].astype(str).unique()))
                    c_edo = df_s.columns[8]
                    fil_edo = st.multiselect("Estado", sorted(df_s[c_edo].astype(str).unique()))
                    c_fmt = df_s.columns[9]
                    fil_fmt = st.multiselect("Formato", sorted(df_s[c_fmt].astype(str).unique()))

            # Filtrado
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
            
            # Columnas Finales
            # G(Nombre), C(Cod), D(Desc), E(Cat), VTA_PROM, V(Dias), T(Cajas)
            cols_fin = [df_s.columns[6], df_s.columns[2], df_s.columns[3], df_s.columns[4], 'VTA_PROM', df_s.columns[21], df_s.columns[19]]
            disp = dff[cols_fin].copy()
            disp.columns = ['TIENDA', 'COD', 'DESC', 'CAT', 'VTA PROM', 'DIAS', 'CAJAS']

            # Botones Acción
            st.write("")
            lbl = "🔴 APAGAR SIN VENTA" if st.session_state.s_rojo else "🔴 INV SIN VENTA"
            st.button(lbl, on_click=tog_s_rojo, use_container_width=True, type="primary")

            # WhatsApp
            msg = [f"*SORIANA ({len(disp)})*"]
            for _, r in disp.head(40).iterrows():
                msg.append(f"🏢 {r['TIENDA']}\n📦 {r['DESC']}\n📊 Inv:{r['CAJAS']} | Dias:{r['DIAS']}\n-")
            if len(disp)>40: msg.append(f"... +{len(disp)-40}")
            url = f"https://wa.me/?text={urllib.parse.quote(chr(10).join(msg))}"
            st.markdown(f'<a href="{url}" target="_blank" style="text-decoration:none;"><div style="background-color:#25D366;color:fff;padding:12px;border-radius:10px;text-align:center;font-weight:bold;margin:10px 0;box-shadow:0 2px 4px rgba(0,0,0,0.2);">📱 WHATSAPP</div></a>', unsafe_allow_html=True)

            # Estilo
            def sty(r): return ['background-color:#ffcccc;color:#000']*len(r) if st.session_state.s_rojo else ['']*len(r)
            
            st.dataframe(disp.style.apply(sty, axis=1).format(precision=2), use_container_width=True, hide_index=True)


# ==============================================================================
#                               PESTAÑA 2: WALMART
# ==============================================================================
with tab_wal:
    if 'w_neg' not in st.session_state: st.session_state.w_neg = False
    if 'w_4w' not in st.session_state: st.session_state.w_4w = False

    def tog_w_neg():
        st.session_state.w_neg = not st.session_state.w_neg
        if st.session_state.w_neg: st.session_state.w_4w = False

    def tog_w_4w():
        st.session_state.w_4w = not st.session_state.w_4w
        if st.session_state.w_4w: st.session_state.w_neg = False

    @st.cache_data(ttl=3600)
    def load_wal(file):
        df = pd.read_excel(file)
        if df.shape[1] < 97: return None
        # Numéricos Calc CO..CS
        for c in df.iloc[:, 92:97].columns: df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
        # Numéricos 4W BV..BY
        for c in df.iloc[:, 73:77].columns: df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
        # Negativos AQ(42)
        c42 = df.columns[42]
        df[c42] = pd.to_numeric(df[c42], errors='coerce').fillna(0)
        
        df['SO_$'] = df.iloc[:, 92:96].sum(axis=1)
        return df

    f_w = st.file_uploader("Cargar Excel WALMART", type=["xlsx"], key="up_w")

    if f_w:
        df_w = load_wal(f_w)
        if df_w is None:
            st.error("Formato incorrecto")
        else:
            # Eliminar BAE/MB en Q(16)
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

            # Botones
            st.write("")
            b1, b2 = st.columns(2)
            with b1: st.button("📉 NEGATIVOS" if not st.session_state.w_neg else "📉 QUITAR NEG", on_click=tog_w_neg, use_container_width=True, type="primary")
            with b2: st.button("🔴 SIN VTA 4SEM" if not st.session_state.w_4w else "🔴 QUITAR 4SEM", on_click=tog_w_4w, use_container_width=True, type="primary")

            # Filtrado
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

            # KPI
            st.metric("TOTAL SELL OUT $", f"${dff[df_w.columns[96]].sum():,.2f}")

            # Tabla: A(0), E(4), P(15), AH(33), AQ(42), CALC, AM(38)
            cols = [df_w.columns[0], df_w.columns[4], df_w.columns[15], df_w.columns[33], df_w.columns[42], 'SO_$', df_w.columns[38]]
            disp = dff[cols].copy()
            disp.columns = ['COD', 'DESC', 'TIENDA', 'DDI', 'EXIST', 'SO $', 'PROM PZAS']

            # Whats
            msg = [f"*WALMART ({len(disp)})*"]
            for _, r in disp.head(40).iterrows():
                msg.append(f"🏢 {r['TIENDA']}\n📦 {r['DESC']}\n📊 Ext:{r['EXIST']} | SO$:{r['SO $']:,.2f}\n-")
            if len(disp)>40: msg.append("...")
            url = f"https://wa.me/?text={urllib.parse.quote(chr(10).join(msg))}"
            st.markdown(f'<a href="{url}" target="_blank" style="text-decoration:none;"><div style="background-color:#25D366;color:fff;padding:12px;border-radius:10px;text-align:center;font-weight:bold;margin:10px 0;box-shadow:0 2px 4px rgba(0,0,0,0.2);">📱 WHATSAPP</div></a>', unsafe_allow_html=True)

            def sty(r): return ['background-color:#ffcccc;color:#000']*len(r) if st.session_state.w_4w else ['']*len(r)
            st.dataframe(disp.style.apply(sty, axis=1).format({'SO $':"${:,.2f}", 'PROM PZAS':"{:,.2f}"}), use_container_width=True, hide_index=True)


# ==============================================================================
#                               PESTAÑA 3: CHEDRAUI
# ==============================================================================
with tab_che:
    if 'c_alt' not in st.session_state: st.session_state.c_alt = False
    if 'c_neg' not in st.session_state: st.session_state.c_neg = False

    def tog_c_alt():
        st.session_state.c_alt = not st.session_state.c_alt
        if st.session_state.c_alt: st.session_state.c_neg = False

    def tog_c_neg():
        st.session_state.c_neg = not st.session_state.c_neg
        if st.session_state.c_neg: st.session_state.c_alt = False

    @st.cache_data(ttl=3600)
    def load_che(file):
        df = pd.read_excel(file)
        if df.shape[1] < 18: return None
        for c in df.iloc[:, [12,14,16,17]].columns: df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
        return df

    f_c = st.file_uploader("Cargar Excel CHEDRAUI", type=["xlsx"], key="up_c")

    if f_c:
        df_c = load_che(f_c)
        if df_c is None:
            st.error("Formato incorrecto")
        else:
            with st.expander("🔍 Filtros Chedraui", expanded=False):
                c1, c2 = st.columns(2)
                with c1:
                    ci = df_c.columns[8] # No
                    fil_no = st.multiselect("No (#)", sorted(df_c[ci].astype(str).unique()))
                    cj = df_c.columns[9] # Tienda
                    fil_ti = st.multiselect("Tienda", sorted(df_c[cj].astype(str).unique()))
                with c2:
                    cd = df_c.columns[3] # Edo
                    fil_ed = st.multiselect("Estado", sorted(df_c[cd].astype(str).unique()))

            # Botones
            st.write("")
            b1, b2 = st.columns(2)
            with b1: st.button("📈 DDI > 30" if not st.session_state.c_alt else "📈 QUITAR FILTRO", on_click=tog_c_alt, use_container_width=True, type="primary")
            with b2: st.button("📉 DDI < 0" if not st.session_state.c_neg else "📉 QUITAR FILTRO", on_click=tog_c_neg, use_container_width=True, type="primary")

            # Filtrado
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

            # Tabla: L(11), M(12), O(14), Q(16), R(17)
            cols = [df_c.columns[11], df_c.columns[12], df_c.columns[14], df_c.columns[16], df_c.columns[17]]
            disp = dff[cols].copy()
            disp.columns = ['DESC', 'INV ULT SEM', 'VTA ULT SEM', 'VTA PROM', 'DDI']
            
            st.dataframe(disp.style.format(precision=2), use_container_width=True, hide_index=True)