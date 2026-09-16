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
    UMBRAL_DUPLICIDAD_GENERADOR_M,
    UMBRAL_DUPLICIDAD_M,
    agrupar_generadores,
    agrupar_puntos_por_radio,
    buscar_por_nombre,
    cargar_generadores_cache,
    cargar_puntos,
    detectar_coincidencias,
    detectar_generadores_coincidentes,
    guardar_generadores,
    guardar_puntos,
    leer_archivo_fuente,
    leer_desde_url,
    leer_generadores_desde_arcgis,
    buscar_coordenada_por_direccion,
    parsear_coordenada_pegada,
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


# ---------------------------------------------------------------------------
# Mapa general combinado (Especialistas / Operación / Generadores)
# ---------------------------------------------------------------------------
# Colores por capa — los que pediste: morado para especialistas, azul claro
# para operación. Generadores y el punto resaltado de una búsqueda usan
# colores distintos para no confundirse con los anteriores.
COLOR_OPERACION = [93, 173, 226]      # azul claro
COLOR_GENERADOR = [230, 126, 34]      # naranja
COLOR_RESALTADO = [225, 30, 30]       # rojo, para el punto que se acaba de buscar

# Vista por defecto del mapa: siempre abre centrado en Bogotá.
BOGOTA_LAT = 4.6097
BOGOTA_LON = -74.0817
ZOOM_BOGOTA_DEFAULT = 10

# Los puntos se dibujan con radio fijo EN PIXELES (radius_units="pixels"),
# no en metros. Con radio en metros, un punto de 18 m se ve del tamaño de
# una manzana entera al acercar mucho el zoom (una "mancha" gigante que se
# encima con las demás); en píxeles, el punto se ve siempre del mismo
# tamaño razonable sin importar cuánto zoom se le haga, como un pin normal
# de Google Maps.
RADIO_PUNTO_MAPA_PX = 7
RADIO_RESALTADO_PX = 11


def _columna_tooltip_especialistas(d: pd.DataFrame) -> pd.Series:
    comite = d["estado_comite"].replace("", "Pendiente de comité")
    return (
        "📍 " + d["local_identificado"].astype(str)
        + "\nEspecialista: " + d["especialista"].astype(str)
        + "\nPracticante: " + d["practicante"].astype(str)
        + "\nComité: " + comite.astype(str)
    )


def _columna_tooltip_generadores(d: pd.DataFrame) -> pd.Series:
    texto = (
        "🏢 " + d["nombre_generador"].astype(str)
        + "\nTipo: " + d["tipo_generador"].astype(str)
        + "\nRegistros agrupados: " + d["cantidad_registros"].astype(str)
        + "\nPuntos asociados: " + d["puntos_asociados"].astype(str)
    )
    if "especialistas_asociados" in d.columns:
        texto = texto + "\nEspecialista(s): " + d["especialistas_asociados"].replace("", "—").astype(str)
    if "upz_asociadas" in d.columns:
        texto = texto + "\nUPZ: " + d["upz_asociadas"].replace("", "—").astype(str)
    return texto


