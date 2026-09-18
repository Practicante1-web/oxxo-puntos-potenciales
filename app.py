"""
Aplicativo para la Consulta y Seguimiento de Puntos Potenciales - Generadores
Inteligencia de Expansión - OXXO
Proyecto de práctica profesional - Alisson Gómez

Prototipo construido con Streamlit. El archivo data/Puntos_potenciales.xlsx
va incluido en el propio proyecto y se carga automáticamente cada vez que
se abre la app (igual que un "Book.xlsx" que viaja con el proyecto): para
actualizar los datos, basta con reemplazar ese archivo en el repositorio.
Desde esta versión, ese Excel trae VARIAS hojas (Especialistas, Terceros,
Operación y, cuando llegue, Inmobiliaria) que se combinan automáticamente
en un solo mapa por capas. También existe, como alternativa, conectarse en
vivo a un link de OneDrive (igual mecanismo que el Excel de puente que ya
se usaba antes, ahora aplicado al archivo de varias hojas).
"""

import json
from datetime import datetime
from pathlib import Path

import altair as alt
import pandas as pd
import pydeck as pdk
import streamlit as st
import streamlit.components.v1 as components

from iconos import icon_data
from utils import (
    CRITERIOS_INMOBILIARIA,
    FUENTE_COLOR_ICONO,
    RAZONES_DESCARTE_INMOBILIARIA,
    UMBRAL_DUPLICIDAD_GENERADOR_M,
    UMBRAL_DUPLICIDAD_M,
    agrupar_generadores,
    buscar_coordenada_por_direccion,
    buscar_lugar,
    buscar_por_nombre,
    cargar_generadores_cache,
    cargar_puntos,
    detectar_coincidencias,
    detectar_duplicados_potenciales,
    detectar_generadores_coincidentes,
    evaluar_punto_inmobiliario,
    guardar_generadores,
    guardar_puntos,
    leer_fuentes_modulo1,
    leer_fuentes_modulo1_desde_url,
    leer_generadores_desde_arcgis,
    parsear_coordenada_pegada,
)

METADATA_PATH = Path("data/metadata.json")
RUTA_EXCEL_BUNDLED = Path("data/Puntos_potenciales.xlsx")

# Nombre de la clave en "Secrets" de Streamlit Cloud donde se guarda, de
# forma privada (nunca visible en el código ni en GitHub), el link de
# OneDrive del archivo de puntos potenciales (Especialistas + Terceros +
# Operación + Inmobiliaria) que actualiza todo el equipo. Si esta clave no
# está configurada, la app sigue funcionando igual con el Excel incluido
# en el proyecto (RUTA_EXCEL_BUNDLED) como hasta ahora.
SECRET_KEY_URL_COMITE = "url_puente_comite"


def url_mapa_embed(lat: float, lon: float, zoom: int = 17) -> str:
    """Google Maps normal (satelital/calles), centrado en el punto. No necesita cuenta ni API key."""
    return f"https://maps.google.com/maps?q={lat},{lon}&z={zoom}&output=embed"


def url_streetview_embed(lat: float, lon: float) -> str:
    """Google Street View (vista a nivel de calle) en el punto indicado. No necesita cuenta ni API key."""
    return f"https://maps.google.com/maps?layer=c&cbll={lat},{lon}&cbp=11,0,0,0,0&output=svembed"


