"""
Aplicativo para la Consulta y Seguimiento de Puntos Potenciales
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
    FUENTE_COLOR_ICONO,
    HOJA_TIENDAS_DEFECTO,
    UMBRAL_DUPLICIDAD_M,
    buscar_coordenada_por_direccion,
    buscar_por_nombre,
    cargar_puntos,
    detectar_coincidencias,
    detectar_duplicados_potenciales,
    guardar_puntos,
    leer_fuentes_modulo1,
    leer_fuentes_modulo1_desde_url,
    leer_tiendas_desde_url,
    parsear_coordenada_pegada,
    tiendas_cercanas,
)
from mapa_html import construir_html_mapa
from zonas import (
    SIN_ASIGNAR,
    buscar_direccion,
    colores_por_grupo,
    leer_jefes_regionales,
    interpretar_zona,
    leer_zonas_kml,
    responsables_probables,
    texto_especialista,
    tiendas_mas_cercanas,
    unir_jefes_a_tiendas,
    zonas_de_punto,
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
# Inmobiliaria).
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


def _capa_pines(
    d: pd.DataFrame, color_key: str, size: int = TAMANO_PIN_PX, desplazamientos=None,
) -> pdk.Layer:
    """
    Arma una capa de pines (ícono en forma de gota, como en Google Maps)
    para el color dado. color_key es una de las claves de iconos.py:
    morado, azul_claro, rosado, verde, naranja, rojo, azul_repetido, gris.

    `desplazamientos` (opcional) es una lista [dx, dy] en PIXELES, una por
    fila de `d` — se usa para abrir en abanico los pines que caen en el
    mismo lugar, así ninguno queda tapado por otro.
    """
    d = d.copy()
    d["icon_data"] = [icon_data(color_key, size)] * len(d)
    extra = {}
    if desplazamientos is not None:
        d["desplazamiento"] = list(desplazamientos)
        extra["get_pixel_offset"] = "desplazamiento"
    return pdk.Layer(
        "IconLayer", data=d, get_position="[longitud, latitud]",
        get_icon="icon_data", get_size=size, size_units="pixels",
        size_min_pixels=max(14, size - 10), size_max_pixels=size + 16,
        pickable=True, **extra,
    )


def _capa_texto_resaltados(resaltados, desplazamientos=None):
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
    d["desplazamiento"] = [
        [(desplazamientos[i][0] if desplazamientos else 0), -26] for i in range(len(resaltados))
    ]
    # Nota: no se fijan get_text_anchor / get_alignment_baseline a mano —
    # pydeck convierte cualquier string de un prop "get_*" en un accesor
    # por fila (para leer columnas de los datos), así que un valor
    # constante como "middle" terminaría interpretado como el nombre de
    # una columna en vez de como texto fijo. Los valores por defecto de
    # TextLayer (centrado) ya son razonables sin tocarlos.
    return pdk.Layer(
        "TextLayer", data=d, get_position="[longitud, latitud]",
        get_text="texto", get_size=15, get_color=[20, 20, 20, 255],
        get_pixel_offset="desplazamiento",
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
    """Arma el tooltip (texto, al pasar el mouse) para un punto resaltado, incluyendo la info extra si se dio."""
    texto = f"🔎 {item[2]}"
    if len(item) > 3 and item[3]:
        texto = texto + "\n" + str(item[3])
    return texto


def _celda_tooltip(d: pd.DataFrame, columna: str) -> pd.Series:
    """Columna de texto lista para el tooltip: vacíos como '—'."""
    if columna not in d.columns:
        return pd.Series(["—"] * len(d), index=d.index)
    return d[columna].fillna("").astype(str).str.strip().replace("", "—")


def _columna_tooltip_fuente(d: pd.DataFrame) -> pd.Series:
    """Tooltip con toda la info del punto: nombre, fuente, responsable, estado, fecha y ciudad."""
    texto = "📍 " + _celda_tooltip(d, "local_identificado")
    texto = texto + "\nFuente: " + _celda_tooltip(d, "fuente")
    texto = texto + "\nResponsable: " + _celda_tooltip(d, "especialista")
    if "practicante" in d.columns:
        texto = texto + "\nPracticante: " + _celda_tooltip(d, "practicante")
    texto = texto + "\nEstado: " + _celda_tooltip(d, "estado")
    texto = texto + "\nFecha de registro: " + _celda_tooltip(d, "fecha_registro")
    texto = texto + "\nCiudad: " + _celda_tooltip(d, "ciudad")
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


# Cuando varios puntos caen en el MISMO lugar (por ejemplo, uno de Operación
# justo encima de uno de Especialistas), el de arriba tapa a los demás. Para
# que todos se vean, esos pines se abren en abanico, uno al lado del otro.
# Una "celda" de 4 decimales equivale a ~11 m: lo que caiga dentro cuenta
# como "el mismo lugar".
CELDA_APILADO_DECIMALES = 4
ESPACIO_ENTRE_APILADOS_PX = 26

def _clave_celda(lat, lon):
    return (
        round(float(lat), CELDA_APILADO_DECIMALES),
        round(float(lon), CELDA_APILADO_DECIMALES),
    )


COLUMNAS_APILADOS = ["Cuántos", "Fuentes", "Puntos en ese lugar", "Coordenada"]
_COLUMNAS_APILADOS_TODAS = COLUMNAS_APILADOS + ["_ids", "_lat", "_lon"]


def detectar_apilados(df, fuentes_activas) -> pd.DataFrame:
    """
    Lugares donde hay MÁS DE UN punto prácticamente en el mismo sitio (≈ 11 m),
    sin importar de qué fuente sean — para avisar cuando, por ejemplo, un
    punto de Operación quedó encima de uno de Especialistas.
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=_COLUMNAS_APILADOS_TODAS)
    base = df[df["fuente"].isin(fuentes_activas)].dropna(subset=["latitud", "longitud"]).copy()
    if base.empty:
        return pd.DataFrame(columns=_COLUMNAS_APILADOS_TODAS)
    base["_celda"] = [_clave_celda(a, b) for a, b in zip(base["latitud"], base["longitud"])]
    filas = []
    for _, g in base.groupby("_celda"):
        if len(g) < 2:
            continue
        filas.append({
            "Cuántos": len(g),
            "Fuentes": ", ".join(sorted(g["fuente"].astype(str).unique())),
            "Puntos en ese lugar": " · ".join(
                f"{n} ({f})" for n, f in zip(g["local_identificado"].astype(str), g["fuente"].astype(str))
            ),
            "Coordenada": f"{g['latitud'].mean():.6f}, {g['longitud'].mean():.6f}",
            "_ids": list(g["id"]),
            "_lat": float(g["latitud"].mean()),
            "_lon": float(g["longitud"].mean()),
        })
    if not filas:
        return pd.DataFrame(columns=_COLUMNAS_APILADOS_TODAS)
    return pd.DataFrame(filas).sort_values("Cuántos", ascending=False).reset_index(drop=True)