def renderizar_mapa_general(
    capas_activas,
    df_especialistas=None,
    df_operacion=None,
    df_generadores_agrupado=None,
    punto_resaltado=None,
):
    """
    Dibuja un solo mapa combinando las capas que estén activas:
    "Especialistas (Excel)", "Operación (Survey)", "Generadores".
    Si punto_resaltado=(lat, lon, etiqueta), agrega un marcador extra rojo
    y centra el mapa ahí; si no, el mapa abre centrado en Bogotá.
    """
    capas = []

    if "Especialistas (Excel)" in capas_activas:
        if df_especialistas is not None and not df_especialistas.empty:
            d = df_especialistas.dropna(subset=["latitud", "longitud"]).copy()
            if not d.empty:
                d["color"] = [COLOR_MORADO] * len(d)
                d["tooltip_text"] = _columna_tooltip_especialistas(d)
                capas.append(
                    pdk.Layer(
                        "ScatterplotLayer", data=d, get_position="[longitud, latitud]",
                        get_fill_color="color", get_radius=RADIO_PUNTO_MAPA_PX, radius_units="pixels", pickable=True,
                    )
                )

    if "Operación (Survey)" in capas_activas:
        if df_operacion is not None and not df_operacion.empty:
            d = df_operacion.dropna(subset=["latitud", "longitud"]).copy()
            if not d.empty:
                d["color"] = [COLOR_OPERACION] * len(d)
                nombre_col = "local_identificado" if "local_identificado" in d.columns else (
                    "nombre" if "nombre" in d.columns else None
                )
                d["tooltip_text"] = (
                    "📍 " + d[nombre_col].astype(str) if nombre_col else "📍 Punto de operación"
                )
                capas.append(
                    pdk.Layer(
                        "ScatterplotLayer", data=d, get_position="[longitud, latitud]",
                        get_fill_color="color", get_radius=RADIO_PUNTO_MAPA_PX, radius_units="pixels", pickable=True,
                    )
                )
        else:
            st.caption(
                "🔧 Capa 'Operación (Survey)' todavía no está conectada — "
                "falta el link de esa fuente."
            )

    if "Generadores" in capas_activas:
        if df_generadores_agrupado is not None and not df_generadores_agrupado.empty:
            d = df_generadores_agrupado.dropna(subset=["latitud", "longitud"]).copy()
            if not d.empty:
                d["color"] = [COLOR_GENERADOR] * len(d)
                d["tooltip_text"] = _columna_tooltip_generadores(d)
                capas.append(
                    pdk.Layer(
                        "ScatterplotLayer", data=d, get_position="[longitud, latitud]",
                        get_fill_color="color", get_radius=RADIO_PUNTO_MAPA_PX, radius_units="pixels", pickable=True,
                    )
                )

    if punto_resaltado is not None:
        lat_h, lon_h, etiqueta_h = punto_resaltado
        d = pd.DataFrame(
            [{"latitud": lat_h, "longitud": lon_h, "tooltip_text": f"🔎 {etiqueta_h}"}]
        )
        d["color"] = [COLOR_RESALTADO] * len(d)
        capas.append(
            pdk.Layer(
                "ScatterplotLayer", data=d, get_position="[longitud, latitud]",
                get_fill_color="color", get_radius=RADIO_RESALTADO_PX, radius_units="pixels", pickable=True,
            )
        )
        vista = pdk.ViewState(latitude=lat_h, longitude=lon_h, zoom=15)
    else:
        vista = pdk.ViewState(latitude=BOGOTA_LAT, longitude=BOGOTA_LON, zoom=ZOOM_BOGOTA_DEFAULT)

    if not capas:
        st.info("No hay ninguna capa para mostrar con la selección actual.")
        return

    st.pydeck_chart(
        pdk.Deck(
            layers=capas,
            initial_view_state=vista,
            tooltip={"text": "{tooltip_text}"},
            map_style="light",
        )
    )


def mostrar_leyenda_colores(incluir_generadores=True, incluir_operacion=True, incluir_resaltado=False):
    """Cuadro de texto fijo explicando qué significa cada color de punto en los mapas."""
    partes = ["🟣 **Morado** = Especialistas (Excel)"]
    if incluir_operacion:
        partes.append("🔵 **Azul claro** = Operación (Survey)")
    if incluir_generadores:
        partes.append("🟠 **Naranja** = Generadores")
    if incluir_resaltado:
        partes.append("🔴 **Rojo** = el punto que acabas de buscar")
    st.caption(" &nbsp;·&nbsp; ".join(partes))


COLOR_GENERADOR_UNICO = [230, 126, 34]     # naranja
COLOR_GENERADOR_REPETIDO = [25, 85, 220]   # azul — antes era rojo, se veía casi
                                            # igual al naranja al encimarse los puntos


