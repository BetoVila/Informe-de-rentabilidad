# -*- coding: utf-8 -*-
"""Tercera sonda: leer la hoja 'Totales' (TOTALES SECCIONES) de TODOS los
resumenes mensuales, xls y xlsx, comprobar identidades y detectar duplicados.
Solo agregados; ningun nombre de empleado se lee ni se imprime."""
import collections
import glob
import os
import re

import openpyxl
import xlrd

RAIZ = r"Z:\LABORAL\_NOMINAS"
MESES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
         "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12}

candidatos = []
for ruta in glob.glob(os.path.join(RAIZ, "NOMINAS", "20*", "*", "*")):
    if ruta.lower().endswith((".xls", ".xlsx")) and "resumen" in os.path.basename(ruta).lower():
        candidatos.append(ruta)
for ruta in glob.glob(os.path.join(RAIZ, "datos nominas", "*RESUMEN*.xls*")):
    candidatos.append(ruta)


def filas_de(ruta):
    """Devuelve (hoja 'Totales' como lista de listas)."""
    if ruta.lower().endswith(".xlsx"):
        wb = openpyxl.load_workbook(ruta, read_only=True, data_only=True)
        nombre = next((n for n in wb.sheetnames if "total" in n.lower()), None)
        if nombre is None:
            return None, wb.sheetnames
        return [list(f) for f in wb[nombre].iter_rows(values_only=True)], wb.sheetnames
    wb = xlrd.open_workbook(ruta)
    nombre = next((n for n in wb.sheet_names() if "total" in n.lower()), None)
    if nombre is None:
        return None, wb.sheet_names()
    hoja = wb.sheet_by_name(nombre)
    return [hoja.row_values(i) for i in range(hoja.nrows)], wb.sheet_names()


def num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0


resultados = []
for ruta in sorted(candidatos):
    r = {"ruta": ruta.replace(RAIZ + "\\", ""), "mtime": os.path.getmtime(ruta), "error": None}
    try:
        filas, hojas = filas_de(ruta)
        if filas is None:
            r["error"] = "sin hoja Totales; hojas=%s" % hojas
            resultados.append(r)
            continue
        cif = periodo = None
        for f in filas[:12]:
            a = str(f[0]).strip() if f and f[0] is not None else ""
            b = str(f[1]).strip() if len(f) > 1 and f[1] is not None else ""
            if a == "Empresa":
                m = re.search(r"[A-Z]\d{8}", b)
                cif = m.group(0) if m else b[:20]
            if a == "Proceso":
                m = re.search(r"([A-Za-zñÑ]+)\s+del\s+(\d{4})", b)
                if m and m.group(1).lower() in MESES:
                    periodo = "%s-%02d" % (m.group(2), MESES[m.group(1).lower()])
                else:
                    periodo = "?" + b[:24]
        r["cif"], r["periodo"] = cif, periodo
        # bloque TOTALES SECCIONES
        ini = next((i for i, f in enumerate(filas) if f and isinstance(f[0], str) and f[0].strip().upper().startswith("TOTALES SECCIONES")), None)
        if ini is None:
            r["error"] = "sin TOTALES SECCIONES"
            resultados.append(r)
            continue
        cab = next(i for i in range(ini, ini + 6) if len(filas[i]) > 2 and any(isinstance(v, (int, float)) for v in filas[i][2:]))
        secciones = [int(v) for v in filas[cab][2:] if isinstance(v, (int, float))]
        filas_concepto = {}
        for f in filas[cab + 1:]:
            if f and isinstance(f[0], str) and f[0].strip():
                filas_concepto[f[0].strip()] = [num(v) for v in f[1:1 + 1 + len(secciones)]]
        r["secciones"] = secciones
        tot = filas_concepto.get("TOTAL")
        dev = filas_concepto.get("TOTAL DEVENGOS")
        ss = filas_concepto.get("TOTAL COSTE S.S.")
        if not (tot and dev and ss):
            r["error"] = "faltan filas TOTAL/DEVENGOS/SS: %s" % [k for k in ("TOTAL", "TOTAL DEVENGOS", "TOTAL COSTE S.S.") if k not in filas_concepto]
            resultados.append(r)
            continue
        r["total"] = tot[0]
        r["devengos"] = dev[0]
        r["ss"] = ss[0]
        r["por_seccion"] = dict(zip(secciones, tot[1:]))
        # identidades
        r["chk_suma_secciones"] = abs(sum(tot[1:]) - tot[0]) < 0.02
        r["chk_dev_mas_ss"] = abs(dev[0] + ss[0] - tot[0]) < 0.02
    except Exception as e:  # noqa: BLE001
        r["error"] = "%s: %s" % (type(e).__name__, str(e)[:90])
    resultados.append(r)

print("ficheros candidatos leidos: %d" % len(resultados))
print("\n%-58s %-11s %-8s %12s %5s %5s" % ("fichero (recortado)", "cif", "periodo", "TOTAL", "sum", "d+ss"))
for r in resultados:
    if r["error"]:
        print("%-58s ERROR %s" % (r["ruta"][-58:], r["error"]))
    else:
        print("%-58s %-11s %-8s %12.2f %5s %5s  secc=%s" % (r["ruta"][-58:], r["cif"], r["periodo"], r["total"],
              r["chk_suma_secciones"], r["chk_dev_mas_ss"], list(r["por_seccion"].keys())))

# duplicados por (cif, periodo)
grupos = collections.defaultdict(list)
for r in resultados:
    if not r["error"]:
        grupos[(r["cif"], r["periodo"])].append(r)
print("\n=== (empresa, periodo) con MAS DE UN fichero ===")
for k, v in sorted(grupos.items()):
    if len(v) > 1:
        print(k)
        for r in v:
            print("     %-70s TOTAL=%.2f" % (r["ruta"][-70:], r["total"]))
print("\n=== cobertura: periodos por empresa ===")
por_cif = collections.defaultdict(set)
for (cif, per) in grupos:
    por_cif[cif].add(per)
for cif, ps in por_cif.items():
    print(cif, len(ps), "periodos:", min(ps), "->", max(ps), " faltan (2025-01..2026-08):",
          [p for p in ["2025-%02d" % m for m in range(1, 13)] + ["2026-%02d" % m for m in range(1, 9)] if p not in ps])
