"""
Aplicativo para la Consulta y Seguimiento de Puntos Potenciales
Inteligencia de Expansión - OXXO
Proyecto de práctica profesional - Alisson Gómez

Prototipo construido con Streamlit. El archivo data/Puntos_potenciales.xlsx
va incluido en el propio proyecto y se carga automáticamente cada vez que
se abre la app (igual que un "Book.xlsx" que viaja con el proyecto): para
actualizar los datos, basta con reemplazar ese archivo en el repositorio.
También existen, como alternativas, subir un archivo desde la app o
conectarse en vivo a un link de OneDrive (pestaña "Actualizar datos").
"""

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import pydeck as pdk
import streamlit as st
import streamlit.components.v1 as components

from utils import (
    COLOR_ESTADO,
    ESTADOS,
    UMBRAL_DUPLICIDAD_GENERADOR_M,
    UMBRAL_DUPLICIDAD_M,
    UMBRAL_SIMILITUD_NOMBRE,
    agrupar_generadores,
    buscar_por_nombre,
    cargar_generadores_cache,
    cargar_puntos,
    detectar_coincidencias,
    detectar_generadores_coincidentes,
    eliminar_punto,
    guardar_generadores,
    guardar_puntos,
    leer_archivo_fuente,
    leer_desde_url,
    leer_generadores_desde_arcgis,
)

METADATA_PATH = Path("data/metadata.json")
RUTA_EXCEL_BUNDLED = Path("data/Puntos_potenciales.xlsx")

# Nombre de la clave en "Secrets" de Streamlit Cloud donde se guarda, de
# forma privada (nunca visible en el código ni en GitHub), el link de
# OneDrive del archivo "Puente" que actualiza todo el equipo. Si esta
# clave no está configurada, la app sigue funcionando igual con el Excel
# incluido en el proyecto (RUTA_EXCEL_BUNDLED) como hasta ahora.
SECRET_KEY_URL_COMITE = "url_puente_comite"

# Color morado por defecto para los puntos potenciales en los mapas
# (mismo estilo que ya reconoce el área). El interruptor "Colorear por
# especialista" lo reemplaza por una paleta distinta por persona.
COLOR_MORADO = [124, 58, 168]
_PALETA_ESPECIALISTAS = [
    [124, 58, 168], [230, 126, 34], [39, 174, 96], [41, 128, 185],
    [192, 57, 43], [22, 160, 133], [211, 84, 0], [142, 68, 173],
    [44, 62, 80], [243, 156, 18], [26, 188, 156], [127, 140, 141],
]


def color_por_especialista(nombre: str):
    """Color determinístico (siempre el mismo para el mismo nombre) tomado de una paleta fija."""
    nombre = str(nombre or "").strip()
    if not nombre:
        return [150, 150, 150]
    indice = sum(ord(c) for c in nombre) % len(_PALETA_ESPECIALISTAS)
    return _PALETA_ESPECIALISTAS[indice]


def url_mapa_embed(lat: float, lon: float, zoom: int = 17) -> str:
    """Google Maps normal (satelital/calles), centrado en el punto. No necesita cuenta ni API key."""
    return f"https://maps.google.com/maps?q={lat},{lon}&z={zoom}&output=embed"


def url_streetview_embed(lat: float, lon: float) -> str:
    """Google Street View (vista a nivel de calle) en el punto indicado. No necesita cuenta ni API key."""
    return f"https://maps.google.com/maps?layer=c&cbll={lat},{lon}&cbp=11,0,0,0,0&output=svembed"

# Paleta de marca OXXO (rojo #E21C2A y naranja/amarillo #F0A929 son los
# colores oficiales de la marca; los demás son neutros de apoyo).
OXXO_ROJO = "#E21C2A"
OXXO_ROJO_OSCURO = "#B7141F"
OXXO_NARANJA = "#F0A929"
OXXO_TEXTO = "#1A1A1A"
OXXO_GRIS_FONDO = "#F7F7F8"
OXXO_GRIS_BORDE = "#E5E5E8"

st.set_page_config(
    page_title="Puntos Potenciales | Inteligencia de Expansión OXXO",
    page_icon="📍",
    layout="wide",
)

