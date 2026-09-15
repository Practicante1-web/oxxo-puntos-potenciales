# Consulta y Seguimiento de Puntos Potenciales — OXXO

Prototipo del aplicativo propuesto en el proyecto de práctica profesional
(Inteligencia de Expansión, OXXO) para que los especialistas puedan:

- Consultar si una ubicación ya tiene un punto potencial registrado cerca **o con el mismo nombre** (evitar duplicidades).
- Visualizar los puntos cercanos y la distancia entre ellos.
- Registrar nuevas oportunidades.
- Hacer seguimiento del estado de cada oportunidad (Solicitado / Revisión / Entregado).
- Ver un mapa general de todas las oportunidades, con filtros por ciudad, especialista y estado.
- **Se carga sola** al abrir, leyendo `data/Puntos_potenciales.xlsx` — el mismo archivo va incluido en el proyecto, como un "Book.xlsx" que viaja con la app.

## ⚠️ Importante: este archivo contiene datos reales de la empresa

`data/Puntos_potenciales.xlsx` es tu archivo real (735 puntos: nombres de
especialistas, ubicaciones exactas, ciudad, estado) — no es un mock. El
loader (`utils.py`) también sabe leer el formato anterior de "Revisión
Microsaturaciones" por si alguna vez lo vuelves a usar. **Antes de subir
esto a GitHub, confirma con tu jefe/tutor de práctica si está permitido
subir esta información** (aunque sea a un repositorio privado). Recomendaciones:

- Crea el repositorio de GitHub como **Privado**, no público.
- Streamlit Community Cloud sí permite desplegar apps desde repos privados
  gratis (autorizando el acceso al conectar tu cuenta de GitHub), así que
  no pierdes la opción de publicarla.
- Si de todas formas no está permitido subir los datos reales, puedes
  quitar `data/Puntos_potenciales.xlsx` del repositorio (o dejarlo con
  datos de ejemplo) y usar la pestaña **"⬆️ Actualizar datos"** de la app
  para cargar el archivo real solo en tu sesión local.

## Estructura del proyecto

```
oxxo-puntos-potenciales/
├── app.py                          # Aplicación principal de Streamlit
├── utils.py                        # Lógica de distancia, nombres y carga de Excel
├── data/
│   ├── Puntos_potenciales.xlsx     # Archivo real, incluido en el proyecto — se carga solo al abrir
│   └── puntos_potenciales.csv      # Copia de trabajo (respaldo / cambios dentro de una sesión)
├── requirements.txt
├── .gitignore
└── README.md
```

## Cómo correrlo en tu computador

1. Instala Python 3.10 o superior (si no lo tienes).
2. Abre una terminal en esta carpeta y crea un entorno virtual (opcional pero recomendado):
   ```bash
   python -m venv venv
   source venv/bin/activate      # En Windows: venv\Scripts\activate
   ```
3. Instala las dependencias:
   ```bash
   pip install -r requirements.txt
   ```
4. Corre la app:
   ```bash
   streamlit run app.py
   ```
5. Se abrirá automáticamente en tu navegador (normalmente en `http://localhost:8501`).

## Cómo actualizar los datos

### Forma principal — reemplazar el archivo en GitHub

`data/Puntos_potenciales.xlsx` se lee automáticamente cada vez que se abre
la app (verás el aviso verde "✅ Puntos_potenciales.xlsx cargado
automáticamente · N puntos potenciales" arriba de todo). Para actualizar:

1. Descarga desde OneDrive/SharePoint la versión más reciente de tu Excel.
2. Entra al repositorio en GitHub, abre la carpeta `data/`, y sube el
   archivo nuevo **con el mismo nombre** (`Puntos_potenciales.xlsx`) — en
   GitHub, arrastrarlo ahí mismo te pregunta si quieres reemplazar el
   existente.
3. Confirma el commit. Si la app está publicada en Streamlit Community
   Cloud, se redepliega sola en 1-2 minutos; si la corres en tu
   computador, solo tienes que recargar la página.

No hace falta abrir la app ni darle clic a nada — por eso es la forma más
simple para el día a día. Las siguientes dos opciones (en la pestaña
**"⬆️ Actualizar datos"**) son alternativas para casos puntuales.

### Opción alterna 1 — Subir el archivo manualmente desde la app

1. Abre la app y ve a la pestaña **"⬆️ Actualizar datos"**.
2. Sube el archivo (.xlsx o .csv) — la app te muestra una vista previa
   antes de confirmar.
3. Haz clic en **"Reemplazar datos de la app con este archivo"**.

Útil para probar un archivo sin tener que subirlo a GitHub primero — pero
ojo, ese cambio **no queda guardado** si la app se reinicia o se
redespliega (en ese momento vuelve a leer `Puntos_potenciales.xlsx`).

### Opción alterna 2 — Conexión en vivo por link de OneDrive (sin subir nada)

La app puede leer el Excel directamente desde un link de OneDrive/SharePoint,
**pero solo si el archivo está compartido con el permiso "Cualquier persona
con el vínculo"** (acceso público, sin necesitar iniciar sesión de
Microsoft). Esto depende de cómo esté configurado el "Compartir" del
archivo en OneDrive, no del código:

