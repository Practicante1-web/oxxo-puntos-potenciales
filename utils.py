"""
Funciones auxiliares para el aplicativo de consulta y seguimiento
de puntos potenciales (Inteligencia de Expansión - OXXO).
"""

import difflib
import io
import math
import re
import unicodedata
from datetime import datetime

import pandas as pd

CSV_PATH = "data/puntos_potenciales.csv"

# Estados reales que se usan hoy en el Excel del área (columna "Estado").
ESTADOS = ["Solicitado", "Revisión", "Entregado"]

COLOR_ESTADO = {
    "Solicitado": [90, 120, 220],   # azul
    "Revisión": [245, 166, 35],     # naranja
    "Entregado": [46, 160, 67],     # verde
    "Sin estado": [150, 150, 150],  # gris, por si algún registro no trae estado
}

# Distancia (en metros) por debajo de la cual se considera posible
# duplicidad entre dos puntos potenciales.
UMBRAL_DUPLICIDAD_M = 150

# Similitud mínima (0 a 1) entre nombres de local para considerarlos
# "el mismo nombre" (permite pequeñas diferencias de mayúsculas,
# tildes, espacios o typos).
UMBRAL_SIMILITUD_NOMBRE = 0.75

# Columnas del dataset normalizado que usa internamente la app.
COLUMNAS = [
    "id",
    "especialista",
    "ciudad",
    "upz",
    "local_identificado",
    "fecha_registro",
    "estado",
    "estado_comite",
    "latitud",
    "longitud",
    "practicante",
    "tiendas_evaluadas",
    "detalle_microsaturacion",
    "comentarios",
    "notas",
]

# Valores reales que usa hoy el área en la columna "Estatus En Bitacora"
# (el estado que le da el comité a cada punto potencial).
ESTADOS_COMITE = ["Aprobado", "Aprobado con tareas", "Con tareas", "Descartado", "Pausado"]

# Variantes de nombres de ciudad que aparecen escritas de forma distinta
# en el Excel (sin tilde, minúsculas, etc.) y su forma "bonita".
_CIUDADES_CONOCIDAS = {
    "bogota": "Bogotá",
    "medellin": "Medellín",
    "cali": "Cali",
    "cundinamarca": "Cundinamarca",
    "girardot": "Girardot",
    "la calera": "La Calera",
    "pereira": "Pereira",
    "mosquera": "Mosquera",
}


# ---------------------------------------------------------------------------
# Utilidades de texto
# ---------------------------------------------------------------------------
def normalizar_texto(texto: str) -> str:
    """Minúsculas, sin tildes y sin espacios repetidos, para comparar nombres."""
    texto = str(texto or "").strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return " ".join(texto.split())


def normalizar_ciudad(valor) -> str:
    """Unifica variantes de escritura de una misma ciudad (Bogota/Bogotá, etc.)."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    texto = str(valor).strip()
    if not texto:
        return ""
    clave = normalizar_texto(texto)
    return _CIUDADES_CONOCIDAS.get(clave, texto.title())


def similitud_nombre(nombre_a: str, nombre_b: str) -> float:
    """Qué tan parecidos son dos nombres de local (0 = nada, 1 = idéntico)."""
    return difflib.SequenceMatcher(
        None, normalizar_texto(nombre_a), normalizar_texto(nombre_b)
    ).ratio()


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia en metros entre dos coordenadas (fórmula de Haversine)."""
    R = 6371000  # radio de la Tierra en metros
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


# ---------------------------------------------------------------------------
# Carga / guardado del dataset normalizado (el que usa la app día a día)
# ---------------------------------------------------------------------------
def cargar_puntos() -> pd.DataFrame:
    """Carga el 'histórico' de puntos potenciales desde el CSV normalizado."""
    df = pd.read_csv(CSV_PATH)
    df["fecha_registro"] = pd.to_datetime(df["fecha_registro"], errors="coerce").dt.date
    return df


def guardar_puntos(df: pd.DataFrame) -> None:
    """Persiste el DataFrame de puntos potenciales en el CSV normalizado."""
    df.to_csv(CSV_PATH, index=False)