def _solo_cerca(tabla, lat, lon, radio_m):
    """Filas de `tabla` (con columnas latitud/longitud) a `radio_m` metros o menos de (lat, lon)."""
    import numpy as np
    if tabla is None or len(tabla) == 0:
        return tabla
    la = pd.to_numeric(tabla["latitud"], errors="coerce").to_numpy(dtype=float)
    lo = pd.to_numeric(tabla["longitud"], errors="coerce").to_numpy(dtype=float)
    p1, p2 = np.radians(la), np.radians(lat)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lon - lo) / 2) ** 2
    dist = 2 * 6371000.0 * np.arcsin(np.sqrt(a))
    return tabla[np.nan_to_num(dist, nan=1e12) <= radio_m]


def renderizar_mapa_general(
    df, fuentes_activas, punto_resaltado=None, key="mapa_general", altura=620,
    centro=None, solo_ids=None, df_tiendas=None, mostrar_capas_vacias=True, radio_cerca_m=None,
):
    """
    Dibuja el mapa combinado del Módulo 1 como una página de mapa propia
    (ver mapa_html.py): una capa por cada fuente (Especialistas=morado,
    Operación=azul, Terceros=rosado, Inmobiliaria=verde, Localizadores=
    naranja) y, si se dan, las tiendas OXXO (abiertas, en expansión, firmadas, en obra, cerradas).

    - punto_resaltado: un (lat, lon, etiqueta[, info]) o una lista de ellos;
      se dibujan en ROJO, encima de todo.
    - Los pines que caen en el mismo lugar se abren en abanico, y la tarjeta
      de información siempre queda dentro del marco del mapa.
    - Las capas se prenden y apagan dentro del propio mapa.
    - radio_cerca_m: si se da y hay un punto resaltado, el mapa solo muestra
      los puntos y tiendas a esa distancia (en metros) o menos del punto buscado.
    """
    resaltados = _resaltados_a_lista(punto_resaltado)

    puntos = pd.DataFrame()
    if df is not None and not df.empty:
        puntos = df[df["fuente"].isin(fuentes_activas)]
        if solo_ids is not None:
            puntos = puntos[puntos["id"].isin(solo_ids)]

    if radio_cerca_m and resaltados:
        puntos = _solo_cerca(puntos, resaltados[0][0], resaltados[0][1], radio_cerca_m)
        df_tiendas = _solo_cerca(df_tiendas, resaltados[0][0], resaltados[0][1], radio_cerca_m)

    colores_fuente = dict(FUENTE_COLOR_ICONO)
    if not mostrar_capas_vacias:
        presentes = set(puntos["fuente"]) if len(puntos) else set()
        colores_fuente = {f: c for f, c in colores_fuente.items() if f in presentes}

    html_mapa = construir_html_mapa(
        puntos, colores_fuente, _COLORES_HEX_LEYENDA,
        resaltados=resaltados, tiendas=df_tiendas, centro=centro, altura=altura,
    )
    components.html(html_mapa, height=altura + 4, scrolling=False)


