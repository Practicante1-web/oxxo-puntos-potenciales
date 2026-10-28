"""
Zonas, jefes de zona y regionales (pestaña «Búsqueda de regional y jefes»).

Aquí viven las funciones nuevas de esa pestaña, separadas de utils.py para no
tocar lo que ya funciona:

- leer el Excel de jefes y regionales (una fila por tienda, con su CR),
- unirlo a las tiendas que ya trae el mapa (por el código CR),
- leer las zonas de especialistas dibujadas en Google My Maps (archivo KML/KMZ),
- saber en qué zona cae una coordenada,
- buscar una dirección (OpenStreetMap / Nominatim, gratis),
- encontrar las tiendas más cercanas a un punto, con su jefe y su regional.
"""

import io
import math
import re
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd

SIN_ASIGNAR = "Sin asignar"
_COLOR_SIN_ASIGNAR = "#9AA0A6"


# ---------------------------------------------------------------------------
# Utilidades pequeñas
# ---------------------------------------------------------------------------
def _norm(texto) -> str:
    t = unicodedata.normalize("NFKD", str(texto or "").strip().lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.split())


def _limpio(v) -> str:
    t = "" if v is None else str(v).strip()
    return "" if t.lower() in ("nan", "none", "nat") else t


def _titulo(nombre: str) -> str:
    """JUAN DIEGO GARCIA -> Juan Diego Garcia (se deja tal cual si ya viene en minúscula)."""
    n = _limpio(nombre)
    return n.title() if n.isupper() else n


# ---------------------------------------------------------------------------
# Jefes de zona y regionales
# ---------------------------------------------------------------------------
COLUMNAS_JEFES = [
    "cr", "region", "plaza", "zona", "municipio", "tienda", "jefe_zona", "regional",
    "segmento", "direccion", "localidad",
]


def leer_jefes_regionales(fuente) -> pd.DataFrame:
    """
    Lee el Excel de jefes y regionales (la hoja que tenga la columna «Jefe de Zona»).
    `fuente` puede ser una ruta o bytes. Devuelve una fila por tienda con:
    cr, region, plaza, zona, municipio, tienda, jefe_zona, regional, segmento,
    direccion, localidad. Si no se puede leer, devuelve una tabla vacía.
    """
    try:
        if isinstance(fuente, (bytes, bytearray)):
            fuente = io.BytesIO(fuente)
        hojas = pd.read_excel(fuente, sheet_name=None, dtype=str)
    except Exception:
        return pd.DataFrame(columns=COLUMNAS_JEFES)

    elegida = None
    for _, tabla in hojas.items():
        if any("jefe" in _norm(c) for c in tabla.columns):
            elegida = tabla
            break
    if elegida is None:
        return pd.DataFrame(columns=COLUMNAS_JEFES)

    normal = {_norm(c): c for c in elegida.columns}

    def col(*claves, contiene=()):
        for k in claves:
            if k in normal:
                return normal[k]
        for n, c in normal.items():
            if any(x in n for x in contiene):
                return c
        return None

    mapa = {
        "cr": col("cr", "crm", "codigo", contiene=()),
        "region": col("region"),
        "plaza": col("plaza"),
        "zona": col("zona"),
        "municipio": col("municipio", "mun"),
        "tienda": col("tienda", "nombre tienda"),
        "jefe_zona": col("jefe de zona", "jefe zona", contiene=("jefe",)),
        "regional": col("responsable", "regional", "gerente regional", contiene=("regional", "responsable")),
        "segmento": col("segmento 2024", "segmento", contiene=("segmento",)),
        "direccion": col("direccion", contiene=("direccion",)),
        "localidad": col("localidad"),
    }
    salida = pd.DataFrame(index=elegida.index)
    for k, c in mapa.items():
        salida[k] = elegida[c].map(_limpio) if c is not None else ""
    salida["cr"] = salida["cr"].str.upper()
    salida = salida[salida["cr"] != ""].drop_duplicates(subset="cr", keep="first").reset_index(drop=True)
    return salida[COLUMNAS_JEFES]


