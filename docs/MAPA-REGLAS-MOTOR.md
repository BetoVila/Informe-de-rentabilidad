# Mapa de reglas del motor (triangulación + conciliación)

Para la sesión del ERP, que pasa a mandar sobre el motor. Aquí está cada regla y **dónde vive** en el código, con parámetros y números de línea. El ERP se lleva esto sin perder nada; mi motor se queda sincronizado con el suyo y enseña las diferencias.

Repositorio: `C:\CLAUDE ESPECIAL\05-PROGRAMAS-Y-HERRAMIENTAS\rentabilidad-informe` · GitHub privado `BetoVila/Informe-de-rentabilidad`.

## 0. Los tres cerebros y el flujo

| Fichero | Qué hace |
|---|---|
| `scripts/demanda_triangular_v2.py` | Saca de GesRuta los **viajes reales que hay que casar** (la demanda): áridos + nacional, o con `--con-hormigon` también hormigón. SOLO LECTURA. |
| `scripts/triangular_v1.py` | Primitivas de medida (coordenadas, paradas, jornada, `medir`, `aprender`, `triangular_dia` v1). `triangular_v2` lo importa como `v1` y reusa `v1.medir`. |
| `scripts/triangular_v2.py` | **El motor.** Cose las trazas del localizador, corta ciclos, los casa con los albaranes, mide km/litros/tiempo por viaje, hormigón y larga distancia, y escribe `triangulado_v2.json`. |
| `src/model.mjs` | **La conciliación** contra la contabilidad: reparte el gasto del libro a los viajes mes a mes y cuadra con las cuentas. Vistas Vehículos/Clientes/Mes. |
| `scripts/prepare-data.mjs` | Prepara los datos del informe: fusión de telemetría, tipo de servicio por cuenta. |

Flujo nocturno (`Actualizar.ps1`, 03:00, desde `C:\ProgramData\RazoRentabilidad`): demanda → bajar localizador de los pares (matrícula, día) → `triangular_v2` → `prepare-data` → build del HTML → mapas de día + export de trazas. Publica atómico en `\\SERVIDOR\Programas\_RENTABILIDAD`.

## 1. La clave y qué es un viaje real

- **Clave de viaje = (empresa, viaje, cantera)**. `cantera` = campo `CAMPO1` de `lineas.dbf` («Alb. cantera»): el número de albarán físico de la cantera. Una línea con `CAMPO1` relleno = un porte real de áridos/nacional; sin él no es viaje.
- Se leen las dos casas: `EMPTR21`=Razo, `EMPAG21`=Agetrans (`demanda_triangular_v2.py:104`).
- Día del viaje = `DESDEF` (o `FECHA`) de la cabecera del albarán (`albara.dbf`), en rango `[desde, hasta]` (`leer_sociedad`, línea 36).
- Matrícula = `viaje.MATRI1` limpiada a `[0-9A-Z]` (`clean_plate`, línea 11); `""`/`"0"`/`"000000"` = sin matrícula.
- **Hormigón** de áridos: `UNIMED == "M3"` o `CODCON` empieza por `K` (`horm`, línea 67). El hormigón solo entra con `--con-hormigon`; va por su propia pasada del motor.
- **Flota del grupo** = matrículas en `vehicu.dbf` **sin proveedor** (`PROVEE` vacío), unión de las dos casas (`flota_grupo`, línea 16). Ojo: `PROPIO` no vale (renting vs propiedad); en la ficha de Agetrans los camiones de Razo llevan `PROVEE=P00099`, por eso es la UNIÓN.
- **Dueño del camión** (para los espejos): la casa que lo tiene sin proveedor; si las dos, **Razo** (tiene las tractoras y le hace los portes a Agetrans) (`demanda…:105-113`).

## 2. Parámetros del motor (triangular_v2.py, cabecera)