def siguiente_id(df: pd.DataFrame) -> int:
    if df.empty:
        return 1
    return int(df["id"].max()) + 1


# ---------------------------------------------------------------------------
# Importar el Excel/CSV real del área (formato "Revisión Microsaturaciones")
# ---------------------------------------------------------------------------
def _construir_detalle_microsaturacion(fila: pd.Series) -> str:
    """
    Junta las columnas 'Tienda Microsaturada N' + 'Riesgo' (+ 'Tipo de
    estudio') en un solo texto legible para la ficha del punto.
    """
    tienda_cols = [f"Tienda Microsaturada {i}" for i in range(1, 7)]
    riesgo_cols = ["Riesgo", "Riesgo.1", "Riesgo.2", "Riesgo.3", "Riesgo.4", "Riesgo.5"]
    tipo_cols = [
        None,
        "Tipo de estudio",
        "Tipo de estudio.1",
        "Tipo de estudio.2",
        "Tipo de estudio.3",
        "Tipo de estudio.4",
    ]

    partes = []
    for tienda_col, riesgo_col, tipo_col in zip(tienda_cols, riesgo_cols, tipo_cols):
        if tienda_col not in fila.index:
            continue
        tienda = fila.get(tienda_col)
        if pd.isna(tienda) or not str(tienda).strip():
            continue
        texto = str(tienda).strip()
        riesgo = fila.get(riesgo_col) if riesgo_col in fila.index else None
        if riesgo is not None and not pd.isna(riesgo) and str(riesgo).strip():
            texto += f" (riesgo {str(riesgo).strip().lower()}"
            tipo = fila.get(tipo_col) if tipo_col and tipo_col in fila.index else None
            if tipo is not None and not pd.isna(tipo) and str(tipo).strip():
                texto += f", {str(tipo).strip()}"
            texto += ")"
        partes.append(texto)
    return "; ".join(partes)


def leer_archivo_fuente(ruta_o_buffer, nombre_archivo: str = "") -> pd.DataFrame:
    """
    Lee el Excel/CSV real del área ("Revisión Microsaturaciones...") y lo
    convierte al esquema normalizado que usa la app.

    Acepta tanto un path en disco como un buffer en memoria (por ejemplo,
    el archivo que sube el usuario con st.file_uploader). Soporta .csv
    (separador ';', codificación latin-1, decimales con coma) y .xlsx.
    """
    nombre = (nombre_archivo or getattr(ruta_o_buffer, "name", "") or str(ruta_o_buffer)).lower()

    if nombre.endswith(".csv"):
        # El export de Excel a CSV en español suele usar ';' como separador,
        # coma como separador decimal y codificación latin-1.
        crudo = pd.read_csv(
            ruta_o_buffer,
            sep=";",
            encoding="latin-1",
            decimal=",",
            engine="python",
        )
    else:
        crudo = pd.read_excel(ruta_o_buffer)

    return _normalizar_crudo(crudo)


def convertir_link_compartido_a_descarga(url: str) -> str:
    """
    Convierte un link para compartir de OneDrive/SharePoint
    (.../:x:/g/personal/...?e=xxxx) en una URL de descarga directa del
    archivo, agregando el parámetro 'download=1'.

    Esto SOLO funciona si el link está compartido como "Cualquier persona
    con el vínculo" (acceso público). Si está restringido a personas de la
    organización, la descarga automática no funcionará y esta función no
    lo puede evitar — eso depende de los permisos que tenga el archivo en
    OneDrive/SharePoint, no del código.
    """
    url = url.strip()
    if "download=1" in url:
        return url
    separador = "&" if "?" in url else "?"
    return f"{url}{separador}download=1"


