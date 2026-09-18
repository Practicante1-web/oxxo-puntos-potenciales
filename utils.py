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
    "fuente",
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

# Módulo 1 ahora combina puntos potenciales de 4 orígenes distintos en un
# solo mapa por capas. Cada uno tiene su propio color de pin (ver
# iconos.py) para poder distinguirlos de un vistazo.
FUENTE_ESPECIALISTAS = "Especialistas"
FUENTE_OPERACION = "Operación"
FUENTE_TERCEROS = "Terceros"
FUENTE_INMOBILIARIA = "Inmobiliaria"

FUENTE_COLOR_ICONO = {
    FUENTE_ESPECIALISTAS: "morado",
    FUENTE_OPERACION: "azul_claro",
    FUENTE_TERCEROS: "rosado",
    FUENTE_INMOBILIARIA: "verde",
}

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


# Hoja del Excel del área donde vive el "Estatus En Bitacora" real (columna
# de estado de comité). El archivo puede traer varias hojas; si esta no
# existe (por ejemplo, un CSV, o un archivo distinto), se usa la primera
# hoja como respaldo en vez de fallar.
HOJA_EXCEL_PREFERIDA = "ISO (2)"


def _leer_excel_hoja_preferida(fuente) -> pd.DataFrame:
    """
    Lee el Excel priorizando la hoja donde vive el estatus de comité.

    En vez de exigir que el nombre de la hoja sea EXACTAMENTE
    "ISO (2)" (lo que se rompe con cosas tan tontas como un espacio de más
    o mayúsculas distintas), esto hace dos cosas para ser más tolerante:

    1) Busca, entre todas las hojas del archivo, una cuyo nombre normalizado
       (sin mayúsculas, sin espacios de más) coincida con HOJA_EXCEL_PREFERIDA.
    2) Si no la encuentra por nombre, busca entre TODAS las hojas cuál tiene
       una columna que se parezca a "Estatus en bitácora" (la que trae el
       estado de comité) y usa esa — así, aunque le cambien el nombre a la
       hoja el próximo mes, la app la sigue encontrando sola.

    Si ninguna de las dos búsquedas encuentra nada, usa la primera hoja
    como respaldo (como antes), para no dejar la app sin datos.
    """
    if hasattr(fuente, "seek"):
        fuente.seek(0)

    try:
        excel = pd.ExcelFile(fuente)
    except Exception:
        if hasattr(fuente, "seek"):
            fuente.seek(0)
        return pd.read_excel(fuente, sheet_name=0)

    nombres_hojas = excel.sheet_names
    objetivo_normalizado = normalizar_texto(HOJA_EXCEL_PREFERIDA)

    # 1) Coincidencia de nombre, tolerante a espacios/mayúsculas.
    for nombre_hoja in nombres_hojas:
        if normalizar_texto(nombre_hoja) == objetivo_normalizado:
            return excel.parse(sheet_name=nombre_hoja)

    # 2) Ninguna hoja se llama así — busca cuál tiene la columna de estatus.
    variantes_estatus = {normalizar_texto(v) for v in _VARIANTES_COLUMNAS["estado_comite"]}
    for nombre_hoja in nombres_hojas:
        try:
            columnas_hoja = {normalizar_texto(c) for c in excel.parse(sheet_name=nombre_hoja, nrows=0).columns}
        except Exception:
            continue
        if columnas_hoja & variantes_estatus:
            return excel.parse(sheet_name=nombre_hoja)

    # 3) Respaldo: primera hoja, como se hacía antes.
    return excel.parse(sheet_name=0)


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
        crudo = _leer_excel_hoja_preferida(ruta_o_buffer)

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
        crudo = _leer_excel_hoja_preferida(io.BytesIO(resp.content))
    except Exception as e:
        raise ValueError(f"El archivo descargado no se pudo leer como Excel: {e}") from e

    return _normalizar_crudo(crudo)