| Constante | Valor | Línea | Significado |
|---|---|---|---|
| `DWELL_S` | 180 | 36 | Parada = ≥ 3 min quieto (las descargas de áridos duran 5-10 min, alguna menos de 5). |
| `KM_MIN_CICLO` | 1.0 | 37 | Ciclo válido: ≥ 1 km. Si no, se funde con el anterior. |
| `MIN_MIN_CICLO` | 8.0 | 37 | Ciclo válido: ≥ 8 min. |
| `HUB_EPS_KM` | 0.35 | 38 | Paradas a < 350 m son el mismo sitio. |
| `LARGA_KM` | 200.0 | 39 | Origen-destino ≥ 200 km = larga distancia (pasada de nacional). Por DISTANCIA, no por el tipo de servicio. |
| `MAX_JORNADA_H` | 24.0 | 40 | Jornada más larga: no es de áridos; sus viajes van a la pasada de nacional. |
| `GAP / MATCH / MISMATCH` | -0.6 / 1.0 / -1.5 | 41 | Alineamiento monótono: saltar / geografía que confirma / que contradice. |
| `VENTANA_DIAS` | 7 | 42 | Un albarán puede agrupar tickets de varios días: se buscan a ±7 días en la traza. |
| `ACT` | {3:conducción, 2:otros, 1:disponible, 0:descanso} | 43 | Códigos de actividad del tacógrafo (ranura 1). |
| `KM_MISMA_CARGA` | 3.0 | 281 | Dos paradas en el mismo origen con < 3 km entre ellas = la misma carga (espera en cantera). |
| `CAP_HORMIGONERA_M3` | 8.5 | 943 | Capacidad de cuba: para agrupar m³ en ciclos de hormigón. |

Parámetros por argumento (main, línea 1545): `--rest-h` (descanso que corta jornada, por defecto 8 h), `--dwell-min`. Se publican en `resumen.parametros` del JSON.

## 3. Trazas: fusión de fuentes y cosido

- **`cargar_trazas(dirs)` (línea 72).** Lee los volcados por matrícula/día del localizador. Cada punto: `lat, lon, t, q` (velocidad), `f` (fuente), y opcionalmente actividad y conductor del tacógrafo (ranura 1).
- **Prioridad de fuente: Wialon > Locatel.** Wialon (Movertis) trae contador CAN de km y litros y tacógrafo; Locatel solo da posición (km por GPS). Si hay Wialon ese día, manda.
- **`coser(trazas)` (línea 107).** Une los tramos del día en una sola serie continua por camión, ordenada por tiempo, sin solapes.
- **`es_mov(q)` (línea 116).** En movimiento si la velocidad supera el umbral de parado.

## 4. Jornadas

- **`jornadas_de(pts, paradas, rest_s)` (línea 145).** Flujo continuo por camión. Corta la jornada por **descanso > `rest_h`** (8 h por defecto) **o por hueco de datos**, **NUNCA por medianoche**. Cada jornada se fecha por su **primer movimiento**.
- Marca `nocturna` y el `modo` de la jornada.
- Jornadas > `MAX_JORNADA_H` (24 h) se cuentan aparte (`jornadas_largas`): no son de áridos.

## 5. Paradas

- **`paradas_flujo(pts)` (línea 122).** Paradas ≥ `DWELL_S` (3 min) sobre el flujo. Cada parada: `t_in, t_out, lat, lon`.
- En el output, cada viaje lleva `paradas = [{t, min, lugar, rol}]` (líneas 1964-1977): paradas ≥ 5 min **dentro de [t_ini, t_fin]**. `rol`:
  - `carga` si solapa con los hitos `t_carga..t_carga_fin`; `lugar` = origen del viaje.
  - `descarga` si solapa con `t_descarga` (+60 s); `lugar` = destino.
  - `espera` en cualquier otro sitio; `lugar` = código de lugar conocido a < 700 m, o null.
- **`espera_por_cliente`** (hallazgo, línea 2186): minutos parado por viaje medido, con media, **mediana, p90 y desviación** (`_est`, línea 2157). ≥ 10 viajes.
- **`paradas_por_lugar`** (línea 2175): por rol y lugar, ≥ 5 paradas, con media/mediana/p90/desv.

## 6. Tacógrafo y `min_coherente`

- **`tacografo_tramo(acts, drvs, d0, d1, mov_s)` (línea 202).** Sobre la ventana `t_ini..t_fin`, suma la actividad de la **ranura 1** del tacógrafo: conducción, otros, disponible, descanso.
- **Regla `min_coherente` (definición en `meta.tacografo`, línea 2075).** El tacógrafo solo se usa (`min_fuente=tacografo`, `min_coherente=True`) si:
  1. hay **tarjeta en la ranura 1 al menos la mitad del viaje**, y
  2. la **conducción registrada cubre al menos la mitad del movimiento** de la traza.