def renderizar_mapa_generadores(df_generadores_agrupado, mostrar, key="mapa_generadores"):
    """
    Mapa de generadores, con la opción de mostrar "Todos" o solo los
    "Repetidos" (cantidad_registros > 1 — la señal de duplicidad).

    Si el clic directo sobre un punto es compatible con la versión de
    Streamlit desplegada, al hacer clic en un generador se muestra su
    Street View debajo del mapa. Si no es compatible (versión más
    antigua), el mapa se sigue mostrando normal, solo sin esa función —
    nunca se cae la app por esto.
    """
    d = df_generadores_agrupado.dropna(subset=["latitud", "longitud"]).copy().reset_index(drop=True)
    if mostrar == "Solo repetidos":
        d = d[d["cantidad_registros"] > 1].reset_index(drop=True)
    if d.empty:
        st.info("No hay generadores para mostrar con esa selección.")
        return

    d["color"] = d["cantidad_registros"].apply(
        lambda n: COLOR_GENERADOR_REPETIDO if n > 1 else COLOR_GENERADOR_UNICO
    )
    d["tooltip_text"] = _columna_tooltip_generadores(d)
    capa = pdk.Layer(
        "ScatterplotLayer", data=d, get_position="[longitud, latitud]",
        get_fill_color="color", get_radius=RADIO_PUNTO_MAPA_PX, radius_units="pixels",
        pickable=True, auto_highlight=True,
    )
    vista = pdk.ViewState(latitude=BOGOTA_LAT, longitude=BOGOTA_LON, zoom=ZOOM_BOGOTA_DEFAULT)
    deck = pdk.Deck(layers=[capa], initial_view_state=vista, tooltip={"text": "{tooltip_text}"}, map_style="light")

    seleccionado = None
    try:
        evento = st.pydeck_chart(
            deck, on_select="rerun", selection_mode="single-object", key=key,
        )
        objetos = evento.selection.get("objects", {}) if evento is not None else {}
        filas_click = objetos.get(capa.id, []) if objetos else []
        if filas_click:
            seleccionado = filas_click[0]
    except TypeError:
        # Streamlit desplegado no soporta on_select en pydeck_chart todavía
        # (versión más vieja) — se muestra el mapa igual, sin clic.
        st.pydeck_chart(deck)

    st.caption(
        "🟠 **Naranja** = generador único &nbsp;·&nbsp; 🔵 **Azul** = generador "
        "repetido (radio de 300 m). Dale clic a un punto para ver su Street View."
    )

    if seleccionado is not None:
        lat_sel, lon_sel = seleccionado.get("latitud"), seleccionado.get("longitud")
        if lat_sel is not None and lon_sel is not None:
            st.write(f"📍 **Street View de '{seleccionado.get('nombre_generador', '')}':**")
            components.iframe(url_streetview_embed(lat_sel, lon_sel), height=350)


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

# Vista agrupada de generadores (un renglón por generador único). Se
# recalcula en cada carga de la página (es una operación rápida de pandas)
# en vez de guardarse en session_state — así nunca queda "pegada" una
# versión vieja o vacía si la primera carga de generadores falló antes de
# que alguien le diera clic a "Actualizar".
generadores_agrupados = agrupar_generadores(df_generadores, df_puntos=df)

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