def leer_desde_url(url: str, timeout: int = 20) -> pd.DataFrame:
    """
    Descarga un Excel desde un link de OneDrive/SharePoint (o cualquier URL
    directa a un .xlsx) y lo normaliza igual que leer_archivo_fuente.

    Lanza ValueError con un mensaje claro si el link no es de acceso
    público (por ejemplo, si Microsoft responde con una página de inicio
    de sesión en vez del archivo).
    """
    import requests

    url_descarga = convertir_link_compartido_a_descarga(url)
    try:
        resp = requests.get(url_descarga, timeout=timeout, allow_redirects=True)
    except requests.exceptions.RequestException as e:
        raise ValueError(f"No se pudo descargar el archivo: {e}") from e

    content_type = resp.headers.get("Content-Type", "")
    if resp.status_code != 200 or "html" in content_type.lower():
        raise ValueError(
            "El link no devolvió un archivo de Excel (parece requerir inicio "
            "de sesión). Para que esto funcione, el archivo debe compartirse "
            "en OneDrive/SharePoint con el permiso 'Cualquier persona con el "
            "vínculo', no solo 'Personas de la organización'."
        )

    try:
        crudo = pd.read_excel(io.BytesIO(resp.content))
    except Exception as e:
        raise ValueError(f"El archivo descargado no se pudo leer como Excel: {e}") from e

    return _normalizar_crudo(crudo)


# Distintos nombres de columna que hemos visto en los archivos reales del
# área, mapeados a una clave interna común. Las claves de búsqueda están
# normalizadas (minúsculas, sin tildes) para que no importen mayúsculas,
# tildes ni espacios de más.
_VARIANTES_COLUMNAS = {
    "especialista": ["especialista"],
    "ciudad": ["ciudad", "region"],
    "upz": ["upz"],
    "nombre": ["nombre pp", "nombre"],
    "estado": ["estado"],
    "estado_comite": ["estatus en bitacora", "estatus"],
    "latitud": ["latitud"],
    "longitud": ["longitud"],
    "practicante": ["practicante"],
    "tiendas_evaluadas": ["tiendas evaluadas"],
    "fecha_recepcion": ["fecha recepcion"],
    "ms": ["ms (si o no)", "ms"],
    "comentarios": ["comentarios"],
}

# Campos sin los cuales no se puede armar un punto potencial.
_COLUMNAS_REQUERIDAS = {"nombre", "especialista", "latitud", "longitud", "estado"}


def _mapear_columnas(crudo: pd.DataFrame) -> dict:
    """
    Detecta, para cada campo interno (especialista, ciudad, nombre, ...),
    cuál es la columna real del archivo que le corresponde — sin importar
    si el archivo usa 'Nombre PP' o 'NOMBRE', 'Region' o 'CIUDAD', etc.
    """
    normalizados = {}
    for c in crudo.columns:
        clave = normalizar_texto(c)
        if clave not in normalizados:  # conserva la primera columna con ese nombre
            normalizados[clave] = c

    mapeo = {}
    for campo, variantes in _VARIANTES_COLUMNAS.items():
        for variante in variantes:
            if variante in normalizados:
                mapeo[campo] = normalizados[variante]
                break
    return mapeo