- Si no: `min_coherente=False` con `motivo_min` (`sin_tarjeta_en_ranura_1` | `tacografo_no_refleja_la_conduccion`) y la conducción sale del movimiento de la traza (`min_fuente=traza`).
- `conductor_hash` = tarjeta (hash) de la ranura 1; `chofer_tacografo` = su código GesRuta si está enlazado. `chofer_coincide` = el código del albarán es uno de los enlazados a esa tarjeta.
- Hallazgo **`tacografo_por_camion`** (línea 2129): % de viajes medidos cuyo tacógrafo se descartó (localizador que no lee el tacógrafo).

## 7. Los tres métodos: geo, orden, día

**`medido`** = tiene `t_ini` y `t_fin` reales, es decir método **`geo` u `orden`**. `dia` = repartido (sin hora propia). `sin_ciclo`/`sin_traza`/`cantera_repetida` = sin dato (no es 0).

### 7a. Método `geo` — el ciclo lo corta la geografía

- **`ciclos_geo(j, viajes, coords, casa, fuente, tablas)` (línea 309).** Máquina de estados sobre el flujo de la jornada: reconoce carga (llegada al origen del albarán) y descarga (llegada al destino), cortando un ciclo por cada pareja carga→descarga que casa con la **geografía del albarán**. Un ciclo = del fin del ciclo anterior a la salida de la descarga.
- Reglas dentro: paso / no vista, doble rol (un sitio es descarga de uno y carga del siguiente), **misma carga** (`KM_MISMA_CARGA` 3 km: dos paradas en el mismo origen sin recorrido = espera en cantera, no dos cargas), arranque de la jornada.
- **`fundir_pequenos(ciclos, …)` (línea 284).** Ciclos < 1 km o < 8 min se funden con el anterior.
- **`dividir_por_alternancias` (línea 473).** Si un ciclo alterna entre dos sitios, se parte.
- **`cerca_cod(stop, cod, coords, casa)` (línea 272).** Una parada está «en» un código de lugar si cae dentro de su radio (según la fuente de la coordenada; ver §11).

### 7b. Método `orden` — alineamiento monótono

- **`alinear(viajes, ciclos, coords, casa)` (línea 617)** + **`_dp(S)` (línea 588).** Cuando la geografía no basta, se alinean los albaranes (en orden de GesRuta) con los ciclos de la jornada por **programación dinámica monótona**: puntúa `MATCH` (+1) si la geografía confirma, `MISMATCH` (−1.5) si contradice, `GAP` (−0.6) por saltar. Respeta el orden cronológico dentro de cada cantera.
- **`asignar_geo` (línea 673)** asigna por geografía; **`asignar_dp` (línea 699)** por el alineamiento. Ambos producen viajes **medidos** con `confianza` (alta/media/baja).

### 7c. Método `dia` — reparto de sobrantes

- **`reparto(tramos, …)` (línea 715).** Los ciclos que sobran (no casan con ningún albarán) o los albaranes de más se reparten **por el día**: se suman km/litros/tiempo de los sobrantes y se dividen entre los albaranes sin ciclo de ese día. `metodo="dia"`, no medido.
- **`sin_dato(metodo, motivo)` (línea 624).** `sin_ciclo` = más albaranes que ciclos en la traza (sin dato, no cero). `sin_traza` con su motivo (ver §14).

### 7d. Medida de un ciclo

- **`medir_ciclo(j, c, k, nc, fuente, tablas, acts, drvs, prestada)` (línea 637)** usa **`medir` (línea 235)** y **`km_litros` (línea 263)**:
  - `km` = contador CAN (Wialon) o GPS reducido monótono (Locatel).
  - `litros` crudo = reducción monótona del contador; `litros_calibrados` = tabla del sensor del ERP + reducción monótona.
  - `km_vacio` = del inicio del viaje a llegar a cargar; `km_cargado` = de salir de la carga a llegar a la descarga. `null` si no se ven las dos visitas.
  - `duracion_min` = horas de trabajo (= `min_transcurridos` en áridos; en largo, sin los descansos > `rest_h` entre jornadas). `min_espera` = `duracion_min − conducción` (complemento, no una categoría más: no se suma al desglose).
- **`SUMABLES` (línea 633):** magnitudes que se suman al agregar (km, litros, minutos por categoría…).

## 8. `triangular_dia` — orquestación por día

- **`triangular_dia(viajes, jornadas, prestados, fuente, coords, tablas, acts, drvs, diag, permitir_ciclos, viajes_sig)` (línea 738).** Por (matrícula, día): construye ciclos geo, alinea, asigna, reparte sobrantes. `viajes_sig` permite recuperar un ticket en el día siguiente si su fecha real cambió.
- **Ciclos prestados** (`prestados`): un camión puede prestar un ciclo sobrante a otro albarán del mismo día. `jornada_prestada`/`ciclos_prestados_usados`.
- **`sitios_jornada` (533) + `elegir_hub` (543) + `particionar_hub` (556):** si la jornada gira sobre un hub (una base o planta), se parte por el hub con `HUB_EPS_KM` (350 m).

