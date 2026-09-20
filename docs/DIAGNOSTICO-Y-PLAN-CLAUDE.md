# Diagnóstico y plan — Rentabilidad Razo + Agetrans

Notas técnicas de Claude tras auditar el paquete que dejó Codex el 05/09/2026.
Continúa la cultura de LEEME.txt: esto es documentación de trabajo para quien
toque esta carpeta después, no un informe para Roberto.

## Por qué "no funciona bien" (diagnóstico, 19/09/2026)

No es un fallo de cálculo. Es que **nunca se completó la instalación**:
- El paquete se probó UNA vez desde PC-ROBERTO el 05/09 a las 05:14 (lectura manual OK).
- El paso 2 — abrir `ACTIVAR EN SERVIDOR.cmd` COMO ADMINISTRADOR **dentro de
  SERVIDOR** — nunca se hizo.
- Resultado: `informe.html` y `estado.json` llevan congelados desde el 05/09
  (dataTo=2026-09-04). Hoy son 15 días de retraso. `estado.json` lo dice
  explícitamente: `"state":"pending"`.
- La tarea programada `Razo-Rentabilidad-Nocturna` no existe en SERVIDOR.

**Esto no lo puede activar una sesión de Claude en PC-ROBERTO**: el instalador
exige `$env:COMPUTERNAME -eq 'SERVIDOR'` + administrador (verificado:
`whoami` aquí es `pc-roberto\roberto`, host `PC-ROBERTO`). Registrar una tarea
SYSTEM en el servidor de ficheros es modificar configuración del sistema —
lo hace quien tenga sesión de administrador en SERVIDOR, con un doble clic.

## Qué hay debajo (auditoría del código, no solo del síntoma)

El paquete (`programa.zip`: ~90 KB de código real + runtimes portables de
Node/Python) es **sólido**, no superficial:
- `scripts/dbf_gesruta.py`: parser DBF/FoxPro propio, sin dependencias,
  resuelve cp1252, memos .fpt/.frt/.mnt/.sct, borrado lógico. Comentario de un
  bug real ya cazado (memo de informes .frx→.frt).
- `export_rentabilidad_access_v3.ps1` + `..._gesruta_v3.py`: leen
  `P:\PartesTrabajo\Partes 7.0.accdb` (ACE OLEDB, solo lectura) y
  `P:\Gesruta\EMPTR21`/`EMPAG21` (facturas/linfaclib/albara/mascli). Verifican
  mtime antes/después de leer (abortan si la fuente cambió durante la
  lectura). Nunca escriben en el origen.
- `prepare-data.mjs`: fusiona ambas extracciones; reparte el coste físico
  (Access, por matrícula/mes) entre cliente/empresa/carga/concepto
  PROPORCIONAL al ingreso de ese mes-matrícula — fijado ANTES de filtrar, así
  que filtrar nunca traslada coste de un cliente a otro. Marca "Sin asignar"
  en vez de inventar.
- `build.mjs`: antes de publicar, contrasta contra los totales SQL
  independientes de Access, comprueba que las 6 agrupaciones
  (vehículo/cliente/empresa/carga/concepto/mes) siempre suman el mismo total,
  verifica duplicados/huérfanos. Si algo no cuadra, **aborta y conserva el
  informe anterior**.
- `Actualizar.ps1`: candado contra ejecuciones simultáneas, sustitución
  atómica (`[IO.File]::Replace`, nunca trunca el HTML que alguien tenga
  abierto), conserva `.anterior`, logs 90 días.
- `scripts/test.mjs`: tests reales con cifras de referencia, no decorativos.
- Frontend (`app.mjs`+`model.mjs`+`dashboard.html/css`): SPA vanilla JS sin
  dependencias, datos embebidos gzip+base64 (`DecompressionStream`), un único
  motor de agregación para tarjetas/gráficos/tablas (dato único). Diseño
  limpio pero genérico (azul/marino corporativo, sin la identidad VP). Las
  pestañas "Conciliación" y "Criterios y fuentes" ya explican en llano qué es
  estimado y qué no — nada se disfraza de exacto.