def leer_fuentes_modulo1_desde_url(url: str, timeout: int = 20) -> pd.DataFrame:
    """
    Igual que leer_desde_url, pero para el Excel multi-hoja del Módulo 1
    (Especialistas + Terceros + Operación + Inmobiliaria si existe). Usa
    leer_fuentes_modulo1 para el parseo en vez de _normalizar_crudo, para
    que la conexión en vivo a OneDrive funcione igual con el archivo nuevo
    de varias hojas.
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
        return leer_fuentes_modulo1(io.BytesIO(resp.content))
    except Exception as e:
        raise ValueError(f"El archivo descargado no se pudo leer como Excel: {e}") from e


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
    normalizado["fuente"] = FUENTE_ESPECIALISTAS
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
# Módulo 1 con varias fuentes: especialistas (arriba) + operación + terceros
# + inmobiliaria — todas viven en UN SOLO archivo Excel, una hoja por fuente.
# ---------------------------------------------------------------------------
def _col_por_nombres(tabla: pd.DataFrame, nombres_posibles: list, default=""):
    """
    Busca, en `tabla`, una columna cuyo nombre (normalizado, sin tildes/
    espacios de más) coincida con alguno de `nombres_posibles` — para no
    depender de que el archivo tenga el nombre EXACTO (ej. 'Especialista
    asignado ' con espacio al final).
    """
    normalizados = {normalizar_texto(c): c for c in tabla.columns}
    for nombre in nombres_posibles:
        clave = normalizar_texto(nombre)
        if clave in normalizados:
            return tabla[normalizados[clave]]
    return pd.Series([default] * len(tabla), index=tabla.index)


def _buscar_hoja(excel: "pd.ExcelFile", palabras_clave: list):
    """
    Busca, entre las hojas de un Excel, la primera cuyo nombre (normalizado)
    contenga alguna de las palabras clave dadas — tolerante a que renombren
    la hoja ligeramente (ej. 'Visitas_Operaciones' o 'Operaciones 2026').
    Devuelve el nombre de la hoja, o None si no encontró ninguna.
    """
    for nombre_hoja in excel.sheet_names:
        clave = normalizar_texto(nombre_hoja)
        if any(normalizar_texto(palabra) in clave for palabra in palabras_clave):
            return nombre_hoja
    return None


def _parsear_terceros(crudo: pd.DataFrame) -> pd.DataFrame:
    """Normaliza la hoja 'Base puntos terceros' al esquema común (COLUMNAS)."""
    crudo = crudo.copy()
    crudo.columns = [str(c).strip() for c in crudo.columns]
    # El export de Excel suele dejar cientos de miles de filas "fantasma"
    # vacías (formato aplicado a toda la columna) — se descartan antes de
    # procesar nada, quedándose solo con las filas que sí tienen un
    # proyecto/nombre.
    crudo = crudo[_col_por_nombres(crudo, ["Proyecto"]).notna()].reset_index(drop=True)
    n = len(crudo)

    coords = _col_por_nombres(crudo, ["Coordenadas"])
    lat_lon = coords.apply(parsear_coordenada_pegada)
    latitud = lat_lon.apply(lambda v: v[0] if v else None)
    longitud = lat_lon.apply(lambda v: v[1] if v else None)

    razon_descarte = _col_por_nombres(crudo, ["Razón de descarte"]).fillna("").astype(str).str.strip()
    comentario_descarte = _col_por_nombres(crudo, ["Comentarios de descarte"]).fillna("").astype(str).str.strip()
    comentario_int = _col_por_nombres(crudo, ["Comentarios Int Exp"]).fillna("").astype(str).str.strip()
    localizador = _col_por_nombres(crudo, ["Localizador"]).fillna("").astype(str).str.strip()
    propietario = _col_por_nombres(crudo, ["Nombre de propietario"]).fillna("").astype(str).str.strip()
    contacto = _col_por_nombres(crudo, ["Contacto propietario"]).fillna("").astype(str).str.strip()

    notas_partes = []
    for i in range(n):
        piezas = []
        if localizador.iloc[i] and localizador.iloc[i].lower() != "no aplica":
            piezas.append(f"Localizador: {localizador.iloc[i]}")
        if propietario.iloc[i]:
            piezas.append(f"Propietario: {propietario.iloc[i]}")
        if contacto.iloc[i]:
            piezas.append(f"Contacto: {contacto.iloc[i]}")
        notas_partes.append(" · ".join(piezas))

    comentarios_final = []
    for i in range(n):
        piezas = [p for p in [comentario_int.iloc[i], comentario_descarte.iloc[i]] if p]
        comentarios_final.append(" | ".join(piezas))

    normalizado = pd.DataFrame()
    normalizado["fuente"] = [FUENTE_TERCEROS] * n
    normalizado["especialista"] = (
        _col_por_nombres(crudo, ["Especialista asignado"]).fillna("").astype(str).str.strip()
    )
    normalizado["ciudad"] = _col_por_nombres(crudo, ["Ciudad"]).apply(normalizar_ciudad)
    normalizado["upz"] = _col_por_nombres(crudo, ["Plaza"]).fillna("").astype(str).str.strip()
    normalizado["local_identificado"] = (
        _col_por_nombres(crudo, ["Proyecto"]).fillna("").astype(str).str.strip()
    )
    normalizado["fecha_registro"] = pd.to_datetime(
        _col_por_nombres(crudo, ["Fecha de recepción", "Fecha de recepcion"]), errors="coerce"
    ).dt.date
    normalizado["estado"] = (
        _col_por_nombres(crudo, ["Estatus general"]).fillna("Sin estado").astype(str).str.strip()
        .replace("", "Sin estado")
    )
    normalizado["estado_comite"] = razon_descarte  # se reutiliza como "por qué se descartó", si aplica
    normalizado["latitud"] = pd.to_numeric(latitud, errors="coerce")
    normalizado["longitud"] = pd.to_numeric(longitud, errors="coerce")
    normalizado["practicante"] = ""
    normalizado["tiendas_evaluadas"] = 0
    normalizado["detalle_microsaturacion"] = ""
    normalizado["comentarios"] = comentarios_final
    normalizado["notas"] = notas_partes

    normalizado = normalizado[normalizado["local_identificado"].str.strip() != ""].reset_index(drop=True)
    return normalizado


def _parsear_operacion(crudo: pd.DataFrame) -> pd.DataFrame:
    """Normaliza la hoja 'Visitas_Operaciones' al esquema común (COLUMNAS)."""
    crudo = crudo.copy()
    crudo.columns = [str(c).strip() for c in crudo.columns]
    crudo = crudo[_col_por_nombres(crudo, ["Nombre del Punto"]).notna()].reset_index(drop=True)
    n = len(crudo)

    direccion = _col_por_nombres(crudo, ["Dirección", "Direccion"]).fillna("").astype(str).str.strip()
    razon_descarte = _col_por_nombres(
        crudo, ["Razón de descarte expansión", "Razon de descarte"]
    ).fillna("").astype(str).str.strip()
    comentarios = _col_por_nombres(crudo, ["Comentarios expansión", "Comentarios"]).fillna("").astype(str).str.strip()

    notas_partes = [f"Dirección: {d}" if d else "" for d in direccion]

    normalizado = pd.DataFrame()
    normalizado["fuente"] = [FUENTE_OPERACION] * n
    normalizado["especialista"] = (
        _col_por_nombres(crudo, ["Especialista asignado"]).fillna("").astype(str).str.strip()
    )
    especialista_vacio = normalizado["especialista"].str.strip() == ""
    jefe_zona = _col_por_nombres(crudo, ["Jefe de zona"]).fillna("").astype(str).str.strip()
    normalizado.loc[especialista_vacio, "especialista"] = jefe_zona[especialista_vacio]

    normalizado["ciudad"] = _col_por_nombres(crudo, ["Plaza", "Región", "Region"]).apply(normalizar_ciudad)
    normalizado["upz"] = ""
    normalizado["local_identificado"] = (
        _col_por_nombres(crudo, ["Nombre del Punto"]).fillna("").astype(str).str.strip()
    )
    normalizado["fecha_registro"] = pd.to_datetime(
        _col_por_nombres(crudo, ["Fecha de inicio"]), errors="coerce"
    ).dt.date
    normalizado["estado"] = (
        _col_por_nombres(crudo, ["Estado Growth", "Estado"]).fillna("Sin estado").astype(str).str.strip()
        .replace("", "Sin estado")
    )
    normalizado["estado_comite"] = razon_descarte
    normalizado["latitud"] = pd.to_numeric(_col_por_nombres(crudo, ["Y"]), errors="coerce")
    normalizado["longitud"] = pd.to_numeric(_col_por_nombres(crudo, ["X"]), errors="coerce")
    normalizado["practicante"] = _col_por_nombres(crudo, ["Gestor asignado"]).fillna("").astype(str).str.strip()
    normalizado["tiendas_evaluadas"] = 0
    normalizado["detalle_microsaturacion"] = ""
    normalizado["comentarios"] = comentarios
    normalizado["notas"] = notas_partes

    normalizado = normalizado[normalizado["local_identificado"].str.strip() != ""].reset_index(drop=True)
    return normalizado


def leer_fuentes_modulo1(ruta_o_buffer, nombre_archivo: str = "") -> pd.DataFrame:
    """
    Lee el Excel de Módulo 1 (una hoja por fuente: especialistas/ISO,
    'Base puntos terceros', 'Visitas_Operaciones') y devuelve UN SOLO
    DataFrame combinado, ya normalizado, con la columna 'fuente' marcando
    de dónde viene cada punto (ver FUENTE_ESPECIALISTAS/OPERACION/TERCEROS).

    Es tolerante a que las hojas no se llamen EXACTAMENTE así: busca por
    palabras clave en el nombre de la hoja. Si alguna de las 3 no aparece,
    simplemente no aporta puntos de esa fuente (no rompe la carga de las
    demás) — pensado para cuando alguna fuente todavía no tiene datos.
    """
    if hasattr(ruta_o_buffer, "seek"):
        ruta_o_buffer.seek(0)
    excel = pd.ExcelFile(ruta_o_buffer)

    partes = []
    errores = []

    hoja_esp = _buscar_hoja(excel, ["iso"])
    if hoja_esp:
        try:
            partes.append(_normalizar_crudo(excel.parse(sheet_name=hoja_esp)))
        except Exception as e:
            errores.append(f"Especialistas (hoja '{hoja_esp}'): {e}")

    hoja_ter = _buscar_hoja(excel, ["terceros"])
    if hoja_ter:
        try:
            partes.append(_parsear_terceros(excel.parse(sheet_name=hoja_ter)))
        except Exception as e:
            errores.append(f"Terceros (hoja '{hoja_ter}'): {e}")

    hoja_ope = _buscar_hoja(excel, ["operacion", "operaciones", "visitas"])
    if hoja_ope:
        try:
            partes.append(_parsear_operacion(excel.parse(sheet_name=hoja_ope)))
        except Exception as e:
            errores.append(f"Operación (hoja '{hoja_ope}'): {e}")

    if not partes:
        detalle = ("; " + "; ".join(errores)) if errores else ""
        raise ValueError(
            "No se encontró ninguna hoja reconocible en el archivo (se "
            "buscaron nombres con 'ISO', 'terceros' u 'operación')" + detalle
        )

    combinado = pd.concat(partes, ignore_index=True)
    combinado["id"] = range(1, len(combinado) + 1)
    combinado = combinado.reindex(columns=COLUMNAS, fill_value="")
    return combinado


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


def detectar_duplicados_potenciales(
    df: pd.DataFrame,
    umbral_m: float = UMBRAL_DUPLICIDAD_M,
    umbral_coordenada_m: float = 15,
    umbral_similitud: float = UMBRAL_SIMILITUD_NOMBRE,
) -> pd.DataFrame:
    """
    Arma la tabla de "posibles duplicados" de Módulo 1, mirando TODAS las
    fuentes juntas (especialistas, operación, terceros, inmobiliaria) —
    porque el punto de este módulo es justo evitar que el mismo local se
    registre dos veces sin importar quién lo mandó.

    Dos puntos se consideran el mismo lugar si:
    1. Coordenada casi exacta (≤ umbral_coordenada_m, 15 m) — sin importar
       el nombre.
    2. Distancia dentro del radio de recolección (≤ umbral_m) Y nombre
       parecido (≥ umbral_similitud).
    3. Nombre IDÉNTICO (normalizado: sin tildes/mayúsculas/espacios de
       más), sin importar qué tan lejos estén — puede ser un error de
       coordenada, o el mismo local escrito igual por dos personas.

    Devuelve UNA FILA POR CADA PAR duplicado (no por grupo), con: nombre,
    nombre_duplicado, coordenadas de cada uno, distancia_m, motivo y
    fuente/fuente_duplicado (qué fuentes están involucradas, ej.
    "Especialistas" y "Terceros" — útil para detectar cuando dos áreas
    distintas están mirando el mismo local sin saberlo).

    Por rendimiento (con cientos/miles de puntos, comparar TODOS contra
    TODOS sería muy lento), los criterios 1 y 2 usan una cuadrícula
    espacial: cada punto solo se compara contra los que caen en su misma
    celda o una vecina (~3x umbral_m de lado), nunca contra el dataset
    completo. El criterio 3 agrupa por nombre normalizado (hash), también
    sin comparar todos contra todos.
    """
    columnas = [
        "nombre", "nombre_duplicado", "latitud", "longitud", "latitud_duplicado",
        "longitud_duplicado", "distancia_m", "motivo", "fuente", "fuente_duplicado",
        "id", "id_duplicado",
    ]
    if df.empty:
        return pd.DataFrame(columns=columnas)

    con_coords = df.dropna(subset=["latitud", "longitud"]).reset_index(drop=True)
    n = len(con_coords)
    pares_vistos = set()
    filas = []

    def _agregar(i, j, distancia, motivo):
        clave = (i, j) if i < j else (j, i)
        if clave in pares_vistos:
            return
        pares_vistos.add(clave)
        a, b = con_coords.iloc[clave[0]], con_coords.iloc[clave[1]]
        filas.append({
            "nombre": a["local_identificado"],
            "nombre_duplicado": b["local_identificado"],
            "latitud": a["latitud"], "longitud": a["longitud"],
            "latitud_duplicado": b["latitud"], "longitud_duplicado": b["longitud"],
            "distancia_m": round(distancia, 1) if distancia is not None else None,
            "motivo": motivo,
            "fuente": a.get("fuente", ""), "fuente_duplicado": b.get("fuente", ""),
            "id": a.get("id", ""), "id_duplicado": b.get("id", ""),
        })

    # --- Criterios 1 y 2: cuadrícula espacial (celdas de ~umbral_m) ---
    if n > 0:
        lado_grados = max(umbral_m, 1) / 111000  # ~metros -> grados (aprox.)
        grid = {}
        for idx, fila in con_coords.iterrows():
            celda = (int(fila["latitud"] // lado_grados), int(fila["longitud"] // lado_grados))
            grid.setdefault(celda, []).append(idx)

        for (cr, cc), indices in grid.items():
            candidatos = list(indices)
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0:
                        continue
                    candidatos.extend(grid.get((cr + dr, cc + dc), []))
            for pos_i, i in enumerate(indices):
                a = con_coords.iloc[i]
                for j in candidatos:
                    if j <= i:
                        continue
                    b = con_coords.iloc[j]
                    distancia = haversine_m(a["latitud"], a["longitud"], b["latitud"], b["longitud"])
                    if distancia <= umbral_coordenada_m:
                        _agregar(i, j, distancia, "Coordenada casi exacta")
                    elif distancia <= umbral_m:
                        similitud = similitud_nombre(a["local_identificado"], b["local_identificado"])
                        if similitud >= umbral_similitud:
                            _agregar(i, j, distancia, f"Cercanía ({distancia:.0f} m) y nombre parecido")

    # --- Criterio 3: mismo nombre normalizado, sin importar la distancia ---
    grupos_nombre = {}
    for idx, fila in con_coords.iterrows():
        clave = normalizar_texto(fila["local_identificado"])
        if clave:
            grupos_nombre.setdefault(clave, []).append(idx)
    for indices in grupos_nombre.values():
        if len(indices) < 2:
            continue
        for pos_i in range(len(indices)):
            for pos_j in range(pos_i + 1, len(indices)):
                i, j = indices[pos_i], indices[pos_j]
                if (i, j) in pares_vistos or (j, i) in pares_vistos:
                    continue
                a, b = con_coords.iloc[i], con_coords.iloc[j]
                distancia = haversine_m(a["latitud"], a["longitud"], b["latitud"], b["longitud"])
                if distancia > umbral_m:  # si ya está cerca, el criterio 1/2 ya lo cubrió
                    _agregar(i, j, distancia, "Mismo nombre, distinta ubicación")

    resultado = pd.DataFrame(filas, columns=columnas)
    if resultado.empty:
        return resultado
    return resultado.sort_values("distancia_m", na_position="last").reset_index(drop=True)


# Abreviaturas comunes en direcciones colombianas que el buscador gratuito
# (Nominatim/OpenStreetMap) a veces no reconoce bien si vienen abreviadas
# ("Cra", "Cl", "#", etc.) — se prueban también en su forma completa.
_ABREVIATURAS_DIRECCION = [
    (r"\bcra\.?\b", "Carrera"),
    (r"\bkr\.?\b", "Carrera"),
    (r"\bcl\.?\b", "Calle"),
    (r"\bcll\.?\b", "Calle"),
    (r"\bdg\.?\b", "Diagonal"),
    (r"\btv\.?\b", "Transversal"),
    (r"\btrv\.?\b", "Transversal"),
    (r"\bav\.?\b", "Avenida"),
]


def _variantes_direccion(direccion: str) -> list:
    """
    Arma varias formas de escribir la misma dirección, de la más parecida a
    lo que escribió la persona a la más "limpia", para intentarlas en orden
    hasta que el buscador encuentre algo. Esto ayuda porque el buscador
    gratuito de direcciones (OpenStreetMap) a veces no reconoce bien
    abreviaturas ("Cra", "Cl") ni el símbolo '#' típico de las direcciones
    colombianas.
    """
    variantes = [direccion]

    tiene_colombia = "colombia" in direccion.lower()
    if not tiene_colombia:
        variantes.append(f"{direccion}, Colombia")

    limpia = direccion
    for patron, reemplazo in _ABREVIATURAS_DIRECCION:
        limpia = re.sub(patron, reemplazo, limpia, flags=re.IGNORECASE)
    limpia = limpia.replace("#", "No. ")
    limpia = re.sub(r"\s+", " ", limpia).strip()
    if limpia != direccion:
        variantes.append(limpia)
        if "colombia" not in limpia.lower():
            variantes.append(f"{limpia}, Colombia")

    # Quita duplicados conservando el orden.
    vistas = set()
    unicas = []
    for v in variantes:
        if v not in vistas:
            vistas.add(v)
            unicas.append(v)
    return unicas


def buscar_coordenada_por_direccion(direccion: str, timeout: int = 10):
    """
    Busca una dirección escrita (como en el buscador de Google Maps) y
    devuelve (lat, lon, nombre_encontrado) del resultado más probable.

    Usa el buscador gratuito de OpenStreetMap (Nominatim) — no necesita
    API key ni cuenta de Google. Prueba varias formas de escribir la misma
    dirección (con Colombia agregado, con las abreviaturas resueltas, etc.)
    antes de rendirse, porque este buscador es más sensible al formato
    exacto que el de Google Maps. Aun así, para direcciones muy nuevas o
    muy específicas puede no encontrar nada — en ese caso, lo más seguro
    sigue siendo copiar la coordenada directamente desde Google Maps y
    pegarla en el buscador "Por coordenada".

    Devuelve None si ninguna variante encontró nada o si falla la conexión.
    """
    import requests

    direccion = (direccion or "").strip()
    if not direccion:
        return None

    for variante in _variantes_direccion(direccion):
        try:
            resp = requests.get(
                "https://nominatim.openstreetmap.org/search",
                params={
                    "q": variante,
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
            continue

        if not resultados:
            continue

        primero = resultados[0]
        try:
            lat = float(primero["lat"])
            lon = float(primero["lon"])
        except (KeyError, TypeError, ValueError):
            continue

        return lat, lon, primero.get("display_name", direccion)

    return None


def parsear_coordenada_pegada(texto: str):
    """
    Si el texto que la persona pegó ya es una coordenada (ej. '4.697614,
    -74.092287' o '4.697614 -74.092287', tal cual la copia Google Maps),
    devuelve (lat, lon). Si no tiene esa forma, devuelve None.
    """
    if texto is None or (isinstance(texto, float) and pd.isna(texto)):
        return None
    texto = str(texto).strip()
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


def agrupar_puntos_por_radio(
    df: pd.DataFrame,
    umbral_m: float = 300,
    umbral_similitud: float = UMBRAL_SIMILITUD_NOMBRE,
) -> pd.DataFrame:
    """
    Agrupa los puntos potenciales (de cualquier fuente) que probablemente
    sean la misma oportunidad física: nombre parecido y a menos de
    umbral_m metros entre sí. Devuelve solo los grupos con más de un
    punto (los que sí representan una posible duplicidad), con la lista
    de ids/especialistas/practicantes involucrados.

    Mismo patrón de agrupamiento voraz que agrupar_generadores.
    """
    columnas = [
        "nombre_representativo", "cantidad_puntos", "ids",
        "especialistas", "practicantes", "latitud", "longitud",
    ]
    con_coords = df.dropna(subset=["latitud", "longitud"]).copy()
    if con_coords.empty:
        return pd.DataFrame(columns=columnas)

    grupos = []
    for _, fila in con_coords.iterrows():
        nombre = fila.get("local_identificado", "")
        lat, lon = fila["latitud"], fila["longitud"]
        grupo_encontrado = None
        for grupo in grupos:
            distancia = haversine_m(lat, lon, grupo["latitud"], grupo["longitud"])
            similitud = similitud_nombre(nombre, grupo["nombre_representativo"])
            if distancia <= umbral_m and similitud >= umbral_similitud:
                grupo_encontrado = grupo
                break

        if grupo_encontrado is not None:
            grupo_encontrado["ids"].append(fila.get("id", ""))
            especialista = str(fila.get("especialista", "")).strip()
            if especialista and especialista not in grupo_encontrado["especialistas"]:
                grupo_encontrado["especialistas"].append(especialista)
            practicante = str(fila.get("practicante", "")).strip()
            if practicante and practicante not in grupo_encontrado["practicantes"]:
                grupo_encontrado["practicantes"].append(practicante)
        else:
            especialista = str(fila.get("especialista", "")).strip()
            practicante = str(fila.get("practicante", "")).strip()
            grupos.append(
                {
                    "nombre_representativo": nombre,
                    "latitud": lat,
                    "longitud": lon,
                    "ids": [fila.get("id", "")],
                    "especialistas": [especialista] if especialista else [],
                    "practicantes": [practicante] if practicante else [],
                }
            )

    resultado = pd.DataFrame(
        [
            {
                "nombre_representativo": g["nombre_representativo"],
                "cantidad_puntos": len(g["ids"]),
                "ids": ", ".join(str(i) for i in g["ids"]),
                "especialistas": ", ".join(g["especialistas"]),
                "practicantes": ", ".join(g["practicantes"]),
                "latitud": g["latitud"],
                "longitud": g["longitud"],
            }
            for g in grupos
            if len(g["ids"]) > 1
        ],
        columns=columnas,
    )
    if resultado.empty:
        return resultado
    return resultado.sort_values("cantidad_puntos", ascending=False).reset_index(drop=True)


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
    "tipo_levantamiento",
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

# Distancia (en metros) para considerar que dos registros están en
# prácticamente la MISMA coordenada exacta (ej. copiar/pegar el mismo
# pin, o dos personas que marcaron el mismo punto en el mapa). Esto se
# trata como duplicado SIEMPRE, sin importar si el nombre coincide o no
# — es más estricto que UMBRAL_DUPLICIDAD_GENERADOR_M (300 m), que además
# exige que el nombre se parezca.
UMBRAL_COORDENADA_DUPLICADO_M = 15


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
                "tipo_levantamiento": attrs.get("tipo_de_levantamiento") or "",
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
        df["tipo_levantamiento"] = df["tipo_levantamiento"].fillna("").astype(str).str.strip()
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
    lat: float,
    lon: float,
    nombre: str = "",
    umbral_m: float = UMBRAL_DUPLICIDAD_GENERADOR_M,
    umbral_similitud: float = UMBRAL_SIMILITUD_NOMBRE,
    incluir_solo_generadores: bool = True,
) -> pd.DataFrame:
    """
    Busca generadores existentes a menos de `umbral_m` de una coordenada.

    El nombre es OPCIONAL y solo se usa para mostrar qué tan parecido es
    (columna similitud_nombre) — no se exige que coincida, porque dos
    personas pueden nombrar el mismo generador físico distinto (ej.
    "Conjunto Acanto" vs "Conjunto Residencial Acanto"). La cercanía por
    coordenada es lo que manda para detectar duplicidad.

    Si `incluir_solo_generadores=True` (por defecto) y el DataFrame trae
    la columna 'tipo_levantamiento', se ignoran las filas marcadas como
    "Punto potencial" (no son generadores, aunque vengan en la misma
    encuesta de Survey123).

    Útil para consultar antes de registrar un generador nuevo en
    Survey123: si ya existe algo cerca, conviene vincularlo al punto
    actual en vez de crear un registro nuevo.
    """
    columnas_resultado = list(GENERADOR_COLUMNAS) + ["distancia_m", "similitud_nombre"]
    if df_generadores.empty:
        return df_generadores.reindex(columns=columnas_resultado).iloc[0:0]

    con_coords = df_generadores.dropna(subset=["latitud", "longitud"]).copy()
    if incluir_solo_generadores and "tipo_levantamiento" in con_coords.columns:
        con_coords = con_coords[
            con_coords["tipo_levantamiento"].astype(str).str.strip().str.lower() != "punto potencial"
        ]
    if con_coords.empty:
        return df_generadores.reindex(columns=columnas_resultado).iloc[0:0]

    con_coords["distancia_m"] = con_coords.apply(
        lambda row: round(haversine_m(lat, lon, row["latitud"], row["longitud"]), 1), axis=1
    )
    nombre = (nombre or "").strip()
    if nombre:
        con_coords["similitud_nombre"] = con_coords["nombre_generador"].apply(
            lambda x: round(similitud_nombre(nombre, x), 2)
        )
    else:
        con_coords["similitud_nombre"] = 0.0

    coincidencias = con_coords[
        con_coords["distancia_m"] <= umbral_m
    ]
    return coincidencias.sort_values("distancia_m")[columnas_resultado]


def agrupar_generadores(
    df_generadores: pd.DataFrame,
    umbral_m: float = UMBRAL_DUPLICIDAD_GENERADOR_M,
    umbral_similitud: float = UMBRAL_SIMILITUD_NOMBRE,
    umbral_coordenada_m: float = UMBRAL_COORDENADA_DUPLICADO_M,
    df_puntos: pd.DataFrame = None,
    incluir_solo_generadores: bool = True,
) -> pd.DataFrame:
    """
    Agrupa los registros crudos de generadores que probablemente sean el
    mismo lugar físico en un solo renglón por generador único, listando
    todos los puntos potenciales a los que quedó vinculado.

    Dos formas de detectar que dos registros son el MISMO generador
    (cualquiera de las dos basta):

    1. Coordenada casi exacta (≤ `umbral_coordenada_m`, 15 m por
       defecto): se asume que es el mismo lugar sin importar el nombre —
       es tan cerca que casi seguro es el mismo pin, solo que alguien lo
       volvió a marcar (o lo copió).
    2. Cercanía + nombre parecido (≤ `umbral_m`, 300 m, Y similitud de
       nombre ≥ `umbral_similitud`): la misma ubicación física puede
       quedar escrita con nombres distintos según quién la registró (ej.
       "Conjunto Acanto" vs "Conjunto Residencial Acanto"), así que
       dentro del radio de recolección se exige que el nombre también se
       parezca — si el nombre es muy distinto, dentro de 300 m puede
       perfectamente haber DOS generadores reales distintos (un colegio y
       un banco en la misma cuadra, por ejemplo), y agruparlos sería
       perder ese punto en el mapa. (Antes se agrupaba solo por
       cercanía, sin exigir nombre parecido, y eso hacía que generadores
       realmente distintos desaparecieran del mapa al quedar fundidos en
       uno solo.)

    Si `incluir_solo_generadores=True` (por defecto) y el DataFrame trae
    la columna 'tipo_levantamiento', se excluyen las filas marcadas como
    "Punto potencial" — esa misma encuesta de Survey123 se usa para
    registrar tanto generadores como puntos potenciales, y un "Punto
    potencial" no es un generador aunque venga en la misma capa.

    Si se pasa df_puntos (el DataFrame de puntos potenciales, con columnas
    'local_identificado' y 'especialista'), también arma la columna
    'especialistas_asociados': quiénes registraron cada uno de los puntos
    vinculados a ese generador — así se ve quién duplicó qué.

    Es un agrupamiento voraz (greedy): recorre los registros uno por uno
    y los suma al primer grupo existente con el que calcen; si no calzan
    con ninguno, abren un grupo nuevo. Con cientos de registros esto es
    rápido y suficientemente preciso para el caso de uso (revisar
    duplicidad), aunque no es un clustering óptimo.
    """
    columnas = [
        "nombre_generador", "tipo_generador", "latitud", "longitud",
        "cantidad_registros", "puntos_asociados", "especialistas_asociados",
        "registrado_por", "duplicado_por", "nombre_duplicado", "registros_originales",
    ]
    con_coords = df_generadores.dropna(subset=["latitud", "longitud"]).copy()
    if incluir_solo_generadores and "tipo_levantamiento" in con_coords.columns:
        con_coords = con_coords[
            con_coords["tipo_levantamiento"].astype(str).str.strip().str.lower() != "punto potencial"
        ]
    if con_coords.empty:
        return pd.DataFrame(columns=columnas)

    # Mapa nombre-de-punto (normalizado) -> especialista, para poder decir
    # quién registró cada punto asociado a un generador repetido.
    mapa_especialista_por_punto = {}
    if df_puntos is not None and not df_puntos.empty and "local_identificado" in df_puntos.columns:
        for _, fp in df_puntos.iterrows():
            clave = normalizar_texto(fp.get("local_identificado", ""))
            if clave:
                mapa_especialista_por_punto[clave] = str(fp.get("especialista", "")).strip()

    grupos = []  # cada grupo: dict con nombre, tipo, lat, lon, registros (list of rows)

    for _, fila in con_coords.iterrows():
        nombre = fila["nombre_generador"]
        lat, lon = fila["latitud"], fila["longitud"]
        grupo_encontrado = None
        razon_match = None
        for grupo in grupos:
            distancia = haversine_m(lat, lon, grupo["latitud"], grupo["longitud"])
            if distancia <= umbral_coordenada_m:
                grupo_encontrado = grupo
                razon_match = "coordenada"
                break
            if distancia <= umbral_m:
                sim = similitud_nombre(nombre, grupo["nombre_generador"])
                if sim >= umbral_similitud:
                    grupo_encontrado = grupo
                    razon_match = "distancia_nombre"
                    break

        if grupo_encontrado is None:
            grupo_encontrado = {
                "nombre_generador": nombre,
                "tipo_generador": fila.get("tipo_generador", ""),
                "latitud": lat,
                "longitud": lon,
                "razones": [],
                "registros": [],
                "puntos": [],
                "especialistas": [],
                "creadores": [],
                "nombres": [],
            }
            grupos.append(grupo_encontrado)

        if razon_match:
            grupo_encontrado["razones"].append(razon_match)

        grupo_encontrado["registros"].append(fila)
        nombre_str = str(nombre).strip()
        if nombre_str and nombre_str not in grupo_encontrado["nombres"]:
            grupo_encontrado["nombres"].append(nombre_str)
        punto = str(fila.get("nombre_punto_potencial", "")).strip()
        if punto and punto not in grupo_encontrado["puntos"]:
            grupo_encontrado["puntos"].append(punto)
        clave_punto = normalizar_texto(punto)
        especialista = mapa_especialista_por_punto.get(clave_punto, "")
        if especialista and especialista not in grupo_encontrado["especialistas"]:
            grupo_encontrado["especialistas"].append(especialista)
        # Quién diligenció ESE registro puntual en Survey123 — a diferencia
        # de 'especialistas_asociados' (que depende de que el generador
        # esté vinculado a un punto potencial del Excel), esto siempre
        # está disponible porque viene directo de la encuesta. Se prefiere
        # 'localizador' (el nombre que la persona escribe en el
        # formulario) sobre 'creador' (la cuenta de inicio de sesión de
        # Survey123/ArcGIS, que puede ser genérica o compartida).
        quien = str(fila.get("localizador", "")).strip() or str(fila.get("creador", "")).strip()
        if quien and quien not in grupo_encontrado["creadores"]:
            grupo_encontrado["creadores"].append(quien)

    def _duplicado_por(g):
        if len(g["registros"]) <= 1:
            return ""
        if "coordenada" in g["razones"]:
            return "Coordenada casi exacta"
        return "Cercanía + nombre parecido"

    def _nombre_duplicado(g):
        # Nombre(s) con los que se está repitiendo: los otros nombres
        # distintos que quedaron agrupados en el mismo generador (sin
        # contar el nombre representativo). Así, en vez de solo decir
        # "es un duplicado", la tabla puede mostrar con cuál se repite.
        if len(g["registros"]) <= 1:
            return ""
        clave_repr = normalizar_texto(g["nombre_generador"])
        otros = [n for n in g["nombres"] if normalizar_texto(n) != clave_repr]
        return ", ".join(otros) if otros else g["nombre_generador"]

    def _registros_originales(g):
        # La coordenada del grupo es UNA sola (representativa), pero cada
        # registro crudo que quedó agrupado ahí tiene su propia coordenada
        # real en Survey123 (puede variar unos metros). Esta lista permite
        # mostrar en el mapa TODOS los puntos reales que se consideraron
        # duplicados entre sí, no solo el representativo.
        vistos = set()
        salida = []
        for r in g["registros"]:
            clave = (round(float(r["latitud"]), 7), round(float(r["longitud"]), 7))
            if clave in vistos:
                continue
            vistos.add(clave)
            quien_r = str(r.get("localizador", "")).strip() or str(r.get("creador", "")).strip()
            salida.append({
                "nombre": str(r.get("nombre_generador", "")).strip() or "(sin nombre)",
                "latitud": float(r["latitud"]),
                "longitud": float(r["longitud"]),
                "quien": quien_r,
            })
        return salida

    resultado = pd.DataFrame(
        [
            {
                "nombre_generador": g["nombre_generador"],
                "tipo_generador": g["tipo_generador"],
                "latitud": g["latitud"],
                "longitud": g["longitud"],
                "cantidad_registros": len(g["registros"]),
                "puntos_asociados": ", ".join(g["puntos"]) if g["puntos"] else "",
                "especialistas_asociados": ", ".join(g["especialistas"]) if g["especialistas"] else "",
                "registrado_por": ", ".join(g["creadores"]) if g["creadores"] else "",
                "duplicado_por": _duplicado_por(g),
                "nombre_duplicado": _nombre_duplicado(g),
                "registros_originales": _registros_originales(g),
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
        "fuente": FUENTE_ESPECIALISTAS,
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


# ---------------------------------------------------------------------------
# Inmobiliarias — evaluación de puntos (Fase 1, borrador funcional)
# ---------------------------------------------------------------------------
# Estas son las razones de descarte que ya maneja el área (tal cual las
# compartió Alisson) — se dejan disponibles para que se puedan elegir a mano
# en el informe, además de las que el sistema sugiere solo según cómo se
# calificó cada criterio.
RAZONES_DESCARTE_INMOBILIARIA = [
    "Variables de éxito",
    "Área/Propuesta de valor",
    "Condiciones comerciales",
    "Rentado a otra marca",
    "Condiciones Jurídicas",
    "Zonas no prioritaria",
    "Vigencia de contrato",
    "Canibalización",
    "Renta del inmueble",
    "Cláusula penal/Contrato",
    "Opción de proyecto con mejor potencial",
    "Duplicado",
    "SAGRILAFT",
]

# Razones de aprobación sugeridas por Claude (no existían antes en el área)
# — complementan las de descarte para poder explicar también por qué SÍ se
# aprueba un punto, no solo por qué se descarta.
RAZONES_APROBACION_INMOBILIARIA = [
    "Buena accesibilidad",
    "Buena visibilidad",
    "Buen flujo de personas",
    "Buenos generadores cercanos",
    "Zona prioritaria para la marca",
    "Condiciones comerciales favorables",
    "Condiciones jurídicas en regla",
    "Vigencia de contrato adecuada",
    "Sin riesgo de canibalización",
    "Renta acorde al presupuesto",
    "Cláusula penal / contrato razonable",
    "Validación SAGRILAFT aprobada",
]

# Criterios de la evaluación (rubrica simple, pensada para que Alisson la
# pueda ajustar con casos reales apenas le lleguen puntos de inmobiliarias).
# Cada criterio tiene 3 opciones posibles y su puntaje (0, 1 o 2). El
# puntaje total se convierte en porcentaje sobre el máximo posible, y ese
# porcentaje decide el nivel (Alto/Medio/Bajo).
CRITERIOS_INMOBILIARIA = [
    {"clave": "accesibilidad", "etiqueta": "Accesibilidad al punto",
     "opciones": {"Buena": 2, "Regular": 1, "Mala": 0}},
    {"clave": "visibilidad", "etiqueta": "Visibilidad del local",
     "opciones": {"Buena": 2, "Regular": 1, "Mala": 0}},
    {"clave": "flujo_personas", "etiqueta": "Flujo de personas",
     "opciones": {"Alto": 2, "Medio": 1, "Bajo": 0}},
    {"clave": "generadores_cercanos", "etiqueta": "Generadores cercanos (tráfico/comercio)",
     "opciones": {"Sí": 2, "Algunos": 1, "No": 0}},
    {"clave": "condiciones_comerciales", "etiqueta": "Condiciones comerciales",
     "opciones": {"Favorables": 2, "Aceptables": 1, "Desfavorables": 0}},
    {"clave": "condiciones_juridicas", "etiqueta": "Condiciones jurídicas",
     "opciones": {"En regla": 2, "Con observaciones": 1, "Con riesgos": 0}},
    {"clave": "zona_prioritaria", "etiqueta": "Zona prioritaria para la marca",
     "opciones": {"Sí": 2, "Parcial": 1, "No": 0}},
    {"clave": "vigencia_contrato", "etiqueta": "Vigencia de contrato disponible",
     "opciones": {"Adecuada": 2, "Corta": 1, "No disponible": 0}},
    {"clave": "canibalizacion", "etiqueta": "Riesgo de canibalización con otra tienda",
     "opciones": {"Sin riesgo": 2, "Riesgo bajo": 1, "Riesgo alto": 0}},
    {"clave": "renta", "etiqueta": "Renta del inmueble frente al presupuesto",
     "opciones": {"Dentro de presupuesto": 2, "Por encima, negociable": 1, "Muy por encima": 0}},
    {"clave": "clausula_penal", "etiqueta": "Cláusula penal / condiciones del contrato",
     "opciones": {"Razonable": 2, "Exigente": 1, "Inaceptable": 0}},
    {"clave": "sagrilaft", "etiqueta": "Validación SAGRILAFT",
     "opciones": {"Aprobado": 2, "Pendiente": 1, "Rechazado": 0}},
    {"clave": "duplicado", "etiqueta": "¿Es un punto duplicado de otro ya evaluado?",
     "opciones": {"No": 2, "Posible duplicado": 1, "Sí, duplicado": 0}},
]

# Qué criterio corresponde a cuál razón de aprobación/descarte, para que el
# informe pueda explicar EN PALABRAS por qué se sugiere aprobar o descartar
# (no solo mostrar un número). Solo se listan los criterios que tienen una
# razón "oficial" de las que dio Alisson o de las que sugiere Claude — los
# demás igual suman al puntaje pero no generan una frase aparte.
_RAZON_APROBACION_POR_CRITERIO = {
    "accesibilidad": "Buena accesibilidad",
    "visibilidad": "Buena visibilidad",
    "flujo_personas": "Buen flujo de personas",
    "generadores_cercanos": "Buenos generadores cercanos",
    "zona_prioritaria": "Zona prioritaria para la marca",
    "condiciones_comerciales": "Condiciones comerciales favorables",
    "condiciones_juridicas": "Condiciones jurídicas en regla",
    "vigencia_contrato": "Vigencia de contrato adecuada",
    "canibalizacion": "Sin riesgo de canibalización",
    "renta": "Renta acorde al presupuesto",
    "clausula_penal": "Cláusula penal / contrato razonable",
    "sagrilaft": "Validación SAGRILAFT aprobada",
}
_RAZON_DESCARTE_POR_CRITERIO = {
    "condiciones_comerciales": "Condiciones comerciales",
    "condiciones_juridicas": "Condiciones Jurídicas",
    "zona_prioritaria": "Zonas no prioritaria",
    "vigencia_contrato": "Vigencia de contrato",
    "canibalizacion": "Canibalización",
    "renta": "Renta del inmueble",
    "clausula_penal": "Cláusula penal/Contrato",
    "sagrilaft": "SAGRILAFT",
    "duplicado": "Duplicado",
}


def evaluar_punto_inmobiliario(respuestas: dict) -> dict:
    """
    Recibe un diccionario {clave_criterio: opción_elegida} (una opción por
    cada criterio de CRITERIOS_INMOBILIARIA) y devuelve el resultado de la
    evaluación: puntaje total, porcentaje, nivel (Alto/Medio/Bajo), el
    detalle criterio por criterio, y listas de razones a favor / en contra
    en palabras (para armar el informe).

    Umbral de nivel (ajustable más adelante con casos reales, tal como
    quedó acordado): >= 70% Alto, >= 40% Medio, el resto Bajo.
    """
    total = 0
    maximo = 0
    detalle = []
    razones_a_favor = []
    razones_en_contra = []

    for criterio in CRITERIOS_INMOBILIARIA:
        clave = criterio["clave"]
        opciones = criterio["opciones"]
        maximo_criterio = max(opciones.values())
        maximo += maximo_criterio
        respuesta = respuestas.get(clave)
        puntos = opciones.get(respuesta, 0)
        total += puntos
        detalle.append({
            "criterio": criterio["etiqueta"],
            "respuesta": respuesta or "—",
            "puntos": puntos,
            "maximo": maximo_criterio,
        })
        if respuesta is not None:
            if puntos == maximo_criterio and clave in _RAZON_APROBACION_POR_CRITERIO:
                razones_a_favor.append(_RAZON_APROBACION_POR_CRITERIO[clave])
            elif puntos == 0 and clave in _RAZON_DESCARTE_POR_CRITERIO:
                razones_en_contra.append(_RAZON_DESCARTE_POR_CRITERIO[clave])

    porcentaje = round((total / maximo) * 100, 1) if maximo else 0.0
    if porcentaje >= 70:
        nivel = "Alto"
    elif porcentaje >= 40:
        nivel = "Medio"
    else:
        nivel = "Bajo"

    return {
        "puntaje_total": total,
        "puntaje_maximo": maximo,
        "porcentaje": porcentaje,
        "nivel": nivel,
        "detalle": detalle,
        "razones_a_favor": razones_a_favor,
        "razones_en_contra": razones_en_contra,
    }