## 9. Pernoctas

- **`pernocta_cargado`** (motivo, `meta`/resumen línea 2056): carga hoy, descarga mañana. Se detecta cuando el hueco entre jornadas es ≤ 40 h y el camión sigue cargado. El viaje conserva su fecha de carga.

## 10. Hormigón

- **`aprender_plantas(dem_h, jornadas_mat)` (línea 803).** Las plantas se **aprenden de la traza**, no del maestro: grupo de paradas más visitado en los días de **un solo origen**; celda ≈ 440×400 m, con margen ×3 en el borde; requiere **≥ 2 días**. Radio de planta 450 m.
- **`visitas_plantas` (868) / `visitas_por_puntos` (850) / `planta_en` (846).** Cuándo el camión está en una planta aprendida.
- **`ciclos_plantas(j, plantas, fuente, tablas)` (línea 897).** Un ciclo de hormigón = de la **llegada a una planta a la llegada a la siguiente**. La **obra** = la parada más larga fuera de plantas (campo `obra {lat, lon, min}`).
- **`agrupar_por_m3(lst, n_ciclos, viajes, cap)` (línea 946).** Agrupa las cargas por m³ con tope de cuba `CAP_HORMIGONERA_M3` (8,5).
- **`triangular_hormigon(…)` (línea 965).** Asigna por planta en orden de GesRuta (cronológico dentro de cada planta). **`hora_carga` impresa = ancla dura** si viene en la carga (±30 min). Alias de planta ≤ 3 km. Respaldo por hub del día. `cantera_repetida` toma su turno. `ciclos_sin_albaran` = cargas que GesRuta no tiene. `km_vacio` = ida a cargar + vuelta de la obra.
- **`es_hormigonera`**: un camión es hormigonera si ≥ 50 % de sus cargas son hormigón. `larga_distancia` va por distancia ≥ 200 km.
- Plantas aprendidas publicadas en `resumen.hormigon.plantas_aprendidas` y `hallazgos.plantas_aprendidas` (línea 2208).

## 11. Larga distancia (pasada de nacional)

- Origen-destino ≥ 200 km (`LARGA_KM`). «Nacional» es el tipo de servicio; la distancia es lo que manda aquí.
- **`zona_larga(cod, coords, casa)` (línea 1100)** define las zonas de origen y destino; **`visitas_zona(…, min_parada_s=600)` (línea 1121)** = estancia ≥ 600 s en la zona.
- **`km_prefijo(pts, tablas)` (línea 1152)** = km acumulados del contador (CAN monótono) para medir cuánto se ha recorrido.
- **`triangular_larga(m, idxs, dem, pts, jornadas, coords, …)` (línea 1198).** Se casan sobre la traza **continua** del camión (cruzan descansos y días):
  - Fecha del albarán = la de **carga**. Carga = estancia con parada en la zona de origen que cubre esa fecha (±1 día).
  - Descarga = primera estancia con parada en la zona de destino tras recorrer **0,8-1,8 veces** la distancia (contador CAN), en **≤ dist/55 + 18 h** y **sin huecos de traza > 3 h**.
  - Inicio del viaje = fin del viaje anterior / última parada ≥ 20 min en lugar conocido / inicio de la jornada en que llega al origen (lo más tarde). Fin = fin de la jornada / salida de la zona / inicio de la carga del siguiente (lo primero).
  - **Conciliación con los ciclos locales del mismo camión: el largo manda.** El local que lo pisa se **absorbe como grupaje** (mismo origen), se **recorta** y se vuelve a medir (`recortado_por_viaje_largo_del_camion_*`), se **descuenta** si cae dentro, o queda `sin_ciclo`. Grupaje = repartido.
  - `pendiente_pasada_nacional` = largo sin casar, repartido por el día; se casará cuando la traza esté completa.
- **`primer_paso_destino` (1469)**: destino por paso cuando no se ve la descarga entera.

## 12. Espejos intragrupo