**Conclusión: la base de cálculo es de fiar y hay que conservarla.** Lo que
falta no es "arreglar el cálculo", es (1) activarlo en SERVIDOR, (2) sumar
fuentes, (3) rediseñar visualmente.

## Fuentes: qué falta y qué ya existe en otro sitio

El propio informe ya avisa (pestañas Conciliación / Criterios): **Movertis y
Locatel no están conectados**; el coste por cliente es un reparto mensual
estimado, no el coste real de cada servicio.

Descubierto en esta sesión — **`P:\Analizador Carburantes` (programa
hermano, activo, tocado hoy 19/09) ya cubre buena parte de "Repsol" y "la
nave":**
- `datos\repostajes\Operaciones AAAAMM.txt`: exportación mensual de Solred
  (Roberto la baja a mano del portal Mi Solred y la suelta ahí). `flota.py`
  la lee junto con `datos\tarifas\oferta_AAAAMMDD.xlsx`.
- `Z:\A CARBURANTES DEJAR AQUI`: buzón único para TODO lo de carburante
  (Solred, ofertas, facturas, albaranes, fotos) — se procesa 2×/día, se
  clasifica por CONTENIDO (no por nombre), OCR con doble lectura cruzada para
  fotos, nunca duplica, lo no reconocido va a revisión humana. Patrón
  excelente y directamente reutilizable para otras fuentes.
- No hay integración de depósito propio/surtidor físico de la nave
  confirmada todavía — "Barril y Surtidor" es sobre todo un comparador de
  precio de mercado (Brent/WTI/Ministerio) + gasto Solred de la flota para
  compararlo, NO telemetría de un tanque propio. `Z:\Z Datos Gasoil`
  (ficheros .txt periódicos 2023-2026) sigue sin identificar — candidato a
  revisar si existe depósito propio con lecturas automáticas.

Pendiente de investigar antes de conectar (no improvisar un scraper frágil,
[[estandar-precision-no-inventar]]):
- **Movertis** (Wialon/Disketta): patrón de descarga ya documentado en
  memoria para DDD; para KM/horas de rentabilidad haría falta
  econduccion.movertis.com o telemetría GPS — necesita token Wialon durable
  (pendiente, lo facilita Roberto).
- **Locatel — PROBADO EN VIVO (19/09/2026, con permiso expreso de Roberto):**
  login OK con las credenciales de memoria (portal rediseñado desde la sesión
  de hace meses, pero el backend sigue siendo ASP: enlaces `.asp` debajo de la
  piel nueva). Cuenta real: 13 vehículos, 58 conductores. **GPS → Vehículos →
  botón Informes → Informe de Recorridos → Informe Semanal**, con "Todos los
  vehículos" marcado, da en UNA sola consulta: por vehículo, día y trayecto —
  hora inicio/fin, origen, destino, duración, **distancia recorrida en km
  (medida por GPS, no autodeclarada)** — más el total diario y un gráfico
  km/día por vehículo. Tiene botón **"Generar Excel"** (no lo pulsé: descargar
  fichero pide permiso aparte). Esto es mejor que `razo_localizador_posicion`
  del ERP para Rentabilidad: ya viene agregado por vehículo+día, no hay que
  reconstruirlo desde posiciones sueltas. Sigue pendiente diseñar CÓMO
  automatizar la descarga periódica (¿exportar Excel con script + login
  guardado, o pedir a Roberto acceso de API si Locatel lo ofrece?) y el
  enlace por matrícula+fecha con GesRuta/Access, igual que con Solred.
- Cruzar el km de GesRuta (conocido "sucio": el remolque repite el km de la
  tractora) contra Locatel/Movertis sería la mejora de fiabilidad real que
  pide Roberto — no solo sumar fuentes, sino usarlas para VALIDAR las que ya
  hay.