# Cómo se nombra cada estado de tienda en los textos de la app.
_NOMBRE_ESTADO_TIENDA = {"Abierta": "abierta", "Expansión": "en expansión", "Firmada": "firmada", "Obra": "en obra", "Cerrada": "cerrada"}
_PLURAL_ESTADO_TIENDA = {"Abierta": "abiertas", "Expansión": "en expansión", "Firmada": "firmadas", "Obra": "en obra", "Cerrada": "cerradas"}


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

    /* Opciones de los selectores (radio) más grandes y en negrilla, para que se lean fácil */
    div[data-testid="stRadio"] > label p {{
        font-size: 1.1rem !important;
        font-weight: 700 !important;
    }}
    div[data-testid="stRadio"] div[role="radiogroup"] label p {{
        font-size: 1.05rem !important;
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

    /* Letra más clara en textos de apoyo y etiquetas */
    [data-testid="stCaptionContainer"] {{
        font-size: 14px !important;
        color: #55555B !important;
    }}
    [data-testid="stWidgetLabel"] p {{
        font-size: 15px !important;
        color: {OXXO_TEXTO} !important;
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


@st.cache_data(show_spinner="Cargando las tiendas OXXO...", ttl=TTL_CACHE_DATOS)
def _leer_tiendas_cacheado(url: str, hoja: str):
    """Tiendas OXXO (abiertas / en expansión / firmadas / en obra / cerradas) desde la hoja indicada del Excel de tiendas."""
    return leer_tiendas_desde_url(url, hoja)


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

# Si el archivo sí se pudo descargar pero alguna hoja en particular falló
# al leerse (por ejemplo, una fila con un formato de columna inesperado),
# esa fuente queda sin puntos en silencio a menos que se avise aquí — sin
# esto, "no hay datos para graficar" se ve igual a "la fuente está vacía".
_errores_fuentes = getattr(df, "attrs", {}).get("errores_fuentes") if df is not None else None
if _errores_fuentes:
    with st.expander(f"⚠️ {len(_errores_fuentes)} hoja(s) no se pudieron leer del Excel — ver detalle", expanded=True):
        for _err in _errores_fuentes:
            st.warning(_err, icon="⚠️")

_resumen_fuentes = getattr(df, "attrs", {}).get("resumen_fuentes") if df is not None else None
if _resumen_fuentes:
    _vacias = [f for f, r in _resumen_fuentes.items() if not r["filas"]]
    _titulo = "📄 Hojas leídas del Excel" + (f" — ⚠️ sin datos: {', '.join(_vacias)}" if _vacias else "")
    with st.expander(_titulo, expanded=bool(_vacias)):
        _hojas = getattr(df, "attrs", {}).get("hojas_excel") or []
        if _hojas:
            st.caption("Hojas que tiene el Excel: " + ", ".join(f"«{h}»" for h in _hojas))
        _usadas = set(getattr(df, "attrs", {}).get("hojas_usadas") or [])
        _no_usadas = [
            h for h in _hojas
            if h not in _usadas and not h.strip().lower().startswith(HOJA_TIENDAS_DEFECTO.lower())
        ]
        if _no_usadas:
            st.caption("Hojas que la app no usa (no son una fuente de puntos): " + ", ".join(f"«{h}»" for h in _no_usadas))
        st.caption(f"La hoja «{HOJA_TIENDAS_DEFECTO}» se usa para las tiendas OXXO (abiertas, en expansión, firmadas, en obra y cerradas).")
        for _f, _r in _resumen_fuentes.items():
            if _r["hoja"] is None:
                st.write(f"• **{_f}**: no encontré ninguna hoja con ese nombre.")
            else:
                st.write(
                    f"• **{_f}**: hoja «{_r['hoja']}» → {_r['filas']} punto(s) leído(s), "
                    f"{_r['con_coordenadas']} con coordenadas."
                )

# Tiendas OXXO (hoja "Jun"): link propio en los Secrets (url_tiendas_oxxo) y,
# si no existe, se intenta con la hoja "Jun" del mismo Excel de puntos. Si
# falla, la app sigue igual, solo que sin tiendas en el mapa.
url_tiendas_secreta = ""
hoja_tiendas = HOJA_TIENDAS_DEFECTO
try:
    url_tiendas_secreta = st.secrets.get("url_tiendas_oxxo", "")
    hoja_tiendas = st.secrets.get("hoja_tiendas", HOJA_TIENDAS_DEFECTO)
except Exception:
    pass
df_tiendas = None
error_tiendas = None
_url_tiendas = url_tiendas_secreta or url_secreta
if _url_tiendas:
    try:
        df_tiendas = _leer_tiendas_cacheado(_url_tiendas, hoja_tiendas)
    except Exception as e:
        if url_tiendas_secreta:  # solo se avisa si ella configuró ese link a propósito
            error_tiendas = str(e)

def _refrescar_puntos_desde_url() -> bool:
    """
    Vuelve a descargar el Excel de puntos potenciales (desde el Secret
    privado, o desde el link manual guardado) y reemplaza los puntos
    cargados. Se usa desde el botón del sidebar, así que sin importar en
    qué módulo esté Alisson, siempre puede traer los datos nuevos.
    """
    _leer_fuentes_modulo1_desde_url_cacheado.clear()
    _leer_tiendas_cacheado.clear()
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


_hay_fuente_url = bool(url_secreta) or (metadata.get("modo") == "url" and metadata.get("url_fuente"))

# ---------------------------------------------------------------------------
# Sidebar — explicación del aplicativo, navegación entre módulos y botones
# de actualizar, para que la página principal quede limpia.
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### 📍 OXXO")
    st.markdown("**Inteligencia de Expansión**")
    st.caption("Consulta y seguimiento de puntos potenciales")
    st.write(
        "Antes de visitar o analizar un punto potencial, revisa aquí si ya "
        "fue reportado por otra fuente o si hay una tienda OXXO cerca. "
        "Así se evitan visitas repetidas y se decide con mejor información."
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
                Consulta y seguimiento de puntos potenciales
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
# (Módulo de Generadores retirado — respaldo guardado aparte; ver respaldo_generadores)
# Resumen general — total de puntos potenciales + una gráfica pequeña
# por cada fuente (para que no salga una sola gráfica gigante). Este
# resumen vive SOLO en Módulo 1.
# ---------------------------------------------------------------------------
# Hoja 4 · Búsqueda de regional y jefes — archivos y funciones de apoyo
# ---------------------------------------------------------------------------
_CARPETA_APP = Path(__file__).resolve().parent


def _ruta_archivo(nombres):
    """Primer archivo que exista (en la carpeta de la app o en data/) con alguno de esos nombres."""
    for carpeta in (_CARPETA_APP, _CARPETA_APP / "data", Path("."), Path("data")):
        for n in nombres:
            p = carpeta / n
            if p.exists():
                return p
    return None


@st.cache_data(show_spinner=False)
def _cargar_jefes(ruta: str, firma: float):
    return leer_jefes_regionales(ruta)


@st.cache_data(show_spinner=False)
def _cargar_zonas(ruta: str, firma: float):
    return leer_zonas_kml(ruta)


@st.cache_data(show_spinner=False, ttl=3600)
def _buscar_direccion_cacheado(texto: str, ciudad: str):
    return buscar_direccion(texto, ciudad)


def _zonas_con_lineas(zonas: list) -> list:
    """
    Deja cada zona lista para dibujar: se nombra por su UPZ/barrio, conserva el color que tiene en el
    mapa de zonas de especialistas y lleva la línea de la tarjeta (mouse encima) con su especialista.
    """
    r = []
    for z in zonas:
        i = interpretar_zona(z)
        z2 = dict(z)
        z2["nombre"] = i["sitio"] or z.get("nombre", "Zona")
        z2["lineas"] = [f"Especialista de la zona: {texto_especialista(z)}"]
        r.append(z2)
    return r


def renderizar_mapa_regional(tiendas, grupos, zonas, resaltado, altura=640, centro=None, clave="mapa_regional"):
    """Mapa solo con tiendas (abiertas, en expansión, firmadas, en obra, cerradas), coloreadas
    por jefe de zona / regional (o por estado), con las zonas de especialistas y la búsqueda en rojo."""
    html = construir_html_mapa(
        pd.DataFrame(), {}, _COLORES_HEX_LEYENDA,
        resaltados=[resaltado] if resaltado is not None else [],
        tiendas=tiendas, centro=centro, altura=altura,
        zonas=zonas or None, grupos_tiendas=grupos or None,
    )
    components.html(html, height=altura + 4, scrolling=False)


# ---------------------------------------------------------------------------
# Tres hojas (pestañas) para tener la información ordenada:
#   1) Mapa y revisión de puntos  2) Resumen general  3) Duplicados
# ---------------------------------------------------------------------------
tab_mapa, tab_resumen, tab_dup, tab_regional = st.tabs([
    "🗺️ Mapa y revisión de puntos",
    "📊 Resumen general",
    "⚠️ Duplicados",
    "🧭 Búsqueda de regional y jefes",
])

# ===== HOJA 1 · Mapa y revisión de puntos ==================================
# Orden: búsqueda (nombre / coordenada) → mapa con la búsqueda y tiendas cerca →
# Google Maps y Street View → resultado (posibles coincidencias o libre) →
# tiendas OXXO cercanas al punto.
with tab_mapa:
    st.subheader("🗺️ Mapa y revisión de puntos")
    st.write(
        "Aquí se revisa un punto antes de visitarlo: si **ya fue reportado** por "
        "otra fuente y si hay **tiendas OXXO cerca**."
    )
    st.markdown(
        "1. **Busca el punto** por nombre o por coordenada.\n"
        "2. **Mira el mapa:** el punto buscado aparece en **rojo**, junto a los puntos "
        "potenciales (Especialistas, Localizadores, Terceros, Operación e Inmobiliarias) y a "
        "las tiendas OXXO (abiertas, en expansión, firmadas, en obra y cerradas) que tiene alrededor.\n"
        "3. **Lee el resultado** más abajo (después de Google Maps y Street View): el punto está **libre para análisis** "
        "o tiene **posibles coincidencias** cerca."
    )

    def _limpiar_busqueda_mapa():
        for _k in ("resultado_busqueda_nombre", "resultado_busqueda_punto", "error_busqueda_punto", "sel_nombre_mapa_unico"):
            st.session_state.pop(_k, None)

    modo_busqueda = st.radio(
        "¿Cómo quieres buscar?",
        ["Por nombre", "Por coordenada"],
        horizontal=True,
        key="modo_busqueda_mapa_unico",
    )

    consulta_punto = None  # se llena si hay un punto válido para mostrar en rojo
    id_punto_buscado = None  # para no contar el propio punto como "cercano"

    tienda_buscada = None  # (nombre, lat, lon) si lo elegido es una tienda OXXO existente

    if modo_busqueda == "Por nombre":
        # Lista de TODO lo que ya existe (tiendas OXXO y puntos potenciales): se escribe
        # una parte del nombre (ej. "parque") y se despliegan los que lo contienen.
        catalogo = {}
        if df_tiendas is not None and len(df_tiendas):
            for _t in df_tiendas.itertuples():
                _et = f"{_t.nombre} · 🏪 Tienda {_NOMBRE_ESTADO_TIENDA.get(str(_t.estado_tienda), str(_t.estado_tienda).lower())}"
                if str(getattr(_t, "ciudad", "") or "").strip():
                    _et += f" · {_t.ciudad}"
                if str(getattr(_t, "cr", "") or "").strip():
                    _et += f" · CR {_t.cr}"
                catalogo[_et] = {"tipo": "tienda", "fila": _t}
        if df is not None and len(df):
            for _p in df.itertuples():
                if not str(_p.local_identificado).strip():
                    continue
                _et = f"{_p.local_identificado} · 📍 {_p.fuente}"
                if str(getattr(_p, "ciudad", "") or "").strip():
                    _et += f" · {_p.ciudad}"
                if _et in catalogo:
                    _et += f" (#{_p.id})"
                catalogo[_et] = {"tipo": "punto", "fila": _p}
        etiquetas = sorted(catalogo.keys(), key=lambda x: x.lower())

        elegido = st.selectbox(
            f"Nombre del punto o tienda ({len(etiquetas)} registrados)",
            etiquetas, index=None, key="sel_nombre_mapa_unico",
            placeholder="Escribe una parte del nombre, ej. parque, y elige de la lista",
        )
        st.caption(
            "🏪 = tienda OXXO ya existente (abierta, en expansión, firmada, en obra o cerrada) · 📍 = punto potencial "
            "(de cualquier fuente). Escribe, por ejemplo, «parque» y salen todos los que lo contienen."
        )
        if elegido is not None:
            _item = catalogo[elegido]
            _f = _item["fila"]
            if _item["tipo"] == "tienda":
                try:
                    _lat, _lon = float(_f.latitud), float(_f.longitud)
                except (TypeError, ValueError):
                    _lat = _lon = None
                _lineas = [x for x in str(getattr(_f, "detalle", "") or "").split("\n") if x.strip()]
                if not any(x.startswith("Estado") for x in _lineas):
                    _lineas.insert(0, f"Estado de la tienda: {_f.estado_tienda}")
                if _lat is not None:
                    tienda_buscada = (str(_f.nombre), _lat, _lon)
                    consulta_punto = {
                        "lat": _lat, "lon": _lon, "etiqueta": str(_f.nombre),
                        "info_extra": "\n".join(_lineas),
                    }
            else:
                _lat, _lon = _f.latitud, _f.longitud
                if pd.isna(_lat) or pd.isna(_lon):
                    st.warning(
                        "Ese punto no tiene coordenadas registradas, así que no se puede "
                        "mostrar en el mapa."
                    )
                else:
                    id_punto_buscado = _f.id
                    def _v(x):
                        return "—" if (x is None or pd.isna(x) or str(x).strip() == "") else str(x)
                    consulta_punto = {
                        "lat": float(_lat), "lon": float(_lon), "etiqueta": str(_f.local_identificado),
                        "info_extra": (
                            f"Fuente: {_v(_f.fuente)}"
                            f"\nResponsable: {_v(_f.especialista)}"
                            f"\nEstado: {_v(_f.estado)}"
                            f"\nFecha de registro: {_v(_f.fecha_registro)}"
                            f"\nCiudad: {_v(_f.ciudad)}"
                        ),
                    }

    else:  # Por coordenada
        col_texto, col_boton = st.columns([5, 1], vertical_alignment="bottom")
        coord_pegada = col_texto.text_input(
            "Coordenada completa (latitud, longitud)", key="coord_pegada_mapa_unico",
            placeholder="Ej. 4.697539545568918, -74.09220071349365",
        )
        if col_boton.button("🔍 Buscar", type="primary", key="buscar_coord_mapa_unico", use_container_width=True):
            coord = parsear_coordenada_pegada(coord_pegada)
            if coord is None:
                st.session_state["error_busqueda_punto"] = True
                st.session_state.pop("resultado_busqueda_punto", None)
            else:
                lat_e, lon_e = coord
                st.session_state["resultado_busqueda_punto"] = {
                    "lat": lat_e, "lon": lon_e,
                    "etiqueta": f"Coordenada {lat_e:.5f}, {lon_e:.5f}",
                    "info_extra": f"Coordenada: {lat_e}, {lon_e}",
                }
                st.session_state["error_busqueda_punto"] = False
        st.caption(
            "Pégala completa, con todos los decimales (de Google Maps o "
            "ArcGIS), para que el punto no se desplace."
        )
        if st.session_state.get("error_busqueda_punto"):
            st.error(
                "Eso no tiene forma de coordenada. Debe verse así: "
                "4.697539545568918, -74.09220071349365"
            )
        consulta_punto = st.session_state.get("resultado_busqueda_punto")

    resaltado_mapa = None
    clave_mapa = "mapa_unico_modulo1_sin_busqueda"

    if consulta_punto is None:
        st.info(
            "Busca un punto arriba para ver aquí el mapa con lo que hay cerca, su "
            "Google Maps, su Street View y si hay otros puntos cerca (posible "
            "duplicidad) o si está libre para análisis."
        )
    else:
        lat_c, lon_c = consulta_punto["lat"], consulta_punto["lon"]
        resaltado_mapa = (lat_c, lon_c, consulta_punto["etiqueta"], consulta_punto.get("info_extra", ""))
        clave_mapa = f"mapa_unico_modulo1_{lat_c:.5f}_{lon_c:.5f}"

        st.button("✖ Quitar la búsqueda", key="quitar_busqueda_mapa_unico", on_click=_limpiar_busqueda_mapa)

    # 2) El mapa con la búsqueda (en rojo) y las tiendas cercanas
    st.markdown("##### Mapa")
    solo_cerca = False
    if resaltado_mapa is not None:
        _vista = st.radio(
            "¿Qué quieres ver en el mapa?",
            ["📍 Solo lo cercano al punto (a menos de 300 m)", "🗺️ Todo el mapa (con el punto buscado en rojo)"],
            horizontal=True, key="vista_mapa_busqueda",
        )
        solo_cerca = _vista.startswith("📍")
    renderizar_mapa_general(
        df, fuentes_activas=list(FUENTE_COLOR_ICONO.keys()), punto_resaltado=resaltado_mapa,
        key=clave_mapa, altura=640, df_tiendas=df_tiendas,
        radio_cerca_m=300 if solo_cerca else None,
        centro=(resaltado_mapa[0], resaltado_mapa[1], 17 if solo_cerca else 16) if resaltado_mapa is not None else None,
    )
    if solo_cerca and df_tiendas is not None and len(df_tiendas) and resaltado_mapa is not None:
        if len(_solo_cerca(df_tiendas, resaltado_mapa[0], resaltado_mapa[1], 300)) == 0:
            st.info(
                "🏪 No hay tiendas OXXO a menos de 300 m de este punto. Para ver las tiendas "
                "de toda la zona, elige **«Todo el mapa»** arriba del mapa.",
                icon="ℹ️",
            )
    st.caption(
        "Pasa el mouse sobre un pin o una tienda para ver su información "
        "(clic para dejar la tarjeta fija). Arriba del mapa eliges entre "
        "**Mapa simple** (limpio, poco saturado) y **Mapa detallado** (calles "
        "con nombres grandes, semáforos y TransMilenio), y prendes o apagas "
        "cada capa. Si dos o más puntos caen en el mismo lugar, se abren uno "
        "al lado del otro para que ninguno quede tapado."
    )

    if consulta_punto is not None:
        # 3) Google Maps y Street View del punto buscado
        st.markdown("##### Google Maps y Street View")
        col_mapa, col_calle = st.columns(2)
        with col_mapa:
            st.caption("Google Maps")
            components.iframe(url_mapa_embed(lat_c, lon_c), height=380)
        with col_calle:
            st.caption("Street View (vista a nivel de calle)")
            components.iframe(url_streetview_embed(lat_c, lon_c), height=380)
        st.caption(
            "Si el punto está en una zona sin cobertura de Street View, "
            "Google muestra ahí mismo un aviso de que no hay imagen disponible."
        )

        # 4) Resultado: tabla de posibles coincidencias (o libre) y tiendas OXXO cercanas
        cercanos = detectar_coincidencias(df, lat_c, lon_c, consulta_punto.get("etiqueta", ""))
        if id_punto_buscado is not None:
            cercanos = cercanos[cercanos["id"] != id_punto_buscado]

        st.markdown(f"##### Resultado para: {consulta_punto['etiqueta']}")
        if cercanos.empty:
            st.success(
                f"✅ Este punto está **libre para análisis**: no hay ningún punto "
                f"registrado a menos de {UMBRAL_DUPLICIDAD_M:.0f} m ni con un nombre parecido.",
                icon="✅",
            )
        else:
            st.warning(
                f"⚠️ Posible duplicidad — hay {len(cercanos)} punto(s) cerca "
                f"(a menos de {UMBRAL_DUPLICIDAD_M:.0f} m) o con nombre parecido.",
                icon="⚠️",
            )
            en_el_mismo_lugar = cercanos[cercanos["distancia_m"] <= 15]
            if not en_el_mismo_lugar.empty:
                st.error(
                    f"🔴 {len(en_el_mismo_lugar)} de ellos están prácticamente en el "
                    "MISMO lugar (a 15 m o menos).",
                    icon="🔴",
                )
            tabla_cercanos = pd.DataFrame({
                "Fuente": cercanos["fuente"].values,
                "Nombre": cercanos["local_identificado"].values,
                "Responsable": cercanos["especialista"].replace("", "—").values,
                "Practicante": cercanos["practicante"].replace("", "—").values if "practicante" in cercanos.columns else "—",
                "Estado": cercanos["estado"].replace("", "Pendiente").values,
                "Fecha de registro": cercanos["fecha_registro"].replace("", "—").values,
                "Ciudad": cercanos["ciudad"].replace("", "—").values,
                "Distancia": [
                    f"{d:.0f} m" if d != float("inf") else "Sin coordenadas"
                    for d in cercanos["distancia_m"]
                ],
                "Por qué aparece": cercanos["coincide_por"].values,
            })
            st.dataframe(tabla_cercanos, use_container_width=True, hide_index=True)

        if df_tiendas is not None and len(df_tiendas):
            tiendas_cerca = tiendas_cercanas(df_tiendas, lat_c, lon_c, 300)
            if tienda_buscada is not None and len(tiendas_cerca):
                tiendas_cerca = tiendas_cerca[
                    ~((tiendas_cerca["nombre"] == tienda_buscada[0]) & (tiendas_cerca["distancia_m"] < 3))
                ]
            if tiendas_cerca.empty:
                st.caption("🏪 No hay tiendas OXXO (abiertas, en expansión, firmadas, en obra ni cerradas) a menos de 300 m de este punto.")
            else:
                st.markdown(f"**🏪 Tiendas OXXO a menos de 300 m ({len(tiendas_cerca)}):**")
                st.dataframe(
                    pd.DataFrame({
                        "Estado": tiendas_cerca["estado_tienda"].values,
                        "CR": (tiendas_cerca["cr"] if "cr" in tiendas_cerca else tiendas_cerca["nombre"]).replace("", "—").values,
                        "Tienda": tiendas_cerca["nombre"].replace("", "—").values,
                        "Apertura": (tiendas_cerca["apertura"] if "apertura" in tiendas_cerca else tiendas_cerca["nombre"].map(lambda _: "")).replace("", "—").values,
                        "Ciudad": tiendas_cerca["ciudad"].replace("", "—").values,
                        "Distancia": [f"{d:.0f} m" for d in tiendas_cerca["distancia_m"]],
                    }),
                    use_container_width=True, hide_index=True,
                )

    if error_tiendas:
        st.warning(f"No se pudieron cargar las tiendas OXXO: {error_tiendas}", icon="⚠️")
    elif df_tiendas is None:
        st.caption(
            "🏪 Las tiendas OXXO todavía no están conectadas (falta el link de "
            "la hoja con las tiendas abiertas, en expansión, firmadas, en obra y cerradas)."
        )
    else:
        _diag_t = getattr(df_tiendas, "attrs", {}).get("diagnostico", {})
        _por_estado = _diag_t.get("por_estado", {})
        with st.expander(
            f"🏪 Tiendas OXXO cargadas: {len(df_tiendas)} "
            f"({', '.join(f'{v} {_PLURAL_ESTADO_TIENDA.get(k, k.lower())}' for k, v in _por_estado.items()) or 'ninguna'})"
        ):
            if _diag_t.get("error"):
                st.error(_diag_t["error"])
            st.caption(
                f"Hoja leída: {df_tiendas.attrs.get('hoja', '—')} · columna de estado usada: "
                f"{_diag_t.get('columna_estado') or 'no encontré ninguna'}"
            )
            if _diag_t.get("expansion_por_tipo"):
                st.caption(
                    f"{_diag_t['expansion_por_tipo']} tienda(s) abierta(s) se dibujan como «en expansión» "
                    "(azul oscuro) porque su Tipo de tienda dice EXP 2025 o EXP 2026."
                )
            if _diag_t.get("sin_coordenada_valida"):
                st.caption(f"{_diag_t['sin_coordenada_valida']} fila(s) sin coordenada válida, no se dibujan.")
            if _diag_t.get("sin_estado_reconocido"):
                st.caption(
                    f"{_diag_t['sin_estado_reconocido']} fila(s) con un estado que no reconozco "
                    f"(no se dibujan): {_diag_t.get('estados_no_reconocidos', {})}"
                )
            st.caption("Columnas de la hoja: " + ", ".join(map(str, _diag_t.get("columnas", []))))


# ===== HOJA 2 · Resumen general ============================================
with tab_resumen:
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
                # Altura mínima generosa (y bastante espacio por barra) para
                # que con pocas categorías (1 o 2) las barras y sus nombres
                # no queden amontonados/superpuestos — con "cantidad" como
                # entero se fuerzan los ticks del eje X a números enteros.
                chart_fuente = (
                    alt.Chart(top5_fuente)
                    .mark_bar(color=_COLORES_HEX_LEYENDA.get(color_resumen, OXXO_ROJO), cornerRadiusEnd=4)
                    .encode(
                        x=alt.X("cantidad:Q", title="Puntos", axis=alt.Axis(tickMinStep=1)),
                        y=alt.Y(
                            "especialista:N", title=None, sort="-x",
                            axis=alt.Axis(labelLimit=160),
                            scale=alt.Scale(paddingInner=0.35, paddingOuter=0.3),
                        ),
                        tooltip=[
                            alt.Tooltip("especialista:N", title="Especialista / responsable"),
                            alt.Tooltip("cantidad:Q", title="Puntos"),
                        ],
                    )
                    .properties(height=max(120, 42 * len(top5_fuente)))
                )
                st.altair_chart(chart_fuente, use_container_width=True)
                if len(conteo_fuente) > 5:
                    st.caption(f"Mostrando los 5 con más puntos, de {len(conteo_fuente)} responsables.")

# ===== HOJA 3 · Duplicados =================================================
with tab_dup:
    st.subheader("⚠️ Duplicados")
    # Aviso: puntos que están uno encima del otro en el mismo lugar.
    apilados = detectar_apilados(df, list(FUENTE_COLOR_ICONO.keys()))
    if not apilados.empty:
        st.warning(
            f"⚠️ Hay {len(apilados)} lugar(es) con más de un punto en el mismo "
            "sitio (por ejemplo, uno de Operación encima de uno de Especialistas).",
            icon="⚠️",
        )
        with st.expander("Ver cuáles son", expanded=True):
            st.caption("Haz clic en una fila para verla en el mapa, con la información de todos los puntos que coinciden.")
            evento_apilados = st.dataframe(
                apilados[COLUMNAS_APILADOS], use_container_width=True, hide_index=True,
                on_select="rerun", selection_mode="single-row", key="tabla_apilados_mapa_unico",
            )
            filas_sel_apilados = list(evento_apilados.selection.rows) if evento_apilados is not None else []
            if filas_sel_apilados:
                grupo = apilados.iloc[filas_sel_apilados[0]]
                puntos_grupo = df[df["id"].isin(grupo["_ids"])].dropna(subset=["latitud", "longitud"])
                st.markdown(
                    f"**Estos {len(puntos_grupo)} puntos están en el mismo lugar** — "
                    "pasa el mouse por cada pin, o mira la tabla de abajo:"
                )
                renderizar_mapa_general(
                    df, fuentes_activas=list(FUENTE_COLOR_ICONO.keys()),
                    punto_resaltado=None,
                    key=f"mapa_apilados_{filas_sel_apilados[0]}_{grupo['Coordenada']}",
                    altura=460, centro=(grupo["_lat"], grupo["_lon"], 18),
                    solo_ids=list(grupo["_ids"]), mostrar_capas_vacias=False,
                )
                st.dataframe(
                    pd.DataFrame({
                        "Fuente": puntos_grupo["fuente"].values,
                        "Nombre": puntos_grupo["local_identificado"].values,
                        "Responsable": puntos_grupo["especialista"].replace("", "—").values,
                        "Practicante": puntos_grupo["practicante"].replace("", "—").values if "practicante" in puntos_grupo.columns else "—",
                        "Estado": puntos_grupo["estado"].replace("", "Pendiente").values,
                        "Fecha de registro": puntos_grupo["fecha_registro"].replace("", "—").values,
                        "Ciudad": puntos_grupo["ciudad"].replace("", "—").values,
                    }),
                    use_container_width=True, hide_index=True,
                )

    st.divider()
    st.markdown("#### 📋 Posibles duplicados")
    st.caption(
        "Compara cada punto contra los demás, sin importar de cuál de las "
        "5 fuentes venga. Se marca como posible duplicado si: la "
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
                altura=480, mostrar_capas_vacias=False,
            )

# ===== HOJA 4 · Búsqueda de regional y jefes ================================
with tab_regional:
    st.subheader("🧭 Búsqueda de regional y jefes")
    st.write(
        "Escribe una **coordenada** o una **dirección** y el mapa te muestra **en qué zona cae** y "
        "**quién es su especialista**, junto con el **jefe de zona** y el **regional** que atienden "
        "las tiendas de alrededor. Aquí solo aparecen tiendas OXXO (abiertas, en expansión, "
        "firmadas, en obra y cerradas)."
    )

    # ---- archivos (los que van en GitHub, o los que se carguen aquí mismo para probar) ----
    _ruta_j = _ruta_archivo(["jefes_regionales.xlsx", "Jefes_regionales.xlsx"])
    _ruta_z = _ruta_archivo(["zonas_especialistas.kml", "zonas_especialistas.kmz", "zonas.kml", "zonas.kmz"])

    with st.expander("📁 Archivos de esta hoja (jefes y zonas)", expanded=False):
        st.caption(
            "Normalmente no tienes que hacer nada: los archivos `jefes_regionales.xlsx` y "
            "`zonas_especialistas.kml` viajan con la app en GitHub. Si quieres probar con otros, "
            "cárgalos aquí (solo duran mientras tengas esta pestaña abierta)."
        )
        _sub_j = st.file_uploader("Excel de jefes y regionales", type=["xlsx"], key="subir_jefes")
        _sub_z = st.file_uploader("Zonas de especialistas (KML o KMZ de Google My Maps)", type=["kml", "kmz"], key="subir_zonas")

    if _sub_j is not None:
        df_jefes = leer_jefes_regionales(_sub_j.getvalue())
        _origen_j = f"cargado ahora: {_sub_j.name}"
    elif _ruta_j is not None:
        df_jefes = _cargar_jefes(str(_ruta_j), _ruta_j.stat().st_mtime)
        _origen_j = _ruta_j.name
    else:
        df_jefes = leer_jefes_regionales(b"")
        _origen_j = ""

    if _sub_z is not None:
        _zonas_crudas = leer_zonas_kml(_sub_z.getvalue())
        _origen_z = f"cargado ahora: {_sub_z.name}"
    elif _ruta_z is not None:
        _zonas_crudas = _cargar_zonas(str(_ruta_z), _ruta_z.stat().st_mtime)
        _origen_z = _ruta_z.name
    else:
        _zonas_crudas = []
        _origen_z = ""
    zonas_especialistas = _zonas_con_lineas(_zonas_crudas)

    if df_tiendas is None or not len(df_tiendas):
        st.warning("Todavía no están cargadas las tiendas OXXO, por eso no se puede dibujar este mapa.", icon="⚠️")
    else:
        tiendas_jefes = unir_jefes_a_tiendas(df_tiendas, df_jefes)
        _n_con = int((tiendas_jefes["jefe_zona"] != SIN_ASIGNAR).sum())

        if df_jefes.empty:
            st.warning(
                "No encontré el Excel de jefes y regionales (`jefes_regionales.xlsx`). "
                "Súbelo a GitHub junto a `app.py`, o cárgalo en «Archivos de esta hoja».",
                icon="⚠️",
            )
        else:
            st.caption(
                f"👥 {_n_con} de {len(tiendas_jefes)} tiendas tienen jefe de zona y regional asignados "
                f"({_origen_j}). Las demás (por ejemplo cerradas o que todavía no abren) salen como «{SIN_ASIGNAR}»."
            )
        if not zonas_especialistas:
            st.info(
                "🧩 Todavía no hay zonas de especialistas cargadas. Exporta tu mapa de Google My Maps "
                "como KML (⋮ junto al nombre del mapa → «Exportar a KML/KMZ») y súbelo a GitHub con el nombre "
                "`zonas_especialistas.kml`, o cárgalo en «Archivos de esta hoja».",
                icon="🧩",
            )
        else:
            st.caption(f"🧩 {len(zonas_especialistas)} zonas de especialistas cargadas ({_origen_z}).")

        # ---- búsqueda ----
        modo_reg = st.radio("¿Cómo quieres buscar?", ["Por coordenada", "Por dirección"], horizontal=True, key="modo_busqueda_regional")
        if modo_reg == "Por coordenada":
            c_txt, c_btn = st.columns([5, 1], vertical_alignment="bottom")
            _coord_txt = c_txt.text_input(
                "Coordenada completa (latitud, longitud)", key="coord_regional",
                placeholder="Ej. 4.697539545568918, -74.09220071349365",
            )
            if c_btn.button("🔍 Buscar", type="primary", key="buscar_coord_regional", use_container_width=True):
                _c = parsear_coordenada_pegada(_coord_txt)
                if _c is None:
                    st.session_state["error_regional"] = "Eso no tiene forma de coordenada. Debe verse así: 4.697539545568918, -74.09220071349365"
                    st.session_state.pop("busqueda_regional", None)
                else:
                    st.session_state["error_regional"] = ""
                    st.session_state["busqueda_regional"] = {
                        "lat": _c[0], "lon": _c[1], "etiqueta": f"Coordenada {_c[0]:.5f}, {_c[1]:.5f}",
                    }
        else:
            c_dir, c_ciu, c_btn2 = st.columns([4, 2, 1], vertical_alignment="bottom")
            _dir_txt = c_dir.text_input("Dirección", key="dir_regional", placeholder="Ej. Calle 80 # 69-50")
            _ciu_txt = c_ciu.text_input("Ciudad", key="ciudad_regional", placeholder="Ej. Bogotá")
            if c_btn2.button("🔍 Buscar", type="primary", key="buscar_dir_regional", use_container_width=True):
                _res, _err = _buscar_direccion_cacheado(_dir_txt, _ciu_txt)
                st.session_state["error_regional"] = _err
                st.session_state["opciones_dir_regional"] = _res
                st.session_state.pop("busqueda_regional", None)
                if _res:
                    st.session_state["busqueda_regional"] = {
                        "lat": _res[0]["lat"], "lon": _res[0]["lon"], "etiqueta": _dir_txt.strip() or "Dirección",
                        "detalle": _res[0]["nombre"],
                    }
            _opc = st.session_state.get("opciones_dir_regional") or []
            if len(_opc) > 1:
                _et = [f"{i + 1}. {o['nombre']}" for i, o in enumerate(_opc)]
                _sel = st.selectbox("Encontré varias direcciones parecidas, elige la correcta:", _et, key="sel_dir_regional")
                _o = _opc[_et.index(_sel)]
                st.session_state["busqueda_regional"] = {
                    "lat": _o["lat"], "lon": _o["lon"], "etiqueta": (_dir_txt.strip() or "Dirección"), "detalle": _o["nombre"],
                }
            st.caption(
                "La dirección se busca en OpenStreetMap. Si no sale o queda mal ubicada, "
                "agrega la ciudad o pega la coordenada de Google Maps."
            )
        if st.session_state.get("error_regional"):
            st.error(st.session_state["error_regional"])
        busq = st.session_state.get("busqueda_regional")

        c_ver, c_quitar = st.columns([4, 1], vertical_alignment="bottom")
        _vista_reg = c_ver.radio(
            "Pintar las tiendas por:", ["Regional", "Jefe de zona", "Estado de la tienda"],
            horizontal=True, key="pintar_regional",
        )
        if busq is not None and c_quitar.button("✖ Quitar la búsqueda", key="quitar_regional"):
            for _k in ("busqueda_regional", "opciones_dir_regional", "error_regional"):
                st.session_state.pop(_k, None)
            st.rerun()

        # ---- datos para el mapa ----
        t_mapa = tiendas_jefes.copy()
        extra = (
            "Jefe de zona: " + t_mapa["jefe_zona"] + "\nRegional: " + t_mapa["regional"]
            + "\nRegión: " + t_mapa["region"] + " · Plaza: " + t_mapa["plaza"]
        )
        t_mapa["detalle"] = extra + "\n" + t_mapa["detalle"].astype(str)
        grupos_mapa = None
        if _vista_reg == "Regional":
            t_mapa["grupo"] = t_mapa["regional"]
            grupos_mapa = colores_por_grupo(t_mapa["grupo"])
        elif _vista_reg == "Jefe de zona":
            t_mapa["grupo"] = t_mapa["jefe_zona"]
            grupos_mapa = colores_por_grupo(t_mapa["grupo"])

        resaltado_reg = None
        if busq is not None:
            _info = []
            if busq.get("detalle"):
                _info.append(busq["detalle"])
            _info.append(f"Coordenada: {busq['lat']:.6f}, {busq['lon']:.6f}")
            resaltado_reg = (busq["lat"], busq["lon"], busq["etiqueta"], "\n".join(_info))

        if _vista_reg != "Estado de la tienda":
            st.caption("Punto lleno = tienda abierta, en expansión, firmada o en obra · anillo (centro blanco) = tienda cerrada.")
        renderizar_mapa_regional(
            t_mapa, grupos_mapa, zonas_especialistas, resaltado_reg, altura=660,
            centro=(busq["lat"], busq["lon"], 15) if busq is not None else None,
        )
        st.caption(
            "Pasa el mouse sobre una tienda para ver su jefe, su regional y su ficha; sobre una zona "
            "para ver su especialista. Arriba del mapa prendes o apagas cada jefe, regional o las zonas."
        )
        if zonas_especialistas:
            _por_esp = {}
            for _z in zonas_especialistas:
                _por_esp.setdefault(texto_especialista(_z), []).append(_z.get("color", "#999"))
            _por_esp = {n: max(set(cs), key=cs.count) for n, cs in _por_esp.items()}
            st.markdown(
                "**Colores de las zonas, por especialista:** "
                + " &nbsp; ".join(
                    f'<span style="display:inline-block;width:12px;height:12px;border-radius:3px;background:{c};'
                    f'margin-right:4px;vertical-align:-1px"></span>{n}'
                    for n, c in sorted(_por_esp.items(), key=lambda x: x[0])
                ),
                unsafe_allow_html=True,
            )

        # ---- resultado de la búsqueda ----
        if busq is not None:
            lat_b, lon_b = busq["lat"], busq["lon"]
            st.markdown(f"##### Resultado para: {busq['etiqueta']}")
            if busq.get("detalle"):
                st.caption(f"📍 Dirección encontrada: {busq['detalle']}")

            col_z, col_r = st.columns(2)
            with col_z:
                st.markdown("**🧩 Zona y especialista**")
                if not zonas_especialistas:
                    st.info("Aún no hay zonas cargadas (ver el aviso de arriba).")
                else:
                    _en = zonas_de_punto(zonas_especialistas, lat_b, lon_b)
                    if not _en:
                        st.warning("Este punto no cae dentro de ninguna zona dibujada en el mapa de especialistas.", icon="⚠️")
                    for _z in _en:
                        _i = interpretar_zona(_z)
                        st.success(
                            f"Zona (UPZ): **{_i['sitio'] or _z['nombre']}**\n\n"
                            f"Especialista de la zona: **{texto_especialista(_z)}**",
                            icon="✅",
                        )

            cerca6 = tiendas_mas_cercanas(tiendas_jefes, lat_b, lon_b, 6)
            prob = responsables_probables(cerca6)
            with col_r:
                st.markdown("**👥 Jefe de zona y regional**")
                if not prob:
                    st.info("Ninguna de las tiendas más cercanas tiene jefe de zona asignado.")
                else:
                    st.success(
                        f"Jefe de zona: **{prob['jefe_zona']}**\n\nRegional: **{prob['regional']}**\n\n"
                        f"Región: {prob['region']} · Plaza: {prob['plaza']}",
                        icon="✅",
                    )
                    st.caption(
                        f"Se toma de la tienda más cercana con jefe asignado: {prob['tienda']} "
                        f"(CR {prob['cr']}), a {prob['distancia_m']:.0f} m."
                    )
                    if prob["hay_mas_de_un_jefe"]:
                        st.warning(
                            "Ojo: entre las tiendas cercanas hay más de un jefe de zona ("
                            + ", ".join(prob["jefes_cercanos"]) + "). El punto queda en un límite entre zonas; "
                            "confírmalo con el regional.", icon="⚠️",
                        )

            st.markdown("**🏪 Tiendas más cercanas**")
            st.dataframe(
                pd.DataFrame({
                    "Tienda": cerca6["nombre"].replace("", "—").values,
                    "CR": cerca6["cr"].replace("", "—").values,
                    "Estado": cerca6["estado_tienda"].values,
                    "Distancia": [f"{d:.0f} m" if d < 1000 else f"{d / 1000:.1f} km" for d in cerca6["distancia_m"]],
                    "Jefe de zona": cerca6["jefe_zona"].values,
                    "Regional": cerca6["regional"].values,
                    "Región": cerca6["region"].values,
                }),
                use_container_width=True, hide_index=True,
            )
            st.caption(
                "El jefe de zona y el regional salen de las tiendas de alrededor (el Excel asigna jefes "
                "por tienda, no por territorio dibujado). La zona y el especialista salen del mapa de zonas."
            )

st.divider()
st.caption(
    "Conectado a los datos reales del área. La herramienta complementa el "
    "proceso actual; no reemplaza el análisis ni el criterio humano."
)
