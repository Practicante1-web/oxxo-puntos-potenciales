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

from utils import (
    COLOR_ESTADO,
    ESTADOS,
    UMBRAL_DUPLICIDAD_M,
    UMBRAL_SIMILITUD_NOMBRE,
    buscar_por_nombre,
    cargar_puntos,
    detectar_coincidencias,
    guardar_puntos,
    leer_archivo_fuente,
    leer_desde_url,
    registrar_punto,
)

METADATA_PATH = Path("data/metadata.json")
RUTA_EXCEL_BUNDLED = Path("data/Puntos_potenciales.xlsx")

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


# ---------------------------------------------------------------------------
# Estado inicial
# ---------------------------------------------------------------------------
metadata = leer_metadata()
error_fuente_url = None
cargado_desde_bundle = False

if "puntos" not in st.session_state:
    if metadata.get("modo") == "url" and metadata.get("url_fuente"):
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

if metadata.get("modo") == "url" and metadata.get("url_fuente"):
    col_espacio, col_refrescar = st.columns([5, 1.3])
    with col_refrescar:
        if st.button("🔄 Actualizar ahora", use_container_width=True, type="primary"):
            _leer_desde_url_cacheado.clear()
            try:
                nuevo_df = _leer_desde_url_cacheado(metadata["url_fuente"])
            except Exception as e:
                st.error(f"No se pudo actualizar: {e}")
            else:
                st.session_state.puntos = nuevo_df
                guardar_puntos(nuevo_df)
                guardar_metadata(modo="url", url_fuente=metadata["url_fuente"], archivo_origen="Link de OneDrive (en vivo)")
                st.rerun()

if cargado_desde_bundle:
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

tab1, tab2, tab3, tab4 = st.tabs(
    [
        "📍 Consulta y validación",
        "📊 Seguimiento de oportunidades",
        "🗺️ Mapa de oportunidades",
        "⬆️ Actualizar datos",
    ]
)