def _refrescar_puntos_desde_url() -> bool:
    """
    Vuelve a descargar el Excel de puente (desde el Secret privado, o desde
    el link manual guardado) y reemplaza los puntos cargados. Se usa tanto
    en el botón de arriba del todo como en el botón dentro del Módulo 1, así
    que cuando lleguen puntos nuevos al Excel de puente, se pueden traer sin
    importar en qué parte de la app esté Alisson.
    """
    _leer_desde_url_cacheado.clear()
    _url_para_refrescar = url_secreta or metadata.get("url_fuente", "")
    try:
        nuevo_df = _leer_desde_url_cacheado(_url_para_refrescar)
    except Exception as e:
        st.error(f"No se pudo actualizar: {e}")
        return False
    st.session_state.puntos = nuevo_df
    guardar_puntos(nuevo_df)
    if not url_secreta:
        # Si la fuente viene del secret, no hace falta guardar el link en
        # metadata.json (ya vive de forma privada en Streamlit); solo se
        # guarda cuando viene del flujo manual de la pestaña "Actualizar
        # datos".
        guardar_metadata(modo="url", url_fuente=_url_para_refrescar, archivo_origen="Link de OneDrive (en vivo)")
    else:
        guardar_metadata(archivo_origen="Puente del equipo (OneDrive, en vivo)")
    return True


if _hay_fuente_url:
    col_espacio, col_refrescar = st.columns([5, 1.3])
    with col_refrescar:
        if st.button("🔄 Actualizar Excel de puente", use_container_width=True, type="primary", key="refrescar_puente_top"):
            if _refrescar_puntos_desde_url():
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
        "Los cambios de estado que hagas en 'Estado de comité' se mantienen "
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

tab1, tab2 = st.tabs(
    [
        "🔁 Duplicidad de puntos potenciales",
        "🏢 Generadores",
    ]
)