# ---------------------------------------------------------------------------
# Mapa general combinado del Módulo 1 (Especialistas / Operación / Terceros /
# Inmobiliaria) — SIN generadores, esos viven solo en el Módulo 2.
# ---------------------------------------------------------------------------
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
    para el color dado. color_key es una de las claves de iconos.py:
    morado, azul_claro, rosado, verde, naranja, rojo, azul_repetido, gris.
    """
    d = d.copy()
    d["icon_data"] = [icon_data(color_key, size)] * len(d)
    return pdk.Layer(
        "IconLayer", data=d, get_position="[longitud, latitud]",
        get_icon="icon_data", get_size=size, size_units="pixels",
        size_min_pixels=max(14, size - 10), size_max_pixels=size + 16,
        pickable=True,
    )


def _capa_texto_resaltados(resaltados):
    """
    Etiqueta de texto (nombre CORTO) que aparece DIRECTAMENTE sobre el
    mapa para cada punto resaltado (rojo) — así el nombre se ve de una
    vez, sin tener que pasar el mouse por encima. Se usa sobre todo
    cuando se resalta un PAR de posibles duplicados, para que se vea de
    inmediato cuál es cuál.

    Cada elemento de `resaltados` puede traer un 4to valor opcional con
    info extra para el tooltip (ver _resaltados_a_lista) — esta capa de
    texto SIEMPRE usa solo el nombre corto (3er valor), nunca ese extra,
    para no llenar el mapa de texto ilegible.
    """
    if not resaltados:
        return None
    d = pd.DataFrame(
        [{"latitud": item[0], "longitud": item[1], "texto": str(item[2])} for item in resaltados]
    )
    # Nota: no se fijan get_text_anchor / get_alignment_baseline a mano —
    # pydeck convierte cualquier string de un prop "get_*" en un accesor
    # por fila (para leer columnas de los datos), así que un valor
    # constante como "middle" terminaría interpretado como el nombre de
    # una columna en vez de como texto fijo. Los valores por defecto de
    # TextLayer (centrado) ya son razonables sin tocarlos.
    return pdk.Layer(
        "TextLayer", data=d, get_position="[longitud, latitud]",
        get_text="texto", get_size=15, get_color=[20, 20, 20, 255],
        get_pixel_offset=[0, -26],
        pickable=False,
    )


def _resaltados_a_lista(punto_resaltado):
    """
    Normaliza punto_resaltado para aceptar tanto un único punto como una
    lista de varios — esto último se usa para mostrar un PAR de posibles
    duplicados al mismo tiempo (por ejemplo, al hacer clic en una fila de
    la tabla de duplicados). Cada punto es una tupla (lat, lon, etiqueta)
    o, si se quiere mostrar info extra en el tooltip al pasar el mouse,
    (lat, lon, etiqueta, info_extra).
    """
    if punto_resaltado is None:
        return []
    if isinstance(punto_resaltado, tuple) and len(punto_resaltado) in (3, 4) and not isinstance(punto_resaltado[0], (list, tuple)):
        return [punto_resaltado]
    return list(punto_resaltado)


def _texto_tooltip_resaltado(item) -> str:
    """Arma el texto del tooltip (al pasar el mouse) para un punto resaltado, incluyendo la info extra si se dio."""
    etiqueta_h = item[2]
    texto = f"🔎 {etiqueta_h}"
    if len(item) > 3 and item[3]:
        texto = texto + "\n" + str(item[3])
    return texto


def _columna_tooltip_fuente(d: pd.DataFrame) -> pd.Series:
    texto = "📍 " + d["local_identificado"].astype(str)
    texto = texto + "\nFuente: " + d["fuente"].astype(str)
    if "especialista" in d.columns:
        texto = texto + "\nResponsable: " + d["especialista"].replace("", "—").astype(str)
    if "estado" in d.columns:
        texto = texto + "\nEstado: " + d["estado"].replace("", "—").astype(str)
    if "ciudad" in d.columns:
        texto = texto + "\nCiudad: " + d["ciudad"].replace("", "—").astype(str)
    return texto


def _columna_tooltip_generadores(d: pd.DataFrame) -> pd.Series:
    texto = (
        "🏢 " + d["nombre_generador"].astype(str)
        + "\nTipo: " + d["tipo_generador"].astype(str)
        + "\nRegistros agrupados: " + d["cantidad_registros"].astype(str)
    )
    if "registrado_por" in d.columns:
        texto = texto + "\nRegistrado por: " + d["registrado_por"].replace("", "—").astype(str)
    if "puntos_asociados" in d.columns:
        texto = texto + "\nPuntos asociados: " + d["puntos_asociados"].replace("", "—").astype(str)
    if "duplicado_por" in d.columns:
        texto = texto + "\n¿Duplicado?: " + d["duplicado_por"].replace("", "No").astype(str)
    if "nombre_duplicado" in d.columns:
        texto = texto + "\nSe repite con: " + d["nombre_duplicado"].replace("", "—").astype(str)
    return texto


def _columna_tooltip_potenciales(d: pd.DataFrame) -> pd.Series:
    texto = "📍 Punto potencial (Survey123)"
    if "nombre_punto_potencial" in d.columns:
        texto = texto + "\nNombre: " + d["nombre_punto_potencial"].replace("", "—").astype(str)
    if "localizador" in d.columns:
        texto = texto + "\nLocalizador: " + d["localizador"].replace("", "—").astype(str)
    if "fecha_creacion" in d.columns:
        texto = texto + "\nFecha: " + d["fecha_creacion"].astype(str)
    return texto


def renderizar_mapa_general(df, fuentes_activas, punto_resaltado=None, key="mapa_general"):
    """
    Dibuja el mapa combinado del Módulo 1: una capa por cada fuente activa
    (Especialistas=morado, Operación=azul, Terceros=rosado,
    Inmobiliaria=verde). NUNCA incluye generadores — el Módulo 1 es solo
    para puntos que llegan (Especialistas/Operación/Terceros/Inmobiliaria).

    punto_resaltado puede ser un único (lat, lon, etiqueta) o una lista de
    varios, para resaltar un par de posibles duplicados a la vez.
    """
    capas = []

    if df is not None and not df.empty:
        base = df.dropna(subset=["latitud", "longitud"])
        for fuente, color in FUENTE_COLOR_ICONO.items():
            if fuente in fuentes_activas:
                d = base[base["fuente"] == fuente].copy()
                if not d.empty:
                    d["tooltip_text"] = _columna_tooltip_fuente(d)
                    capas.append(_capa_pines(d, color))

    resaltados = _resaltados_a_lista(punto_resaltado)
    if resaltados:
        d = pd.DataFrame(
            [{"latitud": item[0], "longitud": item[1], "tooltip_text": _texto_tooltip_resaltado(item)} for item in resaltados]
        )
        capas.append(_capa_pines(d, "rojo", size=TAMANO_PIN_RESALTADO_PX))
        _capa_texto = _capa_texto_resaltados(resaltados)
        if _capa_texto is not None:
            capas.append(_capa_texto)
        if len(resaltados) == 1:
            vista = pdk.ViewState(latitude=resaltados[0][0], longitude=resaltados[0][1], zoom=15)
        else:
            vista = pdk.ViewState(
                latitude=sum(r[0] for r in resaltados) / len(resaltados),
                longitude=sum(r[1] for r in resaltados) / len(resaltados),
                zoom=14,
            )
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
        ),
        key=key,
    )


def mostrar_leyenda_fuentes(incluir_resaltado=False):
    """Fila de chips explicando qué significa cada color de pin en el mapa general."""
    chips = [chip_leyenda(color, fuente) for fuente, color in FUENTE_COLOR_ICONO.items()]
    if incluir_resaltado:
        chips.append(chip_leyenda("rojo", "El punto que acabas de buscar"))
    st.markdown("".join(chips), unsafe_allow_html=True)


def tabla_leyenda_fuentes_html(incluir_resaltado: bool = False) -> str:
    """
    Tablita (no solo chips) con el color de cada fuente — para que quede
    clarísimo qué color es qué. Si incluir_resaltado=True, agrega una fila
    extra "Búsqueda" en rojo — el mismo color del puntero que se muestra
    cuando se consulta o se busca un punto.
    """
    filas = "".join(
        f'<tr><td><span class="punto-leyenda" style="background:{_COLORES_HEX_LEYENDA.get(color, "#999999")}"></span></td>'
        f'<td>{fuente}</td></tr>'
        for fuente, color in FUENTE_COLOR_ICONO.items()
    )
    if incluir_resaltado:
        filas += (
            f'<tr><td><span class="punto-leyenda" style="background:{_COLORES_HEX_LEYENDA.get("rojo", "#E11E1E")}"></span></td>'
            f'<td><b>BÚSQUEDA</b></td></tr>'
        )
    return f'<table class="tabla-leyenda"><tbody>{filas}</tbody></table>'


def renderizar_mapa_generadores(
    df_generadores_agrupado, mostrar, key="mapa_generadores", punto_resaltado=None,
    df_potenciales_survey=None,
):
    """
    Mapa de generadores (Módulo 2). `mostrar` es una de: "Potenciales",
    "Generadores", "Repetidos", "Todos".

    - "Potenciales": solo los puntos potenciales de la misma encuesta (gris).
    - "Generadores": todos los generadores (únicos y repetidos).
    - "Repetidos": solo los generadores con más de un registro (posibles duplicados).
    - "Todos": generadores + puntos potenciales juntos.

    punto_resaltado puede ser un único (lat, lon, etiqueta) o una lista de
    varios (para mostrar un par de duplicados a la vez).

    (Nota: se probó antes hacer clic directo sobre un punto del mapa para
    seleccionar, pero esa función de Streamlit no anda bien en todas las
    versiones y llegó a dejar el mapa en blanco — por eso la selección se
    hace eligiendo de una lista/tabla, que es más confiable.)
    """
    mostrar_generadores = mostrar in ("Generadores", "Repetidos", "Todos")
    mostrar_potenciales = mostrar in ("Potenciales", "Todos")

    d = df_generadores_agrupado.dropna(subset=["latitud", "longitud"]).copy().reset_index(drop=True)
    if mostrar == "Repetidos":
        d = d[d["cantidad_registros"] > 1].reset_index(drop=True)

    resaltados = _resaltados_a_lista(punto_resaltado)

    hay_generadores = mostrar_generadores and not d.empty
    hay_potenciales = mostrar_potenciales and df_potenciales_survey is not None and not df_potenciales_survey.empty
    if not hay_generadores and not hay_potenciales and not resaltados:
        st.info("No hay generadores para mostrar con esa selección.")
        return

    capas = []

    if hay_generadores:
        d["tooltip_text"] = _columna_tooltip_generadores(d)
        d["icon_data"] = d["cantidad_registros"].apply(
            lambda n: icon_data("azul_repetido" if n > 1 else "naranja", TAMANO_PIN_PX)
        )
        capas.append(
            pdk.Layer(
                "IconLayer", data=d, get_position="[longitud, latitud]",
                get_icon="icon_data", get_size=TAMANO_PIN_PX, size_units="pixels",
                size_min_pixels=TAMANO_PIN_PX - 10, size_max_pixels=TAMANO_PIN_PX + 16,
                pickable=True,
            )
        )

    if hay_potenciales:
        dp = df_potenciales_survey.dropna(subset=["latitud", "longitud"]).copy().reset_index(drop=True)
        dp["tooltip_text"] = _columna_tooltip_potenciales(dp)
        capas.append(_capa_pines(dp, "gris", size=TAMANO_PIN_PX))

    if resaltados:
        d_resaltado = pd.DataFrame(
            [{"latitud": item[0], "longitud": item[1], "tooltip_text": _texto_tooltip_resaltado(item)} for item in resaltados]
        )
        capas.append(_capa_pines(d_resaltado, "rojo", size=TAMANO_PIN_RESALTADO_PX))
        _capa_texto_gen = _capa_texto_resaltados(resaltados)
        if _capa_texto_gen is not None:
            capas.append(_capa_texto_gen)
        if len(resaltados) == 1:
            vista = pdk.ViewState(latitude=resaltados[0][0], longitude=resaltados[0][1], zoom=16)
        else:
            vista = pdk.ViewState(
                latitude=sum(r[0] for r in resaltados) / len(resaltados),
                longitude=sum(r[1] for r in resaltados) / len(resaltados),
                zoom=15,
            )
    else:
        vista = pdk.ViewState(latitude=BOGOTA_LAT, longitude=BOGOTA_LON, zoom=ZOOM_BOGOTA_DEFAULT)

    deck = pdk.Deck(layers=capas, initial_view_state=vista, tooltip={"text": "{tooltip_text}"}, map_style="light")
    st.pydeck_chart(deck, key=key)

    chips_gen = []
    if mostrar_generadores:
        chips_gen.append(chip_leyenda("naranja", "Generador único"))
        chips_gen.append(chip_leyenda("azul_repetido", "Generador repetido (ver tabla de abajo)"))
    if mostrar_potenciales:
        chips_gen.append(chip_leyenda("gris", "Punto potencial (mismo survey, informativo)"))
    if resaltados:
        chips_gen.append(chip_leyenda("rojo", "Resaltado(s)"))
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
    page_title="Puntos Potenciales · Generadores | Inteligencia de Expansión OXXO",
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

    /* Radio del sidebar usado como "menú" de módulos: se ve como una lista limpia */
    section[data-testid="stSidebar"] [data-baseweb="radio"] {{
        gap: 4px;
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

    /* Tablita de leyenda de colores (además de los chips) */
    .tabla-leyenda {{
        border-collapse: collapse;
        margin: 6px 0 14px 0;
    }}
    .tabla-leyenda td {{
        padding: 4px 10px 4px 0;
        font-size: 13.5px;
        color: {OXXO_TEXTO};
        vertical-align: middle;
    }}
    .punto-leyenda {{
        display: inline-block;
        width: 12px;
        height: 12px;
        border-radius: 50%;
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
# ---------------------------------------------------------------------------
_COLORES_HEX_LEYENDA = {
    "morado": "#7C3AA8",
    "azul_claro": "#5DADE2",
    "naranja": "#E67E22",
    "rojo": "#E11E1E",
    "azul_repetido": "#1955DC",
    "gris": "#7F8C8D",
    "rosado": "#E84393",
    "verde": "#27AE60",
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
    """Etiqueta de color según el estado del punto (o 'Pendiente' si está vacío)."""
    texto = estado.strip() if estado and str(estado).strip() else "Pendiente"
    return f'<span class="badge-estado {_clase_badge_estado(estado)}">{texto}</span>'


def tarjeta_resultado_html(titulo: str, badge_html: str, filas: list, nota: str = None) -> str:
    """
    Arma una tarjeta de resultado estilo 'ficha' (título + badge de estado +
    filas con íconos + nota opcional al final). `filas` es una lista de
    tuplas (icono, texto_html).
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
# "Actualizar". El botón sigue sirviendo para forzarlo al instante.
TTL_CACHE_DATOS = "10m"


