"""
Mapa del Módulo 1 dibujado como una página web propia (HTML + JavaScript) que
se muestra dentro de la app. Se hizo así a propósito, en vez de usar el mapa
nativo de Streamlit (pydeck), por tres razones:

1. La tarjeta de información al pasar el mouse sobre un punto aparecía muy
   arriba, fuera del marco del mapa, y no se podía ver. Aquí la tarjeta la
   dibujamos nosotros y SIEMPRE queda dentro del marco del mapa.
2. Calles más claras y con letra más grande (mapa base de OpenStreetMap),
   con opción de cambiar a otro mapa base o a satélite, y semáforos.
3. Los puntos que caen en el mismo lugar se abren en abanico, y se pueden
   prender/apagar las capas sin recargar la página.

No necesita ninguna librería extra: solo el navegador. Los mapas base
(OpenStreetMap, CARTO, Esri) y los semáforos (OpenStreetMap/Overpass) se
piden directamente desde el navegador de quien usa la app.
"""

import json

from iconos import _PINES_B64

# Íconos de tiendas OXXO (imagen recortada y reducida) — abierta (roja),
# firmada (negra) y cerrada (gris). Cada uno: base64 PNG + tamaño original.
_TIENDAS_ICONOS = {
    "abierta": {"b64": "iVBORw0KGgoAAAANSUhEUgAAAHAAAABFCAYAAACSV2JVAAATH0lEQVR42u2de5iVVb3HP2u977vffd8zw2W4jJIIiUBpguIha8C8pCJmCWlFXtOsjucUx+uxg9PTUxnpo5nYsdCjR5JEI7xWkGgaKKZhxEVEbI7AAAPMMPv+XtY6f+y956JcZka2s8lZz/M+zzzvvOtda/++67fW9/tbl1fQx2nOnDlyypQpksMszZs3Ty9atEgBmg9rqq+vNwF5mFbfHDVqlF2sv+irSvRZwTNmzDAWLVrEMcccM+rqq6/+uGVZUiklKh01rbVWSoklS5a8uXz58o21tbVqx44dOcD/0HjenDlz5IwZM4zLL7/849u3b9+sD8O0Z8+e5tmzZ581YMCA2MknnxzqK2cw+8Irhw0bZjQ0NLgLFiw4rba29ijHcbx8Pm8IUfEOiNYa0zT96urqgWefffYZt91224snnniiBTiAKnfxBwJQzJkzxzj33HPFq6++yrZt28SwYcPKNUBby5cv1zt27DABlclkRDKZFCUApay8YVEp1Q5gMBgUtm1rKaUYM2ZMYNCgQVx88cXW5MmTy9aNVldXi7Vr19LQ0OAVgdSdARSA2dDQ4DU0NAT345mH2vP13Ftv1WgthRC+lBLTNDEMg1wu126wSkhCCEKhEEopXNdFSokUQrTs3q02bNjAhg0bLMB+4IEHVJm9L19XV2dv2bLFLY65WhTHJLOhoUHed999XznlU6dcJE3LKldXqrUWhhBoIXzTNIcfOXz46L1tbTqdSgmlFEuXLqWpaRvhUKgi+LkQglw2S7yqms+eeSahUIiAbesBNTViR3NzY7KtrREpDBCq+Hw5qq2V7+u/rV79zAUXXDB/7Nix+XXr1uUAT8yZM0fecssteubMmSfMv+++lbFo1PpALeQ47E2l8IBVL7/MX197jQsunEUkGkcrty+JchFBieu6LF60gGHDhnHGGWeAUtTE4xAIfODVue66686bO3fus/X19d7zzz+fNwEphPCu/fo3h0aiUctZ+ke/7V+/g0wkoNzdmGEIkUxJ55tXYl91OanWFuo/cxYfDf+D1hW3Is1g+XSyEAhZknAarRTod5cl0W6a2HFXcMZZ03l1xXMQieA+8TQt3/sBKhLRwvNUmW2E2tNC+MZrVfjSWeZHhg4dBohAIGB0GQPdbFYr0CKTNdTbjTCgBny/3ADC7j3ovXvRQmIYBpZl4aTfRA5IIK0YaAWGhM4M1e9kbNMo/O2r9wCEIbs+246LRHseOpks/EbTRCQSCMvsGG2UAgTaC+Lk3sIwj8MKBNBSoNNp/E1vQVWV0L5vlJctmKidzdDWJrTWwnEcH5CO42hAdJAVw0SA0IZEhEII2wZVZgClAaEQmCXDCTQOxvZxWBtDyJBduJ1Ko/NOwbJSIsJhRNBGez56715EwELEYmivUF9hSLTropMpRDSCsCy01qBBGAY6m0FUV2NPPweswmudPzyH/+ZbBeCkLOQL2OhcDnN4LXqEW2gHutAARCgEH4SNDLNQlmkihEC+S2u1A6h0MQpSan1agyozjRC6oyxAK4UIh3Dm3UvyvvsR0QSk0piTJmJ98l+QVVV4G9/EXf48/tYtyFiC4JWX4a/fQP7pp5CJAaAUOptFDh2CfdFM8o8uRm3dhghYIAQ6l0dUJYj/6n/AAud3fyB1w83I6mrMkyYiIhH89Rtwnn0O3bwbBIROm4K456ddPfmDspHsaqPuCPm+VsqIRByRqMEYPIjIj76P/fnzuj6STpO69iacx58i+pMfAdA248s4zz6PqIkjfJ/EY7/CnDgBtWUrztO/RwyoAc9D+Ir4Yw9jnTSR3P0Pkv7PW4j+9DbsC87vqvt27yF97Y3kFi5C1NTs14B9nSozkKw1OpUictuPsD9/HvnfLKH1jGm0TPo0ya99A51MEZt3J+ZxH2fvZ6eD5xGb/3OsCZ9ANTURu/sOzIkTyN51D+b48cQfnI9u3oVuSxG963askyaSf3QxyW9+m/iC+7EvOJ/cQw/TeupZtJxcT+pb30YYktgv7sGccAJ6bxvIyjRV5XmgYaCTKaxJk7DPPQfnqWdIfvXywnhjWXir/4b/xkYSS58i8oMGWiZMJnn1NcR+MY/Y/HtwV6wkMO0snGXLSX/3FhJPLsY6ZTLhm29EhEPYnzsXZ/mfaLvka9jTz8GaWk9uwUKSV1yNiMbANPBe+yv+5rdJPLWY8HXfwf3ZvD5XM4cPgEKgHQfrxBNAa3IPLQTLQlRVgesi6objrV6Dt/JlrPpPYX5sHLmHHkYEQ0TvmIv9xRm4q14hedlVCDtI8opvEH/wl4Sv/XcA3Bf+TOqqb4HvY50yGZQi/9BCRDSKiMfA9xB1dbgvrcJbuw5r0ol4CweA63Vlwv1d6MFCD6pDamhd8IDOBizJB10Q2zqZbGeEIhBA2AGwLPy3/4Hz7HPt2fK/WYK/ZSsiHEG7blFuGAUyImjXhSWWrA9AIPoB3HfUGGHbuC+/AkIQvHRWAdBde9DZLOqdLZgnn4R18iS811bjrV9P4PRTif1yHqotSW7BQszjjyPx1GK06xG8dBbhG/4D1bQdtaeFyA+/h33WGejWVryXimVcfjE4eXRLa3sZgan1mGPH4L2wAr1rN1hWRQJpViSA0QjeX14l9/AjBC+aSfw3C8nNuxe1pwVzwieIfPcGME1S196EccxHic3/OUhJ6t9mk1/wa4RhYIwfi332mUTvmIve28bez1+IMaSW+GMPE733Z/jbd+A88RTO07/HPn86YuH/kv3l/YXxd/IkwjffgM7lSd96G4HagRXrhWaldg0iFiN943chmyN42VcJnDqlA+OdO2n7ymX4jf9H1R+fQQ4cQPqm/8J54mnkyKNIzb4BY+yxVD3zWxCCti9dgv/mW/hvbCT1neuJ3jGXxG8fobX+dJJXX0N07g+wZ36BwLSzOoI9/2gkfe1N+OvWI0afXf6w4j8ViUml0Htb0RKSV1xF5o6fYk2aiIjF8De/jfv8CxijR1G17AmMo0aQ+eGPyfzwVkRNDbplNzqXhzffIL/kcfILfk1u8WLkgIEgNJk774SASfCLF4DnonY00fblizFv/QnmiScgwmH8TW/hvrgSnU4XJE1rC5VKQ82KA891MCdOJtjiIeLRwv1MFt2cRe9II2uGEfvv+7Fnng2A99Ia/Nc2Erz46wXyoQvhNlyP/IInwEoQuvQbxbiuACFQjbvJ3nE/1omfxvpkYUZBZzLo7Sm0TiLMKuxpXwArgE6lsI4fC8qrSBArCkAhBeQU8vyPEDgNhBEsBLOl7BDShgHkya1/oMA6I5rA3NPbAwBdgtlSFsNdqut9IQr3hCgyXNHxfOk9pRl45WIEB6L36kL9+gHcH3qgfA9hhdA7XyL5ws0YdrwAYOcppZJ0MIwOaeHvb3mmOMB9OOhUlTBQ+TZix38dOWgsvudWnBQ0Kwg/DCvAqhXPcsysiwl94fQKmNDVgMSLHcnLjz1amM0QsqJW8lYEgEII8nmH8ePH8+bmzcy7+y7i1YNQSvdti9eFbj2TbCGfz3PetGm4bmV5YWUAqMBz8iSiUb70xQvZvXsXSlXOOlkhJNU1NYQCAbx8DkPpfgA7j2kiFMSMJ9BaY5sWRw6prTjC53k+ynEwq6oQkUjFCHuzz8ELBMj+bQ2ZXz+CTKXRJeZYeQIVoRUqHCb46l+Jl2b5P8wAaqUwIhH2LF7C1gW/wqwwgrAvouVpzUDbpiqewFOqzzsKs68NorSiJhwhGI4cFtuUFBAElNYV0cub+4qGYBhFwdy55uUhFRqIAXHBYZO0LvMmCNnJ9iUs9kN92wGUQhYksuMI3dqCFqLLskIZjBUjG+Vp1YdbKl9706jc3k7LJk10W0shvgtavWvgLQGoZcASJgi3brgfuHAmIhoF5SOklAJEdsMyVC6JkAYf5k2pZW0SWoFhETr2HDBsrZWvMAx0WxJjzGgFWNI0zc4AmICqr683X13/903Nzc1bBp00sa7q4Qfe8/rW732U/DtNhZlurfrtfejFJvgeRiTBoB/fjpRxAXQex4xUKpVc8corG2OxmLVx48Ysxc0tYuzYsda6desCs2bNmnDRRRedY2odlKaJUMo/dvzHzhs6dPBR224/SfvNm4QIhPoBLJcHKg/smB5+w+uiJU3zy39+4RHDsjS+r5WU3uNPPvmne+65Z1UsFssnk8kk4Ja6clkkV0YnzzQAf82avz8yfvy401ofP8fXyc2GMPsBLF8X6qHNmKqe8YJ8Z+vOtUfWDZsOZIHSdjIjGo2SSqXSFDaU+mYnHpEfMWKEddxxx1mZTEaNHDnSWLVqlRkMhgrsXim0pwqP9gNYtjFQU5hZEVKagwcPjhxxxBEe4FZXV6tt27a569atcwGvxP06ywi/sbFRNTY2OhR261qrV682hRCqSz8txLs4WD+hOTRctmjXjlt6586drmEYmaamplTRC3Wna586sPRPMW7cuKK7lR7WRc9TPSL+ogS87uHv0vv4uwd59X4yiZ7W5RCVu38V3CWs0dncGtDFDaPvwqIbkZiRI0fq4u81lFIKpNJCio6ViEKUNrUXyhLvqZxAoLRG9zR6r9+Hg5eWdEqjU70KddFao8o1k7DPcvf/sCj+Xxe2TRUXpUpAKqUUhlGY/pdS6t6E0vTmzZsF4GYy6aSUUlZNWyC7kFrHQbkeK156iaam7ViBrusmlVIEQyE2b9rMn1e8SNAOdmvfuxAC13Wpra3FtCy2vvNOYV9eNwLHQgg8z6WmpobTTj8TVZwQ1lpjWRa7du3mj0uXYpjmIQ1ECyFwHYdhdcOZOnUq+Xye/Z64IQS+55FIJDh1yhSkaQrsQMfDvpLIAPl8Ng1ko9GoeHe32S0PvPvuu9WIESPMe++9987Zs2cPjsYHDEGKwrIgKZRlRAZGo4G4jB2FkQljWFbXMnyFFYng2jl2ZkKEdbjbADpOnqCqIqADNGd3EVDBbgPoui7Sq8KsGonnuQgh0Epj2jY6G6Y5G8Y8xDMJQgqcnEFMVWNWjcLNZpH7XT9T0HsyFkdGh5NzVDqTzO5EIzRaoyCb3tJ6//z5cyORSD6bzfoH6ofEQXr1IIUtkLHiVRKXmWVLf//9z3zm9It27drle577njNelFJEo1FWrVrFgw8+SDQa7TaAuVyO0aNHY9s2a9asIRQKdRtAx3Goq6vjmmuuwXGcAoCFo0FobGzkrrvuItBNj+526FJKMpkM48aN48orrySdTh/wqBStNdIw/MGDBhtr161dOn78x64B7E5EJVeUDz6Q5ABn0BxsNsIZOnSoCIVCqd27d6e11nLcuHHmhg0b8qFw1EWIwn5Q/d6WoPS+r+5wgX3l073MK+jYh9nT9/Vk/HvP7zzA+7Uu7G1FCCwroILBYProo49ONzY2ZqWUKh6PYxiGamxszBVBVT0dA0vDsmpqasoVW4AAxNFHH22tXLnSMwyjXwweopTL5TzLsryiQPfb2tpKTeCgpyHKg7ctVFE4uoA7ffp0F/DKdB7KhzAEWpAJ0Wi03cbFyzsUAB6I4PensgqS7iWzzM2L0jipe1CzooItXL3MixAfCrR7C2D3rOP7CM/D0BpDa0R3mCQUnvf9wlXMq3uYF8/rB7DXyfeRVQmchY8y9se3c5OUyB7QPq011l/WIIRgWlEKdDuvEJjeKnjjbcSdcztoXz+APUyGRLe2EnxnK5FBA3t86lPJ43p8hqiU6EwG750t+9WKh/pc0nK8s+8BLJ5opE0TX8qeHYgjOnlNjwPhxZ1MprnPRuH7Pr7vH1IhX3pvXxyRWR4ApUS1JQl9bjprI2Ge/N3vCIdCqG7MIwoEecfhyCOPIGAF2LRpE7ZtdyvKLxC4nkvtoEFceMklHSHlYjTGNE0ikUhZIjGlM0X/OQAUonAqUu1gUscew+aVLxKNxnoQSssSGFKLHbTZvGsHoVC4R6E0b0gtHDsGksku94cMGcL1119fDi3X3kDy+fwHeuJw+bpQIcB1kdkstudje163AdSej+W6WFK25+0ugMLzCLguZLP74FY+tm2Xb9TQ+gPvRsuvA6Xs0HTdGeg7Pdvl6mZ57eXsxwt83y8L4dBa9wmROVw/uvG+urvD6b39AP6Tp34A+4V898YH3c1w2Luf723efgAPLtNRSmmlFEop9jUjX7pvWRaWZXWbhfq+j2mamKbZnre7LLRE5/dXr0pInQhPadWZ7hMApZQiFotppZTel6GEEEyePJnjjz++R9qoBEJpjUuPYqFaYxgGtm2XjXEewlhVaYmK7mzXsgK4du1aNWHCBGPZsmWPjxkz5nPxeLz6YHnC4XD/YLUP22cymcyyZcuWAGzfvr1XGzB70zxFXV1dcMuWLYGpU6eOq6+vH+26rjSM/Z++7/fi8wWl9/m9/PTBgerT18n3fSzL4vXXX9+yePHi9RSWrLTRiw9oiV6CLmtra4M7duwofTlDvo/3fViTBuTQoUNlU1NTpgie39NutLcGF4AcNWqUmUgkDNd1hed5/eD1pP80Td3c3Kybmpq8InC9+pzr+zW66Pe89+2FvSIvpfT/KBCo3aqVaf8AAAAASUVORK5CYII=", "w": 112, "h": 69},
    "firmada": {"b64": "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", "w": 112, "h": 67},
    "cerrada": {"b64": "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", "w": 112, "h": 67},
}

