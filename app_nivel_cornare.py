"""
App de Streamlit — Monitoreo Hidrológico (CORNARE / MARCO)
Versión Mejorada - Modo Oscuro & Dashboard Interactivo
"""

import requests
import pandas as pd
import numpy as np
import streamlit as st
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ------------------------------------------------------------------
# Configuración inicial de la página
# ------------------------------------------------------------------
st.set_page_config(
    page_title="HidroSanCarlos - Monitoreo Ambiental",
    page_icon="🌊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ------------------------------------------------------------------
# Estilos CSS Personalizados (Modo Oscuro & Tarjetas)
# ------------------------------------------------------------------
st.markdown("""
    <style>
    /* Fondo principal */
    .stApp {
        background-color: #0E1117;
        color: #E6EDF3;
    }
    
    /* Estilo de la barra lateral */
    [data-testid="stSidebar"] {
        background-color: #161B22;
        border-right: 1px solid #30363D;
    }

    /* Tarjetas de Métricas Personalizadas */
    .metric-box {
        background: #161B22;
        border: 1px solid #30363D;
        border-top: 4px solid #00D2FF;
        border-radius: 10px;
        padding: 16px;
        text-align: center;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
        margin-bottom: 10px;
    }
    .metric-title {
        color: #8B949E;
        font-size: 0.82rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-bottom: 6px;
    }
    .metric-value {
        color: #FFFFFF;
        font-size: 1.8rem;
        font-weight: 700;
    }
    .metric-badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 12px;
        font-size: 0.75rem;
        font-weight: 600;
        margin-top: 4px;
    }
    .badge-good { background-color: rgba(46, 160, 67, 0.2); color: #3FB950; }
    .badge-alert { background-color: rgba(248, 81, 73, 0.2); color: #F85149; }

    /* Personalización del contenedor de imágenes */
    .header-img {
        border-radius: 12px;
        box-shadow: 0 4px 15px rgba(0,210,255,0.2);
    }
    </style>
""", unsafe_allow_html=True)

# ------------------------------------------------------------------
# Constantes y API
# ------------------------------------------------------------------
LAT_DEFECTO = 6.2766
LON_DEFECTO = -75.5901
API_BASE_URL = "https://marco.cornare.gov.co/api/v1/estaciones"

LLAVE_FECHA = "level_date"
LLAVE_VALOR = "level"
CANDIDATOS_LAT = ["lat", "latitude", "latitud"]
CANDIDATOS_LON = ["lng", "lon", "longitude", "longitud"]


# ------------------------------------------------------------------
# Funciones de consulta y procesamiento (Lógica Original Conservada)
# ------------------------------------------------------------------
def obtener_serie_nivel(codigo_estacion, desde, hasta, calidad=1, timeout=30):
    url = f"{API_BASE_URL}/{codigo_estacion}/nivel"
    params = {"desde": desde, "hasta": hasta, "calidad": calidad}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
    }
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=timeout, verify=False)
        if resp.status_code == 200:
            return resp.json(), None
        return None, f"HTTP {resp.status_code}"
    except requests.exceptions.RequestException as e:
        return None, f"Error de red: {e}"


def obtener_todas_las_paginas(datos_json, timeout=30):
    registros = list(datos_json.get("values", []))
    siguiente_url = datos_json.get("next")
    while siguiente_url:
        try:
            resp = requests.get(siguiente_url, timeout=timeout, verify=False)
        except requests.exceptions.RequestException:
            break
        if resp.status_code != 200:
            break
        pagina = resp.json()
        registros.extend(pagina.get("values", []))
        siguiente_url = pagina.get("next")
    return registros


def detectar_coordenadas(datos_json):
    if not isinstance(datos_json, dict):
        return LAT_DEFECTO, LON_DEFECTO, False

    lat = next((datos_json[k] for k in CANDIDATOS_LAT if k in datos_json), None)
    lon = next((datos_json[k] for k in CANDIDATOS_LON if k in datos_json), None)

    if lat is not None and lon is not None:
        try:
            return float(lat), float(lon), True
        except (TypeError, ValueError):
            pass
    return LAT_DEFECTO, LON_DEFECTO, False