@st.cache_data(show_spinner="Descargando la versión más reciente del Excel...", ttl=TTL_CACHE_DATOS)
def _leer_fuentes_modulo1_desde_url_cacheado(url: str):
    """
    Envuelve leer_fuentes_modulo1_desde_url en caché de Streamlit. Se
    refresca sola cada TTL_CACHE_DATOS, y también al instante si el
    usuario le da clic al botón de actualizar (que llama a .clear()).
    """
    return leer_fuentes_modulo1_desde_url(url)


@st.cache_data(show_spinner="Consultando la capa de generadores...", ttl=TTL_CACHE_DATOS)
def _leer_generadores_cacheado():
    """
    Igual patrón que arriba: se refresca sola cada TTL_CACHE_DATOS, y al
    instante con el botón "Actualizar generadores".
    """
    return leer_generadores_desde_arcgis()


# ---------------------------------------------------------------------------
# Estado inicial
# ---------------------------------------------------------------------------
metadata = leer_metadata()
error_fuente_url = None
cargado_desde_bundle = False
cargado_desde_secret = False

# El link del archivo de puntos potenciales vive de forma privada en los
# Secrets de Streamlit Cloud (nunca en el código ni en GitHub). Si está
# configurado, es la fuente de más prioridad — por encima incluso del
# Excel incluido en el proyecto.
url_secreta = ""
try:
    url_secreta = st.secrets.get(SECRET_KEY_URL_COMITE, "")
except Exception:
    url_secreta = ""

# IMPORTANTE: esto se vuelve a ejecutar en CADA carga de la página (no solo
# la primera vez), a propósito — así, como mucho, los datos se demoran
# TTL_CACHE_DATOS en aparecer solos si alguien agrega puntos nuevos al
# Excel conectado, sin que nadie tenga que acordarse de nada.
if url_secreta:
    try:
        df = _leer_fuentes_modulo1_desde_url_cacheado(url_secreta)
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
        df = _leer_fuentes_modulo1_desde_url_cacheado(metadata["url_fuente"])
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
        df = leer_fuentes_modulo1(RUTA_EXCEL_BUNDLED, RUTA_EXCEL_BUNDLED.name)
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
# en vez de guardarse en session_state.
generadores_agrupados = agrupar_generadores(df_generadores, df_puntos=df)

if "tipo_levantamiento" in df_generadores.columns:
    _es_potencial_survey = df_generadores["tipo_levantamiento"].astype(str).str.strip().str.lower() == "punto potencial"
    df_potenciales_survey = df_generadores[_es_potencial_survey].dropna(subset=["latitud", "longitud"])
else:
    df_potenciales_survey = df_generadores.iloc[0:0]


def _refrescar_puntos_desde_url() -> bool:
    """
    Vuelve a descargar el Excel de puntos potenciales (desde el Secret
    privado, o desde el link manual guardado) y reemplaza los puntos
    cargados. Se usa desde el botón del sidebar, así que sin importar en
    qué módulo esté Alisson, siempre puede traer los datos nuevos.
    """
    _leer_fuentes_modulo1_desde_url_cacheado.clear()
    _url_para_refrescar = url_secreta or metadata.get("url_fuente", "")
    try:
        nuevo_df = _leer_fuentes_modulo1_desde_url_cacheado(_url_para_refrescar)
    except Exception as e:
        st.error(f"No se pudo actualizar: {e}")
        return False
    st.session_state.puntos = nuevo_df
    guardar_puntos(nuevo_df)
    if not url_secreta:
        guardar_metadata(modo="url", url_fuente=_url_para_refrescar, archivo_origen="Link de OneDrive (en vivo)")
    else:
        guardar_metadata(archivo_origen="Archivo de puntos potenciales del equipo (OneDrive, en vivo)")
    return True