# ---------------------------------------------------------------------------
# MÓDULO 1 · Duplicidad de puntos potenciales
# ---------------------------------------------------------------------------
with tab1:
    st.subheader("Duplicidad de puntos potenciales")
    st.write(
        "Revisa qué puntos potenciales — de especialistas o de operación — "
        "están repetidos: misma coordenada, o tan cerca (misma cuadra, "
        "misma esquina) que probablemente son el mismo lugar."
    )
    mostrar_leyenda_colores(incluir_resaltado=True)

    if _hay_fuente_url:
        col_espacio_tab1, col_refrescar_tab1 = st.columns([5, 1.6])
        with col_refrescar_tab1:
            if st.button(
                "🔄 Actualizar Excel de puente", use_container_width=True,
                type="primary", key="refrescar_puente_tab1",
            ):
                if _refrescar_puntos_desde_url():
                    st.rerun()
        st.caption(
            "Dale clic aquí si acaban de agregar puntos nuevos al Excel de "
            "puente y quieres traerlos sin salir de esta pestaña."
        )

    st.markdown("#### 🔎 Revisar un punto específico")
    st.write(
        "Busca uno en particular para ver su ubicación exacta y si tiene "
        "algo cerca — así detectas la duplicidad antes de registrarlo."
    )

    modo_busqueda = st.radio(
        "¿Cómo quieres buscar?",
        ["Por nombre", "Por dirección", "Por coordenada"],
        horizontal=True,
        key="modo_busqueda_tab1",
        label_visibility="collapsed",
    )

    consulta_punto = None  # se llena si el modo es "dirección" o "coordenada"

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
                        ["id", "especialista", "ciudad", "local_identificado", "estado_comite", "similitud_nombre"]
                    ],
                    use_container_width=True,
                    hide_index=True,
                )

    elif modo_busqueda == "Por dirección":
        direccion_busqueda = st.text_input(
            "Escribe la dirección", key="direccion_busqueda_tab1",
            placeholder="Ej. Carrera 15 # 93-60, Bogotá",
        )
        if st.button("🔍 Buscar", type="primary", key="buscar_direccion_btn"):
            with st.spinner("Buscando dirección..."):
                resultado = buscar_coordenada_por_direccion(direccion_busqueda)
            if resultado is None:
                st.session_state["error_busqueda_punto"] = True
                st.session_state.pop("resultado_busqueda_punto", None)
            else:
                lat_e, lon_e, etiqueta_e = resultado
                st.session_state["resultado_busqueda_punto"] = {
                    "lat": lat_e, "lon": lon_e, "etiqueta": etiqueta_e,
                }
                st.session_state["error_busqueda_punto"] = False

        if st.session_state.get("error_busqueda_punto"):
            st.error("No se encontró esa dirección. Intenta agregar la ciudad.")
        consulta_punto = st.session_state.get("resultado_busqueda_punto")

    else:  # Por coordenada
        coord_pegada = st.text_input(
            "Pega la coordenada completa (latitud, longitud)",
            key="coord_pegada_tab1",
            placeholder="Ej. 4.697539545568918, -74.09220071349365",
        )
        st.caption(
            "Pégala completa, con todos los decimales que traiga (de Google "
            "Maps o de ArcGIS) — así el punto no se desplaza."
        )
        if st.button("🔍 Buscar", type="primary", key="buscar_coord_btn"):
            coord = parsear_coordenada_pegada(coord_pegada)
            if coord is None:
                st.session_state["error_busqueda_punto"] = True
                st.session_state.pop("resultado_busqueda_punto", None)
            else:
                lat_e, lon_e = coord
                st.session_state["resultado_busqueda_punto"] = {
                    "lat": lat_e, "lon": lon_e,
                    "etiqueta": f"Coordenada {lat_e}, {lon_e}",
                }
                st.session_state["error_busqueda_punto"] = False

        if st.session_state.get("error_busqueda_punto"):
            st.error(
                "Eso no tiene forma de coordenada. Debe verse así: "
                "'4.697539545568918, -74.09220071349365'."
            )
        consulta_punto = st.session_state.get("resultado_busqueda_punto")

    if consulta_punto is not None:
        lat_c, lon_c = consulta_punto["lat"], consulta_punto["lon"]
        cercanos = detectar_coincidencias(df, lat_c, lon_c, "")

        st.divider()

        # 1) Primero Google Maps + Street View del punto consultado.
        st.write("📍 **Vista de calle del lugar consultado:**")
        col_mapa, col_calle = st.columns(2)
        with col_mapa:
            st.caption("Mapa")
            components.iframe(url_mapa_embed(lat_c, lon_c), height=350)
        with col_calle:
            st.caption("Street View (vista a nivel de calle)")
            components.iframe(url_streetview_embed(lat_c, lon_c), height=350)
        st.caption(
            "Si el punto está en una zona sin cobertura de Street View, "
            "Google muestra ahí mismo un aviso de que no hay imagen "
            "disponible."
        )

        # 2) Después el mapa general, centrado y resaltado en el punto buscado.
        st.write("**Ese punto en el mapa general (queda en rojo):**")
        capas_tab1 = st.multiselect(
            "Capas a mostrar",
            ["Especialistas (Excel)", "Operación (Survey)", "Generadores"],
            default=["Especialistas (Excel)", "Generadores"],
            key="capas_mapa_tab1",
        )
        renderizar_mapa_general(
            capas_tab1,
            df_especialistas=df,
            df_operacion=None,
            df_generadores_agrupado=generadores_agrupados,
            punto_resaltado=(lat_c, lon_c, consulta_punto["etiqueta"]),
        )

        # 3) Y por último, si hay algo cerca, por qué se marca como posible duplicado.
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
                    cc1.caption(f"{row['ciudad']} · Fecha: {row['fecha_registro']}")
                    cc1.markdown(f"🔍 **Por qué se marca como posible duplicado:** {row['coincide_por']}")
                    cc2.markdown(f"Comité: **{row['estado_comite'] or 'Pendiente'}**")
        else:
            st.success(
                "✅ No se encontraron oportunidades cercanas registradas en "
                "esa ubicación.",
                icon="✅",
            )

    st.divider()
    st.markdown("#### 🗺️ Mapa general")
    capas_generales = st.multiselect(
        "Capas a mostrar",
        ["Especialistas (Excel)", "Operación (Survey)", "Generadores"],
        default=["Especialistas (Excel)", "Generadores"],
        key="capas_mapa_general",
    )
    renderizar_mapa_general(
        capas_generales,
        df_especialistas=df,
        df_operacion=None,
        df_generadores_agrupado=generadores_agrupados,
        punto_resaltado=None,
    )

    st.markdown("#### 📋 Posibles duplicados (radio de 300 m)")
    st.caption(
        "Agrupa puntos con nombre igual o parecido a menos de 300 m entre "
        "sí — el mismo radio con el que se recogen generadores. Para que "
        "queden en un mismo grupo aquí, el nombre Y la ubicación tienen que "
        "coincidir (por eso el motivo siempre dice 'Ubicación y nombre')."
    )
    duplicados_300 = agrupar_puntos_por_radio(df, umbral_m=300)
    if duplicados_300.empty:
        st.success("No se encontraron grupos de puntos duplicados dentro de 300 m.")
    else:
        duplicados_300 = duplicados_300.assign(por_que="Ubicación y nombre")
        st.warning(f"Se encontraron {len(duplicados_300)} grupo(s) con más de un punto:")
        st.dataframe(
            duplicados_300.drop(columns=["latitud", "longitud"]).rename(
                columns={"por_que": "Por qué se duplica"}
            ),
            use_container_width=True,
            hide_index=True,
        )

    st.divider()
    st.markdown("#### 📊 Estado de comité")
    st.caption(
        "Qué puntos fueron aprobados en comité, aprobados con tareas, o "
        "descartados — columna 'Estatus en bitácora' del Excel. Solo se "
        "muestran aquí los puntos que ya tienen ese estatus diligenciado."
    )

    fc1, fc2, fc3 = st.columns(3)
    filtro_ciudad = fc1.multiselect("Ciudad", sorted(df["ciudad"].dropna().unique()), default=[])
    filtro_especialista = fc2.multiselect(
        "Especialista", sorted(df["especialista"].dropna().unique()), default=[]
    )
    opciones_comite_seg = sorted([v for v in df["estado_comite"].dropna().unique() if str(v).strip()])
    filtro_comite = fc3.multiselect(
        "Estado de comité", opciones_comite_seg, default=[],
        help="Deja vacío para ver todos los que ya tienen estatus de comité.",
    )

    # Solo se muestran los puntos que YA tienen algo en "Estatus en
    # bitácora" — los que aún no han pasado por comité no salen en esta
    # tabla (aunque sí siguen apareciendo en el resto de la app).
    df_filtrado = df[df["estado_comite"].astype(str).str.strip() != ""].copy()
    if filtro_ciudad:
        df_filtrado = df_filtrado[df_filtrado["ciudad"].isin(filtro_ciudad)]
    if filtro_especialista:
        df_filtrado = df_filtrado[df_filtrado["especialista"].isin(filtro_especialista)]
    if filtro_comite:
        df_filtrado = df_filtrado[df_filtrado["estado_comite"].isin(filtro_comite)]

    if df_filtrado.empty:
        st.info("Todavía no hay puntos con estatus de comité diligenciado.")
    else:
        st.dataframe(
            df_filtrado[
                ["id", "especialista", "practicante", "ciudad", "local_identificado",
                 "fecha_registro", "estado_comite"]
            ],
            use_container_width=True,
            hide_index=True,
        )