def calcular_indice_calidad(df):
    if df.empty or len(df) < 2:
        return 0.0, 0, 0

    df_idx = df.set_index("fecha")
    frecuencia_tipica = df["fecha"].diff().dropna().mode()
    if len(frecuencia_tipica) == 0:
        return 0.0, 0, 0
    frecuencia_tipica = frecuencia_tipica[0]

    rango_completo = pd.date_range(start=df_idx.index.min(), end=df_idx.index.max(), freq=frecuencia_tipica)
    esperados = len(rango_completo)
    huecos = esperados - len(df_idx)
    completitud = max(0.0, 1 - (huecos / esperados)) if esperados > 0 else 0.0

    Q1, Q3 = df["nivel"].quantile(0.25), df["nivel"].quantile(0.75)
    IQR = Q3 - Q1
    lim_inf, lim_sup = Q1 - 1.5 * IQR, Q3 + 1.5 * IQR
    es_outlier = (df["nivel"] < lim_inf) | (df["nivel"] > lim_sup) | (df["nivel"] < 0)
    proporcion_outliers = es_outlier.mean()

    indice = (completitud * 0.7 + (1 - proporcion_outliers) * 0.3) * 100
    return round(indice, 1), int(huecos), int(es_outlier.sum())


# ------------------------------------------------------------------
# Sidebar — Parámetros de la consulta
# ------------------------------------------------------------------
st.sidebar.markdown("## ⚙️ Parámetros")
st.sidebar.caption("Ajusta los filtros para consultar la API de CORNARE.")

nombre_estudiante = st.sidebar.text_input("👤 Nombre del estudiante", "Valentina Padilla")
codigo_estacion = st.sidebar.text_input("📍 Código de estación", "28")

col_d1, col_d2 = st.sidebar.columns(2)
with col_d1:
    fecha_desde = st.sidebar.date_input("📅 Desde", pd.to_datetime("2026-08-25")).strftime("%Y-%m-%d")
with col_d2:
    fecha_hasta = st.sidebar.date_input("📅 Hasta", pd.to_datetime("2026-08-31")).strftime("%Y-%m-%d")

calidad = st.sidebar.selectbox("🛡️ Calidad de datos", [1, 0], index=0, help="1 = solo datos validados")

consultar = st.sidebar.button("🔍 Consultar Datos", type="primary", use_container_width=True)


# ------------------------------------------------------------------
# ENCABEZADO CON IMAGEN Y TÍTULO
# ------------------------------------------------------------------
col_head1, col_head2 = st.columns([3, 1])

with col_head1:
    st.title("🌊 HidroSanCarlos 📈")
    st.markdown(f"""
        <div style="background-color: #161B22; padding: 12px 18px; border-radius: 8px; border-left: 4px solid #00D2FF;">
            <b>Estudiante:</b> {nombre_estudiante} &nbsp;|&nbsp; 
            <b>Estación activa:</b> <span style="color:#00D2FF; font-weight:bold;">{codigo_estacion}</span> &nbsp;|&nbsp;
            <b>Rango:</b> {fecha_desde} a {fecha_hasta}
        </div>
    """, unsafe_allow_html=True)

with col_head2:
    # AQUÍ PUEDES REEMPLAZAR LA URL POR LA RUTA LOCAL DE TU IMAGEN O LOGO
    # Ejemplo con archivo local: st.image("logo_estacion.png", use_container_width=True)
    st.image(
        "https://images.unsplash.com/photo-1500382017468-9049fed747ef?auto=format&fit=crop&w=500&q=80",
        caption="Monitoreo Cuenca San Carlos",
        use_container_width=True
    )

st.write("")