def _refrescar_generadores() -> bool:
    _leer_generadores_cacheado.clear()
    try:
        nuevo_df_gen = _leer_generadores_cacheado()
    except Exception as e:
        st.error(f"No se pudo actualizar: {e}")
        return False
    st.session_state.generadores = nuevo_df_gen
    guardar_generadores(nuevo_df_gen)
    return True


_hay_fuente_url = bool(url_secreta) or (metadata.get("modo") == "url" and metadata.get("url_fuente"))

# ---------------------------------------------------------------------------
# Sidebar — explicación del aplicativo, navegación entre módulos y botones
# de actualizar, para que la página principal quede limpia.
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### 📍 OXXO")
    st.markdown("**Inteligencia de Expansión**")
    st.caption("Consulta y seguimiento de puntos potenciales - Generadores")
    st.write(
        "Antes de registrar un punto potencial o un generador nuevo, "
        "revisa aquí si ya existe algo parecido cerca — así se evita "
        "trabajo duplicado en campo y en Survey123."
    )
    st.divider()
    modulo_activo = st.radio(
        "Módulo",
        ["🔁 Puntos potenciales", "🏢 Generadores"],
        key="modulo_activo_sidebar",
    )
    st.divider()
    st.markdown("**🔄 Actualizar datos**")
    if _hay_fuente_url:
        if st.button("Puntos potenciales", use_container_width=True, type="primary", key="refrescar_puente_sidebar"):
            if _refrescar_puntos_desde_url():
                st.rerun()
    else:
        st.caption(
            "Puntos potenciales: se leen del archivo del proyecto "
            "(todavía sin conexión en vivo a OneDrive configurada)."
        )
    if st.button("Generadores", use_container_width=True, type="primary", key="refrescar_generadores_sidebar"):
        if _refrescar_generadores():
            st.rerun()
    st.divider()
    if cargado_desde_secret:
        st.success(f"🔒 Conectado en vivo · {len(df)} puntos potenciales", icon="🔒")
    elif cargado_desde_bundle:
        st.success(f"✅ Cargado del proyecto · {len(df)} puntos potenciales", icon="✅")
    if metadata.get("ultima_actualizacion"):
        st.caption(f"📅 Última actualización: {metadata['ultima_actualizacion']}")

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
            <div style="color: #FFFFFF; font-size: 24px; font-weight: 700; line-height: 1.25;">
                Consulta y seguimiento de puntos potenciales - Generadores
            </div>
            <div style="color: {OXXO_NARANJA}; font-size: 14px; font-weight: 600;">
                Inteligencia de Expansión &nbsp;·&nbsp; Prototipo de práctica profesional
            </div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
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