ESTADOS_TIENDA = ["Abierta", "Firmada", "Cerrada"]
_CLAVE_ESTADO_TIENDA = {"Abierta": "abierta", "Firmada": "firmada", "Cerrada": "cerrada"}

# Semáforo dibujado en SVG (no depende de ninguna imagen externa).
_SEMAFORO_SVG = (
    "data:image/svg+xml;utf8,"
    "%3Csvg xmlns='http://www.w3.org/2000/svg' width='24' height='44' viewBox='0 0 24 44'%3E"
    "%3Crect x='3' y='1' width='18' height='42' rx='6' fill='%23222' stroke='%23fff' stroke-width='2'/%3E"
    "%3Ccircle cx='12' cy='11' r='4.5' fill='%23ff3b30'/%3E"
    "%3Ccircle cx='12' cy='22' r='4.5' fill='%23ffcc00'/%3E"
    "%3Ccircle cx='12' cy='33' r='4.5' fill='%2334c759'/%3E%3C/svg%3E"
)


# Estación / parada de TransMilenio (cuadro rojo con "TM"), dibujada en SVG.
_TM_SVG = (
    "data:image/svg+xml;utf8,"
    "%3Csvg xmlns='http://www.w3.org/2000/svg' width='32' height='32' viewBox='0 0 32 32'%3E"
    "%3Crect x='1.5' y='1.5' width='29' height='29' rx='7' fill='%23D5281B' stroke='%23fff' stroke-width='3'/%3E"
    "%3Ctext x='16' y='21.5' font-family='Arial,Helvetica,sans-serif' font-size='14' font-weight='700' "
    "text-anchor='middle' fill='%23fff'%3ETM%3C/text%3E%3C/svg%3E"
)