# ------------------------------------------------------------------
# CONSULTA Y PROCESAMIENTO
# ------------------------------------------------------------------
if consultar:
    with st.spinner("Conectando con la API de CORNARE/MARCO..."):
        datos_crudos, error = obtener_serie_nivel(codigo_estacion, fecha_desde, fecha_hasta, calidad)

    if error:
        st.error(f"❌ Error al consultar la estación: {error}")
    else:
        registros = obtener_todas_las_paginas(datos_crudos)

        if not registros:
            st.warning("⚠️ No se encontraron registros para esta estación en el rango seleccionado.")
        else:
            # Construcción del DataFrame
            df = pd.DataFrame(registros)
            df = df.rename(columns={LLAVE_FECHA: "fecha", LLAVE_VALOR: "nivel"})
            df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
            df["nivel"] = pd.to_numeric(df["nivel"], errors="coerce")
            df = df.dropna(subset=["fecha", "nivel"]).sort_values("fecha").reset_index(drop=True)

            lat, lon, coords_reales = detectar_coordenadas(datos_crudos)
            indice_calidad, huecos, n_outliers = calcular_indice_calidad(df)

            # --- TARJETAS KPI DE MÉTRICAS ---
            m1, m2, m3, m4 = st.columns(4)

            with m1:
                st.markdown(f"""
                    <div class="metric-box">
                        <div class="metric-title">Lecturas Totales</div>
                        <div class="metric-value">{len(df):,}</div>
                        <div class="metric-badge badge-good">Registros OK</div>
                    </div>
                """, unsafe_allow_html=True)

            with m2:
                st.markdown(f"""
                    <div class="metric-box">
                        <div class="metric-title">Nivel Promedio</div>
                        <div class="metric-value">{df['nivel'].mean():.2f} <span style="font-size:0.9rem; color:#8B949E;">cm</span></div>
                        <div class="metric-badge badge-good">Muestra estable</div>
                    </div>
                """, unsafe_allow_html=True)

            with m3:
                badge_class = "badge-good" if indice_calidad >= 80 else "badge-alert"
                st.markdown(f"""
                    <div class="metric-box">
                        <div class="metric-title">Índice de Calidad</div>
                        <div class="metric-value">{indice_calidad} <span style="font-size:1rem; color:#8B949E;">/100</span></div>
                        <div class="metric-badge {badge_class}">Confiabilidad</div>
                    </div>
                """, unsafe_allow_html=True)

            with m4:
                st.markdown(f"""
                    <div class="metric-box" style="border-top-color: #F85149;">
                        <div class="metric-title">Outliers Detectados</div>
                        <div class="metric-value" style="color: #F85149;">{n_outliers}</div>
                        <div class="metric-badge badge-alert">{huecos} huecos en serie</div>
                    </div>
                """, unsafe_allow_html=True)

            st.write("")

            # --- SECCIONES PESTAÑAS (TABS) ---
            tab_grafico, tab_mapa, tab_datos = st.tabs(["📈 Serie de Nivel Interactivas", "📍 Ubicación Geográfica", "📋 Datos Crudos y Exportación"])

            # 1. PESTAÑA GRÁFICO PLOTLY
            with tab_grafico:
                st.subheader("Serie temporal de nivel de agua")
                
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=df["fecha"],
                    y=df["nivel"],
                    mode='lines',
                    name='Nivel (cm)',
                    line=dict(color='#00D2FF', width=2),
                    fill='tozeroy',
                    fillcolor='rgba(0, 210, 255, 0.08)'
                ))

                fig.update_layout(
                    template="plotly_dark",
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="#161B22",
                    height=450,
                    margin=dict(l=20, r=20, t=30, b=20),
                    hovermode="x unified",
                    xaxis=dict(gridcolor="#21262D", showgrid=True),
                    yaxis=dict(gridcolor="#21262D", title="Nivel (cm)", showgrid=True)
                )

                st.plotly_chart(fig, use_container_width=True)

            # 2. PESTAÑA MAPA
            with tab_mapa:
                st.subheader("Ubicación de la estación hidrológica")
                if not coords_reales:
                    st.info("ℹ️ Coordenadas por defecto (Pascual Bravo). La API no retornó `lat/lon` específicas.")
                
                df_map = pd.DataFrame({"lat": [lat], "lon": [lon]})
                st.map(df_map, zoom=11)

            # 3. PESTAÑA DATOS Y CALIDAD
            with tab_datos:
                col_tab1, col_tab2 = st.columns([2, 1])

                with col_tab1:
                    st.subheader("Tabla de Registros")
                    st.dataframe(df, use_container_width=True, height=350)

                with col_tab2:
                    st.subheader("Informe de Calidad")
                    st.markdown(f"""
                        * **Huecos de reporte:** `{huecos}`
                        * **Anomalías / Outliers:** `{n_outliers}` de `{len(df)}` lecturas
                        * **Cálculo:** Ponderación 70% completitud temporal + 30% filtro IQR.
                    """)
                    
                    csv = df.to_csv(index=False).encode("utf-8")
                    st.download_button(
                        label="⬇️ Descargar archivo CSV",
                        data=csv,
                        file_name=f"estacion_{codigo_estacion}_{fecha_desde}_al_{fecha_hasta}.csv",
                        mime="text/csv",
                        use_container_width=True
                    )

else:
    st.info("👈 Selecciona los parámetros en la barra lateral y presiona el botón **Consultar Datos**.")