1. En OneDrive/SharePoint, dale clic derecho al archivo → **Compartir** →
   revisa que diga **"Cualquier persona con el vínculo puede ver"** (no
   "Personas de OXXO"). Si tu compañero logró conectar un archivo suyo así,
   probablemente lo compartió con ese permiso.
2. Copia ese link y pégalo en la pestaña "Actualizar datos" → "Conectada en
   vivo a un link de OneDrive".
3. Dale clic en **"Probar conexión"**. Si el archivo es realmente público,
   verás la vista previa de los datos. Si en cambio aparece un error
   diciendo que "parece requerir inicio de sesión", significa que el link
   está restringido a la organización y esta opción no va a funcionar —
   en ese caso, usa la forma principal (reemplazar el archivo en GitHub).
4. Si la prueba funciona, haz clic en **"Activar esta conexión en vivo"**.

Una vez activada, la app **no se refresca sola por tiempo** — verás un
botón **"🔄 Actualizar ahora"** junto al título, arriba de la página, que
descarga la versión más reciente del archivo cuando tú lo pidas (por
ejemplo, después de que alguien registre puntos nuevos).

En cualquiera de los dos casos, actualizar los datos **reemplaza por
completo** la base de la app con la del archivo/link (no se combinan
registros), así que asegúrate de que siempre esté completo y actualizado.

## Cómo subirlo a GitHub (paso a paso, sin usar la terminal)

1. Entra a [github.com](https://github.com) e inicia sesión (o crea una cuenta gratis).
2. Haz clic en el botón verde **"New"** (o el símbolo **+** arriba a la derecha → *New repository*).
3. Ponle un nombre, por ejemplo `oxxo-puntos-potenciales`, márcalo como **Private** (ver advertencia arriba) y crea el repositorio (sin marcar "Add a README", ya tenemos uno).
4. En la página del repositorio recién creado, busca el enlace **"uploading an existing file"**.
5. Arrastra ahí todos los archivos de esta carpeta (`app.py`, `utils.py`, `requirements.txt`, `.gitignore`, `README.md` y la carpeta `data` completa, incluyendo `Puntos_potenciales.xlsx`).
6. Escribe un mensaje de commit, por ejemplo "Primera versión del prototipo", y haz clic en **"Commit changes"**.

## Cómo publicarlo gratis (Streamlit Community Cloud)

1. Entra a [share.streamlit.io](https://share.streamlit.io) e inicia sesión con tu cuenta de GitHub.
2. Haz clic en **"New app"**. Si el repositorio es privado, Streamlit te pedirá autorizar el acceso a tu cuenta de GitHub — acéptalo solo para ese repo si te da la opción.
3. Selecciona el repositorio `oxxo-puntos-potenciales`, la rama `main` y como archivo principal `app.py`.
4. Haz clic en **"Deploy"**. En un par de minutos tendrás un enlace con tu aplicativo funcionando. Como el repo es privado, considera además restringir quién puede ver la app en la configuración de la app (Settings → Sharing) si vas a mostrar datos reales.

## Notas para seguir desarrollando

- El umbral de "posible duplicidad" por ubicación está en `utils.py` (`UMBRAL_DUPLICIDAD_M`, 150 metros) y el de "mismo nombre" en `UMBRAL_SIMILITUD_NOMBRE` (75% de parecido) — ajústalos según el criterio real del área.
- Los cambios de estado, notas y nuevos puntos que hagas dentro de la app (pestaña "Seguimiento") se guardan en `data/puntos_potenciales.csv` **solo mientras la app sigue abierta/corriendo**. Como `Puntos_potenciales.xlsx` se vuelve a leer completo cada vez que la app arranca, esos cambios no sobreviven a un reinicio — para que un cambio de estado quede permanente, hay que reflejarlo también en el Excel real y volver a subirlo a GitHub.
- El componente de "isócrona" mencionado en la presentación no está incluido en este prototipo — la microsaturación sí se trae del Excel (columna `detalle_microsaturacion`, a partir del indicador "MS (SI O NO)" o del detalle tienda por tienda, según el formato del archivo).
- El loader (`utils.py`, función `_normalizar_crudo`) reconoce columnas por nombre de forma flexible (p. ej. "Nombre" o "Nombre PP", "Ciudad" o "Region") — si el formato del Excel cambia más adelante, probablemente siga funcionando sin tocar código, siempre que las columnas se llamen de forma parecida.
- Hay especialistas con nombres ligeramente distintos entre sí en el Excel (ej. variantes de un mismo nombre con o sin segundo apellido) — vale la pena revisar si son la misma persona para que los filtros por especialista sean más limpios.
