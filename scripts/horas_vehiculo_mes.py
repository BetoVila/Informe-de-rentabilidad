# -*- coding: utf-8 -*-
"""Horas de trabajo MEDIDAS por (matrícula, mes) a partir de jornadas_conductor_v1.json (localizador: conducción + otros
trabajos, por conductor y día, con la unidad conducida). Sirve para dar HORAS REALES a los viajes de hormigón, que no
casan con la triangulación por viaje. SOLO LECTURA. Salida: JSON {"MATRICULA|YYYY-MM": minutos_medidos}."""
import argparse, json, os, re, collections

def norm(m):
    return re.sub(r"[^0-9A-Z]", "", (m or "").upper())

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jornadas", required=True)
    ap.add_argument("--salida", required=True)
    a = ap.parse_args()
    j = json.load(open(a.jornadas, encoding="utf-8"))
    rows = j if isinstance(j, list) else (j.get("rows") or next((v for v in j.values() if isinstance(v, list)), []))
    out = collections.defaultdict(float)
    for r in rows:
        dia = str(r.get("dia") or "")
        if len(dia) < 7:
            continue
        mes = dia[:7]
        mins = (r.get("conduccion_min") or 0) + (r.get("otros_trabajos_min") or 0)
        uds = [u for u in (r.get("unidades") or []) if norm(u)]
        if not uds or mins <= 0:
            continue
        for u in uds:
            out[norm(u) + "|" + mes] += mins / len(uds)   # si condujo varias ese día, se reparten
    res = {k: round(v) for k, v in out.items()}
    tmp = a.salida + ".tmp"
    json.dump(res, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
    os.replace(tmp, a.salida)
    mats = {k.split("|")[0] for k in res}
    meses = {k.split("|")[1] for k in res}
    print("claves (matricula|mes):", len(res), "| matriculas:", len(mats), "| meses:", sorted(meses)[:12])
    print("horas totales medidas:", round(sum(res.values()) / 60))

if __name__ == "__main__":
    main()