def _lineas_punto(row) -> list:
    def v(col):
        x = row.get(col, "")
        x = "" if x is None else str(x).strip()
        return x if x and x.lower() != "nan" else "—"

    lineas = [
        f"Fuente: {v('fuente')}",
        f"Responsable: {v('especialista')}",
    ]
    if "practicante" in row:
        lineas.append(f"Practicante: {v('practicante')}")
    lineas += [
        f"Estado: {v('estado')}",
        f"Fecha de registro: {v('fecha_registro')}",
        f"Ciudad: {v('ciudad')}",
    ]
    return lineas


def construir_html_mapa(
    puntos,
    colores_fuente: dict,
    colores_hex: dict,
    resaltados=None,
    tiendas=None,
    centro=None,
    altura: int = 620,
    capas_apagadas=None,
    tiendas_apagadas=None,
) -> str:
    """
    Devuelve el HTML completo del mapa.

    - puntos: DataFrame de puntos potenciales (con latitud/longitud y las
      columnas de la app). Ya viene filtrado si hace falta.
    - colores_fuente: {fuente: clave de color de pin} (FUENTE_COLOR_ICONO).
    - colores_hex: {clave de color: hex} para la leyenda.
    - resaltados: lista de (lat, lon, etiqueta[, info_extra]) — se dibujan en
      ROJO, encima de todo.
    - tiendas: DataFrame de tiendas OXXO (columnas: nombre, estado_tienda,
      ciudad, direccion, latitud, longitud, detalle) o None.
    - centro: (lat, lon, zoom). Si no se da y hay resaltados, se centra en
      ellos; si no, abre en Bogotá.
    """
    resaltados = resaltados or []
    capas_apagadas = set(capas_apagadas or [])
    tiendas_apagadas = set(tiendas_apagadas or [])

    pts = []
    if puntos is not None and len(puntos):
        base = puntos.dropna(subset=["latitud", "longitud"])
        for row in base.to_dict("records"):
            fuente = str(row.get("fuente", ""))
            nombre = str(row.get("local_identificado", "") or "—")
            pts.append({
                "a": round(float(row["latitud"]), 7),
                "o": round(float(row["longitud"]), 7),
                "c": fuente,
                "k": colores_fuente.get(fuente, "gris"),
                "t": nombre,
                "l": _lineas_punto(row),
            })

    res = []
    for item in resaltados:
        extra = []
        if len(item) > 3 and item[3]:
            extra = [ln for ln in str(item[3]).split("\n") if ln.strip()]
        res.append({"a": float(item[0]), "o": float(item[1]), "t": str(item[2]), "l": extra})

    tds = []
    if tiendas is not None and len(tiendas):
        base_t = tiendas.dropna(subset=["latitud", "longitud"])
        for row in base_t.to_dict("records"):
            estado = str(row.get("estado_tienda", "") or "")
            if estado not in _CLAVE_ESTADO_TIENDA:
                continue
            lineas = [f"Estado de la tienda: {estado}"]
            for etiqueta, col in (
                ("Ciudad", "ciudad"), ("Dirección", "direccion"), ("Detalle", "detalle"),
            ):
                val = str(row.get(col, "") or "").strip()
                if val and val.lower() != "nan":
                    lineas.append(f"{etiqueta}: {val}")
            tds.append({
                "a": round(float(row["latitud"]), 7),
                "o": round(float(row["longitud"]), 7),
                "e": estado,
                "t": str(row.get("nombre", "") or "Tienda OXXO"),
                "l": lineas,
            })

    if centro is not None:
        vista = [float(centro[0]), float(centro[1]), float(centro[2])]
    elif res:
        vista = None  # se ajusta sola a los resaltados (JavaScript)
    else:
        vista = [4.6097, -74.0817, 10.5]

    datos = {
        "pts": pts,
        "res": res,
        "tds": tds,
        "centro": vista,
        "pines": {k: f"data:image/png;base64,{v}" for k, v in _PINES_B64.items()},
        "capas": [
            {"key": f, "hex": colores_hex.get(k, "#999999"), "color": k, "off": f in capas_apagadas}
            for f, k in colores_fuente.items()
        ],
        "tiendas_cfg": [
            {
                "key": e, "clave": _CLAVE_ESTADO_TIENDA[e],
                "icono": f"data:image/png;base64,{_TIENDAS_ICONOS[_CLAVE_ESTADO_TIENDA[e]]['b64']}",
                "w": _TIENDAS_ICONOS[_CLAVE_ESTADO_TIENDA[e]]["w"],
                "h": _TIENDAS_ICONOS[_CLAVE_ESTADO_TIENDA[e]]["h"],
                "off": e in tiendas_apagadas,
            }
            for e in ESTADOS_TIENDA
        ] if tds else [],
        "semaforo": _SEMAFORO_SVG,
        "tm": _TM_SVG,
        "rojo_hex": colores_hex.get("rojo", "#E11E1E"),
    }
    datos_json = json.dumps(datos, ensure_ascii=False).replace("</", "<\\/")
    return _PLANTILLA.replace("__DATA__", datos_json).replace("__ALTURA__", str(int(altura)))