**19/09/2026 — hallazgo de la sesión "Análisis módulo transportes producción"
(vía SendMessage, solo lectura sobre vilpor_local):** el ERP NO scrapea
Locatel — `razo_locatel` solo ingiere ficheros de tacógrafo/infracciones
(`razo_locatel_registro`=0, `razo_locatel_emision`=0). El km/posición real SÍ
existe ahí: `razo_localizador_posicion` (31.300 filas, 93 dispositivos, 11
localizadores) y `razo_movertis_dia` (1.440 filas). **Pero casi no llega a los
viajes**: solo 1.390 de 29.483 viajes tienen km (7,4% en 2026, 16,8% en los
últimos 30 días) — el hueco de km NO es solo GesRuta sucio, es que el dato
real tampoco está enlazado a viaje en ningún sitio todavía. Y
`razo_remolque_km` (km de remolque separado de tractora, para el problema del
remolque que repite el km) existe como modelo pero nunca se enchufó del todo.
**Conclusión para Rentabilidad:** si se cruza con `razo_localizador_posicion`/
`razo_movertis_dia`, hay que enlazar por matrícula+fecha (mismo patrón que ya
usa `prepare-data.mjs` con Access) — no hay un enlace a viaje ya hecho del que
tirar.

## Actualización 19/09/2026 (tarde) — Solred probado + giro en el km

**Extractor de Solred construido y PROBADO contra datos reales** (no en
`P:\_RENTABILIDAD` todavía, en scratchpad de esta sesión hasta integrarlo en
`prepare-data.mjs`): `scripts/export_rentabilidad_solred_v1.py`. Mismo mapa
de columnas que `Analizador Carburantes\flota.py` (vendorizado, no
importado, para que el paquete siga autónomo — mismo criterio que
`dbf_gesruta.py`). Ejecutado con el runtime propio contra
`P:\Analizador Carburantes\datos\repostajes\*.txt` (may-ago 2026, los 4
ficheros reales que hay): **1.774 filas, 54 matrículas distintas, 15 sin
matrícula reconocible, 0 descuadres bruto−descuento=neto** (la comprobación
que confirma que el mapa de columnas es el que es). Diseño: fuente
OPCIONAL — si la carpeta de Analizador Carburantes no está, `disponible:
false` y el informe sigue con GesRuta+Access como hasta ahora (Solred es un
cruce adicional, no un cimiento; hay que ajustar `Actualizar.ps1` para que
un fallo aquí no aborte, a diferencia de GesRuta/Access que sí abortan).
**Pendiente, y no lo voy a precipitar:** la política de conciliación contra
`GasoilImporte`/`AdBlueImporte` del parte de Access — ¿Solred manda y Access
se contrasta (como ya hace `residual` con directo-vs-desglose), o se
enseñan los dos por separado? Es una decisión de diseño, no mecánica.

**GIRO y CORRECCIÓN sobre la fuente de km (19/09/2026):** una sesión
hermana ("Registrar todo en servidor", reconstruyendo km de neumáticos) me
dijo que `kilome.dbf` (P:\Gesruta\EMPTR21 y EMPAG21) tiene odómetro
encadenado limpio "2021→2026 sin huecos por año" — iba a retirar la
prioridad de Locatel/Movertis por eso. **Roberto avisó que GesRuta no tiene
km en 2026, lo comprobé mes a mes (no por año) y tenía razón:** `kilome.dbf`
tiene filas normales hasta abril de 2026 (Razo: ene 1.346→abr 103;
Agetrans: ene 146→abr 35) y **CERO filas desde mayo de 2026 hasta hoy,
en las dos empresas.** "Sin huecos por año" era cierto pero engañoso — el
dato de 2026 se corta en abril. Aviso ya mandado a la otra sesión (hallazgo
compartido, le afecta igual) y hallazgo apuntado en el buzón.
**CONSECUENCIA: Locatel y Movertis dejan de ser "nice to have" — hoy son
la ÚNICA fuente de km viva desde mayo 2026**, y Roberto ha pedido
explícitamente perseguirlos en serio, para km Y para consumo (no solo
km). Retomo la prioridad original.
**Confirmado en vivo (con permiso de Roberto) que las credenciales de
Locatel siguen funcionando**: `Informes → Informe de Recorridos` da km
real por trayecto con exportación a Excel.

**"Dietagest" (pestaña superior) es OTRO PRODUCTO de Locatel** (cálculo de
dietas/per-diem de conductores, RRHH/laboral) — Roberto no está suscrito,
no aplica a combustible. Descartado.

