# -*- coding: utf-8 -*-
"""Informe «Vehiculos» de Mi Solred (Excel): litros, importe y operaciones POR MATRICULA de un periodo y un NIF. SOLO LECTURA.

Sirve cuando de una cuenta Solred no hay los ficheros mensuales de operaciones (Operaciones AAAAMM.txt) pero si este resumen:
permite ver el combustible real de esa sociedad por matricula aunque no por mes. El detalle mensual siempre es mejor; esto
se usa para que la sociedad no quede en blanco y se dice claramente que es un resumen.

Se buscan los ficheros `vehiculos*.xlsx` (con o sin tilde) en el buzon de carburantes, en sus subcarpetas. No se leen los
numeros de tarjeta ni las hojas de estaciones: solo matricula, importe, consumo (litros), operaciones y descuento.
"""
import argparse, datetime, json, os, re, sys, unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "vendor"))   # openpyxl (Python puro)
import openpyxl  # noqa: E402


def sin_tildes(texto):
    return "".join(c for c in unicodedata.normalize("NFD", str(texto or "")) if unicodedata.category(c) != "Mn").lower().strip()


def matricula(valor):
    return re.sub(r"[^A-Z0-9]", "", str(valor or "").upper())


def numero(valor):
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def leer(ruta):
    libro = openpyxl.load_workbook(ruta, read_only=True, data_only=True)
    hoja = next((h for h in libro.worksheets if sin_tildes(h.title).startswith("veh")), None)
    if hoja is None:
        return None
    filas = [list(f) for f in hoja.iter_rows(values_only=True)]
    nif = desde = hasta = None
    cabecera = None
    for i, fila in enumerate(filas[:25]):
        celdas = [c for c in fila if c not in (None, "")]
        texto = [sin_tildes(c) for c in celdas]
        if len(celdas) >= 2 and texto[0] == "fecha":
            m = re.search(r"(\d{4}-\d{2}-\d{2})\D+(\d{4}-\d{2}-\d{2})", str(celdas[1]))
            if m:
                desde, hasta = m.group(1), m.group(2)
        if len(celdas) >= 2 and texto[0] == "nif":
            nif = str(celdas[1]).strip()
        if texto and texto[0] == "tarjeta" and "matricula" in texto:
            cabecera = i
            break
    if cabecera is None or not desde:
        return None
    nombres = [sin_tildes(c) for c in filas[cabecera]]
    def col(*claves):
        for k in claves:
            for j, n in enumerate(nombres):
                if n == k or n.startswith(k):
                    return j
        return None
    ix = {"plate": col("matricula"), "importe": col("importe"), "litros": col("consumo"), "ops": col("operaciones"), "dto": col("dto", "€ de dto")}
    if ix["plate"] is None or ix["importe"] is None or ix["litros"] is None:
        return None
    if ix["dto"] is None:   # la columna del descuento trae el simbolo del euro y puede llegar con otra codificacion
        ix["dto"] = next((j for j, n in enumerate(nombres) if "dto" in n), None)
    acumulado = {}
    for fila in filas[cabecera + 1:]:
        if not fila or ix["plate"] >= len(fila):
            continue
        placa = matricula(fila[ix["plate"]])
        if not placa:
            continue
        x = acumulado.setdefault(placa, {"plate": placa, "importe": 0.0, "litros": 0.0, "operaciones": 0, "descuento": 0.0})
        x["importe"] += numero(fila[ix["importe"]]) or 0.0
        x["litros"] += numero(fila[ix["litros"]]) or 0.0
        if ix["ops"] is not None and ix["ops"] < len(fila):
            x["operaciones"] += int(numero(fila[ix["ops"]]) or 0)
        if ix["dto"] is not None and ix["dto"] < len(fila):
            x["descuento"] += numero(fila[ix["dto"]]) or 0.0
    if not acumulado:
        return None
    filas_out = [{k: (round(v, 2) if isinstance(v, float) else v) for k, v in x.items()} for x in acumulado.values()]
    return {"nif": nif, "desde": desde, "hasta": hasta, "filas": sorted(filas_out, key=lambda r: -r["importe"])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--roots", nargs="+", required=True, help="Carpetas donde buscar vehiculos*.xlsx (buzon de carburantes)")
    ap.add_argument("--output", required=True)
    a = ap.parse_args()
    encontrados = {}
    for raiz in a.roots:
        for base, _, ficheros in os.walk(raiz):
            for nombre in ficheros:
                limpio = sin_tildes(nombre)
                if not (limpio.endswith(".xlsx") and limpio.startswith("veh")):
                    continue
                ruta = os.path.join(base, nombre)
                try:
                    informe = leer(ruta)
                except Exception as e:   # noqa: BLE001
                    print("AVISO: no se pudo leer %s (%s)" % (nombre, e), file=sys.stderr)
                    continue
                if not informe:
                    continue
                informe["fichero"] = nombre
                informe["modificado"] = datetime.datetime.fromtimestamp(os.path.getmtime(ruta)).isoformat(timespec="seconds")
                clave = (informe["nif"], informe["desde"], informe["hasta"])
                if clave not in encontrados or encontrados[clave]["modificado"] < informe["modificado"]:
                    encontrados[clave] = informe
    informes = sorted(encontrados.values(), key=lambda i: (i["nif"] or "", i["desde"]))
    meta = {"disponible": bool(informes), "informes": len(informes), "leido": datetime.datetime.now().isoformat(timespec="seconds")}
    if not informes:
        meta["aviso"] = "No hay informes de vehiculos de Solred en " + "; ".join(a.roots)
    with open(a.output, "w", encoding="utf-8") as f:
        json.dump({"metadata": meta, "informes": informes}, f, ensure_ascii=False)
    print(json.dumps({"disponible": meta["disponible"], "informes": [{"nif": i["nif"], "desde": i["desde"], "hasta": i["hasta"], "matriculas": len(i["filas"]), "litros": round(sum(r["litros"] for r in i["filas"])), "importe": round(sum(r["importe"] for r in i["filas"]), 2)} for i in informes]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
