# Informe de rentabilidad Razo + Agetrans

Informe único que se recalcula solo cada noche y se consulta desde cualquier PC de la oficina.

| Qué | Dónde |
|---|---|
| **Informe** (icono «RENTABILIDAD - Razo y Agetrans») | `\\SERVIDOR\Programas\_RENTABILIDAD\informe.html` (= `P:\_RENTABILIDAD`) |
| Estado de la última lectura | `...\_RENTABILIDAD\estado.html` |
| **Motor nocturno** | tarea de Windows `Razo-Rentabilidad-Nocturna`, 03:00, en PC-ROBERTO con el usuario Roberto (sin administrador). Programa instalado en `C:\ProgramData\RazoRentabilidad` (logs 90 días, `work` 14 días) |
| **Código fuente** (esta carpeta, con git) | `C:\CLAUDE ESPECIAL\05-PROGRAMAS-Y-HERRAMIENTAS\rentabilidad-informe` |
| Paquete instalable (lleva el runtime de Python y Node) | `P:\_RENTABILIDAD\programa.zip` + `Instalar.ps1` + `LEEME.txt` |
| Bitácora técnica y hallazgos | `docs/DIAGNOSTICO-Y-PLAN-CLAUDE.md` |
| Maqueta aprobada por Roberto | `docs/maqueta-aprobada` |
| Antecedente (paquete de Codex r2, 05/09/2026) | `../rentabilidad-servidor` (superado por esta carpeta) |

Iconos del escritorio de Roberto: **RENTABILIDAD - Razo y Agetrans** (abre el informe), **Rentabilidad - Actualizar ahora**, **Rentabilidad - Clave del personal**.

## Qué lee (todo en SOLO LECTURA)

| Fuente | Cómo | Obligatoria |
|---|---|---|
| GesRuta (facturas y líneas, Razo EMPTR21 y Agetrans EMPAG21) | lector propio de DBF/FPT (`scripts/dbf_gesruta.py`) | sí |
| Access `Partes 7.0.accdb` (partes diarios) | ACE OLEDB en modo lectura | sí |
| Contabilidad (CxConta) | `SELECT` agregado sobre `razo_cxconta_apunte` de la base del ERP (`docker exec odoo15-local-db psql`) | no |
| Movertis: km y litros por camión y día | `razo_movertis_dia` del ERP, solo lectura. **Aquí no se abre sesión en Movertis** (Wialon admite una sola y el ERP ya la usa) | no |
| Solred (tarjeta) | ficheros `Operaciones*.txt` del buzón `Z:\A CARBURANTES` (Analizador Carburantes) | no |
| Surtidor de la nave (GesproWin) | base .mdb + exportaciones de texto | no |
| Nómina de la gestoría | resúmenes mensuales de `Z:\LABORAL\_NOMINAS`; agregados, grupos de menos de 3 personas plegados | no |
| Personal por persona | solo si Roberto ha elegido clave; sale CIFRADA (AES-256-GCM en el navegador) | no |

Si falla una fuente opcional el informe sale igual y lo dice arriba. **Nunca se sustituye un dato que falta por un cero.**

## Flujo

`Actualizar.ps1` → `scripts/export_*` (uno por fuente) → `scripts/prepare-data.mjs` (une, valida, conciliaciones) → `scripts/build.mjs` (aserciones + `informe.html` único y autocontenido, sin recursos externos) → sustitución atómica en la carpeta publicada con `.anterior`. Si algún control falla se conserva el informe anterior y `estado.html` lo dice.

## Reglas que salen de lo medido (no relajar)