_PLANTILLA = r"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  * { box-sizing: border-box; }
  html, body { margin:0; padding:0; height:100%; background:#F7F7F8;
    font-family: "Source Sans Pro", "Segoe UI", Roboto, Arial, sans-serif; color:#1A1A1A; }
  #app { display:flex; flex-direction:column; height:__ALTURA__px; }
  #bar { display:flex; flex-wrap:wrap; align-items:center; gap:6px 8px; padding:2px 2px 8px 2px; }
  .chip { display:inline-flex; align-items:center; gap:7px; background:#fff; border:1px solid #D9D9DE;
    border-radius:999px; padding:5px 12px; font-size:14px; cursor:pointer; user-select:none; color:#1A1A1A; }
  .chip.off { opacity:.45; text-decoration:line-through; }
  .chip .dot { width:12px; height:12px; border-radius:50%; display:inline-block; }
  .chip img { height:16px; width:auto; display:block; }
  .chip .n { color:#6B6B70; font-size:12.5px; }
  .chip.fijo { cursor:default; font-weight:700; }
  .seg { display:inline-flex; border:1px solid #D9D9DE; border-radius:999px; overflow:hidden; background:#fff; }
  .seg button { border:0; background:#fff; padding:6px 14px; font-size:14px; cursor:pointer; color:#1A1A1A; }
  .seg button.on { background:#E11E1E; color:#fff; font-weight:700; }
  .oculto { display:none !important; }
  .sep { width:1px; height:22px; background:#D9D9DE; margin:0 4px; }
  select, .btn { font-size:14px; border:1px solid #D9D9DE; border-radius:8px; background:#fff; padding:5px 9px; color:#1A1A1A; cursor:pointer; }
  #mapwrap { position:relative; flex:1; min-height:200px; border:1px solid #D9D9DE; border-radius:12px; overflow:hidden; background:#E6E3DD; }
  #map { position:absolute; inset:0; cursor:grab; touch-action:none; overflow:hidden; }
  #map.drag { cursor:grabbing; }
  #tiles, #marks { position:absolute; left:0; top:0; width:100%; height:100%; }
  #tiles { z-index:0; overflow:hidden; }
  #tiles img.suave { filter: grayscale(1) contrast(.72) brightness(1.2); }
  #marks { z-index:1; }
  #tiles img { position:absolute; left:0; top:0; max-width:none; user-select:none; -webkit-user-drag:none; pointer-events:none; }
  .mk { position:absolute; left:0; top:0; will-change:transform; }
  .mk img { position:absolute; display:block; max-width:none; -webkit-user-drag:none; user-select:none; filter:drop-shadow(0 1px 2px rgba(0,0,0,.35)); }
  .mk.sem img { filter:none; pointer-events:none; }
  .mk.hov img { filter:drop-shadow(0 0 5px rgba(0,0,0,.6)); }
  .lbl { position:absolute; transform:translate(-50%,0); white-space:nowrap; font-size:14px; font-weight:700; color:#111;
    background:rgba(255,255,255,.92); border-radius:6px; padding:1px 7px; border:1px solid rgba(0,0,0,.15); pointer-events:none; }
  #tip { position:absolute; z-index:50; display:none; background:#fff; border:1px solid #CFCFD6; border-radius:12px;
    box-shadow:0 8px 28px rgba(0,0,0,.28); padding:11px 15px; font-size:14.5px; line-height:1.55; max-width:340px; pointer-events:none; }
  #tip.fijada { pointer-events:auto; border-color:#E11E1E; }
  #tip .tt { font-weight:700; font-size:15.5px; margin-bottom:3px; }
  #tip .ap { margin-top:6px; padding-top:6px; border-top:1px dashed #D9D9DE; color:#B42318; font-weight:600; }
  #tip .pie { margin-top:6px; color:#8A8A90; font-size:12.5px; }
  #zoom { position:absolute; right:10px; top:10px; z-index:20; display:flex; flex-direction:column; gap:6px; }
  #zoom button { width:38px; height:38px; font-size:22px; line-height:1; background:#fff; border:1px solid #CFCFD6; border-radius:9px; cursor:pointer; color:#222; }
  #estado { position:absolute; left:10px; bottom:24px; z-index:20; background:rgba(255,255,255,.92); border-radius:8px;
    padding:3px 9px; font-size:12.5px; color:#444; display:none; }
  #attr { position:absolute; right:6px; bottom:3px; z-index:20; background:rgba(255,255,255,.8); font-size:11px; padding:0 5px; color:#444; border-radius:4px; }
</style></head>
<body>
<div id="app">
  <div id="bar"></div>
  <div id="mapwrap">
    <div id="map"><div id="tiles"></div><div id="marks"></div></div>
    <div id="zoom"><button id="zin" title="Acercar">+</button><button id="zout" title="Alejar">&minus;</button></div>
    <div id="estado"></div>
    <div id="attr"></div>
    <div id="tip"></div>
  </div>
</div>
<script>
(function(){
"use strict";
var D = __DATA__;
var $ = function(id){ return document.getElementById(id); };
var mapEl=$('map'), tilesEl=$('tiles'), marksEl=$('marks'), tip=$('tip'), wrap=$('mapwrap');
var W=0, H=0;
var MIN_Z=3, MAX_Z=20;

function esc(s){ return String(s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];}); }
function clamp(v,a,b){ return Math.max(a,Math.min(b,v)); }

/* ---------- mapas base ---------- */
var BASES = {
  osm: {url:'https://tile.openstreetmap.org/{z}/{x}/{y}.png', max:19, attr:'© OpenStreetMap'},
  gris: {url:'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}', max:16, attr:'© Esri, © OpenStreetMap'},
  grisref: {url:'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}', max:16, attr:''}
};
var S = { mode:'simple', big:false, sem:false, tm:false };

/* ---------- proyección (Web Mercator) ---------- */
function ws(z){ return 256*Math.pow(2,z); }
function proj(lat,lon,z){
  var s=ws(z), r=lat*Math.PI/180;
  return [(lon+180)/360*s, (1-Math.log(Math.tan(r)+1/Math.cos(r))/Math.PI)/2*s];
}
function unproj(x,y,z){
  var s=ws(z), n=Math.PI*(1-2*y/s);
  return [180/Math.PI*Math.atan(0.5*(Math.exp(n)-Math.exp(-n))), x/s*360-180];
}

var view = {lat:4.6097, lon:-74.0817, z:10.5};

/* ---------- marcadores ---------- */
var marks = [];      // todos los marcadores
var TZ = {};         // por tipo
function mkImg(src){ var i=document.createElement('img'); i.src=src; i.draggable=false; return i; }

function addMark(o){
  var el=document.createElement('div'); el.className='mk'+(o.kind==='s'?' sem':'');
  var img=mkImg(o.src); el.appendChild(img);
  o.el=el; o.img=img; o.ox=0; o.oy=0; o.stack=1; o.vis=true; o.x=0; o.y=0;
  if(o.label){ var l=document.createElement('div'); l.className='lbl'; l.textContent=o.label; el.appendChild(l); o.lbl=l; }
  el.style.zIndex = o.z;
  if(o.kind!=='s'){
    el.addEventListener('mouseenter',function(){ hoverMark=o; el.classList.add('hov'); if(!pinned) showTip(o,false); });
    el.addEventListener('mouseleave',function(){ el.classList.remove('hov'); if(hoverMark===o) hoverMark=null; if(!pinned) hideTip(); });
    el.addEventListener('click',function(ev){
      if(moved>4) return; ev.stopPropagation();
      if(pinned===o){ pinned=null; hideTip(); } else { pinned=o; showTip(o,true); }
    });
  }
  marksEl.appendChild(el); marks.push(o);
  return o;
}
var hoverMark=null, pinned=null, moved=0;

var capaOn = {}, tiendaOn = {};

function build(){
  // tiendas (debajo de los pines)
  var cfgT={}; D.tiendas_cfg.forEach(function(c){ cfgT[c.key]=c; tiendaOn[c.key]=!c.off; });
  D.tds.forEach(function(t){
    var c=cfgT[t.e]; if(!c) return;
    addMark({kind:'t', a:t.a, o:t.o, grp:t.e, src:c.icono, w:c.w, h:c.h, t:t.t, l:t.l, z:2});
  });
  // puntos potenciales
  D.capas.forEach(function(c){ capaOn[c.key]=!c.off; });
  var porColor={}; D.capas.forEach(function(c){ porColor[c.key]=c; });
  D.pts.forEach(function(p){
    addMark({kind:'p', a:p.a, o:p.o, grp:p.c, src:D.pines[p.k]||D.pines.gris, t:p.t, l:p.l, z:4});
  });
  // resaltados (rojo, encima de todo)
  D.res.forEach(function(r){
    addMark({kind:'r', a:r.a, o:r.o, grp:'__res', src:D.pines.rojo, t:r.t, l:r.l, z:6, label:r.t});
  });
}
build();

/* ---------- barra de capas ---------- */
var counts={};
marks.forEach(function(m){ counts[m.grp]=(counts[m.grp]||0)+1; });
var bar=$('bar');
function chip(html, on, cb, cls){
  var b=document.createElement('span'); b.className='chip'+(on?'':' off')+(cls?' '+cls:''); b.innerHTML=html;
  if(cb){ b.addEventListener('click',function(){ cb(b); }); }
  bar.appendChild(b); return b;
}
D.capas.forEach(function(c){
  chip('<span class="dot" style="background:'+c.hex+'"></span>'+esc(c.key)+' <span class="n">'+(counts[c.key]||0)+'</span>', !c.off, function(b){
    capaOn[c.key]=!capaOn[c.key]; b.classList.toggle('off',!capaOn[c.key]); refresh();
  });
});
if(D.res.length){ chip('<span class="dot" style="background:'+D.rojo_hex+'"></span><b>Punto buscado</b>', true, null, 'fijo'); }
if(D.tiendas_cfg.length){
  var s1=document.createElement('span'); s1.className='sep'; bar.appendChild(s1);
  D.tiendas_cfg.forEach(function(c){
    chip('<img src="'+c.icono+'">Tiendas '+esc(c.key.toLowerCase()+'s')+' <span class="n">'+(counts[c.key]||0)+'</span>', !c.off, function(b){
      tiendaOn[c.key]=!tiendaOn[c.key]; b.classList.toggle('off',!tiendaOn[c.key]); refresh();
    });
  });
}
var chipSem=chip('<img src="'+D.semaforo+'" style="height:18px"> Semáforos', true, function(b){
  S.sem=!S.sem; b.classList.toggle('off',!S.sem); refresh(); fetchExtra();
}, 'solo-detalle');
var chipTm=chip('<img src="'+D.tm+'" style="height:18px"> TransMilenio', true, function(b){
  S.tm=!S.tm; b.classList.toggle('off',!S.tm); refresh(); fetchExtra();
}, 'solo-detalle');
var chipBig=chip('Aa Letras grandes', false, function(b){ S.big=!S.big; b.classList.toggle('off',!S.big); refresh(); });

/* Dos formas de ver el mapa: simple (limpio, poco saturado) y detallado (calles,
   direcciones, semáforos y TransMilenio). */
function setMode(m){
  S.mode=m; S.big=false; S.sem=(m==='detalle'); S.tm=(m==='detalle');
  segBtns.simple.classList.toggle('on', m==='simple'); segBtns.detalle.classList.toggle('on', m==='detalle');
  chipSem.classList.toggle('oculto', m==='simple'); chipTm.classList.toggle('oculto', m==='simple');
  chipSem.classList.toggle('off', !S.sem); chipTm.classList.toggle('off', !S.tm); chipBig.classList.toggle('off', !S.big);
  setEstado(''); refresh(); fetchExtra();
}
var seg=document.createElement('span'); seg.className='seg';
var segBtns={};
[['simple','Mapa simple'],['detalle','Mapa detallado']].forEach(function(x){
  var b=document.createElement('button'); b.type='button'; b.textContent=x[1];
  b.addEventListener('click',function(){ setMode(x[0]); });
  seg.appendChild(b); segBtns[x[0]]=b;
});
bar.insertBefore(seg, bar.firstChild);
var sepSeg=document.createElement('span'); sepSeg.className='sep'; bar.insertBefore(sepSeg, seg.nextSibling);

/* ---------- semáforos y TransMilenio (OpenStreetMap vía Overpass) ---------- */
var extras = {};           // id -> marcador
var sigCells = {};         // celda -> 'ok' | 'cargando' | 'fallo'
var sigQueue = [], sigActive = 0, sigFail = 0;
function setEstado(t){ var e=$('estado'); if(t){ e.textContent=t; e.style.display='block'; } else { e.style.display='none'; } }
function sigPump(){
  while(sigActive<2 && sigQueue.length){
    var c=sigQueue.shift(); sigActive++;
    (function(c){
      var step=0.01, bb='('+(c.i*step)+','+(c.j*step)+','+((c.i+1)*step)+','+((c.j+1)*step)+')';
      var re='[~"^(network|operator)$"~"transmilenio",i]';
      var q='[out:json][timeout:25];('
        +'node["highway"="traffic_signals"]'+bb+';'
        +'node'+re+'["highway"="bus_stop"]'+bb+';'
        +'node'+re+'["public_transport"="station"]'+bb+';'
        +'way'+re+'["public_transport"="station"]'+bb+';'
        +'node'+re+'["amenity"="bus_station"]'+bb+';'
        +');out center tags;';
      var done=false;
      function fin(ok){
        if(done) return; done=true; sigActive--; sigCells[c.key]=ok?'ok':'fallo'; if(!ok) sigFail++;
        if(!sigQueue.length && !sigActive) setEstado(sigFail && !Object.keys(extras).length ? 'No se pudieron cargar los semáforos / TransMilenio' : '');
        refresh(); sigPump();
      }
      try{
        fetch('https://overpass-api.de/api/interpreter',{method:'POST',body:'data='+encodeURIComponent(q),headers:{'Content-Type':'application/x-www-form-urlencoded'}})
          .then(function(r){ if(!r.ok) throw new Error('http'); return r.json(); })
          .then(function(j){ (j.elements||[]).forEach(function(e){
              var la=e.lat!==undefined?e.lat:(e.center?e.center.lat:undefined), lo=e.lon!==undefined?e.lon:(e.center?e.center.lon:undefined);
              var id=e.type+e.id; if(la===undefined||extras[id]) return;
              var tg=e.tags||{};
              if(tg.highway==='traffic_signals'){
                extras[id]=addMark({kind:'s', a:la, o:lo, grp:'__sem', src:D.semaforo, t:'Semáforo', l:[], z:3});
              } else {
                var nom=tg.name||'Parada / estación';
                extras[id]=addMark({kind:'m', a:la, o:lo, grp:'__tm', src:D.tm, t:nom, l:['TransMilenio'+(tg.operator&&!/transmilenio/i.test(tg.operator)?' · '+tg.operator:'')], z:3});
              }
            }); fin(true); })
          .catch(function(){ fin(false); });
      }catch(e){ fin(false); }
    })(c);
  }
}
function fetchExtra(){
  if(!S.sem && !S.tm){ setEstado(''); return; }
  if(view.z<15.2){ setEstado(view.z>=13.5 ? 'Acércate un poco más para ver los semáforos y TransMilenio' : ''); return; }
  var c=proj(view.lat,view.lon,view.z);
  var tl=unproj(c[0]-W/2, c[1]-H/2, view.z), br=unproj(c[0]+W/2, c[1]+H/2, view.z);
  var step=0.01;
  var la0=Math.floor(br[0]/step), la1=Math.floor(tl[0]/step), lo0=Math.floor(tl[1]/step), lo1=Math.floor(br[1]/step);
  var nuevas=0;
  for(var i=la0;i<=la1;i++){ for(var j=lo0;j<=lo1;j++){
    var key=i+'_'+j; if(sigCells[key]) continue;
    sigCells[key]='cargando'; sigQueue.push({key:key,i:i,j:j}); nuevas++;
  }}
  if(nuevas) setEstado('Cargando semáforos y TransMilenio…'); else if(!sigQueue.length && !sigActive) setEstado('');
  sigPump();
}

/* ---------- tarjeta de información ---------- */
function tipHtml(m, fijada){
  var h='<div class="tt">'+(m.kind==='r'?'🔎 ':(m.kind==='t'?'🏪 ':(m.kind==='m'?'🚌 ':'📍 ')))+esc(m.t)+'</div>';
  m.l.forEach(function(x){ h+='<div>'+esc(x)+'</div>'; });
  if(m.stack>1) h+='<div class="ap">⚠️ Hay '+m.stack+' puntos en este mismo lugar</div>';
  h+='<div class="pie">'+(fijada?'Clic de nuevo para cerrar':'Clic para dejar la tarjeta fija')+'</div>';
  return h;
}
function showTip(m, fijada){
  tip.innerHTML=tipHtml(m,fijada); tip.className=fijada?'fijada':''; tip.style.display='block';
  tip.style.visibility='hidden';
  placeTip(m);
  tip.style.visibility='visible';
}
function placeTip(m){
  var w=tip.offsetWidth, h=tip.offsetHeight, gap=26;
  var x=m.x+gap; if(x+w>W-8) x=m.x-gap-w;
  x=clamp(x,8,Math.max(8,W-w-8));
  var y=m.y-h/2-((m.kind==='t'||m.kind==='m')?0:18);
  y=clamp(y,8,Math.max(8,H-h-8));
  tip.style.left=x+'px'; tip.style.top=y+'px';
}
function hideTip(){ tip.style.display='none'; }

/* ---------- dibujo ---------- */
var tileCache={}, cleanTimer=null;
function tileUrl(b,z,x,y){
  var bm=BASES[b], u=bm.url.replace('{z}',z).replace('{x}',x).replace('{y}',y);
  if(bm.sub) u=u.replace('{s}',bm.sub[(x+y)%bm.sub.length]);
  return u;
}
function capasBase(){
  /* Mapa simple: gris claro de Esri (como el mapa claro de antes) hasta el zoom 16;
     más cerca se usa OpenStreetMap en gris suave. Mapa detallado: OpenStreetMap a color. */
  if(S.mode==='simple'){
    if(view.z<=16.5) return [{id:'gris',cls:'',o:0},{id:'grisref',cls:'',o:1}];
    return [{id:'osm',cls:'suave',o:0}];
  }
  return [{id:'osm',cls:'',o:0}];
}
function renderTiles(cx,cy){
  var caps=capasBase(), used={}, activas={};
  var k=S.big?1.5:1;
  caps.forEach(function(cp){
    activas[cp.id+'|'+cp.cls]=1;
    var bm=BASES[cp.id];
    var tz=S.big ? Math.floor(view.z-Math.log(k)/Math.LN2) : Math.floor(view.z+0.7);
    tz=clamp(tz,0,bm.max);
    var sc=Math.pow(2,view.z-tz), ts=256*sc, n=Math.pow(2,tz);
    var x0=Math.floor((cx-W/2)/ts), x1=Math.floor((cx+W/2)/ts), y0=Math.floor((cy-H/2)/ts), y1=Math.floor((cy+H/2)/ts);
    for(var ty=y0;ty<=y1;ty++){ if(ty<0||ty>=n) continue;
      for(var tx=x0;tx<=x1;tx++){
        var txw=((tx%n)+n)%n, key=cp.id+'|'+cp.cls+'/'+tz+'/'+tx+'/'+ty; used[key]=1;
        if(!tileCache[key]){
          var im=document.createElement('img'); im.src=tileUrl(cp.id,tz,txw,ty); im.draggable=false;
          if(cp.cls) im.className=cp.cls;
          im.onerror=function(){ this.style.visibility='hidden'; };
          tilesEl.appendChild(im);
          tileCache[key]={el:im,tz:tz,tx:tx,ty:ty,lay:cp.id+'|'+cp.cls,o:cp.o};
        }
        tileCache[key].used=1;
      }
    }
  });
  $('attr').textContent = S.mode==='simple' ? (view.z<=16.5 ? BASES.gris.attr : '© OpenStreetMap') : BASES.osm.attr;
  Object.keys(tileCache).forEach(function(key){
    var t=tileCache[key];
    var s2=Math.pow(2,view.z-t.tz), size=256*s2;
    t.el.style.width=(size+0.6)+'px'; t.el.style.height=(size+0.6)+'px';
    t.el.style.transform='translate('+(W/2+t.tx*size-cx)+'px,'+(H/2+t.ty*size-cy)+'px)';
    t.el.style.zIndex=t.o*100+t.tz;
    t.el.style.display = activas[t.lay]?'block':'none';
    if(!used[key]) t.used=0;
  });
  clearTimeout(cleanTimer);
  cleanTimer=setTimeout(function(){
    Object.keys(tileCache).forEach(function(key){
      var t=tileCache[key];
      if(!t.used || !activas[t.lay]){ if(t.el.parentNode) t.el.parentNode.removeChild(t.el); delete tileCache[key]; }
    });
  },450);
}

function sizeFor(m){
  var z=view.z;
  if(m.kind==='t'){ var w=z<11?18:(z<13?24:(z<15?32:42)); return [w, w*m.h/m.w]; }
  if(m.kind==='s'){ var s=z<17?14:(z<18?18:22); return [s*0.55, s]; }
  if(m.kind==='m'){ var q=z<16.5?18:(z<17.5?22:26); return [q, q]; }
  var hgt = m.kind==='r' ? (z<12?46:54) : (z<11?22:(z<13?28:(z<15?34:40)));
  return [hgt*64/88, hgt];
}
function render(){
  W=wrap.clientWidth; H=wrap.clientHeight;
  var c=proj(view.lat,view.lon,view.z), cx=c[0], cy=c[1];
  renderTiles(cx,cy);
  // visibilidad + abanico de apilados
  var grupos={};
  marks.forEach(function(m){
    if(m.kind==='p') m.vis=!!capaOn[m.grp];
    else if(m.kind==='t') m.vis=!!tiendaOn[m.grp];
    else if(m.kind==='s') m.vis=S.sem && view.z>=15.2;
    else if(m.kind==='m') m.vis=S.tm && view.z>=15.2;
    else m.vis=true;
    m.ox=0; m.oy=0; m.stack=1;
    if(m.vis && (m.kind==='p'||m.kind==='r')){
      var key=m.a.toFixed(4)+','+m.o.toFixed(4); (grupos[key]=grupos[key]||[]).push(m);
    }
  });
  Object.keys(grupos).forEach(function(key){
    var g=grupos[key], n=g.length; if(n<2) return;
    var esp=(view.z<13)?18:26;
    g.sort(function(a,b){ return (a.kind==='r')-(b.kind==='r'); });
    g.forEach(function(m,i){ m.ox=(i-(n-1)/2)*esp; m.stack=n; });
  });
  marks.forEach(function(m){
    if(!m.vis){ m.el.style.display='none'; return; }
    var p=proj(m.a,m.o,view.z), x=W/2+p[0]-cx+m.ox, y=H/2+p[1]-cy+m.oy;
    m.x=x; m.y=y;
    if(x<-60||x>W+60||y<-90||y>H+60){ m.el.style.display='none'; return; }
    var sz=sizeFor(m), w=sz[0], h=sz[1];
    m.img.style.width=w+'px'; m.img.style.height=h+'px';
    if(m.kind==='p'||m.kind==='r'){ m.img.style.left=(-w/2)+'px'; m.img.style.top=(-h*84/88)+'px'; if(m.lbl){ m.lbl.style.left='0px'; m.lbl.style.top=(-h*84/88-26)+'px'; } }
    else { m.img.style.left=(-w/2)+'px'; m.img.style.top=(-h/2)+'px'; }
    m.el.style.display='block';
    m.el.style.transform='translate('+x+'px,'+y+'px)';
  });
  var act=pinned||hoverMark; if(act && act.vis && tip.style.display==='block'){ tip.innerHTML=tipHtml(act,pinned===act); placeTip(act); }
}
var raf=0;
function refresh(){ if(raf) return; raf=requestAnimationFrame(function(){ raf=0; render(); }); }

/* ---------- interacción ---------- */
var drag=null;
mapEl.addEventListener('pointerdown',function(e){
  if(e.button!==undefined && e.button>0) return;
  drag={x:e.clientX,y:e.clientY,lat:view.lat,lon:view.lon}; moved=0;
});
window.addEventListener('pointermove',function(e){
  if(!drag) return;
  var dx=e.clientX-drag.x, dy=e.clientY-drag.y; moved=Math.max(moved,Math.abs(dx),Math.abs(dy));
  if(moved>4){ mapEl.classList.add('drag'); if(!pinned) hideTip();
    var c=proj(drag.lat,drag.lon,view.z), g=unproj(c[0]-dx,c[1]-dy,view.z); view.lat=g[0]; view.lon=g[1]; refresh(); }
});
window.addEventListener('pointerup',function(){ if(drag){ drag=null; mapEl.classList.remove('drag'); fetchExtra(); } });
mapEl.addEventListener('click',function(){ if(moved>4) return; if(pinned){ pinned=null; hideTip(); } });
function zoomAt(px,py,nz){
  nz=clamp(nz,MIN_Z,MAX_Z); var c=proj(view.lat,view.lon,view.z);
  var g=unproj(c[0]+(px-W/2), c[1]+(py-H/2), view.z);
  var p=proj(g[0],g[1],nz), n=unproj(p[0]-(px-W/2), p[1]-(py-H/2), nz);
  view.lat=n[0]; view.lon=n[1]; view.z=nz; refresh();
}
var wheelT=null;
mapEl.addEventListener('wheel',function(e){
  e.preventDefault(); var r=wrap.getBoundingClientRect();
  zoomAt(e.clientX-r.left,e.clientY-r.top, view.z + clamp(-e.deltaY*0.0016,-0.6,0.6));
  clearTimeout(wheelT); wheelT=setTimeout(fetchExtra,350);
},{passive:false});
mapEl.addEventListener('dblclick',function(e){ var r=wrap.getBoundingClientRect(); zoomAt(e.clientX-r.left,e.clientY-r.top,view.z+1); fetchExtra(); });
$('zin').addEventListener('click',function(){ zoomAt(W/2,H/2,view.z+1); fetchExtra(); });
$('zout').addEventListener('click',function(){ zoomAt(W/2,H/2,view.z-1); fetchExtra(); });
window.addEventListener('resize',refresh);

/* ---------- vista inicial ---------- */
function fit(list){
  W=wrap.clientWidth; H=wrap.clientHeight;
  var la=list.map(function(m){return m.a;}), lo=list.map(function(m){return m.o;});
  var mnA=Math.min.apply(null,la), mxA=Math.max.apply(null,la), mnO=Math.min.apply(null,lo), mxO=Math.max.apply(null,lo);
  view.lat=(mnA+mxA)/2; view.lon=(mnO+mxO)/2;
  var z=17;
  if(list.length>1){
    for(z=18; z>MIN_Z; z-=0.25){
      var a=proj(mxA,mnO,z), b=proj(mnA,mxO,z);
      if(Math.abs(b[0]-a[0])<W-160 && Math.abs(b[1]-a[1])<H-200) break;
    }
  }
  view.z=Math.min(z,18);
}
if(D.centro){ view.lat=D.centro[0]; view.lon=D.centro[1]; view.z=D.centro[2]; }
else { var rr=marks.filter(function(m){return m.kind==='r';}); if(rr.length) fit(rr); }
setMode('simple');
render(); setTimeout(function(){ render(); fetchExtra(); },60);
})();
</script></body></html>
"""