- **Definición (`meta.espejos`, línea 2079):** el mismo porte en Razo y en Agetrans (mismo camión, mismo ticket, mismo día). Clave del espejo = (matrícula, cantidad, día) presente en las dos casas.
- Se **mide una vez** en la casa **dueña del camión**; la otra línea **hereda** con `espejo_de = {empresa, viaje, cantera, linea}` de la principal.
- **Regla de oro para agregar: los totales de grupo deben SALTAR las filas con `espejo_de`** (si no, se cuenta el km/litros/coste dos veces). El motor y la conciliación ya lo hacen; el ERP tiene que hacerlo igual.
- Asignación del dueño en `main` (línea 1545); herencia en la segunda pasada.

## 13. Segundas pasadas

- **`fecha_del_albaran_corregida_por_traza`**: si la traza dice que el ticket es de otro día (±7 días, `VENTANA_DIAS`), se corrige `fecha` (≠ `fecha_gesruta`). Hallazgo `fecha_corregida` (línea 2194).
- **Largos sin casar**: reparto del día con `pendiente_pasada_nacional`; hallazgo `largos_pendientes_de_traza` (línea 2197).
- **`cargar_ancla(ruta)` (línea 1515)**: identidad (casa, origen, cantera, año) para detectar `cantera_repetida` (mismo número de albarán reusado): error de grabación, el albarán existe pero su número está mal.

## 14. Motivos de `sin_traza`

`camion_ajeno` (subcontratado, nunca tendrá traza nuestra), `sin_telemetria_o_pendiente_locatel`, `pendiente_bajada`, `sin_matricula`, `sin_traza_en_esas_fechas(_locatel)`, `mas_albaranes_que_ciclos_en_la_traza`. Hallazgo `sin_localizador` (línea 2192): camiones con albaranes y sin traza.

## 15. Campos de salida por viaje (triangulado_v2.json)

`empresa, viaje, cantera, matricula, fecha, fecha_gesruta, origen, destino, tipo, larga_distancia, dist_od_km, km, duracion_min, litros, litros_calibrados, metodo, medido, fuente, km_fuente, repartido, confianza, motivo, t_ini, t_fin, orden_dia, ciclo, geo_score, jornada_ini/fin, jornada_nocturna, jornada_prestada, min_conduccion, min_espera, min_otros, min_disponible, min_descanso, min_sin_dato, min_fuente, min_coherente, motivo_min, min_transcurridos, km_cargado, km_vacio, litros_cargado, litros_vacio, conductor_hash, chofer_tacografo, chofer_gesruta, chofer_coincide, t_carga, t_carga_fin, t_descarga, t_descarga_fin, viajes_dia, albara, linea, cliente, n_cargas_clave, espejo_de, pendiente_pasada_nacional, paradas, obra, matricula_de_baja, coord_origen, coord_destino, coord_revisar` (líneas 1978-2004).

El JSON lleva además `meta` (autodescripción de todas las reglas, líneas 2069-2085), `resumen` (agregados y `parametros`) y `hallazgos` (12 listas para actuar).

## 16. Conciliación contra la contabilidad (src/model.mjs)

- **`ledgerView(f)` (línea 149).** Lee el libro (asientos por cuenta) de las sociedades del filtro, con el ajuste intragrupo. Devuelve `income`, `gasto` y `accounts` por categoría contable.
- **`bridge(f)` (línea 194).** Puente entre el libro y las magnitudes; parte de `ledgerView`.
- **`_reparto(f)` (línea 310) — el corazón de la conciliación.** Reparte el gasto del libro a los viajes **MES A MES**:
  - El gasto de cada mes va **solo a los viajes de ese mes**.
  - Dentro del mes, cada partida se reparte entre **viajes medidos** (por su base física: litros / horas / km) y **viajes no medidos** (por su **cuota de ingreso**).
  - Subcontratación: `IMPPRO` escalado a la cuenta **607**. Áridos por cliente-mes vía `inggas`. Indirectos por ingreso. **La cuenta 630 (impuesto de sociedades) se excluye del reparto.**
  - Meses no cerrados usan los coeficientes del último mes cerrado y se marcan **«coste estimado»** (`costeEstimado`, `mesesEstimados`).
  - **Ingreso de transporte = facturado − material** (para no inflar el margen con la compraventa de áridos).
  - Devuelve `{A, rows, cost, desglose, dRateOf, nameOf, sub, coef, K, mesesEstimados, income, gasto, margenLibroPct, scale, …}`.