**"Informe de emisiones" (Informes → Informe de emisiones) SÍ trae
CONSUMO, no solo km** — probado en vivo con rango de una semana
(12–19/09/2026), los 13 vehículos: por matrícula da Fecha inicial/final
con dato, **Kilómetros, Litros, CO₂ y más columnas de emisiones**
(cortadas en pantalla, sin explorar del todo — parecen más gases). Aviso
propio: "Para hacer el cálculo de emisiones se necesita el servicio de
CANbus o tacógrafo habilitado en el vehículo" — 2 de los 13 vehículos
(5790FSH, 5869KRC) salieron sin datos esa semana (probablemente sin
CANbus activo). Total de la flota esa semana: 16.822,08 km · 4.843,39 L ·
14.889,27 kg CO₂. **Esto es una TERCERA fuente de consumo, independiente
de Access (autodeclarado en el parte) y de Solred (litros comprados con
tarjeta)** — exactamente el cruce que pidió Roberto: km y consumo, no solo
uno. Admite rango de fechas personalizado (no until probé la semana
default). Sin explorar aún: exportación a fichero de este informe
concreto (Recorridos sí tenía Excel; este no se comprobó).

**Pendiente:** acceso a Movertis (necesita que Roberto facilite algo —
token Wialon o credenciales — todavía no lo tengo en esta sesión); diseñar
cómo automatizar la descarga periódica de Locatel (login guardado +
script, sin pegar la contraseña en ningún fichero del paquete) y cómo
casar sus datos (por matrícula+fecha) con Access/GesRuta/Solred sin
duplicar ni inventar un consenso donde las fuentes no coinciden.

## Nómina (Z:\LABORAL) — descubierto y medido 19/09/2026

