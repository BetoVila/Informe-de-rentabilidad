# -*- coding: utf-8 -*-
"""Km reales medidos por Locatel, para el informe de rentabilidad. SOLO LECTURA, SIN CLAVES.

El ERP NO carga Locatel en su base (su tabla `razo_locatel_emision` esta vacia), pero su agente de actualizacion, en el PC de
Roberto, SI baja Locatel cada rato con `extraer_locatel.py` y lo deja en `C:\\ODOO15-LOCAL\\copias\\locatel_stage\\locatel.json`.
Ese fichero trae la pagina `historicos_gps`: una fila por posicion GPS con su matricula, su fecha y el recorrido del tramo en km.
Aqui se lee ESE fichero (sin conectarse a Locatel) y se suma el recorrido por matricula y dia.

El fichero solo cubre unas dos semanas, asi que los km de cada dia se ACUMULAN en una cache propia del programa: noche a noche
se completa el historico sin volver a pedirlo. El dia de hoy (incompleto) no se guarda. Litros: el historico GPS no los trae.
"""
import argparse, datetime, json, os, re, sys

MESES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
         "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12}
FECHA = re.compile(r"(\d{1,2})\s+de\s+([a-záéíóúñ]+)\s+de\s+(\d{4})", re.IGNORECASE)
NUM = re.compile(r"-?\d+(?:[.,]\d+)?")
PLACA = re.compile(r"(\d{4}[A-Z]{3})")


def placa(s):
    # Locatel pega sufijos al nombre del vehiculo («8111JSB NAC», «8810GKT BA»): se deja la matricula (4 cifras + 3 letras).
    s = (s or "").replace(" ", "").replace("-", "").upper()
    m = PLACA.match(s)
    return m.group(1) if m else s


def dia(texto):
    # «lunes, día 7 de septiembre de 2026» -> '2026-09-07'
    m = FECHA.search(texto or "")
    if not m or m.group(2).lower() not in MESES:
        return None
    return datetime.date(int(m.group(3)), MESES[m.group(2).lower()], int(m.group(1))).isoformat()


def km(texto):
    # «12,3 Km» -> 12.3 ; vacio -> 0
    m = NUM.search((texto or "").replace(".", "").replace(",", ".") if "," in (texto or "") else (texto or ""))
    return float(m.group(0)) if m else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default=r"C:\ODOO15-LOCAL\copias\locatel_stage\locatel.json")
    ap.add_argument("--cache", required=True, help="cache propia de km por matricula y dia (se acumula)")
    ap.add_argument("--output", required=True)
    ap.add_argument("--from-date", default="2025-01-01")
    ap.add_argument("--to-date", default="")
    a = ap.parse_args()
    hoy = datetime.date.today().isoformat()
    hasta = a.to_date or (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    leido = datetime.datetime.now().isoformat(timespec="seconds")

    cache = {}
    if os.path.isfile(a.cache):
        with open(a.cache, encoding="utf-8") as f:
            cache = json.load(f)

    ventana = None
    if os.path.isfile(a.stage):
        with open(a.stage, encoding="utf-8") as f:
            st = json.load(f)
        ventana = {"desde": st.get("desde"), "hasta": st.get("hasta"), "generado_utc": st.get("generado")}
        filas = ((st.get("paginas") or {}).get("historicos_gps") or {}).get("filas") or []
        suma = {}
        for r in filas:
            p = placa(r.get("matricula"))
            d = dia(r.get("fecha"))
            if not p or not d or d >= hoy:
                continue
            x = suma.setdefault(p + "|" + d, {"km": 0.0, "pos": 0})
            x["km"] += km(r.get("recorrido"))
            x["pos"] += 1
        # Lo recien bajado manda sobre lo guardado (es la foto mas completa de esos dias).
        for k, x in suma.items():
            cache[k] = {"km": round(x["km"], 2), "pos": x["pos"], "visto": leido}
        os.makedirs(os.path.dirname(a.cache), exist_ok=True)
        tmp = a.cache + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
        os.replace(tmp, a.cache)

    rows = []
    for k, x in sorted(cache.items()):
        p, d = k.split("|", 1)
        if a.from_date <= d <= hasta and x["km"] > 0:
            rows.append({"p": p, "from": d, "to": d, "km": x["km"], "litres": None, "co2e": None,
                         "estimado": False, "fuel": None})
    fuente = "Locatel (posiciones GPS que baja el agente del ERP en el PC; acumuladas por dia)"
    if not rows:
        motivo = ("No hay km de Locatel en el periodo." if ventana else
                  "No se encuentra el fichero de Locatel del agente del ERP (" + a.stage + ").")
        out = {"metadata": {"disponible": False, "fuente": fuente, "leido": leido, "motivo": motivo}}
    else:
        out = {"metadata": {"disponible": True, "fuente": fuente, "desde": rows[0]["from"],
                            "hasta": max(r["to"] for r in rows), "registros": len(rows), "estimados": 0,
                            "unidades": len({r["p"] for r in rows}), "dias_en_cache": len(cache),
                            "ventana_agente": ventana, "leido": leido}, "rows": rows}
    with open(a.output, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print(json.dumps(out["metadata"], ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print("ERROR: %s" % e, file=sys.stderr)
        sys.exit(1)