def _normalizar_crudo(crudo: pd.DataFrame) -> pd.DataFrame:
    """
    Convierte un DataFrame crudo (recién leído de CSV/Excel, en cualquiera
    de los formatos conocidos del área) al esquema normalizado que usa la app.
    """
    crudo = crudo.copy()
    crudo.columns = [str(c).strip() for c in crudo.columns]

    # Quitar columnas fantasma sin nombre que a veces deja el export de Excel.
    crudo = crudo.loc[:, ~crudo.columns.str.match(r"^Unnamed", na=False)]

    mapeo = _mapear_columnas(crudo)
    faltantes = _COLUMNAS_REQUERIDAS - set(mapeo)
    if faltantes:
        raise ValueError(
            "El archivo no tiene el formato esperado. No se encontró una "
            "columna para: " + ", ".join(sorted(faltantes))
        )

    def columna(campo: str, tabla: pd.DataFrame, default=""):
        if campo in mapeo:
            return tabla[mapeo[campo]]
        return pd.Series([default] * len(tabla), index=tabla.index)

    # Quitar filas completamente vacías (renglones fantasma del export).
    # El reset_index es importante: si no, al filtrar quedan índices con
    # huecos y las asignaciones de columnas más abajo se desalinean.
    mascara_real = columna("nombre", crudo).notna() | columna("especialista", crudo).notna()
    real = crudo[mascara_real].copy()
    real = real.reset_index(drop=True)

    normalizado = pd.DataFrame()
    normalizado["id"] = range(1, len(real) + 1)
    normalizado["especialista"] = columna("especialista", real).fillna("").astype(str).str.strip()
    normalizado["ciudad"] = columna("ciudad", real).apply(normalizar_ciudad)
    normalizado["upz"] = columna("upz", real).fillna("").astype(str).str.strip()
    normalizado["local_identificado"] = columna("nombre", real).fillna("").astype(str).str.strip()
    normalizado["fecha_registro"] = pd.to_datetime(
        columna("fecha_recepcion", real), dayfirst=True, errors="coerce"
    ).dt.date
    normalizado["estado"] = (
        columna("estado", real).fillna("Sin estado").astype(str).str.strip().replace("", "Sin estado")
    )
    # Estado ante comité (columna "Estatus En Bitacora" en el archivo real).
    # Vacío significa que el punto todavía no ha pasado por comité.
    normalizado["estado_comite"] = columna("estado_comite", real).fillna("").astype(str).str.strip()
    normalizado["latitud"] = pd.to_numeric(columna("latitud", real), errors="coerce")
    normalizado["longitud"] = pd.to_numeric(columna("longitud", real), errors="coerce")
    normalizado["practicante"] = columna("practicante", real).fillna("").astype(str).str.strip()
    normalizado["tiendas_evaluadas"] = (
        pd.to_numeric(columna("tiendas_evaluadas", real, 0), errors="coerce").fillna(0).astype(int)
    )

    if "Tienda Microsaturada 1" in real.columns:
        # Formato "Revisión Microsaturaciones": detalle tienda por tienda.
        normalizado["detalle_microsaturacion"] = real.apply(_construir_detalle_microsaturacion, axis=1)
    else:
        # Formato simplificado: solo el indicador "MS (SI O NO)".
        ms = columna("ms", real, "").fillna("").astype(str).str.strip()
        normalizado["detalle_microsaturacion"] = ms.apply(
            lambda v: f"Microsaturación: {v}" if v and v.strip().lower() not in ("no", "nan") else ""
        )

    normalizado["comentarios"] = columna("comentarios", real).fillna("").astype(str).str.strip()
    normalizado["notas"] = ""

    # Red de seguridad adicional por si queda alguna fila realmente vacía.
    normalizado = normalizado[
        (normalizado["local_identificado"].str.strip() != "")
        | (normalizado["especialista"].str.strip() != "")
    ].copy()
    normalizado["id"] = range(1, len(normalizado) + 1)

    return normalizado[COLUMNAS]


# ---------------------------------------------------------------------------
# Búsqueda de cercanos / coincidencias por nombre
# ---------------------------------------------------------------------------
def buscar_cercanos(
    df: pd.DataFrame, lat: float, lon: float, umbral_m: float = UMBRAL_DUPLICIDAD_M
) -> pd.DataFrame:
    """
    Devuelve los puntos existentes (con coordenadas) dentro del umbral (en
    metros) de la coordenada dada, ordenados de más cercano a más lejano.
    """
    con_coords = df.dropna(subset=["latitud", "longitud"])
    if con_coords.empty:
        return con_coords.assign(distancia_m=[])

    distancias = con_coords.apply(
        lambda row: haversine_m(lat, lon, row["latitud"], row["longitud"]), axis=1
    )
    resultado = con_coords.copy()
    resultado["distancia_m"] = distancias.round(1)
    resultado = resultado[resultado["distancia_m"] <= umbral_m]
    return resultado.sort_values("distancia_m")