Roberto avisó: «las nóminas están en Z:\LABORAL, ahí hay los costes por
empleado y por tipo de trabajo».
- **Dónde:** `Z:\LABORAL\_NOMINAS\NOMINAS\<año>\<NN Mes AAAA>\`, un
  «RESUMEN DE NÓMINA» de la gestoría por empresa y mes (xls y xlsx mezclados,
  nombres muy variables; agosto 2025 está aparte en `datos nominas\`). Leídos
  los 99 de **jun-2022 → ago-2026**: cobertura completa 2025-01→2026-08 en
  Razo (B15226095) y Agetrans (B15938442). Septiembre 2026 aún no existe
  (la gestoría lo entrega ~10 días después de cerrar el mes: el último mes
  tendrá siempre nómina pendiente → NO tratarlo como cero, avisar).
- **Estructura:** hoja `Totales` → bloque «TOTALES SECCIONES»: col B = total
  empresa, col C sin cabecera = «sin sección» (solo algunos meses), luego un
  código de sección por columna. **El layout cambia de un mes a otro →
  localizar por VALOR de cabecera, no por posición.** En los 99 ficheros:
  TOTAL = TOTAL DEVENGOS + TOTAL COSTE S.S. y la suma de columnas = total
  (coste de empresa exacto; no hay que recalcular la cuota patronal).
- **Secciones = «trabajo que realiza»** (cruce por nombre con el «Listado de
  personal por funciones», 27/01/2026, ago-2026): Razo 1=Conductor-Hormigonera
  (~55% del coste, 94.892 € en ago-26), 2=Conductor-Nacional, 3=Conductor-
  Bañera, 4=Administración, 5=Taller. Agetrans usa 1 y 3, cruce no
  concluyente → **preguntar a Roberto**.
- **Duplicados a resolver («sin duplicados»):** Razo feb-2025 aparece dos
  veces (146.750,54 mal archivado en la carpeta de enero, 10/03/2025;
  146.223,17 en febrero, 16/04/2025); enero-2025 solo existe como «Copia
  de …». Regla: la de mtime más reciente por (empresa, periodo); si las
  versiones difieren, se enseña en Conciliación.
- **Privacidad (decisión de diseño):** la hoja `Detalle` trae sueldos CON
  NOMBRE. **El informe solo lleva agregados por mes y sección** (y el nº de
  personas), nunca nombres ni salarios individuales — cualquiera con acceso
  a `Programas` abre el HTML. El extractor no escribe nombres a disco.
- **Cruce con Access — reconciliar, NO sumar** (los conductores YA están en
  el coste del parte: sumar la nómina encima los duplicaría): mostrar «Personal
  según nómina» frente a «Personal imputado en los partes» y la diferencia
  como «personal sin imputar» (vacaciones, bajas, horas no partidas). Tercer
  modo de coste opcional: «Con personal de nómina real».
- **Lectura de .xls:** hay 30+ ficheros .xls (BIFF) → hace falta `xlrd` (y
  `openpyxl` para .xlsx), ambos Python puro; se incluyen en el runtime privado
  (no se instala nada global), con sus licencias.
- **Otras fuentes de Z:\LABORAL vistas, no usadas aún:** `FICHEIRO DE HORAS Y
  DIETAS.xlsx` (actualizado 18/09/2026: horas y dietas por empleado y mes,
  agrupado por sección de flota), `2021-02-17 Simulador nómina.xlsx`,
  `2018-09-21 Coste Trabajador Hormigonera.xlsx`.

## Refresco manual y primer cruce nómina↔partes (19/09/2026, 22:15)

- **El programa de Codex funciona HOY de punta a punta**: ejecutado desde
  PC-ROBERTO (carpeta de pruebas, luego contra `P:\_RENTABILIDAD`), lee
  19.879 partes de Access y 40.202 líneas / 4.086 cabeceras de GesRuta en
  ~30 s, pasa sus controles (0 duplicados, 0 huérfanas) y publica. El fallo
  de fondo era solo que nadie lo activó en SERVIDOR.
- **`informe.html` refrescado a mano el 19/09/2026 22:15 con datos hasta el
  18/09** (antes: 04/09). Copia de lo anterior: `informe.html.anterior`
  (05/09). Sigue sin actualizarse solo: falta la activación nocturna.
- **Primer cruce (aprox.; el cruce por titular del vehículo NO es empleador
  del conductor)** ago-2026, Razo: nómina de conductores (secciones 1+2+3) =
  148.276,55 € frente a 119.284,26 € imputados en los partes (conductor
  ordinario + extra, vehículos de titular Razo) → ~80 % imputado; unos
  29.000 €/mes de coste de conductor no llega a ningún parte. Agetrans
  ago-2026: nómina total 37.198,18 € frente a 19.180,67 € en partes.
- Categorías de vehículo de Access (14): TRACTORA BAÑERA, HORMIGONERA,
  TRACTORA NACIONAL, TURISMOS Y FURGONETAS, REMOLQUE-BAÑERA, …
  → se corresponden con las secciones de nómina Bañera / Hormigonera /
  Nacional; permite repartir el personal por tipo de vehículo (estimado).

## Coste por empleado, combustible y fuentes (19/09/2026, noche)

**Decisiones de Roberto:** (1) SÍ quiere el coste por empleado — «hazme también
el coste por empleado»; (2) sobre las secciones de Agetrans: «no lo sé».
Como el HTML lo abre cualquiera con acceso a `Programas`, el coste por
persona va en una **pestaña «Personal» cifrada con una clave que elige él**
(AES-GCM/PBKDF2 en el navegador; el instalador en SERVIDOR le pide la clave a
quien lo ejecute y la guarda con ACL de Administradores+SYSTEM: yo nunca la
veo). Sin clave el resto del informe funciona igual y los sueldos no están en
claro en el fichero. Los agregados por sección llevan mínimo 3 personas.

**Lector de nóminas construido y verificado** (`scripts/export_rentabilidad_
nomina_v1.py`, en el scratchpad de la sesión hasta integrarlo): 41 ficheros →
40 meses-empresa (2025-01→2026-08, ninguno falta), 0 errores, suma por persona
= suma por sección en los 40, duplicado de Razo feb-2025 resuelto y anotado,
1.300 personas-mes. Lee .xls (xlrd) y .xlsx (openpyxl), ambos Python puro,
incluidos en `vendor/` (1,2 MB, con licencias); probado con el Python 3.12 del
paquete. 4 s.

**Access ya trae el «trabajo que realiza» por persona:** la consulta
`UltimoContratoVigentePorEmpleado` de `Partes 7.0.accdb` tiene, por
`IdResponsable` (el mismo que lleva cada parte), las casillas Hormigonera /
Bañera / Nacional / Taller / Administracion + `CosteHoraOrdinaria`,
`SueldoMensualPactado`, `CosteMensualEstimado`. Sirve para (a) enlazar cada
parte con su conductor, (b) casar persona de nómina ↔ contrato por nombre y
cerrar lo de Agetrans con datos, (c) comparar €/hora real con la tarifa que
usan los partes. **Nunca extraer** de `EmpleadosConsulta` el DNI ni el IBAN
(están en esa consulta): solo id y nombre.

**Personal — con «Gastos empleado» incluidos (son las dietas de la nómina):**
acumulado ene–ago 2026 los partes imputan el 94,5 % de la nómina de
conductores; mes a mes 89,8 / 115,2 / 98,0 / 101,0 / 91,0 / 90,1 / 88,8 /
84,7 % → oscila y desde abril baja cada mes. Por tipo (ago): hormigonera 87,2,
bañera 84,4, nacional 81,1 % (nacional = Razo s2 + Agetrans s1, lo que cuadra
mucho mejor que dejar s1 fuera → refuerza «Agetrans s1 = conductores
nacional»). Solo 3 categorías de vehículo llevan coste de conductor en los
partes (hormigonera, tractora bañera, tractora nacional).
**Modo «con nómina real» previsto:** factor por (mes, tipo) = nómina del tipo /
(conductor + extra + gastos empleado imputados en esas categorías), aplicado a
cada parte; mes sin nómina (el último) → factor 1 y aviso; nunca cero.

**Combustible (may–ago 2026), litros de gasóleo:** partes 122.086 / 135.012 /
131.591 / 112.634; Solred 89.731 / 98.409 / 95.276 / 86.335; surtidor de la
nave 7.471 / 6.754 / 11.965 / 5.761 → **20–30 mil litros al mes (18–22 %) sin
respaldo** en tarjeta ni surtidor. Donde la matrícula sale en las dos fuentes
los litros coinciden (mediana 0 %). El «programa de repostajes de la nave» es
**GesproWin V3** (Access, tabla `Serveis`: fecha, hora, matrícula,
**kilómetros**, litros, tanque, id de operación; sin precio). La copia en
`P:\Analizador Carburantes\datos\gespro\GesproWinBD.mdb` **se corta el
06/08/2026** (la tarea nocturna del PC AUXILIAR no está llegando) y en 2026
mueve 6–12 mil L/mes. Copias semanales también en `Z:\GESPROWIN` (última
2026-06-19).

**Maqueta (v4):** pestañas nuevas **Conciliación** (personal, combustible,
km, versiones duplicadas — cifras reales agregadas) y **Personal** (candado +
tabla con filas FICTICIAS; ningún dato personal real en Claude).

## Plan

1. **Activar ya** el motor en SERVIDOR — un clic de quien tenga admin ahí.
   Mejor esperar a la v2 (paso 2) para no instalar dos veces: el instalador
   rechaza reinstalar sobre una tarea ya existente.
2. **Rediseño visual** (maqueta Artifact primero, identidad VP) antes de
   tocar `dashboard.css`/`dashboard.html`. Añadir una tira de "fuentes
   conectadas" (GesRuta/Access/Solred-flota/Movertis/Locatel) para que se vea
   de un vistazo qué es real y qué sigue pendiente — nunca disfrazar un
   reparto estimado de coste real.
3. **Conectar el gasto real de Solred** (ya lo recoge Analizador
   Carburantes) como fuente adicional de coste de combustible por vehículo,
   contrastándolo con el litro/importe que declara el parte de Access —
   primera "fiabilidad cruzada" real, sin scraper nuevo.
4. **Movertis/Locatel**: investigar viabilidad de lectura periódica antes de
   prometer nada; si sale, primero para KM/horas (contraste con
   GesRuta/Access).
5. Todo pasa por los mismos controles que ya existen en `build.mjs` (no
   publicar si algo no cuadra) — extender esa disciplina a las fuentes
   nuevas, no relajarla.


---

## ACTUALIZACIÓN 20/09/2026 (madrugada) — el gasto que se mostraba NO era el real

**Lo que dijo Roberto:** «los gastos no son reales y el consumo aparente tampoco»; «hay más gastos que los que muestras, no hay ese margen que me pones». Tenía razón. Medido:

1. **Contabilidad (CxConta, vía el espejo `razo_cxconta_apunte` del ERP), 01/01–31/08/2026, ambas sociedades:** ingresos 6,50 M€, gastos **5,80 M€**, resultado **0,70 M€ (10,7 %)**. Razo: 4,02 M€ − 3,68 M€ = 8,3 %. Agetrans: 2,48 M€ − 2,12 M€ = 14,6 %. El informe anterior enseñaba un «saldo observado» del 40 % porque solo restaba el coste de los partes de Access (3,43 M€ en ese periodo).
2. **Puente contabilidad ↔ partes (mismos meses):** los partes captan el **59,2 %** del gasto real. Faltan 2,37 M€: subcontratación (607) 1,33 M€ (de ellos Agetrans 1,25 M€), compra de áridos 0,49 M€, sueldos y SS 0,36 M€ (personal que no conduce), reparaciones/repuestos/neumáticos 0,12 M€, seguros 0,07 M€… Al revés, los partes SOBRE-imputan estructura (+0,16 M€) y «gastos vehículo» (peajes: 0,12 M€ frente a 0,05 M€ reales).
3. **Calidad de los partes de Access:** 2 partes con 4,49 M km imposibles (km totales 10,2 M frente a 5,7 M reales): el «consumo aparente» salía 22 o 40 l/100 km según cómo se contase, ambos falsos. Ahora esos km se excluyen (el importe se conserva) y se anotan.
4. **Partes frente a Movertis (20/08–17/09):** cuando existe parte, su km coincide con el del localizador (mediana 1,00; ±15 % en el 84 %; suma 1,04). Pero falta el parte en el **36 % de los días-camión activos** (47.200 km en 4 semanas). Por eso el gasto de los partes queda corto.
5. Solred solo cubre a Razo (98 % de sus litros declarados); Agetrans no tiene fichero. El surtidor de la nave llega a 19/08 (la copia nocturna desde PC AUXILIAR está parada).

**Cambios en el informe (v2):** cabecera VilPor con barra de fuentes; tarjetas = ingresos, gastos y resultado CONTABLES (meses cerrados; el mes en curso no se compara) + «gasto que no llega a los partes»; comparador interanual sobre la contabilidad (tarjetas y líneas discontinuas en el gráfico); pestaña Conciliación con puente contabilidad/partes, nómina real frente a partes, combustible/AdBlue/peajes y calidad de los partes; con filtros de vehículo/cliente solo se ve el coste imputable y se avisa de que no es el resultado real; gastos y consumo de los partes rotulados «declarado».

**Motor nocturno:** tarea `Razo-Rentabilidad-Nocturna` (03:00) en el PC de Roberto (usuario Roberto), programa en `C:\ProgramData\RazoRentabilidad`, publica en esta carpeta. Fuentes: GesRuta y Access (obligatorias); Solred, surtidor de la nave, nómina (agregada) y contabilidad (opcionales: si fallan, el informe sale igual y lo dice). Instalador único `Instalar.ps1` (repetirlo actualiza sin tocar configuración ni tarea). SERVIDOR (192.168.0.3) no se puede administrar en remoto sin su credencial: alternativa `ACTIVAR EN SERVIDOR.cmd` dentro de SERVIDOR (ACE 16 ya registrado allí), pero las claves de Movertis/Locatel viven en el PC.

**Pendiente:** (a) km y consumo REALES de Movertis (`razo_movertis_dia`: hoy solo 20/08 en adelante; falta histórico) y Locatel (informe de emisiones, CANbus); (b) capa de Personal cifrada (clave que solo conoce Roberto); (c) reparto con criterio de subcontratación, áridos y gastos generales por vehículo/cliente; (d) fichero Solred de Agetrans; (e) reparar la copia nocturna de GesproWin.