# ---------------------------------------------------------------------------
# MÓDULO 2 · Generadores
# ---------------------------------------------------------------------------
with tab2:
    st.subheader("Generadores")
    st.write(
        "Cuando el radio de recolección (300 m) de dos puntos potenciales "
        "distintos se superpone, el mismo generador físico (por ejemplo, "
        "las oficinas de un banco) puede quedar registrado dos veces en "
        "Survey123 — una por cada punto — sin que nadie lo note. Consulta "
        "aquí antes de registrar uno nuevo en campo."
    )
    st.caption(
        "🟠 **Naranja** = generador único &nbsp;·&nbsp; "
        "🔵 **Azul** = generador repetido (dos o más registros a menos de "
        f"{UMBRAL_DUPLICIDAD_GENERADOR_M:.0f} m entre sí)."
    )

    col_espacio_gen, col_refrescar_gen = st.columns([5, 1.6])
    with col_refrescar_gen:
        if st.button(
            "🔄 Actualizar generadores", use_container_width=True,
            type="primary", key="refrescar_generadores_tab2",
        ):
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

        st.markdown("#### 🗺️ Mapa de generadores")
        modo_mapa_gen = st.radio(
            "¿Cuáles quieres ver?",
            ["Todos", "Solo repetidos"],
            horizontal=True,
            key="modo_mapa_generadores",
        )
        renderizar_mapa_generadores(generadores_agrupados, modo_mapa_gen, key="mapa_generadores_tab2")

        st.markdown("#### ⚠️ Alertas de duplicidad (radio de 300 m)")
        st.caption(
            "Cada fila de aquí abajo es un generador que quedó registrado "
            "MÁS DE UNA VEZ (probablemente por especialistas distintos, con "
            "nombres distintos, pero en el mismo lugar). La columna "
            "'nombre_generador' es el nombre representativo del grupo — no "
            "significa que todos lo hayan escrito igual."
        )
        alertas_gen = generadores_agrupados[generadores_agrupados["cantidad_registros"] > 1]
        if alertas_gen.empty:
            st.success("No hay generadores repetidos por ahora.")
        else:
            st.warning(f"{len(alertas_gen)} generador(es) parecen estar registrados más de una vez:")
            st.dataframe(
                alertas_gen[
                    [
                        "nombre_generador", "tipo_generador", "cantidad_registros",
                        "puntos_asociados", "especialistas_asociados",
                    ]
                ].rename(columns={
                    "nombre_generador": "Generador (repetido)",
                    "tipo_generador": "Tipo",
                    "cantidad_registros": "Veces registrado",
                    "puntos_asociados": "Puntos potenciales asociados",
                    "especialistas_asociados": "Especialistas que lo repitieron",
                }),
                use_container_width=True,
                hide_index=True,
            )

        st.divider()
        st.markdown("#### Consultar antes de registrar un generador nuevo")
        st.write(
            "Busca por coordenada o dirección (no por nombre) — dos "
            "especialistas pueden ponerle nombres distintos al mismo "
            "generador (ej. 'Conjunto Acanto' vs 'Conjunto Residencial "
            "Acanto'), así que lo que de verdad confirma si ya existe es "
            "la ubicación."
        )

        modo_busqueda_gen = st.radio(
            "¿Cómo quieres buscar?",
            ["Por dirección", "Por coordenada"],
            horizontal=True,
            key="modo_busqueda_gen",
            label_visibility="collapsed",
        )

        consulta_gen = None

        if modo_busqueda_gen == "Por dirección":
            direccion_gen = st.text_input(
                "Escribe la dirección del generador", key="direccion_gen",
                placeholder="Ej. Carrera 15 # 93-60, Bogotá",
            )
            nombre_gen = st.text_input(
                "Nombre del generador (opcional, solo informativo)",
                key="nombre_gen_direccion", placeholder="Ej. Bancolombia",
            )
            if st.button("🔍 Consultar generador", type="primary", key="consultar_gen_direccion_btn"):
                with st.spinner("Buscando dirección..."):
                    resultado_gen = buscar_coordenada_por_direccion(direccion_gen)
                if resultado_gen is None:
                    st.session_state["error_busqueda_gen"] = True
                    st.session_state.pop("consulta_gen_resultado", None)
                else:
                    lat_g, lon_g, etiqueta_g = resultado_gen
                    st.session_state["consulta_gen_resultado"] = {
                        "lat": lat_g, "lon": lon_g, "etiqueta": etiqueta_g, "nombre": nombre_gen,
                    }
                    st.session_state["error_busqueda_gen"] = False

            if st.session_state.get("error_busqueda_gen"):
                st.error("No se encontró esa dirección. Intenta agregar la ciudad.")
            consulta_gen = st.session_state.get("consulta_gen_resultado")

        else:  # Por coordenada
            coord_pegada_gen = st.text_input(
                "Pega la coordenada completa (latitud, longitud)",
                key="coord_pegada_gen",
                placeholder="Ej. 4.697539545568918, -74.09220071349365",
            )
            nombre_gen_coord = st.text_input(
                "Nombre del generador (opcional, solo informativo)",
                key="nombre_gen_coordenada", placeholder="Ej. Bancolombia",
            )
            st.caption(
                "Pégala completa, con todos los decimales que traiga — así el "
                "punto no se desplaza."
            )
            if st.button("🔍 Consultar generador", type="primary", key="consultar_gen_coord_btn"):
                coord_g = parsear_coordenada_pegada(coord_pegada_gen)
                if coord_g is None:
                    st.session_state["error_busqueda_gen"] = True
                    st.session_state.pop("consulta_gen_resultado", None)
                else:
                    lat_g, lon_g = coord_g
                    st.session_state["consulta_gen_resultado"] = {
                        "lat": lat_g, "lon": lon_g,
                        "etiqueta": f"Coordenada {lat_g}, {lon_g}",
                        "nombre": nombre_gen_coord,
                    }
                    st.session_state["error_busqueda_gen"] = False

            if st.session_state.get("error_busqueda_gen"):
                st.error(
                    "Eso no tiene forma de coordenada. Debe verse así: "
                    "'4.697539545568918, -74.09220071349365'."
                )
            consulta_gen = st.session_state.get("consulta_gen_resultado")

        if consulta_gen is not None:
            lat_gc, lon_gc = consulta_gen["lat"], consulta_gen["lon"]
            st.write("📍 **Vista de calle del lugar consultado:**")
            col_mapa_gen, col_calle_gen = st.columns(2)
            with col_mapa_gen:
                st.caption("Mapa")
                components.iframe(url_mapa_embed(lat_gc, lon_gc), height=300)
            with col_calle_gen:
                st.caption("Street View")
                components.iframe(url_streetview_embed(lat_gc, lon_gc), height=300)

            coincidencias_gen = detectar_generadores_coincidentes(
                df_generadores, lat_gc, lon_gc, nombre=consulta_gen.get("nombre", "")
            )
            if coincidencias_gen.empty:
                st.success(
                    "✅ No se encontró ningún generador registrado a menos de "
                    f"{UMBRAL_DUPLICIDAD_GENERADOR_M:.0f} m de esa ubicación. "
                    "Parece nuevo, puedes registrarlo en Survey123.",
                    icon="✅",
                )
            else:
                puntos_ya_vinculados = sorted(
                    set(coincidencias_gen["nombre_punto_potencial"]) - {""}
                )
                st.warning(
                    f"⚠️ Ya existe {len(coincidencias_gen)} generador(es) registrado(s) "
                    f"a menos de {UMBRAL_DUPLICIDAD_GENERADOR_M:.0f} m, vinculado(s) a: "
                    f"**{', '.join(puntos_ya_vinculados) if puntos_ya_vinculados else 'otro punto'}**. "
                    "Considera vincularlo al punto actual en Survey123 en vez de "
                    "crear uno nuevo.",
                    icon="⚠️",
                )
                st.dataframe(
                    coincidencias_gen[
                        [
                            "nombre_generador", "nombre_punto_potencial", "tipo_generador",
                            "distancia_m", "localizador",
                        ]
                    ].rename(columns={
                        "nombre_generador": "Nombre registrado",
                        "nombre_punto_potencial": "Punto potencial asociado",
                        "tipo_generador": "Tipo",
                        "distancia_m": "Distancia (m)",
                        "localizador": "Localizador",
                    }),
                    use_container_width=True,
                    hide_index=True,
                )

st.divider()
st.caption(
    "Conectado a los datos reales del área. La herramienta complementa el "
    "proceso actual; no reemplaza el análisis ni el criterio humano."
)
