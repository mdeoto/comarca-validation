# Comarca Validation

Sistema de adquisición, organización y validación de observaciones ambientales
para la Comarca Andina del Paralelo 42.

El proyecto busca construir una base observacional reproducible para el análisis
y la validación de productos meteorológicos y de calidad del aire en una región
de topografía compleja.

## Estado actual

Actualmente se encuentra implementada una primera cadena operativa para la
adquisición de observaciones de calidad del aire desde el mapa público de
PurpleAir.

La adquisición se realiza mediante captura automatizada del mapa, detección del
marcador y lectura OCR del valor mostrado. Este mecanismo permite mantener una
serie temporal operativa sin depender de la API de PurpleAir.

Variables implementadas:

- PM2.5
- PM10

La arquitectura permite incorporar nuevas variables y proveedores sin modificar
la estructura general del proyecto.

## Sitios PurpleAir

Actualmente se monitorean:

- Eco Comarca (PA-1)
- GeoMuseo - El Bolsón (PA-3)
- Lago Puelo - Villa del Lago (PA-6)

La configuración de los sitios, variables y parámetros de captura se encuentra
en:

    config/sites.yaml

Los parámetros de `capture` corresponden al posicionamiento operativo del mapa
y pueden diferir ligeramente de las coordenadas físicas del sitio.

## Adquisición PurpleAir

El script principal es:

    scripts/capture_purpleair.py

Para cada sitio y variable habilitada, el proceso:

1. abre el producto correspondiente en el mapa de PurpleAir;
2. posiciona el mapa según `config/sites.yaml`;
3. genera una captura temporal;
4. recorta y amplía la región central;
5. detecta el marcador independientemente de su color;
6. aplica varias transformaciones de imagen;
7. realiza OCR mediante Tesseract;
8. compara las distintas lecturas;
9. guarda el resultado y metadata de diagnóstico;
10. elimina las imágenes temporales.

Las imágenes utilizadas para el procesamiento no se conservan de forma
operativa.

## Control de la lectura OCR

Para reducir falsas lecturas se utilizan varias versiones de la imagen.

Una observación es aceptada cuando al menos dos variantes producen el mismo
valor.

Los datasets conservan, además del valor observado:

- estado de la lectura;
- radio del marcador detectado;
- cantidad de votos coincidentes;
- cantidad de candidatos obtenidos.

Ejemplos de estados:

    ok
    ocr_fail
    ocr_uncertain
    no_marker
    bad_radius
    capture_fail

Una falla de OCR no interrumpe la serie temporal: se registra la observación con
el valor vacío y el correspondiente estado de diagnóstico.

## Datos operativos

Se genera un CSV independiente para cada sitio:

    data/observations/purpleair/<site_id>.csv

Por ejemplo:

    data/observations/purpleair/eco_comarca_pa1.csv
    data/observations/purpleair/geomuseo_el_bolson_pa3.csv
    data/observations/purpleair/lago_puelo_villa_del_lago_pa6.csv

Cada ejecución agrega una nueva observación.

Los datos operativos no se versionan en Git.

## Entorno

La adquisición PurpleAir utiliza un entorno independiente para no modificar los
entornos científicos del proyecto.

Crear el entorno con:

    conda env create -f environments/purpleair-capture.yml

Activarlo:

    conda activate purpleair-capture

Playwright requiere además instalar Chromium:

    python -m playwright install chromium

El entorno incluye Python, Tesseract, pytesseract, NumPy, OpenCV, PyYAML y
Playwright.

## Ejecución manual

La forma recomendada de ejecutar la adquisición es mediante el wrapper:

    ./scripts/run_purpleair_capture.sh

El wrapper:

- localiza automáticamente la raíz del repositorio;
- utiliza el entorno `purpleair-capture`;
- evita ejecuciones simultáneas mediante `flock`;
- establece un tiempo máximo de ejecución mediante `timeout`;
- registra la actividad en un log operativo.

El log se genera en:

    logs/purpleair_capture.log

## Ejecución automática

En la instalación operativa actual la adquisición se ejecuta cada 10 minutos
mediante cron.

Ejemplo:

    */10 * * * * /ruta/al/repositorio/scripts/run_purpleair_capture.sh

El path del cron depende de la ubicación local del repositorio.

La combinación de `flock` y `timeout` evita que ejecuciones demoradas produzcan
procesos superpuestos.

## Archivos no versionados

Los siguientes productos son locales y se excluyen del repositorio:

    data/observations/
    data/debug/
    logs/
    *.lock

Esto evita versionar datasets que crecen continuamente, capturas temporales,
logs y archivos utilizados para control de procesos.

## Próximos pasos

El desarrollo previsto incluye:

- evaluación de la estabilidad de la adquisición PurpleAir;
- control de calidad de las series observadas;
- incorporación de observaciones AirGradient;
- incorporación de nuevas variables de calidad del aire;
- integración de observaciones meteorológicas;
- generación de un dataset observacional unificado;
- desarrollo de productos y visualización operativa;
- utilización de las observaciones para validación meteorológica y ambiental.

## Nota sobre PurpleAir

La adquisición implementada utiliza la información visual disponible en el mapa
público de PurpleAir y no constituye una integración mediante su API.

Los valores adquiridos deben conservar información de procedencia y control de
calidad antes de ser utilizados en análisis científicos.