# ---------------------------------------------------------------------------
# MÓDULO 1 · Puntos potenciales
# ---------------------------------------------------------------------------
if modulo_activo.startswith("🔁"):
    # Resumen general — total de puntos potenciales + una gráfica pequeña
    # por cada fuente (para que no salga una sola gráfica gigante). Este
    # resumen vive SOLO en Módulo 1.
    st.markdown("#### Resumen general de puntos potenciales")
    st.metric("Total de puntos potenciales (todas las fuentes)", len(df))
    resumen_fuente = (
        df["fuente"].replace("", "Sin fuente").value_counts()
        .rename_axis("Fuente").reset_index(name="Cantidad")
    )
    st.dataframe(resumen_fuente, hide_index=True, use_container_width=True)

    st.markdown("**Puntos registrados por responsable, en cada fuente**")
    cols_resumen_fuente = st.columns(2)
    for i_fuente, (fuente_resumen, color_resumen) in enumerate(FUENTE_COLOR_ICONO.items()):
        with cols_resumen_fuente[i_fuente % 2]:
            sub_fuente = df[
                (df["fuente"] == fuente_resumen) & (df["especialista"].astype(str).str.strip() != "")
            ]
            conteo_fuente = (
                sub_fuente.groupby("especialista").size().reset_index(name="cantidad")
                .sort_values("cantidad", ascending=False)
            )

            st.markdown(f"*{fuente_resumen}*")
            if conteo_fuente.empty:
                st.caption("Todavía no hay datos para graficar.")
            else:
                # Se muestran solo los 5 con más puntos, para que la
                # gráfica quede compacta — si tiene más, usa el ícono de
                # pantalla completa que trae la gráfica (arriba a la
                # derecha, al pasar el mouse) para verla más grande y sin
                # que los nombres queden cortados.
                top5_fuente = conteo_fuente.head(5)
                chart_fuente = (
                    alt.Chart(top5_fuente)
                    .mark_bar(color=_COLORES_HEX_LEYENDA.get(color_resumen, OXXO_ROJO), cornerRadiusEnd=4)
                    .encode(
                        x=alt.X("cantidad:Q", title="Puntos"),
                        y=alt.Y("especialista:N", title=None, sort="-x"),
                        tooltip=[
                            alt.Tooltip("especialista:N", title="Especialista / responsable"),
                            alt.Tooltip("cantidad:Q", title="Puntos"),
                        ],
                    )
                    .properties(height=max(90, 26 * len(top5_fuente)))
                )
                st.altair_chart(chart_fuente, use_container_width=True)
                if len(conteo_fuente) > 5:
                    st.caption(f"Mostrando los 5 con más puntos, de {len(conteo_fuente)} responsables.")

    st.divider()
    st.subheader("Puntos potenciales")
    st.write(
        "Revisa qué puntos potenciales — de especialistas, operación, "
        "terceros o inmobiliarias — están repetidos: misma coordenada, o "
        "tan cerca que probablemente son el mismo lugar."
    )

    st.markdown("#### 🔎 Revisar un punto específico")
    st.write(
        "Busca uno en particular (o pega su coordenada) para ver si ya "
        "existe algo parecido cerca — así detectas la posible duplicidad "
        "ANTES de registrarlo."
    )
    st.caption(
        "Aquí no se busca por dirección: la búsqueda de direcciones no "
        "siempre cae en el punto exacto. Si solo tienes la dirección, "
        "conviértela primero a coordenada en Google Maps (clic derecho → "
        "copiar coordenadas) y pégala aquí."
    )

    modo_busqueda = st.radio(
        "¿Cómo quieres buscar?",
        ["Por nombre", "Por coordenada"],
        horizontal=True,
        key="modo_busqueda_tab1",
        label_visibility="collapsed",
    )

    consulta_punto = None  # se llena si se elige un resultado válido

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
                        ["id", "fuente", "especialista", "ciudad", "local_identificado", "estado", "similitud_nombre"]
                    ].rename(columns={
                        "fuente": "Fuente", "especialista": "Especialista/responsable",
                        "ciudad": "Ciudad", "local_identificado": "Nombre",
                        "estado": "Estado", "similitud_nombre": "Qué tan parecido",
                    }),
                    use_container_width=True,
                    hide_index=True,
                )

                con_coords_nombre = resultado_nombre.dropna(subset=["latitud", "longitud"])
                if con_coords_nombre.empty:
                    st.caption(
                        "Ninguno de estos resultados tiene coordenadas registradas, "
                        "así que no se puede mostrar el mapa ni Street View."
                    )
                else:
                    opciones_nombre = {
                        f"{row.local_identificado} · {row.fuente}": row.id
                        for row in con_coords_nombre.itertuples()
                    }
                    etiqueta_nombre_elegida = st.selectbox(
                        "Ver ese punto en el mapa y revisar si tiene algo cerca:",
                        list(opciones_nombre.keys()),
                        key="preview_resultado_nombre",
                    )
                    id_elegido = opciones_nombre[etiqueta_nombre_elegida]
                    fila_elegida_nombre = con_coords_nombre[con_coords_nombre["id"] == id_elegido].iloc[0]
                    consulta_punto = {
                        "lat": fila_elegida_nombre["latitud"], "lon": fila_elegida_nombre["longitud"],
                        "etiqueta": fila_elegida_nombre["local_identificado"],
                    }

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
        cercanos = detectar_coincidencias(df, lat_c, lon_c, consulta_punto.get("etiqueta", ""))

        st.divider()

        st.write("📍 **Vista de calle del lugar consultado:**")
        col_mapa, col_calle = st.columns(2)
        with col_mapa:
            st.caption("Mapa")
            components.iframe(url_mapa_embed(lat_c, lon_c), height=340)
        with col_calle:
            st.caption("Street View (vista a nivel de calle)")
            components.iframe(url_streetview_embed(lat_c, lon_c), height=340)
        st.caption(
            "Si el punto está en una zona sin cobertura de Street View, "
            "Google muestra ahí mismo un aviso de que no hay imagen "
            "disponible."
        )

        st.write("**Ese punto en el mapa general (queda en rojo):**")
        renderizar_mapa_general(
            df, fuentes_activas=list(FUENTE_COLOR_ICONO.keys()),
            punto_resaltado=(lat_c, lon_c, consulta_punto["etiqueta"]),
            key="mapa_revisar_punto",
        )
        st.markdown(tabla_leyenda_fuentes_html(incluir_resaltado=True), unsafe_allow_html=True)

        if not cercanos.empty:
            st.warning(
                f"⚠️ Posible duplicidad — se encontraron {len(cercanos)} punto(s) "
                f"cercano(s) (< {UMBRAL_DUPLICIDAD_M:.0f} m) o con nombre parecido.",
                icon="⚠️",
            )
            for _, row in cercanos.iterrows():
                detalle_distancia = (
                    f"A {row['distancia_m']:.0f} m de tu ubicación"
                    if row["distancia_m"] != float("inf")
                    else "Sin coordenadas para comparar distancia"
                )
                registrado_por = f"Registrado por <b>{row['especialista'] or '—'}</b>"
                if row.get("practicante"):
                    registrado_por += f" · practicante <b>{row['practicante']}</b>"
                filas_tarjeta = [
                    ("🗂️", f"Fuente: {row['fuente']}"),
                    ("👤", registrado_por),
                    ("📅", f"Fecha de registro: {row['fecha_registro']}"),
                    ("📍", f"{detalle_distancia} · {row['ciudad']}"),
                ]
                st.markdown(
                    tarjeta_resultado_html(
                        titulo=row["local_identificado"],
                        badge_html=badge_estado_html(row.get("estado", "")),
                        filas=filas_tarjeta,
                        nota=f"Por qué se marca como posible duplicado: {row['coincide_por']}",
                    ),
                    unsafe_allow_html=True,
                )
        else:
            st.success(
                "✅ No se encontraron coincidencias cercanas registradas en "
                "esa ubicación — puedes continuar con el registro.",
                icon="✅",
            )

    st.divider()
    st.markdown("#### 🗺️ Mapa general")
    st.caption(
        "Todos los puntos que llegan por las 4 fuentes del Módulo 1 "
        "(especialistas, operación, terceros e inmobiliaria). Aquí NO se "
        "muestran generadores — eso vive solo en el Módulo 2."
    )

    st.markdown("**🔍 Ubicar por nombre, dirección o coordenada**")
    modo_busqueda_mapa = st.radio(
        "Ubicar en el mapa por…",
        ["Nombre (punto ya registrado)", "Dirección o coordenada"],
        horizontal=True,
        key="modo_busqueda_mapa_general",
        label_visibility="collapsed",
    )
    punto_resaltado_mapa = None
    if modo_busqueda_mapa.startswith("Nombre"):
        nombre_mapa = st.text_input("Nombre a ubicar", key="nombre_ubicar_mapa", placeholder="Ej. Toberin 168")
        if nombre_mapa:
            encontrados_mapa = buscar_por_nombre(df, nombre_mapa)
            con_coords_mapa = encontrados_mapa.dropna(subset=["latitud", "longitud"])
            if con_coords_mapa.empty:
                st.caption("No se encontró ese nombre (o no tiene coordenadas registradas).")
            else:
                fila_mapa = con_coords_mapa.iloc[0]
                punto_resaltado_mapa = (fila_mapa["latitud"], fila_mapa["longitud"], fila_mapa["local_identificado"])
    else:
        texto_lugar = st.text_input(
            "Dirección o coordenada", key="texto_ubicar_mapa",
            placeholder="Ej. Carrera 15 # 93-60, Bogotá   ó   4.6975, -74.0922",
        )
        if st.button("Ubicar", key="btn_ubicar_mapa"):
            with st.spinner("Buscando..."):
                resultado_lugar = buscar_lugar(texto_lugar)
            if resultado_lugar is None:
                st.session_state["error_ubicar_mapa"] = True
                st.session_state.pop("punto_ubicado_mapa", None)
            else:
                lat_u, lon_u, etq_u = resultado_lugar
                st.session_state["punto_ubicado_mapa"] = {"lat": lat_u, "lon": lon_u, "etiqueta": etq_u}
                st.session_state["error_ubicar_mapa"] = False
        if st.session_state.get("error_ubicar_mapa"):
            st.error(
                "No se encontró esa dirección o coordenada. La búsqueda por "
                "dirección usa un servicio gratuito de mapas (OpenStreetMap) "
                "que a veces no tiene cobertura exacta en Colombia — si el "
                "resultado no cae en el lugar correcto, prueba pegando la "
                "coordenada exacta desde Google Maps."
            )
        p_ubicado = st.session_state.get("punto_ubicado_mapa")
        if p_ubicado:
            punto_resaltado_mapa = (p_ubicado["lat"], p_ubicado["lon"], p_ubicado["etiqueta"])

    if punto_resaltado_mapa is not None:
        col_mapa_u, col_calle_u = st.columns(2)
        with col_mapa_u:
            st.caption("Mapa")
            components.iframe(url_mapa_embed(punto_resaltado_mapa[0], punto_resaltado_mapa[1]), height=280)
        with col_calle_u:
            st.caption("Street View")
            components.iframe(url_streetview_embed(punto_resaltado_mapa[0], punto_resaltado_mapa[1]), height=280)

    capas_generales = st.multiselect(
        "Capas a mostrar",
        list(FUENTE_COLOR_ICONO.keys()),
        default=list(FUENTE_COLOR_ICONO.keys()),
        key="capas_mapa_general",
    )
    renderizar_mapa_general(
        df, fuentes_activas=capas_generales,
        punto_resaltado=punto_resaltado_mapa,
        key="mapa_general_tab1",
    )
    st.markdown(
        tabla_leyenda_fuentes_html(incluir_resaltado=bool(punto_resaltado_mapa)),
        unsafe_allow_html=True,
    )

    st.markdown("**🔎 Ver info y Street View de un punto del mapa**")
    st.caption(
        "Elige un punto de la lista para ver toda su información y su "
        "Street View — es la forma más confiable de 'pararte' en un punto "
        "del mapa (el clic directo sobre el mapa no es confiable en todas "
        "las versiones de Streamlit)."
    )
    df_en_mapa = df[df["fuente"].isin(capas_generales)].dropna(subset=["latitud", "longitud"])
    if df_en_mapa.empty:
        st.caption("No hay puntos con coordenadas en las capas seleccionadas.")
    else:
        opciones_info = {"— Ninguno —": None}
        for row in df_en_mapa.itertuples():
            opciones_info[f"{row.local_identificado} · {row.fuente}"] = row.id
        elegido_info = st.selectbox("Elige un punto", list(opciones_info.keys()), key="selector_info_mapa_tab1")
        if opciones_info[elegido_info] is not None:
            fila_info = df_en_mapa[df_en_mapa["id"] == opciones_info[elegido_info]].iloc[0]
            col_info_m1, col_calle_m1 = st.columns([1, 1])
            with col_info_m1:
                st.markdown(
                    tarjeta_resultado_html(
                        titulo=fila_info["local_identificado"],
                        badge_html=badge_estado_html(fila_info.get("estado", "")),
                        filas=[
                            ("🗂️", f"Fuente: {fila_info['fuente']}"),
                            ("👤", f"Responsable: {fila_info.get('especialista', '') or '—'}"),
                            ("📅", f"Fecha de registro: {fila_info.get('fecha_registro', '') or '—'}"),
                            ("📍", f"Coordenadas: {fila_info['latitud']:.6f}, {fila_info['longitud']:.6f}"),
                        ],
                    ),
                    unsafe_allow_html=True,
                )
            with col_calle_m1:
                st.caption("Street View")
                components.iframe(url_streetview_embed(fila_info["latitud"], fila_info["longitud"]), height=300)

    st.divider()
    st.markdown("#### 📋 Posibles duplicados")
    st.caption(
        "Compara cada punto contra los demás, sin importar de cuál de las "
        "4 fuentes venga. Se marca como posible duplicado si: la "
        "coordenada es casi exacta (≤ 15 m, sin importar el nombre), o "
        "están cerca (≤ " + f"{UMBRAL_DUPLICIDAD_M:.0f}" + " m) Y el nombre se "
        "parece, o tienen exactamente el mismo nombre en cualquier "
        "ubicación."
    )
    duplicados_m1 = detectar_duplicados_potenciales(df)
    if duplicados_m1.empty:
        st.success("No se encontraron posibles duplicados.")
    else:
        st.warning(f"Se encontraron {len(duplicados_m1)} posible(s) duplicado(s):")
        tabla_dup_m1 = duplicados_m1.copy()
        tabla_dup_m1["coordenada"] = tabla_dup_m1.apply(
            lambda r: f"{r['latitud']:.15f}, {r['longitud']:.15f}", axis=1
        )
        evento_dup_m1 = st.dataframe(
            tabla_dup_m1[["nombre", "nombre_duplicado", "coordenada", "motivo"]].rename(columns={
                "nombre": "Nombre", "nombre_duplicado": "Posible duplicado",
                "coordenada": "Coordenada", "motivo": "Motivo de duplicado",
            }),
            use_container_width=True, hide_index=True,
            on_select="rerun", selection_mode="single-row", key="tabla_duplicados_m1",
        )
        filas_sel_m1 = list(evento_dup_m1.selection.rows) if evento_dup_m1 is not None else []
        if filas_sel_m1:
            par = duplicados_m1.iloc[filas_sel_m1[0]]

            def _info_extra_punto(id_punto):
                # Trae toda la info del punto (especialista, cuándo se
                # solicitó, practicante, etc.) para mostrarla al pasar el
                # mouse sobre el pin resaltado en el mapa de abajo.
                coincidencias_id = df[df["id"] == id_punto]
                if coincidencias_id.empty:
                    return ""
                f = coincidencias_id.iloc[0]
                return (
                    f"Fuente: {f.get('fuente', '') or '—'}"
                    f"\nEspecialista/responsable: {f.get('especialista', '') or '—'}"
                    f"\nCuándo se solicitó: {f.get('fecha_registro', '') or '—'}"
                    f"\nPracticante: {f.get('practicante', '') or '—'}"
                    f"\nEstado: {f.get('estado', '') or '—'}"
                )

            st.markdown(
                f"**Mostrando en el mapa SOLO estos dos: '{par['nombre']}' y su "
                f"posible duplicado '{par['nombre_duplicado']}'** — pasa el mouse "
                "sobre cada pin para ver toda su información."
            )
            renderizar_mapa_general(
                df, fuentes_activas=[],
                punto_resaltado=[
                    (par["latitud"], par["longitud"], par["nombre"], _info_extra_punto(par["id"])),
                    (
                        par["latitud_duplicado"], par["longitud_duplicado"], par["nombre_duplicado"],
                        _info_extra_punto(par["id_duplicado"]),
                    ),
                ],
                key="mapa_duplicado_m1_seleccionado",
            )

    st.divider()
    st.markdown("#### 🏠 Inmobiliarias — evaluación de puntos")
    st.caption(
        "Primer borrador funcional del módulo de inmobiliarias — todavía "
        "no llegan puntos reales en el Excel, así que por ahora se prueba "
        "subiendo o diligenciando la información a mano. Apenas llegue un "
        "punto real, se ajusta la evaluación con Alisson."
    )

    with st.expander("📎 Adjuntar archivo o foto de referencia (opcional)"):
        archivo_inmo = st.file_uploader(
            "Excel/imagen con la info del punto (foto de fachada, ficha, etc.)",
            type=["xlsx", "csv", "png", "jpg", "jpeg"], key="archivo_inmobiliaria",
        )
        if archivo_inmo is not None:
            st.success(f"Archivo '{archivo_inmo.name}' recibido — puedes usarlo como referencia al llenar el formulario de abajo.")
            if archivo_inmo.type and archivo_inmo.type.startswith("image"):
                st.image(archivo_inmo, caption="Foto de fachada", width=320)

    with st.form("form_inmobiliaria"):
        col_nombre_inmo, col_ciudad_inmo = st.columns(2)
        nombre_inmo = col_nombre_inmo.text_input("Nombre del punto")
        ciudad_inmo = col_ciudad_inmo.text_input("Ciudad")
        direccion_inmo = st.text_input("Dirección")
        foto_inmo = st.file_uploader("Foto de fachada (opcional)", type=["png", "jpg", "jpeg"], key="foto_fachada_inmo")

        st.markdown("**Variables de evaluación**")
        respuestas_inmo = {}
        cols_criterios = st.columns(2)
        for i, criterio in enumerate(CRITERIOS_INMOBILIARIA):
            with cols_criterios[i % 2]:
                respuestas_inmo[criterio["clave"]] = st.selectbox(
                    criterio["etiqueta"], list(criterio["opciones"].keys()),
                    key=f"inmo_{criterio['clave']}",
                )

        razones_manual_descarte = st.multiselect(
            "Razones de descarte adicionales (elige si aplica)",
            RAZONES_DESCARTE_INMOBILIARIA, key="inmo_razones_descarte_manual",
        )
        notas_inmo = st.text_area("Notas / comentarios adicionales", key="inmo_notas")
        enviado_inmo = st.form_submit_button("📊 Generar informe de evaluación", type="primary")

    if enviado_inmo:
        resultado_inmo = evaluar_punto_inmobiliario(respuestas_inmo)
        st.session_state["resultado_evaluacion_inmo"] = {
            "nombre": nombre_inmo, "direccion": direccion_inmo, "ciudad": ciudad_inmo,
            "resultado": resultado_inmo,
            "razones_manual_descarte": razones_manual_descarte,
            "notas": notas_inmo,
            "foto": foto_inmo.getvalue() if foto_inmo is not None else None,
        }

    informe_inmo = st.session_state.get("resultado_evaluacion_inmo")
    if informe_inmo:
        r = informe_inmo["resultado"]
        color_nivel = {"Alto": "badge-aprobado", "Medio": "badge-pendiente", "Bajo": "badge-descartado"}[r["nivel"]]
        razones_en_contra_todas = r["razones_en_contra"] + informe_inmo["razones_manual_descarte"]
        st.markdown(
            '<div class="tarjeta-resultado"><div class="tarjeta-header">'
            f'<span class="titulo">{informe_inmo["nombre"] or "(sin nombre)"}</span>'
            f'<span class="badge-estado {color_nivel}">Nivel {r["nivel"]} · {r["porcentaje"]:.0f}%</span>'
            '</div>'
            f'<div class="fila">📍 {informe_inmo["direccion"] or "—"}, {informe_inmo["ciudad"] or "—"}</div>'
            f'<div class="fila">✅ Razones a favor: {", ".join(r["razones_a_favor"]) or "—"}</div>'
            f'<div class="fila">⚠️ Razones en contra: {", ".join(razones_en_contra_todas) or "—"}</div>'
            + (f'<div class="fila nota">📝 {informe_inmo["notas"]}</div>' if informe_inmo["notas"] else "")
            + '</div>',
            unsafe_allow_html=True,
        )
        if informe_inmo["foto"]:
            st.image(informe_inmo["foto"], caption="Foto de fachada", width=360)
        st.markdown("**Detalle de la evaluación:**")
        st.dataframe(
            pd.DataFrame(r["detalle"]).rename(columns={
                "criterio": "Criterio", "respuesta": "Respuesta", "puntos": "Puntos", "maximo": "Máximo",
            }),
            use_container_width=True, hide_index=True,
        )
        st.caption(f"Puntaje total: {r['puntaje_total']} de {r['puntaje_maximo']} ({r['porcentaje']:.1f}%).")