def buscar_por_nombre(
    df: pd.DataFrame, nombre: str, umbral_similitud: float = UMBRAL_SIMILITUD_NOMBRE
) -> pd.DataFrame:
    """
    Busca puntos potenciales cuyo 'local_identificado' sea igual o muy
    parecido al nombre dado, sin importar en qué parte del mapa estén (o si
    tienen coordenadas registradas).
    """
    if df.empty or not nombre or not nombre.strip():
        return df.assign(similitud_nombre=[])

    resultado = df.copy()
    resultado["similitud_nombre"] = resultado["local_identificado"].apply(
        lambda x: round(similitud_nombre(nombre, x), 2)
    )
    resultado = resultado[resultado["similitud_nombre"] >= umbral_similitud]
    return resultado.sort_values("similitud_nombre", ascending=False)


def buscar_coordenada_por_direccion(direccion: str, timeout: int = 10):
    """
    Busca una dirección escrita (como en el buscador de Google Maps) y
    devuelve (lat, lon, nombre_encontrado) del resultado más probable.

    Usa el buscador gratuito de OpenStreetMap (Nominatim) — no necesita
    API key ni cuenta de Google. Devuelve None si no encuentra nada o si
    falla la conexión.
    """
    import requests

    direccion = (direccion or "").strip()
    if not direccion:
        return None

    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": direccion,
                "format": "json",
                "limit": 1,
                "countrycodes": "co",
            },
            headers={"User-Agent": "oxxo-puntos-potenciales-app (practica-oxxo)"},
            timeout=timeout,
        )
        resp.raise_for_status()
        resultados = resp.json()
    except Exception:
        return None

    if not resultados:
        return None

    primero = resultados[0]
    try:
        lat = float(primero["lat"])
        lon = float(primero["lon"])
    except (KeyError, TypeError, ValueError):
        return None

    return lat, lon, primero.get("display_name", direccion)


def parsear_coordenada_pegada(texto: str):
    """
    Si el texto que la persona pegó ya es una coordenada (ej. '4.697614,
    -74.092287' o '4.697614 -74.092287', tal cual la copia Google Maps),
    devuelve (lat, lon). Si no tiene esa forma, devuelve None.
    """
    texto = (texto or "").strip()
    if not texto:
        return None
    patron = re.match(r"^\s*(-?\d+(?:\.\d+)?)\s*[,\s]\s*(-?\d+(?:\.\d+)?)\s*$", texto)
    if not patron:
        return None
    lat, lon = float(patron.group(1)), float(patron.group(2))
    if -90 <= lat <= 90 and -180 <= lon <= 180:
        return lat, lon
    return None


def buscar_lugar(texto: str, timeout: int = 10):
    """
    Buscador único: acepta una coordenada pegada (como la copia Google
    Maps) O una dirección escrita, igual que el buscador normal de Google
    Maps. Devuelve (lat, lon, etiqueta) o None si no encontró nada.
    """
    como_coordenada = parsear_coordenada_pegada(texto)
    if como_coordenada is not None:
        lat, lon = como_coordenada
        return lat, lon, f"Coordenada {lat:.6f}, {lon:.6f}"
    return buscar_coordenada_por_direccion(texto, timeout=timeout)


def detectar_coincidencias(
    df: pd.DataFrame,
    lat: float,
    lon: float,
    nombre: str = "",
    umbral_m: float = UMBRAL_DUPLICIDAD_M,
    umbral_similitud: float = UMBRAL_SIMILITUD_NOMBRE,
) -> pd.DataFrame:
    """
    Detecta posibles coincidencias combinando dos criterios:
    - Ubicación cercana (distancia <= umbral_m), solo entre puntos que sí
      tienen coordenadas registradas.
    - Nombre de local igual o muy parecido, esté cerca, lejos o sin coordenadas.

    Devuelve los puntos que cumplen al menos uno de los dos criterios,
    con una columna 'coincide_por' que explica la razón.
    """
    if df.empty:
        return df.assign(distancia_m=[], similitud_nombre=[], coincide_por=[])

    resultado = df.copy()
    resultado["distancia_m"] = df.apply(
        lambda row: (
            round(haversine_m(lat, lon, row["latitud"], row["longitud"]), 1)
            if pd.notna(row["latitud"]) and pd.notna(row["longitud"])
            else float("inf")
        ),
        axis=1,
    )
    nombre = (nombre or "").strip()
    if nombre:
        resultado["similitud_nombre"] = df["local_identificado"].apply(
            lambda x: round(similitud_nombre(nombre, x), 2)
        )
    else:
        resultado["similitud_nombre"] = 0.0

    por_distancia = resultado["distancia_m"] <= umbral_m
    por_nombre = resultado["similitud_nombre"] >= umbral_similitud

    resultado["coincide_por"] = ""
    resultado.loc[por_distancia & por_nombre, "coincide_por"] = "Ubicación y nombre"
    resultado.loc[por_distancia & ~por_nombre, "coincide_por"] = "Ubicación cercana"
    resultado.loc[~por_distancia & por_nombre, "coincide_por"] = "Nombre similar"

    return resultado[por_distancia | por_nombre].sort_values("distancia_m")


