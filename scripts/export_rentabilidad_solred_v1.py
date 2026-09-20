# -*- coding: utf-8 -*-
"""Lectura del gasto real de combustible en Solred, tal como llega a la
flota (ficheros 'Operaciones AAAAMM.txt' de ancho fijo junto a la tarjeta,
que Roberto baja a mano de Mi Solred y deja en Analizador Carburantes).

FUENTE DEL MAPA DE COLUMNAS: el formato no lo documenta Solred. El mapa y
las dos trampas de abajo vienen ya cazadas y verificadas contra datos reales
en P:\\Analizador Carburantes\\flota.py (programa hermano, no relacionado con
el ERP). No se importa ese fichero desde aqui -este paquete se queda
autonomo, igual que dbf_gesruta.py no depende de GesRuta- pero el mapa es el
mismo a proposito, para no tener DOS lecturas distintas del mismo formato
sin documentar:

* LOS LITROS LLEVAN UN SOLO DECIMAL (columnas 279-284), no dos. Con dos
  decimales todo parece cuadrar pero el consumo sale diez veces menor.
* El NETO (347-358) es lo que se paga de verdad; BRUTO (288-299) es precio
  de surtidor y DESCUENTO (340-347) va aparte. bruto-descuento=neto se
  cumple en el 100% de las lineas reales (comprobado).

SOLO LECTURA. No se toca ningun fichero de Analizador Carburantes ni de
Solred. Si la carpeta no existe (Analizador Carburantes movido, desinstalado
o no presente en este SERVIDOR), esto NO aborta el informe de Rentabilidad:
se marca la fuente como no disponible y el resto del informe sigue con
GesRuta+Access, igual que hasta ahora. Solred es un cruce adicional, no un
cimiento.
"""
import argparse
import datetime as dt
import glob
import json
import os
import re

parser = argparse.ArgumentParser()
parser.add_argument("--root", required=True,
                     help=r"Carpeta datos\repostajes de Analizador Carburantes")
parser.add_argument("--output", required=True)
parser.add_argument("--from-date", default="2025-01-01")
parser.add_argument("--to-date", default=(dt.date.today() - dt.timedelta(days=1)).isoformat())
args = parser.parse_args()
START, END = args.from_date, args.to_date

# Mismas columnas que flota.py (verificadas contra datos reales, no a ojo).
COL = {
    "operacion": (205, 212), "vehiculo": (175, 190), "fecha": (212, 220),
    "hora": (220, 224), "estacion": (224, 244), "producto": (269, 279),
    "litros": (279, 284), "bruto": (288, 299), "descuento": (340, 347),
    "neto": (347, 358),
}
# Solo lo que es coste de combustible de flota; peajes/lavados/aparcamiento
# (que el fichero de Solred tambien trae) no son gasoil y no se mezclan aqui.
FAMILIA = {
    "DIE E+": "gasoleo", "DIE E+10": "gasoleo", "DIESEL": "gasoleo",
    "ADB+GRN": "adblue", "ADBLUE": "adblue",
}
MATRICULA = re.compile(r"(\d{4}[A-Z]{3})$")


def matricula(bruto):
    limpio = (bruto or "").strip().replace("-", "").replace(" ", "").upper()
    m = MATRICULA.search(limpio)
    return None if not m else m.group(1)[:4] + " " + m.group(1)[4:]


def _n(s):
    s = s.strip()
    return int(s) if s.isdigit() else 0


def leer(root):
    filas = []
    vistas = set()
    ficheros = []
    for ruta in sorted(glob.glob(os.path.join(root, "*.txt"))):
        stamp = os.stat(ruta).st_mtime_ns
        ficheros.append({"path": ruta,
                          "modified": dt.datetime.fromtimestamp(stamp / 1e9).astimezone().isoformat()})
        with open(ruta, encoding="latin-1") as fh:
            for linea in fh:
                linea = linea.rstrip("\n")
                if len(linea) < 372:
                    continue
                g = {k: linea[a:b] for k, (a, b) in COL.items()}
                prod = g["producto"].strip()
                familia = FAMILIA.get(prod) or FAMILIA.get(prod[:8])
                if familia is None:
                    continue
                f = g["fecha"].strip()
                if not (len(f) == 8 and f.isdigit()):
                    continue
                fecha_iso = "%s-%s-%s" % (f[:4], f[4:6], f[6:])
                if not (START <= fecha_iso <= END):
                    continue
                clave = (g["operacion"].strip(), f, g["hora"], g["litros"], g["bruto"])
                if clave in vistas:
                    continue
                vistas.add(clave)
                filas.append({
                    "vehiculo": matricula(g["vehiculo"]),
                    "fecha": fecha_iso,
                    "hora": g["hora"].strip(),
                    "estacion": g["estacion"].strip(),
                    "familia": familia,
                    "litros": round(_n(g["litros"]) / 10.0, 1),
                    "bruto": round(_n(g["bruto"]) / 100.0, 2),
                    "descuento": round(_n(g["descuento"]) / 100.0, 2),
                    "neto": round(_n(g["neto"]) / 100.0, 2),
                })
    return filas, ficheros


if not os.path.isdir(args.root):
    result = {
        "metadata": {"desde": START, "hasta": END,
                     "read_at": dt.datetime.now().astimezone().isoformat(),
                     "disponible": False,
                     "aviso": "No se encuentra la carpeta de Analizador Carburantes: " + args.root},
        "rows": [], "files": [],
    }
else:
    filas, ficheros = leer(args.root)
    sin_matricula = sum(1 for r in filas if not r["vehiculo"])
    # Comprobacion bruto-descuento=neto (la misma que confirma que las tres
    # columnas son las que son). Si falla en mas de una linea suelta de
    # redondeo, el mapa de columnas ya no vale y hay que avisar, no publicar.
    descuadres = sum(1 for r in filas if abs(r["bruto"] - r["descuento"] - r["neto"]) > 0.02)
    result = {
        "metadata": {"desde": START, "hasta": END,
                     "read_at": dt.datetime.now().astimezone().isoformat(),
                     "disponible": True,
                     "sin_matricula": sin_matricula,
                     "descuadres_bruto_neto": descuadres},
        "rows": filas, "files": ficheros,
    }

with open(args.output, "w", encoding="utf-8") as fh:
    json.dump(result, fh, ensure_ascii=False, separators=(",", ":"))

resumen = {"disponible": result["metadata"]["disponible"], "filas": len(result["rows"]),
           "output": args.output}
if result["metadata"]["disponible"]:
    resumen["sin_matricula"] = result["metadata"]["sin_matricula"]
    resumen["descuadres_bruto_neto"] = result["metadata"]["descuadres_bruto_neto"]
print(json.dumps(resumen, ensure_ascii=False))
