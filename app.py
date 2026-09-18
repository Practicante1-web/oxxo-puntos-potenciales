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

from iconos import icon_data
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

def url_mapa_embed(lat: float, lon: float, zoom: int = 17) -> str:
    """Google Maps normal (satelital/calles), centrado en el punto. No necesita cuenta ni API key."""
    return f"https://maps.google.com/maps?q={lat},{lon}&z={zoom}&output=embed"


def url_streetview_embed(lat: float, lon: float) -> str:
    """Google Street View (vista a nivel de calle) en el punto indicado. No necesita cuenta ni API key."""
    return f"https://maps.google.com/maps?layer=c&cbll={lat},{lon}&cbp=11,0,0,0,0&output=svembed"


# ---------------------------------------------------------------------------
# Mapa general combinado (Especialistas / Operación / Generadores)
# ---------------------------------------------------------------------------
# Colores por capa (ahora como pines en forma de gota, ver iconos.py) — los
# que pediste: morado para especialistas, azul claro para operación.
# Generadores y el punto resaltado de una búsqueda usan colores distintos
# para no confundirse con los anteriores.

# Vista por defecto del mapa: siempre abre centrado en Bogotá.
BOGOTA_LAT = 4.6097
BOGOTA_LON = -74.0817
ZOOM_BOGOTA_DEFAULT = 10

# Tamaño (alto, en pixeles de pantalla) de los pines en el mapa. Van en
# pixeles fijos, no en metros — así se ven siempre del mismo tamaño
# razonable sin importar cuánto zoom se le haga (con un tamaño en metros,
# un punto se puede ver del tamaño de una manzana entera al acercar mucho
# el zoom). size_min_pixels/size_max_pixels ponen además un tope duro al
# tamaño real en pantalla, pase lo que pase.
TAMANO_PIN_PX = 30
TAMANO_PIN_RESALTADO_PX = 42


def _capa_pines(d: pd.DataFrame, color_key: str, size: int = TAMANO_PIN_PX) -> pdk.Layer:
    """
    Arma una capa de pines (ícono en forma de gota, como en Google Maps)
    para el color dado — en vez de los círculos planos que se usaban antes.
    color_key es una de las claves de iconos.py: morado, azul_claro,
    naranja, rojo, azul_repetido, gris.
    """
    d = d.copy()
    d["icon_data"] = [icon_data(color_key, size)] * len(d)
    return pdk.Layer(
        "IconLayer", data=d, get_position="[longitud, latitud]",
        get_icon="icon_data", get_size=size, size_units="pixels",
        size_min_pixels=max(14, size - 10), size_max_pixels=size + 16,
        pickable=True,
    )


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
                d["tooltip_text"] = _columna_tooltip_especialistas(d)
                capas.append(_capa_pines(d, "morado"))

    if "Operación (Survey)" in capas_activas:
        if df_operacion is not None and not df_operacion.empty:
            d = df_operacion.dropna(subset=["latitud", "longitud"]).copy()
            if not d.empty:
                nombre_col = "local_identificado" if "local_identificado" in d.columns else (
                    "nombre" if "nombre" in d.columns else None
                )
                d["tooltip_text"] = (
                    "📍 " + d[nombre_col].astype(str) if nombre_col else "📍 Punto de operación"
                )
                capas.append(_capa_pines(d, "azul_claro"))
        else:
            st.caption(
                "🔧 Capa 'Operación (Survey)' todavía no está conectada — "
                "falta el link de esa fuente."
            )

    if "Generadores" in capas_activas:
        if df_generadores_agrupado is not None and not df_generadores_agrupado.empty:
            d = df_generadores_agrupado.dropna(subset=["latitud", "longitud"]).copy()
            if not d.empty:
                d["tooltip_text"] = _columna_tooltip_generadores(d)
                capas.append(_capa_pines(d, "naranja"))

    if punto_resaltado is not None:
        lat_h, lon_h, etiqueta_h = punto_resaltado
        d = pd.DataFrame(
            [{"latitud": lat_h, "longitud": lon_h, "tooltip_text": f"🔎 {etiqueta_h}"}]
        )
        capas.append(_capa_pines(d, "rojo", size=TAMANO_PIN_RESALTADO_PX))
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
    """Fila de chips explicando qué significa cada color de pin en los mapas."""
    chips = [chip_leyenda("morado", "Especialistas (Excel)")]
    if incluir_operacion:
        chips.append(chip_leyenda("azul_claro", "Operación (Survey)"))
    if incluir_generadores:
        chips.append(chip_leyenda("naranja", "Generadores"))
    if incluir_resaltado:
        chips.append(chip_leyenda("rojo", "El punto que acabas de buscar"))
    st.markdown("".join(chips), unsafe_allow_html=True)