st.markdown(
    f"""
    <style>
    .stApp {{
        background-color: {OXXO_GRIS_FONDO};
    }}

    h1, h2, h3 {{
        color: {OXXO_TEXTO} !important;
        font-weight: 700 !important;
    }}

    /* Botones primarios (type="primary") en rojo OXXO */
    button[kind="primary"], button[kind="primaryFormSubmit"] {{
        background-color: {OXXO_ROJO} !important;
        border-color: {OXXO_ROJO} !important;
        color: #FFFFFF !important;
        font-weight: 600 !important;
        border-radius: 8px !important;
    }}
    button[kind="primary"]:hover, button[kind="primaryFormSubmit"]:hover {{
        background-color: {OXXO_ROJO_OSCURO} !important;
        border-color: {OXXO_ROJO_OSCURO} !important;
    }}

    /* Botones secundarios: borde rojo, texto rojo */
    button[kind="secondary"], button[kind="secondaryFormSubmit"] {{
        border-color: {OXXO_ROJO} !important;
        color: {OXXO_ROJO} !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
    }}
    button[kind="secondary"]:hover, button[kind="secondaryFormSubmit"]:hover {{
        background-color: rgba(226, 28, 42, 0.08) !important;
    }}

    /* Pestañas: subrayado y texto en rojo cuando están activas */
    .stTabs [data-baseweb="tab-list"] {{
        gap: 4px;
        border-bottom: 2px solid {OXXO_GRIS_BORDE};
    }}
    .stTabs [data-baseweb="tab"] {{
        font-weight: 600;
        color: #6B6B70;
    }}
    .stTabs [data-baseweb="tab"][aria-selected="true"] {{
        color: {OXXO_ROJO} !important;
        border-bottom: 3px solid {OXXO_ROJO} !important;
    }}

    /* Valores de las métricas en rojo OXXO */
    [data-testid="stMetricValue"] {{
        color: {OXXO_ROJO};
        font-weight: 700;
    }}

    /* Contenedores con borde (st.container(border=True)) con acento rojo a la izquierda */
    [data-testid="stVerticalBlockBorderWrapper"] {{
        border-radius: 10px !important;
    }}

    /* Radio buttons y checkboxes en rojo cuando están seleccionados */
    [data-baseweb="radio"] div:first-child {{
        border-color: {OXXO_ROJO} !important;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)


def leer_metadata() -> dict:
    if METADATA_PATH.exists():
        return json.loads(METADATA_PATH.read_text())
    return {}


def guardar_metadata(**campos) -> None:
    actual = leer_metadata()
    actual.update(campos)
    actual["ultima_actualizacion"] = datetime.now().strftime("%d/%m/%Y %H:%M")
    METADATA_PATH.write_text(json.dumps(actual))


@st.cache_data(show_spinner="Descargando la versión más reciente del Excel...")
def _leer_desde_url_cacheado(url: str):
    """
    Envuelve leer_desde_url en caché de Streamlit. La caché NO expira sola
    por tiempo: solo se refresca cuando el usuario le da clic al botón
    "Actualizar ahora" (que llama a .clear()), para que la actualización
    ocurra únicamente cuando se necesite y no en cada rato.
    """
    return leer_desde_url(url)


@st.cache_data(show_spinner="Consultando la capa de generadores...")
def _leer_generadores_cacheado():
    """
    Igual patrón que _leer_desde_url_cacheado: caché sin expiración por
    tiempo, solo se refresca con el botón "Actualizar generadores".
    """
    return leer_generadores_desde_arcgis()


# ---------------------------------------------------------------------------
# Estado inicial
# ---------------------------------------------------------------------------
metadata = leer_metadata()
error_fuente_url = None
cargado_desde_bundle = False
cargado_desde_secret = False

# El link del archivo "Puente" del equipo vive de forma privada en los
# Secrets de Streamlit Cloud (nunca en el código ni en GitHub). Si está
# configurado, es la fuente de más prioridad — por encima incluso del
# Excel incluido en el proyecto.
url_secreta = ""
try:
    url_secreta = st.secrets.get(SECRET_KEY_URL_COMITE, "")
except Exception:
    url_secreta = ""

if "puntos" not in st.session_state:
    if url_secreta:
        try:
            st.session_state.puntos = _leer_desde_url_cacheado(url_secreta)
            cargado_desde_secret = True
        except Exception as e:
            # Si falla la descarga en vivo (p. ej. el link dejó de ser público),
            # no se cae la app: se usa la última copia local guardada.
            error_fuente_url = str(e)
            st.session_state.puntos = cargar_puntos()
    elif metadata.get("modo") == "url" and metadata.get("url_fuente"):
        try:
            st.session_state.puntos = _leer_desde_url_cacheado(metadata["url_fuente"])
        except Exception as e:
            # Si falla la descarga en vivo (p. ej. el link dejó de ser público),
            # no se cae la app: se usa la última copia local guardada.
            error_fuente_url = str(e)
            st.session_state.puntos = cargar_puntos()
    elif RUTA_EXCEL_BUNDLED.exists():
        # Forma principal: el Excel viaja incluido en el proyecto y se lee
        # solo, cada vez que se abre la app — igual que un "Book.xlsx".
        try:
            st.session_state.puntos = leer_archivo_fuente(
                RUTA_EXCEL_BUNDLED, RUTA_EXCEL_BUNDLED.name
            )
            cargado_desde_bundle = True
        except Exception as e:
            error_fuente_url = f"No se pudo leer {RUTA_EXCEL_BUNDLED.name}: {e}"
            st.session_state.puntos = cargar_puntos()
    else:
        st.session_state.puntos = cargar_puntos()

df = st.session_state.puntos

if error_fuente_url:
    st.error(f"⚠️ {error_fuente_url} (se está mostrando la última copia guardada).", icon="⚠️")

error_generadores = None
if "generadores" not in st.session_state:
    try:
        st.session_state.generadores = _leer_generadores_cacheado()
        guardar_generadores(st.session_state.generadores)
    except Exception as e:
        error_generadores = str(e)
        st.session_state.generadores = cargar_generadores_cache()

df_generadores = st.session_state.generadores

# ---------------------------------------------------------------------------
# Encabezado — barra de marca estilo OXXO
# ---------------------------------------------------------------------------
st.markdown(
    f"""
    <div style="
        background: linear-gradient(135deg, {OXXO_ROJO}, {OXXO_ROJO_OSCURO});
        border-radius: 16px;
        padding: 24px 30px;
        margin-bottom: 18px;
        box-shadow: 0 4px 18px rgba(226, 28, 42, 0.28);
        display: flex;
        align-items: center;
        gap: 20px;
    ">
        <div style="
            background: #FFFFFF;
            color: {OXXO_ROJO};
            font-weight: 800;
            font-size: 26px;
            padding: 8px 14px;
            border-radius: 10px;
            letter-spacing: 1px;
            font-family: Arial, Helvetica, sans-serif;
            line-height: 1;
        ">OXXO</div>
        <div>
            <div style="color: #FFFFFF; font-size: 25px; font-weight: 700; line-height: 1.25;">
                Consulta y Seguimiento de Puntos Potenciales
            </div>
            <div style="color: {OXXO_NARANJA}; font-size: 14px; font-weight: 600;">
                Inteligencia de Expansión &nbsp;·&nbsp; Prototipo de práctica profesional
            </div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

_hay_fuente_url = bool(url_secreta) or (metadata.get("modo") == "url" and metadata.get("url_fuente"))
if _hay_fuente_url:
    col_espacio, col_refrescar = st.columns([5, 1.3])
    with col_refrescar:
        if st.button("🔄 Actualizar desde OneDrive", use_container_width=True, type="primary"):
            _leer_desde_url_cacheado.clear()
            _url_para_refrescar = url_secreta or metadata.get("url_fuente", "")
            try:
                nuevo_df = _leer_desde_url_cacheado(_url_para_refrescar)
            except Exception as e:
                st.error(f"No se pudo actualizar: {e}")
            else:
                st.session_state.puntos = nuevo_df
                guardar_puntos(nuevo_df)
                if not url_secreta:
                    # Si la fuente viene del secret, no hace falta guardar el
                    # link en metadata.json (ya vive de forma privada en
                    # Streamlit); solo se guarda cuando viene del flujo manual
                    # de la pestaña "Actualizar datos".
                    guardar_metadata(modo="url", url_fuente=_url_para_refrescar, archivo_origen="Link de OneDrive (en vivo)")
                else:
                    guardar_metadata(archivo_origen="Puente del equipo (OneDrive, en vivo)")
                st.rerun()

if cargado_desde_secret:
    st.success(
        f"🔒 Conectado en vivo al archivo Puente del equipo · {len(df)} puntos potenciales",
        icon="🔒",
    )
    st.caption(
        "El link de OneDrive está guardado de forma privada (no aparece en "
        "el código ni en GitHub). Dale clic a '🔄 Actualizar desde OneDrive' "
        "arriba cuando quieras traer los cambios más recientes del equipo."
    )
elif cargado_desde_bundle:
    st.success(
        f"✅ {RUTA_EXCEL_BUNDLED.name} cargado automáticamente · {len(df)} puntos potenciales",
        icon="✅",
    )
    st.caption(
        "Cada vez que se abre la app vuelve a leer este archivo desde cero. "
        "Los cambios de estado que hagas en '📊 Seguimiento' se mantienen "
        "mientras tengas la app abierta, pero para que queden para siempre "
        "hay que actualizarlos también en el Excel del proyecto."
    )
elif metadata.get("ultima_actualizacion"):
    st.caption(
        f"📅 Datos actualizados por última vez el {metadata['ultima_actualizacion']} "
        f"· archivo: {metadata.get('archivo_origen', '—')}"
    )

st.info(
    "El aplicativo identifica posibles coincidencias; la decisión final "
    "continúa dependiendo del criterio del especialista.",
    icon="ℹ️",
)

sin_coords = int(df["latitud"].isna().sum())
if sin_coords:
    st.caption(
        f"⚠️ {sin_coords} punto(s) del archivo no tienen coordenadas registradas — "
        "aparecen en las tablas pero no en los mapas."
    )

tab1, tab2, tab3, tab4, tab5 = st.tabs(
    [
        "📍 Consulta y validación",
        "📊 Seguimiento de oportunidades",
        "🗺️ Mapa de oportunidades",
        "⬆️ Actualizar datos",
        "🏢 Generadores",
    ]
)

# ---------------------------------------------------------------------------
# TAB 1 · Consulta y validación
# ---------------------------------------------------------------------------
with tab1:
    st.subheader("Buscar y validar un punto potencial")
    st.write(
        "Antes de crear el punto en Survey123, revisa aquí si ya existe uno "
        "igual o muy cercano."
    )

    modo_busqueda = st.radio(
        "¿Cómo quieres buscar?",
        ["Por nombre", "Por coordenada"],
        horizontal=True,
        key="modo_busqueda_tab1",
    )

    if modo_busqueda == "Por nombre":
        nombre_busqueda = st.text_input(
            "Nombre del local a buscar", key="busqueda_nombre",
            placeholder="Ej. Toberin 168",
        )
        if st.button("🔍 Buscar", type="primary", key="buscar_por_nombre_btn"):
            resultado_nombre = buscar_por_nombre(df, nombre_busqueda)
            st.session_state["resultado_busqueda_nombre"] = resultado_nombre

        resultado_nombre = st.session_state.get("resultado_busqueda_nombre")
        if resultado_nombre is not None:
            if resultado_nombre.empty:
                st.success("No hay ningún local registrado con un nombre igual o parecido.")
            else:
                st.warning(
                    f"Se encontraron {len(resultado_nombre)} local(es) con nombre "
                    "igual o muy parecido:"
                )
                st.dataframe(
                    resultado_nombre[
                        ["id", "especialista", "ciudad", "local_identificado", "estado", "estado_comite", "similitud_nombre"]
                    ],
                    use_container_width=True,
                    hide_index=True,
                )

    else:  # Por coordenada
        c1, c2 = st.columns(2)
        lat = c1.number_input("Latitud", value=4.650000, format="%.6f", key="lat_busqueda")
        lon = c2.number_input("Longitud", value=-74.080000, format="%.6f", key="lon_busqueda")

        if st.button("🔍 Buscar", type="primary", key="buscar_por_coord_btn"):
            cercanos = detectar_coincidencias(df, lat, lon, "")
            st.session_state["ultima_consulta_coord"] = {"lat": lat, "lon": lon, "cercanos": cercanos}

        consulta = st.session_state.get("ultima_consulta_coord")
        if consulta is not None:
            cercanos = consulta["cercanos"]

            if not cercanos.empty:
                st.warning(
                    f"⚠️ Posible duplicidad — se encontraron {len(cercanos)} punto(s) "
                    f"con ubicación cercana (< {UMBRAL_DUPLICIDAD_M} m).",
                    icon="⚠️",
                )
                for _, row in cercanos.iterrows():
                    with st.container(border=True):
                        cc1, cc2 = st.columns([3, 1])
                        detalle_distancia = (
                            f"{row['distancia_m']:.0f} m de distancia"
                            if row["distancia_m"] != float("inf")
                            else "sin coordenadas para comparar distancia"
                        )
                        cc1.markdown(
                            f"**{row['local_identificado']}** — {detalle_distancia}, "
                            f"registrado por **{row['especialista']}**"
                            + (f" · practicante **{row['practicante']}**" if row.get("practicante") else "")
                        )
                        cc1.caption(
                            f"{row['ciudad']} · Fecha: {row['fecha_registro']}"
                        )
                        cc2.markdown(f"Estado: **{row['estado']}**")
                        cc2.markdown(
                            f"Comité: **{row['estado_comite'] or 'Pendiente'}**"
                        )
            else:
                st.success(
                    "✅ No se encontraron oportunidades cercanas registradas en "
                    "esa ubicación.",
                    icon="✅",
                )

            # Vista real del lugar: mapa de Google + Street View del punto consultado
            st.write("📍 **Vista del lugar consultado:**")
            col_mapa, col_calle = st.columns(2)
            with col_mapa:
                st.caption("Mapa")
                components.iframe(
                    url_mapa_embed(consulta["lat"], consulta["lon"]), height=350
                )
            with col_calle:
                st.caption("Street View (vista a nivel de calle)")
                components.iframe(
                    url_streetview_embed(consulta["lat"], consulta["lon"]), height=350
                )
            st.caption(
                "Si el punto está en una zona sin cobertura de Street View, "
                "Google muestra ahí mismo un aviso de que no hay imagen "
                "disponible."
            )

# ---------------------------------------------------------------------------
# TAB 2 · Seguimiento de oportunidades
# ---------------------------------------------------------------------------
with tab2:
    st.subheader("Seguimiento de oportunidades")
    st.write("Consulta qué ha ocurrido con cada punto después de entrar al proceso.")

    f1, f2, f3, f4 = st.columns(4)
    filtro_ciudad = f1.multiselect("Ciudad", sorted(df["ciudad"].dropna().unique()), default=[])
    filtro_especialista = f2.multiselect(
        "Especialista", sorted(df["especialista"].dropna().unique()), default=[]
    )
    filtro_estado = f3.multiselect("Estado", sorted(df["estado"].dropna().unique()), default=[])
    fechas_validas = df["fecha_registro"].dropna()
    rango_fechas = f4.date_input(
        "Rango de fechas",
        value=(fechas_validas.min(), fechas_validas.max()) if not fechas_validas.empty else None,
    )
    opciones_comite_seg = sorted([v for v in df["estado_comite"].dropna().unique() if str(v).strip()])
    filtro_comite = st.multiselect(
        "Estado de comité", opciones_comite_seg, default=[],
        help="Deja vacío para ver todos, incluyendo los que aún no han pasado por comité.",
    )

    df_filtrado = df.copy()
    if filtro_ciudad:
        df_filtrado = df_filtrado[df_filtrado["ciudad"].isin(filtro_ciudad)]
    if filtro_especialista:
        df_filtrado = df_filtrado[df_filtrado["especialista"].isin(filtro_especialista)]
    if filtro_estado:
        df_filtrado = df_filtrado[df_filtrado["estado"].isin(filtro_estado)]
    if filtro_comite:
        df_filtrado = df_filtrado[df_filtrado["estado_comite"].isin(filtro_comite)]
    if isinstance(rango_fechas, tuple) and len(rango_fechas) == 2:
        ini, fin = rango_fechas
        df_filtrado = df_filtrado[
            df_filtrado["fecha_registro"].isna()
            | ((df_filtrado["fecha_registro"] >= ini) & (df_filtrado["fecha_registro"] <= fin))
        ]

    metricas = st.columns(len(ESTADOS) + 1)
    metricas[0].metric("Total filtrado", len(df_filtrado))
    for col, estado in zip(metricas[1:], ESTADOS):
        col.metric(estado, int((df_filtrado["estado"] == estado).sum()))

    st.write("Actualiza el estado o las notas de una oportunidad:")
    columnas_editor = [
        "id", "especialista", "practicante", "ciudad", "upz", "local_identificado",
        "fecha_registro", "estado", "estado_comite", "tiendas_evaluadas", "notas",
    ]
    edited = st.data_editor(
        df_filtrado[columnas_editor],
        column_config={
            "estado": st.column_config.SelectboxColumn("estado", options=ESTADOS),
        },
        disabled=[c for c in columnas_editor if c not in ("estado", "notas")],
        use_container_width=True,
        hide_index=True,
        key="editor_seguimiento",
    )

    if st.button("💾 Guardar cambios de seguimiento", type="primary"):
        df_actualizado = df.set_index("id")
        edited_idx = edited.set_index("id")
        df_actualizado.update(edited_idx)
        st.session_state.puntos = df_actualizado.reset_index()
        guardar_puntos(st.session_state.puntos)
        st.success("Cambios guardados.")
        st.rerun()

    with st.expander("Ver detalle completo (incluye microsaturación)"):
        st.dataframe(df_filtrado, use_container_width=True, hide_index=True)

    with st.expander("🗑️ Eliminar un punto (por ejemplo, uno de prueba)"):
        st.write(
            "Úsalo para borrar puntos que no deberían estar, como pruebas o "
            "duplicados metidos por error. Esta acción no se puede deshacer."
        )
        if df.empty:
            st.caption("No hay puntos registrados todavía.")
        else:
            opciones_borrar = {
                f"#{row.id} · {row.local_identificado} · {row.especialista}": row.id
                for row in df.itertuples()
            }
            etiqueta_elegida = st.selectbox(
                "Elige el punto a eliminar", list(opciones_borrar.keys())
            )
            id_a_borrar = opciones_borrar[etiqueta_elegida]
            confirmar = st.checkbox(f"Sí, quiero eliminar el punto #{id_a_borrar} definitivamente")
            if st.button("🗑️ Eliminar este punto", disabled=not confirmar):
                st.session_state.puntos = eliminar_punto(df, id_a_borrar)
                guardar_puntos(st.session_state.puntos)
                st.success(f"Punto #{id_a_borrar} eliminado.")
                st.rerun()

# ---------------------------------------------------------------------------
# TAB 3 · Mapa de oportunidades
# ---------------------------------------------------------------------------
with tab3:
    st.subheader("Mapa general de oportunidades")
    st.write(
        "Todos los puntos potenciales enviados por especialistas. Pasa el "
        "mouse (o toca) un punto para ver quién lo trabajó, cuándo, y su "
        "estado ante comité."
    )

    g1, g2, g3, g4 = st.columns(4)
    filtro_ciudad_mapa = g1.multiselect(
        "Ciudad", sorted(df["ciudad"].dropna().unique()), default=[], key="ciudad_mapa"
    )
    filtro_estado_mapa = g2.multiselect(
        "Estado", sorted(df["estado"].dropna().unique()),
        default=sorted(df["estado"].dropna().unique()), key="estado_mapa",
    )
    filtro_especialista_mapa = g3.multiselect(
        "Especialista", sorted(df["especialista"].dropna().unique()), default=[], key="esp_mapa"
    )
    opciones_comite = sorted([v for v in df["estado_comite"].dropna().unique() if str(v).strip()])
    filtro_comite_mapa = g4.multiselect(
        "Estado de comité", opciones_comite, default=[], key="comite_mapa"
    )

    modo_color = st.radio(
        "Color de los puntos",
        ["🟣 Morado (por defecto)", "🎨 Por especialista"],
        horizontal=True,
        key="modo_color_mapa",
    )

    df_mapa = df[df["estado"].isin(filtro_estado_mapa)]
    if filtro_ciudad_mapa:
        df_mapa = df_mapa[df_mapa["ciudad"].isin(filtro_ciudad_mapa)]
    if filtro_especialista_mapa:
        df_mapa = df_mapa[df_mapa["especialista"].isin(filtro_especialista_mapa)]
    if filtro_comite_mapa:
        df_mapa = df_mapa[df_mapa["estado_comite"].isin(filtro_comite_mapa)]

    df_mapa = df_mapa.copy()
    if modo_color.startswith("🎨"):
        df_mapa["color"] = df_mapa["especialista"].apply(color_por_especialista)
    else:
        df_mapa["color"] = [COLOR_MORADO] * len(df_mapa)

    df_mapa["estado_comite_mostrar"] = df_mapa["estado_comite"].replace("", "Pendiente de comité")

    df_mapa_geo = df_mapa.dropna(subset=["latitud", "longitud"])

    if df_mapa_geo.empty:
        st.info("No hay puntos con coordenadas que coincidan con los filtros seleccionados.")
    else:
        capa = pdk.Layer(
            "ScatterplotLayer",
            data=df_mapa_geo,
            get_position="[longitud, latitud]",
            get_fill_color="color",
            get_radius=40,
            pickable=True,
        )
        vista = pdk.ViewState(
            latitude=df_mapa_geo["latitud"].mean(),
            longitude=df_mapa_geo["longitud"].mean(),
            zoom=10,
        )
        st.pydeck_chart(
            pdk.Deck(
                layers=[capa],
                initial_view_state=vista,
                tooltip={
                    "text": (
                        "{local_identificado}\nEspecialista: {especialista}\n"
                        "Practicante: {practicante}\nFecha: {fecha_registro}\n"
                        "Estado: {estado}\nComité: {estado_comite_mostrar}"
                    )
                },
            )
        )
        if modo_color.startswith("🎨"):
            especialistas_en_mapa = sorted(df_mapa_geo["especialista"].dropna().unique())
            st.caption(
                "Cada especialista tiene un color fijo — pasa el mouse sobre "
                "un punto para confirmar de quién es."
            )
        else:
            st.caption("🟣 Todos los puntos en morado (cambia el color arriba si quieres verlos por especialista)")
        faltantes_filtro = len(df_mapa) - len(df_mapa_geo)
        if faltantes_filtro:
            st.caption(f"({faltantes_filtro} punto(s) de este filtro no tienen coordenadas y no se muestran en el mapa)")

    st.dataframe(
        df_mapa.drop(columns=["color", "estado_comite_mostrar"]), use_container_width=True, hide_index=True
    )

# ---------------------------------------------------------------------------
# TAB 4 · Actualizar datos
# ---------------------------------------------------------------------------
with tab4:
    st.subheader("Actualizar datos desde el Excel del área")

    st.markdown(
        f"**Forma principal (recomendada):** reemplaza el archivo "
        f"`{RUTA_EXCEL_BUNDLED}` directamente en el repositorio de GitHub "
        "(mismo nombre, arrastrando el archivo nuevo como se explica en el "
        "README) y súbelo con un commit. La próxima vez que se abra la app, "
        "se carga sola y muestra el aviso verde de arriba con el conteo "
        "actualizado — no hace falta tocar nada más."
    )
    st.caption(
        "Las dos opciones de abajo son alternativas para casos puntuales: "
        "probar un archivo distinto sin tocar GitHub, o conectar un link "
        "de OneDrive que sea público."
    )

    modo = st.radio(
        "¿Cómo quieres actualizar los datos ahora?",
        ["📎 Subiendo el archivo yo misma (manual)", "🔗 Conectada en vivo a un link de OneDrive"],
        index=0 if metadata.get("modo", "archivo") != "url" else 1,
        horizontal=False,
    )

    st.divider()

    if modo.startswith("📎"):
        st.write(
            "Sube aquí el archivo más reciente (el mismo formato del Excel/CSV "
            "de *Revisión Microsaturaciones*, descargado directamente de "
            "OneDrive) para refrescar la información de la app."
        )
        st.warning(
            "⚠️ Subir un archivo **reemplaza por completo** la base de datos "
            "actual de la app por la del archivo nuevo (no se combinan). "
            "Asegúrate de subir la versión más actualizada y completa.",
            icon="⚠️",
        )

        archivo = st.file_uploader("Archivo Excel (.xlsx) o CSV (.csv)", type=["xlsx", "csv"])

        if archivo is not None:
            try:
                nuevo_df = leer_archivo_fuente(archivo, archivo.name)
            except Exception as e:
                st.error(f"No se pudo leer el archivo: {e}")
            else:
                st.success(f"Archivo leído correctamente: {len(nuevo_df)} puntos encontrados.")
                c1, c2, c3 = st.columns(3)
                c1.metric("Puntos totales", len(nuevo_df))
                c2.metric("Sin coordenadas", int(nuevo_df["latitud"].isna().sum()))
                c3.metric("Ciudades distintas", nuevo_df["ciudad"].nunique())
                st.write("Vista previa:")
                st.dataframe(nuevo_df.head(15), use_container_width=True, hide_index=True)

                if st.button("✅ Reemplazar datos de la app con este archivo", type="primary"):
                    st.session_state.puntos = nuevo_df
                    guardar_puntos(nuevo_df)
                    guardar_metadata(modo="archivo", archivo_origen=archivo.name, url_fuente="")
                    st.success("¡Datos actualizados! Recargando la app...")
                    st.rerun()

    else:
        st.write(
            "Pega aquí el link para compartir del archivo en OneDrive/SharePoint "
            "(el mismo que usas para compartirlo por correo o Teams). Una vez "
            "conectada, la app **no se refresca sola** — verás un botón "
            "'🔄 Actualizar ahora' arriba en la parte superior para traer los "
            "datos más recientes cuando tú lo necesites."
        )
        st.warning(
            "⚠️ Esto **solo funciona si el link está compartido como "
            "'Cualquier persona con el vínculo'** (acceso público, sin iniciar "
            "sesión). Si está restringido a 'Personas de OXXO', la descarga "
            "automática fallará — eso lo define el permiso en OneDrive, no "
            "algo que se pueda arreglar desde el código. Revisa el botón "
            "'Compartir' del archivo para confirmar qué permiso tiene.",
            icon="⚠️",
        )

        url_actual = metadata.get("url_fuente", "")
        url_input = st.text_input(
            "Link para compartir de OneDrive/SharePoint",
            value=url_actual,
            placeholder="https://...sharepoint.com/:x:/g/personal/.../....?e=...",
        )

        if st.button("🔄 Probar conexión"):
            if not url_input.strip():
                st.error("Pega primero el link del archivo.")
            else:
                with st.spinner("Probando la descarga..."):
                    try:
                        _leer_desde_url_cacheado.clear()
                        nuevo_df = _leer_desde_url_cacheado(url_input.strip())
                    except Exception as e:
                        st.error(f"No se pudo conectar: {e}")
                    else:
                        st.session_state["preview_url_df"] = nuevo_df
                        st.session_state["preview_url_valor"] = url_input.strip()
                        st.success(
                            f"¡Conexión exitosa! Se descargaron {len(nuevo_df)} puntos."
                        )

        preview_df = st.session_state.get("preview_url_df")
        if preview_df is not None:
            c1, c2, c3 = st.columns(3)
            c1.metric("Puntos totales", len(preview_df))
            c2.metric("Sin coordenadas", int(preview_df["latitud"].isna().sum()))
            c3.metric("Ciudades distintas", preview_df["ciudad"].nunique())
            st.write("Vista previa:")
            st.dataframe(preview_df.head(15), use_container_width=True, hide_index=True)

            if st.button("✅ Activar esta conexión en vivo", type="primary"):
                st.session_state.puntos = preview_df
                guardar_puntos(preview_df)
                guardar_metadata(
                    modo="url",
                    url_fuente=st.session_state["preview_url_valor"],
                    archivo_origen="Link de OneDrive (en vivo)",
                )
                del st.session_state["preview_url_df"]
                st.success(
                    "¡Conectado! Usa el botón '🔄 Actualizar ahora' (arriba, junto "
                    "al título) cuando quieras traer los datos más recientes."
                )
                st.rerun()

# ---------------------------------------------------------------------------
# TAB 5 · Generadores
# ---------------------------------------------------------------------------
with tab5:
    st.subheader("Validación de generadores")
    st.write(
        "Cuando el radio de recolección (300 m) de dos puntos potenciales "
        "distintos se superpone, el mismo generador físico (por ejemplo, "
        "las oficinas de un banco) puede quedar registrado dos veces en "
        "Survey123 — una por cada punto — sin que nadie lo note. Consulta "
        "aquí antes de registrar uno nuevo en campo."
    )

    col_espacio_gen, col_refrescar_gen = st.columns([5, 1.6])
    with col_refrescar_gen:
        if st.button("🔄 Actualizar generadores", use_container_width=True, type="primary"):
            _leer_generadores_cacheado.clear()
            try:
                nuevo_df_gen = _leer_generadores_cacheado()
            except Exception as e:
                st.error(f"No se pudo actualizar: {e}")
            else:
                st.session_state.generadores = nuevo_df_gen
                guardar_generadores(nuevo_df_gen)
                st.rerun()

    if error_generadores:
        st.error(
            f"⚠️ No se pudo conectar con la capa de generadores en vivo "
            f"({error_generadores}) — se está mostrando la última copia "
            "guardada.",
            icon="⚠️",
        )

    if df_generadores.empty:
        st.info(
            "Todavía no hay generadores cargados. Dale clic a "
            "'🔄 Actualizar generadores' arriba para traerlos."
        )
    else:
        st.caption(f"📡 Conectado en vivo a la capa de Survey123 · {len(df_generadores)} registros cargados")

        st.markdown("#### Consultar antes de registrar un generador nuevo")
        with st.form("form_consulta_generador"):
            cg1, cg2, cg3 = st.columns(3)
            nombre_gen = cg1.text_input("Nombre del generador", placeholder="Ej. Bancolombia")
            lat_gen = cg2.number_input("Latitud", value=4.650000, format="%.6f", key="lat_gen")
            lon_gen = cg3.number_input("Longitud", value=-74.080000, format="%.6f", key="lon_gen")
            consultar_gen = st.form_submit_button(
                "🔍 Consultar generador", use_container_width=True, type="primary"
            )

        if consultar_gen:
            if not nombre_gen.strip():
                st.error("Escribe el nombre del generador para poder consultar.")
            else:
                coincidencias_gen = detectar_generadores_coincidentes(
                    df_generadores, nombre_gen, lat_gen, lon_gen
                )
                if coincidencias_gen.empty:
                    st.success(
                        "✅ No se encontró ningún generador igual o parecido "
                        f"a menos de {UMBRAL_DUPLICIDAD_GENERADOR_M} m. Parece nuevo, "
                        "puedes registrarlo en Survey123.",
                        icon="✅",
                    )
                else:
                    puntos_ya_vinculados = sorted(
                        set(coincidencias_gen["nombre_punto_potencial"]) - {""}
                    )
                    st.warning(
                        f"⚠️ Ya existe un generador igual o muy parecido, vinculado a: "
                        f"**{', '.join(puntos_ya_vinculados) if puntos_ya_vinculados else 'otro punto'}**. "
                        "Considera vincularlo al punto actual en Survey123 en vez de "
                        "crear uno nuevo.",
                        icon="⚠️",
                    )
                    st.dataframe(
                        coincidencias_gen[
                            [
                                "nombre_generador", "nombre_punto_potencial", "tipo_generador",
                                "distancia_m", "similitud_nombre", "localizador",
                            ]
                        ],
                        use_container_width=True,
                        hide_index=True,
                    )

        st.divider()
        st.markdown("#### Generadores únicos registrados hasta hoy")
        st.caption(
            "Cada fila es un generador físico único (ya agrupado); la columna "
            "'puntos_asociados' muestra a cuántos puntos potenciales distintos "
            "quedó vinculado — más de uno ahí es justamente lo que antes pasaba "
            "desapercibido."
        )

        tipos_generador = sorted(
            [t for t in df_generadores["tipo_generador"].dropna().unique() if str(t).strip()]
        )
        filtro_tipo_gen = st.multiselect("Tipo de generador", tipos_generador, default=[])

        generadores_agrupados = agrupar_generadores(df_generadores)
        if filtro_tipo_gen:
            generadores_agrupados = generadores_agrupados[
                generadores_agrupados["tipo_generador"].isin(filtro_tipo_gen)
            ]

        c1g, c2g = st.columns(2)
        c1g.metric("Generadores únicos", len(generadores_agrupados))
        c2g.metric(
            "Vinculados a más de un punto",
            int((generadores_agrupados["cantidad_registros"] > 1).sum()),
        )

        st.dataframe(
            generadores_agrupados[
                ["nombre_generador", "tipo_generador", "cantidad_registros", "puntos_asociados"]
            ],
            use_container_width=True,
            hide_index=True,
        )

st.divider()
st.caption(
    "Conectado a los datos reales del área (actualizables desde la pestaña "
    "'Actualizar datos'). La herramienta complementa el proceso actual; "
    "no reemplaza el análisis ni el criterio humano."
)