# ---------------------------------------------------------------------------
# Generadores (Survey123 / ArcGIS Online) — evitar duplicidad de generadores
# ---------------------------------------------------------------------------
# Capa pública de resultados de la encuesta de generadores (Survey123).
# Confirmada como accesible sin inicio de sesión.
URL_GENERADORES = (
    "https://services.arcgis.com/mcvxP1ZaVXPjA6pf/arcgis/rest/services/"
    "survey123_b917f791dc994dc5a9d45c398c77ceb4_results/FeatureServer/0"
)

GENERADORES_CSV_PATH = "data/generadores_cache.csv"

# Umbral (en metros) para considerar que dos registros de generador son en
# realidad el mismo lugar físico, si además el nombre es parecido. Acordado
# con el área: 300 m (el mismo radio con el que se recogen generadores
# alrededor de un punto potencial).
UMBRAL_DUPLICIDAD_GENERADOR_M = 300

GENERADOR_COLUMNAS = [
    "localizador",
    "nombre_punto_potencial",
    "nombre_generador",
    "tipo_generador",
    "tipo_generador_otro",
    "empleados_habitantes",
    "unidades_residenciales",
    "trafico_peatonal",
    "trafico_vehicular",
    "comentarios",
    "fecha_creacion",
    "creador",
    "latitud",
    "longitud",
]


def leer_generadores_desde_arcgis(url: str = URL_GENERADORES, timeout: int = 20) -> pd.DataFrame:
    """
    Descarga en vivo los registros de la capa de generadores (Survey123 /
    ArcGIS Online) vía su servicio REST público, y los normaliza al
    esquema que usa la app.

    Lanza ValueError con un mensaje claro si el servicio no responde, no
    es accesible, o devuelve un error (por ejemplo si la capa dejó de ser
    pública).
    """
    import requests

    # El servicio limita cuántos registros devuelve por consulta (viene
    # marcado con "exceededTransferLimit": true cuando hay más), así que
    # hay que paginar con "resultOffset" hasta traerlos todos.
    todas_las_features = []
    offset = 0
    while True:
        try:
            resp = requests.get(
                f"{url}/query",
                params={
                    "where": "1=1",
                    "outFields": "*",
                    "outSR": 4326,
                    "returnGeometry": "true",
                    "resultOffset": offset,
                    "f": "json",
                },
                timeout=timeout,
            )
        except requests.exceptions.RequestException as e:
            raise ValueError(f"No se pudo conectar con la capa de generadores: {e}") from e

        try:
            datos = resp.json()
        except Exception as e:
            raise ValueError(f"La capa de generadores no devolvió un JSON válido: {e}") from e

        if "error" in datos:
            mensaje = datos["error"].get("message", "error desconocido")
            raise ValueError(
                f"La capa de generadores devolvió un error ({mensaje}). Puede que "
                "haya dejado de ser pública o que la URL haya cambiado."
            )

        pagina = datos.get("features", [])
        todas_las_features.extend(pagina)

        if not datos.get("exceededTransferLimit") or not pagina:
            break
        offset += len(pagina)

    filas = []
    for feat in todas_las_features:
        attrs = feat.get("attributes", {})
        geom = feat.get("geometry") or {}
        filas.append(
            {
                "localizador": attrs.get("localizador") or "",
                "nombre_punto_potencial": attrs.get("nombre_del_punto_potencial") or "",
                "nombre_generador": attrs.get("nombre_del_generador") or "",
                "tipo_generador": attrs.get("tipo_de_generador") or "",
                "tipo_generador_otro": attrs.get("tipo_de_generador_other") or "",
                "empleados_habitantes": attrs.get("cantidad_de_empleados_o_habitan"),
                "unidades_residenciales": attrs.get("cantidad_de_unidades_residencia"),
                "trafico_peatonal": attrs.get("tr_fico_peatonal_promedio_15_mi"),
                "trafico_vehicular": attrs.get("tr_fico_vehicular_promedio_15_m"),
                "comentarios": attrs.get("comentarios_de_la_ubicaci_n") or "",
                "fecha_creacion": attrs.get("CreationDate"),
                "creador": attrs.get("Creator") or "",
                "latitud": geom.get("y"),
                "longitud": geom.get("x"),
            }
        )

    df = pd.DataFrame(filas, columns=GENERADOR_COLUMNAS)
    if not df.empty:
        df["fecha_creacion"] = pd.to_datetime(
            df["fecha_creacion"], unit="ms", errors="coerce"
        ).dt.date
        df["latitud"] = pd.to_numeric(df["latitud"], errors="coerce")
        df["longitud"] = pd.to_numeric(df["longitud"], errors="coerce")
        df["nombre_generador"] = df["nombre_generador"].fillna("").astype(str).str.strip()
        df["nombre_punto_potencial"] = (
            df["nombre_punto_potencial"].fillna("").astype(str).str.strip()
        )
    return df