1. **El resultado sale de la contabilidad** (grupos 6 y 7 de CxConta, `clase='ordinario'`, solo meses cerrados), **nunca** de restar el coste de los partes: los partes captan ~59 % del gasto (enero–agosto 2026: contabilidad 10,7 % de margen; solo partes, 40 %). Faltan subcontratación, compra de áridos, personal que no conduce y generales.
2. **Lo de Access es DECLARADO** (km, litros, gastos, horas): hay partes con 4,5 millones de km (se excluyen los de más de 1.500 km por parte) y falta el parte en ~1 de cada 3 días en que el camión circula. Se muestra rotulado «declarado».
3. Lo real: contabilidad, Solred, surtidor, nómina y, para km y consumo, los localizadores.
4. Sin claves en ficheros ni en el chat: Movertis/Locatel = variables de entorno de usuario (`WIALON_TOKEN`, `LOCATEL_USUARIO`, `LOCATEL_CLAVE`); la clave del apartado de personal la teclea Roberto en su ventana (`CLAVE DEL PERSONAL.cmd`, DPAPI del usuario).
5. Con filtros de vehículo/cliente solo se ve el coste imputable y se avisa de que no es el resultado real.
6. **Facturación consolidada**: el selector «Suma de empresas / Consolidada» elimina el intragrupo Razo↔Agetrans, medido en el libro por la cuenta de empresas del grupo (clientes 433-436 → ingreso 7xx; proveedores 403-406 → gasto 6xx; la 552 cta. cte. es tesorería y se excluye), sin cablear cuentas. 2026 ene-ago: 924k de ingreso y 758k de gasto intragrupo; el margen del grupo pasa de 10,7 % (suma) a 9,5 % (consolidado) y un panel enseña los 166k sin casar por timing. Solo meses cerrados.
7. **Costes de personal por tramo**: en Conciliación, el coste de empresa de la nómina de la gestoría se acumula por tramo de la plantilla (conductor hormigonera/nacional/bañera, administración, taller) y se compara con el periodo elegido en «Comparar con». Agregado, **sin nombres** (los datos por persona siguen cifrados en la pestaña Personal).
8. **Resultado según combustible y personal**: en Resumen, panel de sensibilidad sobre la contabilidad real. Combustible (cuenta 628) y personal (640-649) son los dos costes que más mueven el resultado; se enseña su peso (€ y % de ingresos), lo que se lleva cada 1 % y una matriz combustible × personal (la fila y la columna del 0 % = cada coste por separado; el resto = los dos juntos; verde mejora, rojo empeora). Respeta periodo, sociedad y el selector Suma/Consolidada.

## Cómo se trabaja

```powershell
# 1) restaurar el runtime (Python 3.12 + Node) desde el paquete publicado
powershell -File scripts\restaurar-runtime.ps1
# 2) pruebas (modelo, tres modos de coste, contabilidad, puente) sobre unos datos ya extraídos
runtime\node\node.exe scripts\test.mjs <current.json.gz> <informe.html>
runtime\node\node.exe scripts\test-cripto.mjs
# 3) copiar el programa de trabajo a la carpeta instalada y lanzar la tarea (solo desarrollo)
powershell -File deploy-dev.ps1
# 4) empaquetar una versión nueva y publicarla junto a Instalar.ps1
powershell -File scripts\package.ps1 -ReleaseName release-rN
```

`Instalar.ps1` instala o actualiza (repetirlo no toca configuración ni tarea): `-Modo Pc` (actual) o `-Modo Servidor` (dentro de SERVIDOR, tarea SYSTEM; no activar las dos a la vez). Los `.ps1` van con BOM UTF-8 (Windows PowerShell 5.1 lee sin BOM como ANSI y estropea las tildes) y los JSON se leen con `-Encoding UTF8`.

## Pendiente (20/09/2026)

- Roberto: elegir la clave del apartado «Personal» (icono) y bajar de Mi Solred, con la cuenta de Agetrans, los `Operaciones` en **texto** (no Excel) a `Z:\A CARBURANTES\1 DEJAR AQUI`.
- Locatel (km/consumo CANbus): el extractor ya lee `razo_locatel_emision` del ERP y el informe muestra Locatel como fuente; hoy esa tabla está **VACÍA en la copia local** (el agente del ERP la llena en producción), así que aún no hay km de Locatel y el chip dice «sin datos». En cuanto lleguen a la copia local se usan solos, sin tocar nada. Igual con el histórico de Movertis anterior al 20/08/2026 y `razo_km_historico` (filtrando `descartada = False`).
- Repartir con criterio subcontratación, áridos y generales por vehículo/cliente (la contabilidad ya trae cuentas por actividad y amortización por matrícula).
- Rentabilidad por cliente y viaje: aplicar también ahí la eliminación intragrupo (en la vista contable ya está) y, del marco de Tactio (referencia, no plantilla), el margen de contribución por unidad de negocio alimentado con dato real, no con % fijos.
- Copia nocturna de GesproWin desde PC AUXILIAR (parada desde el 06/08).