def unir_jefes_a_tiendas(tiendas: pd.DataFrame, jefes: pd.DataFrame) -> pd.DataFrame:
    """
    Agrega a cada tienda (por su CR) su región, plaza, jefe de zona y regional.
    Las tiendas que no están en el Excel de jefes quedan como «Sin asignar»
    (por ejemplo las cerradas o las que todavía no abren).
    """
    t = tiendas.copy()
    if "cr" not in t.columns:
        t["cr"] = ""
    clave = t["cr"].map(lambda x: _limpio(x).upper())
    if jefes is None or jefes.empty:
        for c in ("region", "plaza", "jefe_zona", "regional"):
            t[c] = SIN_ASIGNAR
        return t
    j = jefes.set_index("cr")
    for c_dest, c_orig in (("region", "region"), ("plaza", "plaza"), ("jefe_zona", "jefe_zona"), ("regional", "regional")):
        t[c_dest] = clave.map(j[c_orig]).map(_limpio).replace("", SIN_ASIGNAR)
    t["jefe_zona"] = t["jefe_zona"].map(lambda x: x if x == SIN_ASIGNAR else _titulo(x))
    t["regional"] = t["regional"].map(lambda x: x if x == SIN_ASIGNAR else _titulo(x))
    return t


def _paleta(n: int) -> list:
    """n colores bien distintos entre sí (alterna tonos y luminosidad)."""
    import colorsys
    base = [
        "#1D4ED8", "#16A34A", "#F59E0B", "#7C3AA8", "#0891B2", "#DB2777", "#65A30D", "#334155",
        "#EA580C", "#0F766E", "#4F46E5", "#B45309", "#BE123C", "#0369A1", "#15803D", "#A21CAF",
    ]
    if n <= len(base):
        return base[:n]
    cols = list(base)
    k = 0
    while len(cols) < n:
        h = (k * 0.381966) % 1.0                 # proporción áurea: tonos bien repartidos
        l = 0.38 if k % 2 == 0 else 0.55
        r, g, b = colorsys.hls_to_rgb(h, l, 0.75)
        cols.append("#%02X%02X%02X" % (int(r * 255), int(g * 255), int(b * 255)))
        k += 1
    return cols[:n]


def colores_por_grupo(etiquetas) -> dict:
    """{nombre del grupo: color #hex}. «Sin asignar» siempre en gris."""
    nombres = sorted({str(e) for e in etiquetas if str(e) != SIN_ASIGNAR}, key=lambda x: _norm(x))
    paleta = _paleta(len(nombres))
    colores = {n: paleta[i] for i, n in enumerate(nombres)}
    if any(str(e) == SIN_ASIGNAR for e in etiquetas):
        colores[SIN_ASIGNAR] = _COLOR_SIN_ASIGNAR
    return colores


# ---------------------------------------------------------------------------
# Distancias y tiendas más cercanas
# ---------------------------------------------------------------------------
def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371000.0 * math.asin(math.sqrt(a))


def tiendas_mas_cercanas(tiendas: pd.DataFrame, lat: float, lon: float, n: int = 6) -> pd.DataFrame:
    """Las `n` tiendas más cercanas a (lat, lon), con la columna `distancia_m`."""
    if tiendas is None or tiendas.empty:
        return pd.DataFrame(columns=list(getattr(tiendas, "columns", [])) + ["distancia_m"])
    import numpy as np
    la = pd.to_numeric(tiendas["latitud"], errors="coerce").to_numpy(dtype=float)
    lo = pd.to_numeric(tiendas["longitud"], errors="coerce").to_numpy(dtype=float)
    p1, p2 = np.radians(la), math.radians(lat)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * math.cos(p2) * np.sin(np.radians(lon - lo) / 2) ** 2
    dist = 2 * 6371000.0 * np.arcsin(np.sqrt(a))
    dist = np.nan_to_num(dist, nan=1e12)
    r = tiendas.copy()
    r["distancia_m"] = dist
    return r.sort_values("distancia_m").head(n).reset_index(drop=True)