# ---------------------------------------------------------------------------
# TAB 1 · Consulta y validación
# ---------------------------------------------------------------------------
with tab1:
    st.subheader("Registrar una nueva oportunidad")
    st.write(
        "Ingresa las coordenadas y el nombre del local identificado para "
        "consultar si ya existe una oportunidad registrada cerca **o con el "
        "mismo nombre**, antes de continuar."
    )

    with st.expander("🔎 Buscar solo por nombre del local"):
        st.caption(
            "Útil cuando dos puntos potenciales podrían compartir nombre "
            "(mismo centro comercial, misma referencia), aunque estén en "
            "zonas distintas del mapa."
        )
        nombre_busqueda = st.text_input(
            "Nombre del local a buscar", key="busqueda_nombre",
            placeholder="Ej. Toberin 168",
        )
        if st.button("Buscar por nombre"):
            resultado_nombre = buscar_por_nombre(df, nombre_busqueda)
            if resultado_nombre.empty:
                st.success("No hay ningún local registrado con un nombre igual o parecido.")
            else:
                st.warning(
                    f"Se encontraron {len(resultado_nombre)} local(es) con nombre "
                    "igual o muy parecido:"
                )
                st.dataframe(
                    resultado_nombre[
                        ["id", "especialista", "ciudad", "local_identificado", "estado", "similitud_nombre"]
                    ],
                    use_container_width=True,
                    hide_index=True,
                )

    with st.form("form_consulta"):
        c1, c2, c3 = st.columns(3)
        especialista = c1.text_input("Especialista", placeholder="Ej. Laura Ávila")
        ciudad = c2.text_input("Ciudad", placeholder="Ej. Bogotá")
        upz = c3.text_input("UPZ / zona", placeholder="Ej. Chico Lago")

        c4, c5 = st.columns(2)
        lat = c4.number_input("Latitud", value=4.650000, format="%.6f")
        lon = c5.number_input("Longitud", value=-74.080000, format="%.6f")

        local_identificado = st.text_input(
            "Nombre del punto potencial", placeholder="Ej. Toberin 168"
        )
        notas = st.text_area("Información adicional / notas del entorno", "")

        consultar = st.form_submit_button(
            "🔍 Consultar aplicativo", use_container_width=True, type="primary"
        )

    if consultar:
        cercanos = detectar_coincidencias(df, lat, lon, local_identificado)
        st.session_state["ultima_consulta"] = {
            "especialista": especialista,
            "ciudad": ciudad,
            "upz": upz,
            "lat": lat,
            "lon": lon,
            "local_identificado": local_identificado,
            "notas": notas,
            "cercanos": cercanos,
        }

    consulta = st.session_state.get("ultima_consulta")
    if consulta is not None:
        cercanos = consulta["cercanos"]

        if not cercanos.empty:
            st.warning(
                f"⚠️ Posible duplicidad — se encontraron {len(cercanos)} punto(s) "
                f"con ubicación cercana (< {UMBRAL_DUPLICIDAD_M} m) o nombre "
                "igual/similar al ingresado.",
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
                    detalle_nombre = (
                        f" · {row['similitud_nombre']*100:.0f}% de parecido en el nombre"
                        if row["similitud_nombre"] >= UMBRAL_SIMILITUD_NOMBRE
                        else ""
                    )
                    cc1.markdown(
                        f"**{row['coincide_por']}** — {detalle_distancia}{detalle_nombre}, "
                        f"registrado por **{row['especialista']}**"
                    )
                    cc1.caption(
                        f"{row['local_identificado']} · {row['ciudad']} · "
                        f"Fecha: {row['fecha_registro']}"
                    )
                    cc2.markdown(f"Estado: **{row['estado']}**")
        else:
            st.success(
                "✅ No se encontraron oportunidades cercanas ni con nombre "
                "similar registradas. Puedes continuar con el proceso.",
                icon="✅",
            )

        # Mapa de contexto: punto consultado + puntos existentes cercanos (con coordenadas)
        puntos_mapa = cercanos.dropna(subset=["latitud", "longitud"]).copy()
        if not puntos_mapa.empty:
            puntos_mapa["color"] = puntos_mapa["estado"].map(COLOR_ESTADO)
            puntos_mapa["color"] = puntos_mapa["color"].apply(
                lambda x: x if isinstance(x, list) else COLOR_ESTADO["Sin estado"]
            )
            puntos_mapa["tipo"] = "Punto potencial existente"
        nuevo_punto = pd.DataFrame(
            [{"latitud": consulta["lat"], "longitud": consulta["lon"],
              "tipo": "Ubicación consultada", "color": [0, 90, 220],
              "local_identificado": consulta["local_identificado"], "estado": "-"}]
        )
        capas = []
        if not puntos_mapa.empty:
            capas.append(
                pdk.Layer(
                    "ScatterplotLayer",
                    data=puntos_mapa,
                    get_position="[longitud, latitud]",
                    get_fill_color="color",
                    get_radius=25,
                    pickable=True,
                )
            )
        capas.append(
            pdk.Layer(
                "ScatterplotLayer",
                data=nuevo_punto,
                get_position="[longitud, latitud]",
                get_fill_color="color",
                get_radius=35,
                pickable=True,
            )
        )
        vista = pdk.ViewState(latitude=consulta["lat"], longitude=consulta["lon"], zoom=15)
        st.pydeck_chart(
            pdk.Deck(
                layers=capas,
                initial_view_state=vista,
                tooltip={"text": "{tipo}\n{local_identificado}\nEstado: {estado}"},
            )
        )

        st.divider()
        st.write("El especialista decide si continúa con la oportunidad:")
        b1, b2 = st.columns(2)
        if b1.button(
            "➡️ Continuar con la oportunidad (registrar)",
            use_container_width=True,
            type="primary",
        ):
            if not consulta["especialista"] or not consulta["local_identificado"]:
                st.error("Completa especialista y nombre del punto antes de registrar.")
            else:
                st.session_state.puntos = registrar_punto(
                    df,
                    consulta["especialista"],
                    consulta["lat"],
                    consulta["lon"],
                    consulta["local_identificado"],
                    consulta["ciudad"],
                    consulta["upz"],
                    consulta["notas"],
                )
                guardar_puntos(st.session_state.puntos)
                st.success("Punto potencial registrado con estado **Solicitado**.")
                del st.session_state["ultima_consulta"]
                st.rerun()
        if b2.button("✋ Descartar (posible duplicidad confirmada)", use_container_width=True):
            del st.session_state["ultima_consulta"]
            st.rerun()

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

    df_filtrado = df.copy()
    if filtro_ciudad:
        df_filtrado = df_filtrado[df_filtrado["ciudad"].isin(filtro_ciudad)]
    if filtro_especialista:
        df_filtrado = df_filtrado[df_filtrado["especialista"].isin(filtro_especialista)]
    if filtro_estado:
        df_filtrado = df_filtrado[df_filtrado["estado"].isin(filtro_estado)]
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
        "id", "especialista", "ciudad", "upz", "local_identificado",
        "fecha_registro", "estado", "tiendas_evaluadas", "notas",
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

# ---------------------------------------------------------------------------
# TAB 3 · Mapa de oportunidades
# ---------------------------------------------------------------------------
with tab3:
    st.subheader("Mapa general de oportunidades")
    st.write("Visualización general de los puntos potenciales registrados.")

    g1, g2, g3 = st.columns(3)
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

    df_mapa = df[df["estado"].isin(filtro_estado_mapa)]
    if filtro_ciudad_mapa:
        df_mapa = df_mapa[df_mapa["ciudad"].isin(filtro_ciudad_mapa)]
    if filtro_especialista_mapa:
        df_mapa = df_mapa[df_mapa["especialista"].isin(filtro_especialista_mapa)]

    df_mapa = df_mapa.copy()
    df_mapa["color"] = df_mapa["estado"].map(COLOR_ESTADO)
    df_mapa["color"] = df_mapa["color"].apply(
        lambda x: x if isinstance(x, list) else COLOR_ESTADO["Sin estado"]
    )

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
                tooltip={"text": "{local_identificado}\nEspecialista: {especialista}\nEstado: {estado}"},
            )
        )
        st.caption("🔵 Solicitado &nbsp;&nbsp; 🟠 Revisión &nbsp;&nbsp; 🟢 Entregado")
        faltantes_filtro = len(df_mapa) - len(df_mapa_geo)
        if faltantes_filtro:
            st.caption(f"({faltantes_filtro} punto(s) de este filtro no tienen coordenadas y no se muestran en el mapa)")

    st.dataframe(
        df_mapa.drop(columns=["color"]), use_container_width=True, hide_index=True
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

st.divider()
st.caption(
    "Conectado a los datos reales del área (actualizables desde la pestaña "
    "'Actualizar datos'). La herramienta complementa el proceso actual; "
    "no reemplaza el análisis ni el criterio humano."
)