# ---------------------------------------------------------------------------
# MÓDULO 2 · Generadores
# ---------------------------------------------------------------------------
else:
    # Esta gráfica va primero (antes que todo lo demás) — a diferencia del
    # resumen de Módulo 1, esta vive SOLO en Módulo 2.
    st.markdown("#### 📊 Generadores registrados por persona (localizador)")

    df_gen_solo = df_generadores.copy()
    if "tipo_levantamiento" in df_gen_solo.columns:
        df_gen_solo = df_gen_solo[
            df_gen_solo["tipo_levantamiento"].astype(str).str.strip().str.lower() != "punto potencial"
        ]

    # Quién hizo cada registro: se prefiere 'localizador' (nombre que la
    # persona escribe en el formulario de Survey123) sobre 'creador' (la
    # cuenta de inicio de sesión, que puede ser genérica o compartida
    # entre varias personas).
    df_gen_solo["quien"] = df_gen_solo.get("localizador", "").astype(str).str.strip()
    if "creador" in df_gen_solo.columns:
        df_gen_solo["quien"] = df_gen_solo["quien"].where(
            df_gen_solo["quien"] != "", df_gen_solo["creador"].astype(str).str.strip()
        )

    por_creador = (
        df_gen_solo[df_gen_solo["quien"].astype(str).str.strip() != ""]
        .groupby("quien").size().reset_index(name="cantidad")
        .sort_values("cantidad", ascending=False)
    )
    if por_creador.empty:
        st.info("No hay datos de quién registró cada uno todavía.")
    else:
        chart_creador = (
            alt.Chart(por_creador)
            .mark_bar(color=OXXO_ROJO, cornerRadiusEnd=4)
            .encode(
                x=alt.X("cantidad:Q", title="Generadores registrados"),
                y=alt.Y("quien:N", title=None, sort="-x"),
                tooltip=[
                    alt.Tooltip("quien:N", title="Persona (localizador)"),
                    alt.Tooltip("cantidad:Q", title="Generadores"),
                ],
            )
            .properties(height=max(160, 28 * len(por_creador)))
        )
        st.altair_chart(chart_creador, use_container_width=True)

    st.divider()
    st.subheader("Generadores")
    st.write(
        "Cuando el radio de recolección (300 m) de dos puntos potenciales "
        "distintos se superpone, el mismo generador físico (por ejemplo, "
        "las oficinas de un banco) puede quedar registrado dos veces en "
        "Survey123 — una por cada punto — sin que nadie lo note. Consulta "
        "aquí antes de registrar uno nuevo en campo."
    )

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
            "'🔄 Generadores' en el menú de la izquierda para traerlos."
        )
    else:
        st.caption(f"📡 Conectado en vivo a la capa de Survey123 · {len(df_generadores)} registros cargados")

        alertas_gen = generadores_agrupados[generadores_agrupados["cantidad_registros"] > 1].reset_index(drop=True)

        if "tipo_levantamiento" in df_generadores.columns:
            es_potencial = df_generadores["tipo_levantamiento"].astype(str).str.strip().str.lower() == "punto potencial"
            registros_generador = int((~es_potencial).sum())
            registros_punto_potencial = int(es_potencial.sum())
        else:
            registros_generador = len(df_generadores)
            registros_punto_potencial = 0

        with st.container(border=True):
            mc1, mc2, mc3, mc4 = st.columns(4)
            mc1.metric("📋 Registros en Survey123", len(df_generadores))
            mc2.metric("🏢 Generadores (únicos)", len(generadores_agrupados))
            mc3.metric("📍 Puntos potenciales", registros_punto_potencial)
            mc4.metric("⚠️ Con duplicidad", len(alertas_gen))
        st.caption(
            f"De los {len(df_generadores)} registros: {registros_generador} son tipo "
            f"'Generador' y {registros_punto_potencial} son tipo 'Punto potencial' "
            "(misma encuesta, pero no es un generador — se muestran en gris en el "
            "mapa, solo aquí en Módulo 2, informativos)."
        )

        st.markdown("#### 🗺️ Mapa de generadores")
        modo_mapa_gen = st.radio(
            "¿Cuáles quieres ver?",
            ["Potenciales", "Generadores", "Repetidos", "Todos"],
            index=3,
            horizontal=True,
            key="modo_mapa_generadores",
        )

        gen_ordenados = generadores_agrupados.sort_values("nombre_generador").reset_index(drop=True)
        opciones_todos = ["— Ninguno —"] + [
            f"{row.nombre_generador or '(sin nombre)'}"
            + (f" · repetido {row.cantidad_registros}x" if row.cantidad_registros > 1 else "")
            for row in gen_ordenados.itertuples()
        ]
        etiqueta_elegida_gen = st.selectbox(
            "🔎 Busca un generador para ver toda su información (empieza a escribir el nombre):",
            opciones_todos,
            key="generador_resaltado_tab2",
        )

        punto_resaltado_gen = None
        fila_elegida = None
        if etiqueta_elegida_gen != "— Ninguno —":
            idx_elegido = opciones_todos.index(etiqueta_elegida_gen) - 1
            fila_elegida = gen_ordenados.iloc[idx_elegido]
            punto_resaltado_gen = (
                fila_elegida["latitud"], fila_elegida["longitud"], fila_elegida["nombre_generador"],
            )

        renderizar_mapa_generadores(
            generadores_agrupados, modo_mapa_gen, key="mapa_generadores_tab2",
            punto_resaltado=punto_resaltado_gen,
            df_potenciales_survey=df_potenciales_survey,
        )

        if fila_elegida is not None:
            es_duplicado = bool(fila_elegida["duplicado_por"])
            filas_card_gen = [
                ("🏷️", f"Tipo: {fila_elegida['tipo_generador'] or '—'}"),
                ("👤", f"Registrado por: {fila_elegida['registrado_por'] or '—'}"),
                ("📍", f"Coordenadas: {fila_elegida['latitud']:.15f}, {fila_elegida['longitud']:.15f}"),
                ("📋", f"Registros agrupados: {fila_elegida['cantidad_registros']}"),
                ("🔗", f"Puntos potenciales asociados: {fila_elegida['puntos_asociados'] or '—'}"),
            ]
            if es_duplicado:
                filas_card_gen.append((
                    "⚠️",
                    f"Se repite con: <b>{fila_elegida['nombre_duplicado']}</b> "
                    f"(mismo punto en el mapa · {fila_elegida['latitud']:.15f}, {fila_elegida['longitud']:.15f})",
                ))
            st.markdown(
                tarjeta_resultado_html(
                    titulo=fila_elegida["nombre_generador"] or "(sin nombre)",
                    badge_html=(
                        f'<span class="badge-estado badge-descartado">⚠️ Duplicado — {fila_elegida["duplicado_por"]}</span>'
                        if es_duplicado
                        else '<span class="badge-estado badge-aprobado">Único</span>'
                    ),
                    filas=filas_card_gen,
                ),
                unsafe_allow_html=True,
            )
            col_mapa_gen_sel, col_calle_gen_sel = st.columns(2)
            with col_mapa_gen_sel:
                st.caption("Mapa")
                components.iframe(url_mapa_embed(fila_elegida["latitud"], fila_elegida["longitud"]), height=380)
            with col_calle_gen_sel:
                st.caption("Street View")
                components.iframe(url_streetview_embed(fila_elegida["latitud"], fila_elegida["longitud"]), height=380)

        st.markdown("#### ⚠️ Alertas de duplicidad")
        st.caption(
            "Cada fila de aquí abajo es un generador que quedó registrado "
            "MÁS DE UNA VEZ. 'Nombre con el que se repite' muestra con "
            "cuál otro nombre quedó agrupado. 'Cómo se detectó' dice por "
            "qué se considera duplicado: **'Coordenada casi exacta'** = "
            "quedó marcado prácticamente en el mismo punto del mapa "
            "(≤ 15 m), sin importar el nombre; **'Cercanía + nombre "
            "parecido'** = está dentro del radio de recolección (300 m) Y "
            "el nombre se parece. Selecciona una fila para verla resaltada "
            "en el mapa."
        )
        if alertas_gen.empty:
            st.success("No hay generadores repetidos por ahora.")
        else:
            st.warning(f"{len(alertas_gen)} generador(es) parecen estar registrados más de una vez:")
            tabla_alertas = alertas_gen.copy()
            tabla_alertas["Latitud"] = tabla_alertas["latitud"].map(lambda v: f"{v:.15f}")
            tabla_alertas["Longitud"] = tabla_alertas["longitud"].map(lambda v: f"{v:.15f}")
            evento_alertas = st.dataframe(
                tabla_alertas[[
                    "nombre_generador", "nombre_duplicado", "tipo_generador", "duplicado_por",
                    "Latitud", "Longitud", "registrado_por", "puntos_asociados",
                ]].rename(columns={
                    "nombre_generador": "Generador repetido",
                    "nombre_duplicado": "Nombre con el que se repite",
                    "tipo_generador": "Tipo",
                    "duplicado_por": "Cómo se detectó",
                    "registrado_por": "Registrado por",
                    "puntos_asociados": "Puntos potenciales asociados",
                }),
                use_container_width=True, hide_index=True,
                on_select="rerun", selection_mode="single-row", key="tabla_alertas_generadores",
            )
            filas_sel_gen = list(evento_alertas.selection.rows) if evento_alertas is not None else []
            if filas_sel_gen:
                parg = alertas_gen.iloc[filas_sel_gen[0]]
                st.markdown(
                    f"**Mostrando en el mapa SOLO este: '{parg['nombre_generador']}' "
                    f"(repetido con '{parg['nombre_duplicado']}')**"
                )
                # registros_originales trae la coordenada REAL de cada registro
                # crudo que quedó agrupado como este generador (cada uno puede
                # estar unos metros distinto en Survey123) — así se ven todos
                # los puntos duplicados, no solo uno representativo.
                registros_originales_grupo = parg.get("registros_originales") or []
                if registros_originales_grupo:
                    resaltados_gen = [
                        (
                            r["latitud"], r["longitud"], r["nombre"],
                            f"Registrado por: {r.get('quien', '') or '—'}"
                            f"\nCómo se detectó: {parg['duplicado_por']}",
                        )
                        for r in registros_originales_grupo
                    ]
                else:
                    # Respaldo por si el grupo no trae registros_originales
                    # (por ejemplo datos viejos en caché) — se muestra al menos
                    # el punto representativo, como antes.
                    resaltados_gen = (
                        parg["latitud"], parg["longitud"], parg["nombre_generador"],
                        f"Se repite con: {parg['nombre_duplicado']}\nCómo se detectó: {parg['duplicado_por']}",
                    )
                # mostrar=None: no dibuja la capa de "Repetidos" completa (todos
                # los demás generadores repetidos de Bogotá) — solo los pines
                # resaltados de este grupo, para que no se llene el mapa de
                # puntos que no tienen que ver con la fila que se seleccionó.
                renderizar_mapa_generadores(
                    generadores_agrupados, None, key="mapa_generadores_seleccionado_alerta",
                    punto_resaltado=resaltados_gen,
                    df_potenciales_survey=None,
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
        st.caption(
            "La búsqueda por dirección depende de un servicio gratuito de "
            "mapas (OpenStreetMap) que a veces no tiene cobertura exacta "
            "en Colombia. Si el resultado no cae en el lugar correcto, usa "
            "'Por coordenada' pegando la coordenada exacta desde Google Maps."
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
                tabla_coinc_gen = coincidencias_gen.copy()
                tabla_coinc_gen["Latitud"] = tabla_coinc_gen["latitud"].map(lambda v: f"{v:.15f}")
                tabla_coinc_gen["Longitud"] = tabla_coinc_gen["longitud"].map(lambda v: f"{v:.15f}")
                st.dataframe(
                    tabla_coinc_gen[[
                        "nombre_generador", "nombre_punto_potencial", "tipo_generador",
                        "distancia_m", "Latitud", "Longitud", "localizador",
                    ]].rename(columns={
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
