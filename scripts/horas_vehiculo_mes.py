# -*- coding: utf-8 -*-
"""Horas de trabajo MEDIDAS por (matrícula, mes). SOLO LECTURA. Salida: JSON {"MATRICULA|YYYY-MM": minutos_medidos}.

Dos fuentes, en orden de fiabilidad:
  1) jornadas_conductor_v1.json (canal de tacógrafo del localizador: conducción + otros trabajos por conductor y día,
     con la unidad conducida). Base para todo el que mete la tarjeta.
  2) --hormigon horas_hormigon_v1.json (traza GPS de movimiento de Wialon, agregada por vehículo-mes). PRIORITARIA
     para las hormigoneras, que casi nunca meten la tarjeta de tacógrafo: donde el tacógrafo existe, INFRAVALORA
     mucho (p. ej. 1533NFJ marzo: tacógrafo 853 min vs traza 7.647). Corrección de Roberto (22/09/2026): «los
     tiempos se sacan de las localizaciones, de los históricos, no solo de archivos de tacógrafo». Por eso la traza
     GPS GANA sobre el tacógrafo en esas claves (matrícula|mes). Se produce con descargar_horas_hormigon.py.
Al regenerar esta tabla se reaplica siempre el override, así la fusión es durable en cada pasada."""
import argparse, json, os, re, collections

def norm(m):
    return re.sub(r"[^0-9A-Z]", "", (m or "").upper())

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jornadas", required=True)
    ap.add_argument("--hormigon", help="horas_hormigon_v1.json (traza GPS); GANA sobre el tacógrafo en sus claves")
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
    # Override con la traza GPS de las hormigoneras (fuente superior; ver docstring)
    nsust, nnuevo = 0, 0
    if a.hormigon and os.path.isfile(a.hormigon):
        horm = json.load(open(a.hormigon, encoding="utf-8"))
        for k, v in horm.items():
            if not v:
                continue
            kk = norm(k.split("|")[0]) + "|" + k.split("|", 1)[1]
            if kk in res:
                nsust += 1
            else:
                nnuevo += 1
            res[kk] = round(v)
    tmp = a.salida + ".tmp"
    json.dump(res, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
    os.replace(tmp, a.salida)
    mats = {k.split("|")[0] for k in res}
    meses = {k.split("|")[1] for k in res}
    print("claves (matricula|mes):", len(res), "| matriculas:", len(mats), "| meses:", sorted(meses)[:12])
    print("horas totales medidas:", round(sum(res.values()) / 60))
    if a.hormigon:
        print("override hormigón (traza GPS): sustituidas", nsust, "| nuevas", nnuevo)

if __name__ == "__main__":
    main()
