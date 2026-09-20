# -*- coding: utf-8 -*-
"""Esquema de Partes 7.0.accdb: tablas y columnas relacionadas con empleados /
responsables (solo nombres de tabla y de columna, ningun dato personal)."""
import pyodbc

RUTA = r"P:\PartesTrabajo\Partes 7.0.accdb"
drv = [d for d in pyodbc.drivers() if "Access" in d and "accdb" in d]
cn = pyodbc.connect("DRIVER={%s};DBQ=%s" % (drv[0], RUTA), readonly=True)
c = cn.cursor()
todas = [(r.table_name, r.table_type) for r in c.tables()]
print("TODAS LAS TABLAS Y TIPOS:", [x for x in todas if x[1] in ("TABLE", "LINK", "PASS-THROUGH", "VIEW")])
tablas = [n for n, t in todas if t in ("TABLE", "LINK", "PASS-THROUGH")]
for t in tablas:
    cols = [r.column_name for r in c.columns(table=t)]
    if any(k in t.lower() for k in ("emple", "respons", "conduc", "chofer", "trabaj", "person")) or t == "PartesTrabajo":
        clave = [x for x in cols if any(k in x.lower() for k in ("respons", "emple", "chofer", "conduc", "precio", "coste", "dni", "nombre", "categor", "cod", "id"))]
        print("\n== %s (%d columnas)%s" % (t, len(cols), "" if t == "PartesTrabajo" else ": " + str(cols)))
        if t == "PartesTrabajo":
            print("   columnas candidatas:", clave)
            print("   TODAS:", cols)
        try:
            c.execute("SELECT COUNT(*) FROM [%s]" % t)
            print("   filas:", c.fetchone()[0])
        except Exception as e:  # noqa: BLE001
            print("   (no se pudo contar)", str(e)[:80])
cn.close()
