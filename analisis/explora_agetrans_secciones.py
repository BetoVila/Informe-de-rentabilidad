# -*- coding: utf-8 -*-
"""Que son las secciones 1 y 3 de la nomina de Agetrans: cruce (en memoria,
por nombre) de las personas de cada bloque con la tabla de choferes de GesRuta.
Solo se imprimen recuentos."""
import collections
import os
import re
import sys
import unicodedata

import openpyxl

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "rentabilidad-extract", "scripts"))
from dbf_gesruta import abrir  # noqa: E402

RUIDO = {"DE", "DEL", "LA", "LAS", "LOS", "Y"}


def toks(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().upper()
    return frozenset(t for t in re.sub(r"[^A-Z ]", " ", s).split() if t not in RUIDO and len(t) > 1)


def jacc(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


for emp, carpeta in (("Agetrans", r"P:\Gesruta\EMPAG21"), ("Razo", r"P:\Gesruta\EMPTR21")):
    with abrir(carpeta, "chofer.dbf") as db:
        campos = db.nombres()
        campo_nombre = next((c for c in campos if c.upper() in ("NOMBRE", "NOMCHO", "NOMBRECHO", "CHOFER", "NOM")), None)
        print("\n%s chofer.dbf: %d registros; campos=%s" % (emp, db.numrec, campos))
        nombres = []
        for rec in db.registros():
            f = db.fila(rec)
            n = f.get(campo_nombre) if campo_nombre else None
            if n:
                nombres.append(toks(n))
        print("   nombres de chofer con dato: %d (campo usado: %s)" % (len(nombres), campo_nombre))
    globals()["CHOF_" + emp] = nombres

RES = {
    "Agetrans": [r"Z:\LABORAL\_NOMINAS\NOMINAS\2026\%s\AGETRANS - RESUMEN%s.xlsx" % (m, s) for m, s in (
        ("08 Agosto 2026", " NOMINA"), ("07 Julio 2026", " NÓMINA"), ("05 Mayo 2026", ""), ("03 Marzo 2026", " MARZO"), ("01 Enero 2026", " NÓMINA"))],
    "Razo": [r"Z:\LABORAL\_NOMINAS\NOMINAS\2026\08 Agosto 2026\TR - RESUMEN NOMINA.xlsx"],
}
for emp, rutas in RES.items():
    chof = globals()["CHOF_" + emp]
    for ruta in rutas:
        if not os.path.exists(ruta):
            print("no existe:", ruta)
            continue
        wb = openpyxl.load_workbook(ruta, read_only=True, data_only=True)
        filas = [list(f) for f in wb["Detalle"].iter_rows(values_only=True)]
        inicios = [i for i, f in enumerate(filas) if len(f) > 1 and isinstance(f[1], str) and f[1].strip().startswith("Cód. sección")]
        print("\n#### %s | %s" % (emp, ruta.split("\\")[-2]))
        for n, i0 in enumerate(inicios):
            fin = inicios[n + 1] if n + 1 < len(inicios) else len(filas)
            bloque = filas[i0:fin]
            fila_t = next((f for f in bloque if isinstance(f[0], str) and f[0].strip() == "TOTAL"), None)
            total = fila_t[1] if fila_t else None
            cods = bloque[2] if len(bloque) > 2 else []
            es_chofer = no = 0
            for j in range(2, len(cods)):
                if cods[j] in (None, ""):
                    continue
                partes = [bloque[k][j] for k in (3, 4, 5) if len(bloque) > k and len(bloque[k]) > j and bloque[k][j]]
                t = toks(" ".join(str(p) for p in partes))
                if max((jacc(t, c) for c in chof), default=0) >= 0.5:
                    es_chofer += 1
                else:
                    no += 1
            print("   bloque %d: total=%s | personas=%d | son chofer en GesRuta=%d | no=%d" % (n + 1, None if total is None else round(total, 2), es_chofer + no, es_chofer, no))