- **`realView(f, dim)` (línea 416).** Vistas por dimensión `plate | client | month | tipo | ruta | carga | descarga` con **detalle al pinchar**; los coeficientes son fijos del periodo (no cambian al filtrar). Los totales cuadran con «Margen por viaje».
- **`netaTrips(f)` (línea 392).** Margen neto por viaje usando `desglose`; marca `costeEstimado`.
- **`telemetryView(f)` (línea 211).** Cobertura del localizador por día y fuente, con lo recortado (`dias`, `porFuente`, `recortado`), obedeciendo las fechas elegidas.
- **`plateSociety` (línea 138).** Sociedad de cada matrícula por mayoría de partes; base para saltar espejos y separar flota propia.

## 17. Telemetría del informe (scripts/prepare-data.mjs)

- **Fusión (líneas 95-121).** Movertis del ERP > histórico Wialon (`historicos\wialon_hist\_resumen.jsonl`, desde ago-2025) > km diario de Locatel. Guardas: `km_fuente` obligatorio, `KM_MAX_DIA=1500`, `LITROS_MAX_DIA=900` (línea 98); `KM_MAX_PARTE=1500` (línea 24). Sin contador o km imposibles = no es dato (línea 121).
- **Tipo de servicio (`tipoServicio`, línea 34).** Por la cuenta contable de la línea (`CUECON`), no por el texto libre del concepto (2.000 variantes que no sirven para filtrar). Gana el prefijo más largo. Config en `config/cuentas-contables.json` → `conceptosFacturacion`.

## 18. Categorías de cuenta (config/cuentas-contables.json)

**Gasto (grupos 6):** subcontratación=607, combustible=6280000000, personal=640/641/642/643/649, dietas=6290080, áridos=600/601/6020000006/6020000022, repuestos=6020020000/6020000003, reparaciones=622, seguros=625, peajes=6290000070, amortización=680/681/682, renting=621, **impuesto de sociedades=630 (fuera del reparto)**, tributos=63, financieros=66, extraordinarios=67, suministros=628, otras compras=602/608/609, otros=6. Gana el **prefijo más largo**.

**Ingreso (grupo 7):** servicios=705, ventas=700/701/702, subvenciones=74, extraordinarios=77/79, otros=7.

**Tipos de servicio en factura (`conceptosFacturacion`):** portes nacionales 7050000000, regionales 7050000006, camión por horas 7050000002, áridos toneladas 705002, hormigón m³ 7050031001, hormigón m³ mínimos 7050031002, hormigón horas/esperas 7050032001, hormigón desplazamientos 7050032002, hormigón otros 705003, otros transporte 705, venta de productos 700-703, otros ingresos 75/77/79.

## 19. Ficheros que publica el informe (para el ERP y para tarifas)

| Fichero | Contenido |
|---|---|
| `_RENTABILIDAD\triangulado_v2.json` | Todos los viajes medidos con sus reglas (§15) + meta + resumen + hallazgos. |
| `_RENTABILIDAD\export\costes.json` | Gasoil (628 completa) y personal de conductores por mes y sociedad, para que tarifas calibre litros y horas contra la contabilidad: `sociedades.<Razo\|Agetrans\|Grupo_suma\|Grupo_consolidado>.meses["AAAA-MM"].agregados.gasoil` y `.personalConductor`. |
| `_RENTABILIDAD\export\trazas_viajes.jsonl.gz` | Una línea por viaje medido con clave (empresa, viaje, cantera), tiempos e hitos, posc/posd, km/km_cargado/km_vacio, litros, min, y el recorrido real simplificado (Douglas-Peucker 30 m): `ciclo` entero y `cargado`. El trazo dibuja ~90 % del km_cargado; **para distancias usar km_cargado**, la línea es para pintar. |

## 20. Cómo sincronizamos (ERP manda)

1. El ERP se lleva estas reglas y parámetros al motor único. **`coste_cargas` y `tarifas_rutas` de tarifas pasan a ser salidas de COMPARACIÓN, no maestro.**
2. Mi motor se queda y consume los **parámetros y resultados del ERP** (por XML-RPC solo lectura o por fichero; el ERP me pasa el esquema). Donde el ERP y yo discrepemos, **enseño la diferencia**; el ERP gana.
3. **Mi conciliación mensual con la contabilidad sigue siendo mía** (es lo que cuadra con el libro): el ERP no la duplica, la consume.
4. Cambios de esquema se avisan por SendMessage y en el canal del buzón. Nada de dos cifras distintas para el mismo porte.

_Última revisión: 2026-09-23. Números de línea sobre `triangular_v2.py`, `model.mjs`, `prepare-data.mjs` y `cuentas-contables.json` a esta fecha._
