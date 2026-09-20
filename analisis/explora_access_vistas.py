# -*- coding: utf-8 -*-
"""Columnas (solo nombres) de las consultas de Access que hablan de empleados."""
import pyodbc

RUTA = r"P:\PartesTrabajo\Partes 7.0.accdb"
drv = [d for d in pyodbc.drivers() if "Access" in d and "accdb" in d]
cn = pyodbc.connect("DRIVER={%s};DBQ=%s" % (drv[0], RUTA), readonly=True)
c = cn.cursor()
for v in ("EmpleadosConsulta", "UltimoContratoVigentePorEmpleado", "EmpleadosContratos", "ConductorConsulta", "MaquinasAsignadas"):
    try:
        c.execute("SELECT TOP 1 * FROM [%s]" % v)
        cols = [d[0] for d in c.description]
        c.execute("SELECT COUNT(*) FROM [%s]" % v)
        n = c.fetchone()[0]
        print("\n== %s: %d filas; columnas: %s" % (v, n, cols))
    except Exception as e:  # noqa: BLE001
        print("\n== %s: ERROR %s" % (v, str(e)[:140]))
# valores distintos de IdResponsable en los partes recientes (solo cuantos)
c.execute("SELECT COUNT(DISTINCT IdResponsable), COUNT(*) FROM PartesTrabajo WHERE Fecha >= #01/01/2026#")
print("\nIdResponsable distintos / partes en 2026:", c.fetchone())
c.execute("SELECT COUNT(*) FROM PartesTrabajo WHERE Fecha >= #01/01/2026# AND (IdResponsable IS NULL OR IdResponsable = 0)")
print("partes 2026 sin responsable:", c.fetchone()[0])
cn.close()