def renderizar_mapa_generadores(df_generadores_agrupado, mostrar, key="mapa_generadores", punto_resaltado=None):
    """
    Mapa de generadores, con la opción de mostrar "Todos" o solo los
    "Repetidos" (cantidad_registros > 1 — la señal de duplicidad).

    Si se pasa punto_resaltado=(lat, lon, etiqueta) — por ejemplo, al elegir
    un generador repetido de la tabla de alertas — se agrega un marcador
    rojo extra y el mapa abre centrado y acercado ahí, en vez de la vista
    general de Bogotá.

    (Nota: se probó antes hacer clic directo sobre un punto del mapa para
    seleccionar, pero esa función de Streamlit no anda bien en todas las
    versiones y llegó a dejar el mapa en blanco — por eso ahora la
    selección se hace eligiendo de una lista/tabla, que es más confiable.)
    """
    d = df_generadores_agrupado.dropna(subset=["latitud", "longitud"]).copy().reset_index(drop=True)
    if mostrar == "Solo repetidos":
        d = d[d["cantidad_registros"] > 1].reset_index(drop=True)
    if d.empty:
        st.info("No hay generadores para mostrar con esa selección.")
        return

    d["tooltip_text"] = _columna_tooltip_generadores(d)
    d["icon_data"] = d["cantidad_registros"].apply(
        lambda n: icon_data("azul_repetido" if n > 1 else "naranja", TAMANO_PIN_PX)
    )
    capas = [
        pdk.Layer(
            "IconLayer", data=d, get_position="[longitud, latitud]",
            get_icon="icon_data", get_size=TAMANO_PIN_PX, size_units="pixels",
            size_min_pixels=TAMANO_PIN_PX - 10, size_max_pixels=TAMANO_PIN_PX + 16,
            pickable=True,
        )
    ]

    if punto_resaltado is not None:
        lat_h, lon_h, etiqueta_h = punto_resaltado
        d_resaltado = pd.DataFrame(
            [{"latitud": lat_h, "longitud": lon_h, "tooltip_text": f"🔎 {etiqueta_h}"}]
        )
        capas.append(_capa_pines(d_resaltado, "rojo", size=TAMANO_PIN_RESALTADO_PX))
        vista = pdk.ViewState(latitude=lat_h, longitude=lon_h, zoom=16)
    else:
        vista = pdk.ViewState(latitude=BOGOTA_LAT, longitude=BOGOTA_LON, zoom=ZOOM_BOGOTA_DEFAULT)

    deck = pdk.Deck(layers=capas, initial_view_state=vista, tooltip={"text": "{tooltip_text}"}, map_style="light")
    st.pydeck_chart(deck, key=key)

    chips_gen = [
        chip_leyenda("naranja", "Generador único"),
        chip_leyenda("azul_repetido", f"Generador repetido (radio de {UMBRAL_DUPLICIDAD_GENERADOR_M:.0f} m)"),
    ]
    if punto_resaltado is not None:
        chips_gen.append(chip_leyenda("rojo", "El que elegiste de la tabla"))
    st.markdown("".join(chips_gen), unsafe_allow_html=True)


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

    /* Cajas de texto y selects redondeados, estilo barra de búsqueda */
    [data-testid="stTextInput"] input,
    [data-testid="stNumberInput"] input,
    .stSelectbox div[data-baseweb="select"] > div {{
        border-radius: 10px !important;
    }}

    /* Chips de leyenda (puntico de color + texto), en vez de texto plano */
    .chip-leyenda {{
        display: inline-flex;
        align-items: center;
        gap: 6px;
        background: #FFFFFF;
        border: 1px solid {OXXO_GRIS_BORDE};
        border-radius: 999px;
        padding: 4px 12px;
        margin: 2px 6px 6px 0;
        font-size: 13px;
        color: {OXXO_TEXTO};
    }}
    .chip-leyenda .punto {{
        width: 10px;
        height: 10px;
        min-width: 10px;
        border-radius: 50%;
        display: inline-block;
    }}

    /* Tarjeta de resultado (punto o generador encontrado en una búsqueda) */
    .tarjeta-resultado {{
        background: #FFFFFF;
        border: 1px solid {OXXO_GRIS_BORDE};
        border-radius: 14px;
        padding: 14px 18px;
        margin-bottom: 12px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.05);
    }}
    .tarjeta-resultado .tarjeta-header {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
        flex-wrap: wrap;
    }}
    .tarjeta-resultado .titulo {{
        font-size: 15.5px;
        font-weight: 700;
        color: {OXXO_TEXTO};
    }}
    .tarjeta-resultado .fila {{
        display: flex;
        align-items: flex-start;
        gap: 8px;
        font-size: 13.5px;
        color: #4A4A4F;
        margin-top: 7px;
        line-height: 1.35;
    }}
    .tarjeta-resultado .fila.nota {{
        font-style: italic;
        color: #6B6B70;
        border-top: 1px dashed {OXXO_GRIS_BORDE};
        padding-top: 7px;
    }}

    /* Etiqueta de estado (badge), estilo "PENDIENTE" / "APROBADO" de la referencia */
    .badge-estado {{
        display: inline-block;
        padding: 3px 12px;
        border-radius: 999px;
        font-size: 11px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.3px;
        white-space: nowrap;
    }}
    .badge-aprobado {{ background: #DDF3E4; color: #1F7A3F; }}
    .badge-tareas {{ background: #E0ECFB; color: #1E5FA8; }}
    .badge-descartado {{ background: #FBE0E0; color: {OXXO_ROJO_OSCURO}; }}
    .badge-pendiente {{ background: #FFF3CD; color: #8A6D1D; }}
    .badge-neutral {{ background: {OXXO_GRIS_FONDO}; color: #6B6B70; border: 1px solid {OXXO_GRIS_BORDE}; }}
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Piezas visuales reutilizables: chips de leyenda y tarjetas de resultado
# (inspiradas en la referencia de diseño que compartiste — mismos badges de
# estado, filas con íconos, y colores por tipo de punto).
# ---------------------------------------------------------------------------
_COLORES_HEX_LEYENDA = {
    "morado": "#7C3AA8",
    "azul_claro": "#5DADE2",
    "naranja": "#E67E22",
    "rojo": "#E11E1E",
    "azul_repetido": "#1955DC",
    "gris": "#7F8C8D",
}


def chip_leyenda(color_key: str, texto: str) -> str:
    """Una 'píldora' con un puntico de color + texto, para la leyenda del mapa."""
    color_hex = _COLORES_HEX_LEYENDA.get(color_key, "#999999")
    return (
        f'<span class="chip-leyenda"><span class="punto" '
        f'style="background:{color_hex}"></span>{texto}</span>'
    )


def _clase_badge_estado(estado: str) -> str:
    e = (estado or "").strip().lower()
    if "descart" in e:
        return "badge-descartado"
    if "tarea" in e:
        return "badge-tareas"
    if "aprob" in e:
        return "badge-aprobado"
    if not e:
        return "badge-pendiente"
    return "badge-neutral"


def badge_estado_html(estado: str) -> str:
    """Etiqueta de color según el estado de comité (o 'Pendiente' si está vacío)."""
    texto = estado.strip() if estado and str(estado).strip() else "Pendiente"
    return f'<span class="badge-estado {_clase_badge_estado(estado)}">{texto}</span>'


def tarjeta_resultado_html(titulo: str, badge_html: str, filas: list, nota: str = None) -> str:
    """
    Arma una tarjeta de resultado estilo 'ficha' (título + badge de estado +
    filas con íconos + nota opcional al final) — el mismo look de la
    referencia que compartiste, adaptado a lo que Streamlit puede mostrar.
    `filas` es una lista de tuplas (icono, texto_html).
    """
    filas_html = "".join(f'<div class="fila">{icono} {texto}</div>' for icono, texto in filas)
    nota_html = f'<div class="fila nota">🔍 {nota}</div>' if nota else ""
    return (
        '<div class="tarjeta-resultado">'
        '<div class="tarjeta-header">'
        f'<span class="titulo">{titulo}</span>{badge_html}'
        '</div>'
        f'{filas_html}{nota_html}'
        '</div>'
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


# Cuánto tiempo se guarda en caché la última descarga antes de volver a
# traer los datos solos, sin que nadie tenga que acordarse de darle clic a
# "Actualizar". Antes no tenía límite de tiempo — por eso, si alguien
# agregaba puntos nuevos al Excel de puente y nadie más le daba clic al
# botón de actualizar, esos puntos nuevos se quedaban invisibles para
# todo el mundo indefinidamente. Con esto, como mucho se puede quedar
# desactualizado este rato; el botón sigue sirviendo para forzarlo al
# instante.
TTL_CACHE_DATOS = "10m"


@st.cache_data(show_spinner="Descargando la versión más reciente del Excel...", ttl=TTL_CACHE_DATOS)
def _leer_desde_url_cacheado(url: str):
    """
    Envuelve leer_desde_url en caché de Streamlit. Se refresca sola cada
    TTL_CACHE_DATOS, y también al instante si el usuario le da clic al
    botón "Actualizar Excel de puente" (que llama a .clear()).
    """
    return leer_desde_url(url)


@st.cache_data(show_spinner="Consultando la capa de generadores...", ttl=TTL_CACHE_DATOS)
def _leer_generadores_cacheado():
    """
    Igual patrón que _leer_desde_url_cacheado: se refresca sola cada
    TTL_CACHE_DATOS, y al instante con el botón "Actualizar generadores".
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

# IMPORTANTE: esto se vuelve a ejecutar en CADA carga de la página (no solo
# la primera vez), a propósito. Antes solo se cargaba una vez por sesión
# (guardado en session_state) y se quedaba pegado ahí — si alguien más
# agregaba puntos nuevos al Excel de puente, esos puntos nuevos no
# aparecían para nadie que ya tuviera la app abierta, ni para quien la
# abriera de nuevo, hasta que alguien le diera clic manualmente al botón
# de actualizar. Ahora, como _leer_desde_url_cacheado ya tiene su propia
# caché con vencimiento (TTL_CACHE_DATOS), volver a llamarla aquí es
# barato (la mayoría de las veces solo devuelve lo que ya tenía guardado)
# pero garantiza que, como mucho, los datos se demoren ese rato en
# aparecer solos — sin que nadie tenga que acordarse de nada.
if url_secreta:
    try:
        df = _leer_desde_url_cacheado(url_secreta)
        st.session_state.puntos = df
        cargado_desde_secret = True
    except Exception as e:
        # Si falla la descarga en vivo (p. ej. el link dejó de ser público),
        # no se cae la app: se usa la última copia que sí se pudo cargar.
        error_fuente_url = str(e)
        df = st.session_state.get("puntos")
        if df is None:
            df = cargar_puntos()
        st.session_state.puntos = df
elif metadata.get("modo") == "url" and metadata.get("url_fuente"):
    try:
        df = _leer_desde_url_cacheado(metadata["url_fuente"])
        st.session_state.puntos = df
    except Exception as e:
        error_fuente_url = str(e)
        df = st.session_state.get("puntos")
        if df is None:
            df = cargar_puntos()
        st.session_state.puntos = df
elif RUTA_EXCEL_BUNDLED.exists():
    # Forma principal: el Excel viaja incluido en el proyecto y se lee
    # solo, cada vez que se abre la app — igual que un "Book.xlsx". Para
    # que esto refleje siempre lo último, hay que reemplazar este archivo
    # en el repositorio de GitHub (no basta con editar el Excel en tu
    # computador si no lo subes).
    try:
        df = leer_archivo_fuente(RUTA_EXCEL_BUNDLED, RUTA_EXCEL_BUNDLED.name)
        st.session_state.puntos = df
        cargado_desde_bundle = True
    except Exception as e:
        error_fuente_url = f"No se pudo leer {RUTA_EXCEL_BUNDLED.name}: {e}"
        df = st.session_state.get("puntos")
        if df is None:
            df = cargar_puntos()
        st.session_state.puntos = df
else:
    if "puntos" not in st.session_state:
        st.session_state.puntos = cargar_puntos()
    df = st.session_state.puntos

if error_fuente_url:
    st.error(f"⚠️ {error_fuente_url} (se está mostrando la última copia guardada).", icon="⚠️")

error_generadores = None
try:
    df_generadores = _leer_generadores_cacheado()
    st.session_state.generadores = df_generadores
    guardar_generadores(df_generadores)
except Exception as e:
    error_generadores = str(e)
    df_generadores = st.session_state.get("generadores")
    if df_generadores is None:
        df_generadores = cargar_generadores_cache()
    st.session_state.generadores = df_generadores

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

                # También mostramos Google Maps + Street View del resultado
                # elegido (por defecto, el más parecido — la primera fila).
                con_coords_nombre = resultado_nombre.dropna(subset=["latitud", "longitud"])
                if con_coords_nombre.empty:
                    st.caption(
                        "Ninguno de estos resultados tiene coordenadas registradas, "
                        "así que no se puede mostrar el mapa ni Street View."
                    )
                else:
                    opciones_nombre = {
                        f"{row.local_identificado} · {row.especialista}": row.id
                        for row in con_coords_nombre.itertuples()
                    }
                    etiqueta_nombre_elegida = st.selectbox(
                        "Ver mapa y Street View de:", list(opciones_nombre.keys()),
                        key="preview_resultado_nombre",
                    )
                    id_elegido = opciones_nombre[etiqueta_nombre_elegida]
                    fila_elegida_nombre = con_coords_nombre[con_coords_nombre["id"] == id_elegido].iloc[0]
                    lat_n, lon_n = fila_elegida_nombre["latitud"], fila_elegida_nombre["longitud"]
                    col_mapa_n, col_calle_n = st.columns(2)
                    with col_mapa_n:
                        st.caption("Mapa")
                        components.iframe(url_mapa_embed(lat_n, lon_n), height=300)
                    with col_calle_n:
                        st.caption("Street View")
                        components.iframe(url_streetview_embed(lat_n, lon_n), height=300)

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
                detalle_distancia = (
                    f"A {row['distancia_m']:.0f} m de tu ubicación"
                    if row["distancia_m"] != float("inf")
                    else "Sin coordenadas para comparar distancia"
                )
                registrado_por = f"Registrado por <b>{row['especialista']}</b>"
                if row.get("practicante"):
                    registrado_por += f" · practicante <b>{row['practicante']}</b>"
                filas_tarjeta = [
                    ("👤", registrado_por),
                    ("📅", f"Fecha de registro: {row['fecha_registro']}"),
                    ("📍", f"{detalle_distancia} · {row['ciudad']}"),
                ]
                st.markdown(
                    tarjeta_resultado_html(
                        titulo=row["local_identificado"],
                        badge_html=badge_estado_html(row["estado_comite"]),
                        filas=filas_tarjeta,
                        nota=f"Por qué se marca como posible duplicado: {row['coincide_por']}",
                    ),
                    unsafe_allow_html=True,
                )
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

        alertas_gen = generadores_agrupados[generadores_agrupados["cantidad_registros"] > 1].reset_index(drop=True)

        with st.container(border=True):
            mc1, mc2, mc3 = st.columns(3)
            mc1.metric("🏢 Generadores (únicos)", len(generadores_agrupados))
            mc2.metric("📋 Registros en Survey123", len(df_generadores))
            mc3.metric("⚠️ Con duplicidad", len(alertas_gen))

        st.markdown("#### 🗺️ Mapa de generadores")
        modo_mapa_gen = st.radio(
            "¿Cuáles quieres ver?",
            ["Todos", "Solo repetidos"],
            horizontal=True,
            key="modo_mapa_generadores",
        )

        punto_resaltado_gen = None
        etiqueta_elegida_gen = "— Ver todos —"
        if not alertas_gen.empty:
            opciones_alerta = ["— Ver todos —"] + [
                f"{row.nombre_generador or '(sin nombre)'} · {row.cantidad_registros}x"
                for row in alertas_gen.itertuples()
            ]
            etiqueta_elegida_gen = st.selectbox(
                "Elige un generador repetido de la tabla de abajo para verlo resaltado en el mapa:",
                opciones_alerta,
                key="generador_resaltado_tab2",
            )
            if etiqueta_elegida_gen != "— Ver todos —":
                idx_elegido = opciones_alerta.index(etiqueta_elegida_gen) - 1
                fila_elegida = alertas_gen.iloc[idx_elegido]
                punto_resaltado_gen = (
                    fila_elegida["latitud"], fila_elegida["longitud"], fila_elegida["nombre_generador"],
                )

        renderizar_mapa_generadores(
            generadores_agrupados, modo_mapa_gen, key="mapa_generadores_tab2",
            punto_resaltado=punto_resaltado_gen,
        )

        if punto_resaltado_gen is not None:
            lat_g_sel, lon_g_sel, nombre_g_sel = punto_resaltado_gen
            st.write(f"📍 **Street View de '{nombre_g_sel}':**")
            components.iframe(url_streetview_embed(lat_g_sel, lon_g_sel), height=350)

        st.markdown("#### ⚠️ Alertas de duplicidad (radio de 300 m)")
        st.caption(
            "Cada fila de aquí abajo es un generador que quedó registrado "
            "MÁS DE UNA VEZ (probablemente por especialistas distintos, con "
            "nombres distintos, pero en el mismo lugar). La columna "
            "'nombre_generador' es el nombre representativo del grupo — no "
            "significa que todos lo hayan escrito igual. Elígelo en la lista "
            "de arriba del mapa para verlo resaltado."
        )
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