def cargar_generadores_cache() -> pd.DataFrame:
    """Última copia de generadores guardada localmente (respaldo si falla la conexión en vivo)."""
    try:
        df = pd.read_csv(GENERADORES_CSV_PATH)
        df["fecha_creacion"] = pd.to_datetime(df["fecha_creacion"], errors="coerce").dt.date
        return df
    except FileNotFoundError:
        return pd.DataFrame(columns=GENERADOR_COLUMNAS)


def guardar_generadores(df: pd.DataFrame) -> None:
    """Guarda una copia local de los generadores, como respaldo por si falla la conexión en vivo."""
    df.to_csv(GENERADORES_CSV_PATH, index=False)


def detectar_generadores_coincidentes(
    df_generadores: pd.DataFrame,
    nombre: str,
    lat: float,
    lon: float,
    umbral_m: float = UMBRAL_DUPLICIDAD_GENERADOR_M,
    umbral_similitud: float = UMBRAL_SIMILITUD_NOMBRE,
) -> pd.DataFrame:
    """
    Busca, entre TODOS los registros de generadores (sin importar a qué
    punto potencial estén asociados), aquellos que probablemente sean el
    mismo lugar físico que el que se está por registrar: nombre parecido
    Y a menos de `umbral_m` metros.

    Útil para consultar antes de registrar un generador nuevo en
    Survey123: si ya existe algo parecido cerca, conviene vincularlo al
    punto actual en vez de crear un registro nuevo.
    """
    columnas_resultado = list(GENERADOR_COLUMNAS) + ["distancia_m", "similitud_nombre"]
    if df_generadores.empty or not nombre or not nombre.strip():
        return df_generadores.reindex(columns=columnas_resultado).iloc[0:0]

    con_coords = df_generadores.dropna(subset=["latitud", "longitud"]).copy()
    if con_coords.empty:
        return df_generadores.reindex(columns=columnas_resultado).iloc[0:0]

    con_coords["distancia_m"] = con_coords.apply(
        lambda row: round(haversine_m(lat, lon, row["latitud"], row["longitud"]), 1), axis=1
    )
    con_coords["similitud_nombre"] = con_coords["nombre_generador"].apply(
        lambda x: round(similitud_nombre(nombre, x), 2)
    )

    coincidencias = con_coords[
        (con_coords["distancia_m"] <= umbral_m)
        & (con_coords["similitud_nombre"] >= umbral_similitud)
    ]
    return coincidencias.sort_values("distancia_m")[columnas_resultado]


