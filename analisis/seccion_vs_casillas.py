# -*- coding: utf-8 -*-
"""Cruza (en memoria, por nombre) las personas de cada seccion de la nomina con
las casillas de trabajo de Access. Solo se imprimen recuentos."""
import collections
import json
import os
import re
import subprocess
import unicodedata

X = r"C:\Users\Roberto\AppData\Local\Temp\claude\C--Users-Roberto-Downloads-Nueva-carpeta\28602b99-e589-45df-aa45-17dc43911990\scratchpad\rentabilidad-extract"
det_path = os.path.join(X, "nomina_detalle_tmp.json")
subprocess.run([os.path.join(X, "runtime", "python", "python.exe"), os.path.join(X, "scripts", "export_rentabilidad_nomina_v1.py"),
                "--root", r"Z:\LABORAL\_NOMINAS", "--output", os.path.join(X, "nomina_tmp.json"), "--output-detail", det_path,
                "--from-date", "2025-01-01", "--to-date", "2026-09-18"], check=True, capture_output=True)
det = json.load(open(det_path, encoding="utf-8"))["rows"]
per = json.load(open(os.path.join(X, "personal_test.json"), encoding="utf-8"))
RUIDO = {"DE", "DEL", "LA", "LAS", "LOS", "Y"}


def toks(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().upper()
    return frozenset(t for t in re.sub(r"[^A-Z ]", " ", s).split() if t not in RUIDO and len(t) > 1)


acc = [(e["id"], toks(e["nombre"]), e["tipo"], e["empresa"]) for e in per["employees"]]
por_set = collections.defaultdict(list)
for i, (eid, t, tipo, emp) in enumerate(acc):
    por_set[t].append(i)


def casar(t):
    if t in por_set and len(por_set[t]) == 1:
        return por_set[t][0]
    mejor, sc, segundo = None, 0.0, 0.0
    for i, (_, t2, _, _) in enumerate(acc):
        j = len(t & t2) / len(t | t2) if t and t2 else 0
        if j > sc:
            mejor, sc, segundo = i, j, sc
        elif j > segundo:
            segundo = j
    return mejor if sc >= 0.75 and sc - segundo >= 0.1 else None


# personas-mes de nomina en los ultimos 6 meses
meses = sorted({p["period"] for p in det})[-6:]
cuenta = collections.defaultdict(collections.Counter)      # (empresa, seccion) -> tipo -> n
sin = collections.Counter()
vistos = set()
tot = ok = 0
for p in det:
    if p["period"] not in meses:
        continue
    tot += 1
    i = casar(toks(p["nombre"]))
    k = (p["company"], p["seccion"])
    if i is None:
        sin[k] += 1
        continue
    ok += 1
    tipo = acc[i][2]
    marcas = [n for n in ("hormigonera", "banera", "nacional", "taller", "administracion") if tipo.get(n)]
    cuenta[k][("+".join(marcas)) or "(sin casilla)"] += 1
print("personas-mes de nomina (ultimos 6 meses): %d; casadas con Access: %d (%.0f%%)" % (tot, ok, 100.0 * ok / tot))
for k in sorted(cuenta):
    print("%-9s seccion %d -> %s   [sin casar: %d]" % (k[0], k[1], dict(cuenta[k].most_common(5)), sin[k]))
for k in sorted(sin):
    if k not in cuenta:
        print("%-9s seccion %d -> (ninguna casada)   [sin casar: %d]" % (k[0], k[1], sin[k]))
os.remove(det_path)
os.remove(os.path.join(X, "nomina_tmp.json"))