def responsables_probables(cercanas: pd.DataFrame) -> dict:
    """
    A partir de las tiendas más cercanas a un punto, saca quién es el jefe de
    zona y el regional más probables: los de la tienda más cercana que SÍ tenga
    asignación. Devuelve {} si ninguna la tiene.
    """
    if cercanas is None or cercanas.empty:
        return {}
    con = cercanas[cercanas["jefe_zona"] != SIN_ASIGNAR]
    if con.empty:
        return {}
    primera = con.iloc[0]
    # ¿Todas las tiendas asignadas de alrededor comparten jefe?
    jefes = con["jefe_zona"].unique().tolist()
    regionales = con["regional"].unique().tolist()
    return {
        "jefe_zona": primera["jefe_zona"], "regional": primera["regional"],
        "region": primera.get("region", ""), "plaza": primera.get("plaza", ""),
        "tienda": primera.get("nombre", ""), "cr": primera.get("cr", ""),
        "distancia_m": float(primera["distancia_m"]),
        "hay_mas_de_un_jefe": len(jefes) > 1, "jefes_cercanos": jefes,
        "hay_mas_de_un_regional": len(regionales) > 1, "regionales_cercanos": regionales,
    }


# ---------------------------------------------------------------------------
# Zonas de especialistas (Google My Maps → KML / KMZ)
# ---------------------------------------------------------------------------
def _sin_ns(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def _texto_plano(html: str) -> str:
    t = re.sub(r"<\s*br\s*/?>|</\s*(p|div|li|tr)\s*>", "\n", str(html or ""), flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = (t.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<")
          .replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'"))
    return "\n".join(x.strip() for x in t.splitlines() if x.strip())


def _kml_color_a_hex(c: str) -> str:
    """KML guarda el color como aabbggrr; se pasa a #rrggbb."""
    c = (c or "").strip().lstrip("#")
    if len(c) == 8:
        return "#" + c[6:8] + c[4:6] + c[2:4]
    if len(c) == 6:
        return "#" + c
    return ""


def _anillo(texto: str) -> list:
    pts = []
    for trio in re.split(r"\s+", (texto or "").strip()):
        partes = trio.split(",")
        if len(partes) >= 2:
            try:
                pts.append([float(partes[1]), float(partes[0])])   # [lat, lon]
            except ValueError:
                pass
    return pts


def leer_zonas_kml(fuente) -> list:
    """
    Lee un KML o KMZ (el que se exporta desde Google My Maps) y devuelve una lista
    de zonas: {nombre, descripcion, datos, color, capa, anillos, huecos}.
    `anillos` = contornos exteriores [[lat, lon], …]; `huecos` = agujeros interiores.
    `fuente` puede ser una ruta (str/Path) o bytes. Si falla, devuelve [].
    """
    try:
        if isinstance(fuente, (str, Path)):
            datos = Path(fuente).read_bytes()
        else:
            datos = bytes(fuente)
        if datos[:2] == b"PK":                                   # KMZ = zip con un doc.kml
            with zipfile.ZipFile(io.BytesIO(datos)) as z:
                nombre_kml = next((n for n in z.namelist() if n.lower().endswith(".kml")), None)
                datos = z.read(nombre_kml) if nombre_kml else b""
        raiz = ET.fromstring(datos)
    except Exception:
        return []

    # Estilos (color del relleno de cada zona)
    estilos, mapas = {}, {}
    for el in raiz.iter():
        t = _sin_ns(el.tag)
        if t == "Style" and el.get("id"):
            for sub in el.iter():
                if _sin_ns(sub.tag) == "PolyStyle":
                    for c in sub:
                        if _sin_ns(c.tag) == "color" and c.text:
                            estilos[el.get("id")] = _kml_color_a_hex(c.text)
                if _sin_ns(sub.tag) == "LineStyle" and el.get("id") not in estilos:
                    for c in sub:
                        if _sin_ns(c.tag) == "color" and c.text:
                            estilos[el.get("id")] = _kml_color_a_hex(c.text)
        elif t == "StyleMap" and el.get("id"):
            for par in el:
                if _sin_ns(par.tag) == "Pair":
                    k = [c.text for c in par if _sin_ns(c.tag) == "key"]
                    u = [c.text for c in par if _sin_ns(c.tag) == "styleUrl"]
                    if k and k[0] == "normal" and u:
                        mapas[el.get("id")] = u[0].lstrip("#")

    zonas = []

    def recorrer(nodo, capa=""):
        for hijo in nodo:
            t = _sin_ns(hijo.tag)
            if t in ("Folder", "Document"):
                nombre_capa = next((c.text.strip() for c in hijo if _sin_ns(c.tag) == "name" and c.text), capa)
                recorrer(hijo, nombre_capa or capa)
            elif t == "Placemark":
                nombre, desc, extra, estilo = "", "", {}, ""
                anillos, huecos = [], []
                for c in hijo:
                    ct = _sin_ns(c.tag)
                    if ct == "name":
                        nombre = (c.text or "").strip()
                    elif ct == "description":
                        desc = _texto_plano(c.text or "")
                    elif ct == "styleUrl":
                        estilo = (c.text or "").lstrip("#")
                    elif ct == "ExtendedData":
                        for d in c.iter():
                            if _sin_ns(d.tag) == "Data":
                                v = next((x.text for x in d if _sin_ns(x.tag) == "value"), "") or ""
                                if _limpio(v):
                                    extra[d.get("name", "")] = _limpio(v)
                for g in hijo.iter():
                    gt = _sin_ns(g.tag)
                    if gt == "outerBoundaryIs":
                        for c in g.iter():
                            if _sin_ns(c.tag) == "coordinates":
                                a = _anillo(c.text)
                                if len(a) >= 3:
                                    anillos.append(a)
                    elif gt == "innerBoundaryIs":
                        for c in g.iter():
                            if _sin_ns(c.tag) == "coordinates":
                                a = _anillo(c.text)
                                if len(a) >= 3:
                                    huecos.append(a)
                if anillos:
                    color = estilos.get(estilo) or estilos.get(mapas.get(estilo, "")) or ""
                    zonas.append({
                        "nombre": nombre or "Zona", "descripcion": desc, "datos": extra,
                        "color": color, "capa": capa, "anillos": anillos, "huecos": huecos,
                    })

    recorrer(raiz)
    return zonas


def _punto_en_anillo(lat: float, lon: float, anillo: list) -> bool:
    dentro = False
    n = len(anillo)
    j = n - 1
    for i in range(n):
        yi, xi = anillo[i]
        yj, xj = anillo[j]
        if (yi > lat) != (yj > lat):
            if lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-18) + xi:
                dentro = not dentro
        j = i
    return dentro


def zonas_de_punto(zonas: list, lat: float, lon: float) -> list:
    """Zonas (de la lista) que contienen la coordenada (puede haber más de una si se traslapan)."""
    r = []
    for z in zonas or []:
        if any(_punto_en_anillo(lat, lon, a) for a in z["anillos"]) and not any(
            _punto_en_anillo(lat, lon, h) for h in z.get("huecos", [])
        ):
            r.append(z)
    return r


_RE_ESP = re.compile(r"^\s*(.+?)\s*[-–]\s*(Esp\.?\s*\d+)\s*$", re.I)


def interpretar_zona(zona: dict) -> dict:
    """
    Entiende cómo viene armado el mapa de zonas de especialistas (Google My Maps):

    - Cada carpeta (o el nombre del polígono) es «Nombre Apellido- Esp N»: ese es el
      especialista que tiene la zona.
    - El polígono es una UPZ/barrio; su nombre sale del título o de la primera línea
      de la descripción.
    - Si la descripción trae «Especialista: X» (el campo de la ventana emergente del
      mapa), se devuelve aparte como `especialista_mapa`.
    """
    nombre = _limpio(zona.get("nombre"))
    capa = _limpio(zona.get("capa"))
    desc = zona.get("descripcion", "") or ""
    primera = next((x.strip() for x in desc.splitlines() if x.strip()), "")
    persona, codigo, sitio = "", "", nombre
    m_nombre, m_capa = _RE_ESP.match(nombre), _RE_ESP.match(capa)
    if m_nombre:
        persona, codigo = m_nombre.group(1).strip(), re.sub(r"\s+", " ", m_nombre.group(2).strip().title())
        sitio = primera or nombre
    elif m_capa:
        persona, codigo = m_capa.group(1).strip(), re.sub(r"\s+", " ", m_capa.group(2).strip().title())
    especialista_mapa = ""
    for linea in desc.splitlines():
        if _norm(linea).startswith("popupinfo") or "especialista:" in _norm(linea):
            especialista_mapa = linea.split("Especialista:", 1)[-1].strip() if "Especialista:" in linea else linea.strip()
            break
    return {"sitio": sitio, "especialista": persona, "codigo": codigo, "especialista_mapa": especialista_mapa}


def texto_especialista(zona: dict) -> str:
    """Quién tiene la zona, como «Stefania Babativa (Esp 4)». Si el mapa no sigue ese
    formato, se usa un dato llamado «especialista», la descripción o el nombre."""
    i = interpretar_zona(zona)
    if i["especialista"]:
        return i["especialista"] + (f" ({i['codigo']})" if i["codigo"] else "")
    for k, v in (zona.get("datos") or {}).items():
        if "especialista" in _norm(k) and _limpio(v):
            return _limpio(v)
    if i["especialista_mapa"]:
        return i["especialista_mapa"]
    return zona.get("nombre", "")


# ---------------------------------------------------------------------------
# Buscar una dirección (OpenStreetMap / Nominatim — gratis, sin llave)
# ---------------------------------------------------------------------------
def buscar_direccion(texto: str, ciudad: str = "") -> tuple:
    """
    Convierte una dirección en coordenadas. Devuelve (resultados, error), donde
    resultados es una lista de {nombre, lat, lon}. Usa Nominatim (uso ligero y
    gratuito); si la dirección tiene un formato muy colombiano (Cra 45A #34-155)
    y no aparece, conviene agregar la ciudad o pegar la coordenada de Google Maps.
    """
    import requests

    consulta = " ".join(x for x in (_limpio(texto), _limpio(ciudad)) if x)
    if not consulta:
        return [], "Escribe una dirección."

    def pedir(q):
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": q, "format": "jsonv2", "limit": 5, "countrycodes": "co", "accept-language": "es"},
            headers={"User-Agent": "oxxo-puntos-potenciales/1.0 (practica Inteligencia de Expansion)"},
            timeout=15,
        )
        r.raise_for_status()
        return r.json()

    try:
        datos = pedir(consulta)
        if not datos:
            # Segundo intento: sin el número de la placa («#34-155») ni el local.
            simple = re.split(r"#|no\.?\s*\d|local|lc\b|bodega|piso", consulta, flags=re.I)[0].strip(" ,-")
            if simple and simple != consulta:
                datos = pedir(simple + (" " + ciudad if ciudad and ciudad.lower() not in simple.lower() else ""))
    except Exception as e:      # sin internet, límite de uso, etc.
        return [], f"No pude consultar el buscador de direcciones ({type(e).__name__}). Pega la coordenada de Google Maps."
    res = []
    for d in datos or []:
        try:
            res.append({"nombre": str(d.get("display_name", ""))[:140], "lat": float(d["lat"]), "lon": float(d["lon"])})
        except (KeyError, ValueError, TypeError):
            continue
    if not res:
        return [], "No encontré esa dirección. Prueba agregando la ciudad, o pega la coordenada de Google Maps."
    return res, ""