def agrupar_generadores(
    df_generadores: pd.DataFrame,
    umbral_m: float = UMBRAL_DUPLICIDAD_GENERADOR_M,
    umbral_similitud: float = UMBRAL_SIMILITUD_NOMBRE,
) -> pd.DataFrame:
    """
    Agrupa los registros crudos de generadores que probablemente sean el
    mismo lugar físico (nombre parecido + cercanos) en un solo renglón por
    generador único, listando todos los puntos potenciales a los que
    quedó vinculado.

    Es un agrupamiento voraz (greedy): recorre los registros uno por uno
    y los suma al primer grupo existente con el que calcen; si no calzan
    con ninguno, abren un grupo nuevo. Con cientos de registros esto es
    rápido y suficientemente preciso para el caso de uso (revisar
    duplicidad), aunque no es un clustering óptimo.
    """
    columnas = [
        "nombre_generador", "tipo_generador", "latitud", "longitud",
        "cantidad_registros", "puntos_asociados",
    ]
    con_coords = df_generadores.dropna(subset=["latitud", "longitud"]).copy()
    if con_coords.empty:
        return pd.DataFrame(columns=columnas)

    grupos = []  # cada grupo: dict con nombre, tipo, lat, lon, registros (list of rows)

    for _, fila in con_coords.iterrows():
        nombre = fila["nombre_generador"]
        lat, lon = fila["latitud"], fila["longitud"]
        grupo_encontrado = None
        for grupo in grupos:
            distancia = haversine_m(lat, lon, grupo["latitud"], grupo["longitud"])
            similitud = similitud_nombre(nombre, grupo["nombre_generador"])
            if distancia <= umbral_m and similitud >= umbral_similitud:
                grupo_encontrado = grupo
                break

        if grupo_encontrado is not None:
            grupo_encontrado["registros"].append(fila)
            punto = str(fila.get("nombre_punto_potencial", "")).strip()
            if punto and punto not in grupo_encontrado["puntos"]:
                grupo_encontrado["puntos"].append(punto)
        else:
            punto = str(fila.get("nombre_punto_potencial", "")).strip()
            grupos.append(
                {
                    "nombre_generador": nombre,
                    "tipo_generador": fila.get("tipo_generador", ""),
                    "latitud": lat,
                    "longitud": lon,
                    "registros": [fila],
                    "puntos": [punto] if punto else [],
                }
            )

    resultado = pd.DataFrame(
        [
            {
                "nombre_generador": g["nombre_generador"],
                "tipo_generador": g["tipo_generador"],
                "latitud": g["latitud"],
                "longitud": g["longitud"],
                "cantidad_registros": len(g["registros"]),
                "puntos_asociados": ", ".join(g["puntos"]) if g["puntos"] else "",
            }
            for g in grupos
        ],
        columns=columnas,
    )
    return resultado.sort_values("cantidad_registros", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Registro de nuevos puntos (desde el formulario de la app)
# ---------------------------------------------------------------------------
def registrar_punto(
    df: pd.DataFrame,
    especialista: str,
    lat: float,
    lon: float,
    local_identificado: str,
    ciudad: str = "",
    upz: str = "",
    notas: str = "",
) -> pd.DataFrame:
    """Agrega un nuevo punto potencial al DataFrame y lo retorna."""
    nuevo = {
        "id": siguiente_id(df),
        "especialista": especialista,
        "ciudad": ciudad,
        "upz": upz,
        "local_identificado": local_identificado,
        "fecha_registro": datetime.now().date(),
        "estado": "Solicitado",
        "estado_comite": "",
        "latitud": lat,
        "longitud": lon,
        "practicante": "",
        "tiendas_evaluadas": 0,
        "detalle_microsaturacion": "",
        "comentarios": "",
        "notas": notas,
    }
    return pd.concat([df, pd.DataFrame([nuevo])], ignore_index=True)


def eliminar_punto(df: pd.DataFrame, id_punto: int) -> pd.DataFrame:
    """Elimina el punto con ese id (por ejemplo, uno de prueba) y retorna el DataFrame resultante."""
    return df[df["id"] != id_punto].reset_index(drop=True)
