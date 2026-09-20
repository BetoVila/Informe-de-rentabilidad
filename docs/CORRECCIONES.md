# Correcciones de Roberto y cómo se aplicaron

Regla de trabajo (Roberto, 20/09/2026): la rentabilidad por cliente y por viaje exige **muchos cruces indirectos** (no todo viene en un dato directo), así que habrá errores y **correcciones futuras**. Por eso: cada cifra derivada lleva su **método, su fuente y su confianza** (medida / deducida / extrapolada), las **reglas van en ficheros editables** (`config/`) y cada corrección se anota aquí con su fecha para no volver a cometerla.

| Fecha | Lo que dijo Roberto | Qué era en realidad | Cómo se aplicó |
|---|---|---|---|
| 19/09/2026 | «los gastos no son reales y el consumo aparente tampoco» | Los partes de Access son declarados: 2 partes con 4,49 M km imposibles; falta el parte en ~1 de cada 3 días en que el camión circula | Km > 1.500 por parte excluidos; gastos y consumo de Access rotulados «declarado»; km reales de Movertis |
| 19/09/2026 | «hay más gastos que los que muestras, no hay ese margen que me pones» | Solo se restaba el coste de los partes (59 % del gasto real): margen 40 % frente al 10,7 % contable | Cabecera con ingresos, gastos y resultado de la contabilidad (meses cerrados); puente contabilidad/partes en Conciliación |
| 20/09/2026 | «el hormigón se factura mixto, o por horas o por km; los KPIs de todos los viajes en horas y en kilómetros» | Yo había dicho que el hormigón de Razo se factura por horas: se factura por horas, por m³ con tramos de km o por porte | Todos los ratios en horas y en km (ingresos y beneficio por hora, por km y por € gastado); nunca solo la base de facturación |
| 20/09/2026 | «también ratios por personal» | — | Pestaña Personal: facturación declarada, por hora, por km y por € de coste por persona |
| 20/09/2026 | «prepárate para futuras correcciones» | — | Este fichero + confianza por cifra + reglas editables |

## Hallazgos de método que evitan errores repetidos
- `LINEAS` (GesRuta) se une con `ALBARA` por **(VIAJE, ALBARA↔ALBARA.NUMERO)**; `LINEAS.NUMERO` es un id global de línea.
- `LINEAS.IMPPRO` es el coste del subcontratista por línea, pero hay basura (p. ej. 0,9 en una línea de 620 €): usar solo valores > 20 € y contrastar con la cuenta 607.
- ORIGEN/DESTINO están en `LINEAS` (Agetrans: códigos postales; Razo: códigos de planta), no en `ALBARA` (LUGCAR/LUGDES casi vacíos).
- Hay **intercompany**: Razo factura a Agetrans (cliente «AGETRANS BERGANTIÑOS» en Razo) y parte de la subcontratación de Agetrans es Razo. En rentabilidad por cliente hay que eliminarlo o marcarlo (aún sin hacer).
- Las horas y los km por viaje NO están en GesRuta (KILOME acaba el 17/04/2026): salen de los localizadores (Movertis solo desde el 20/08/2026 en el ERP; Locatel sin conectar).
