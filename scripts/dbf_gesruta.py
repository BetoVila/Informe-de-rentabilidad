# -*- coding: utf-8 -*-
"""Lector de DBF de Visual FoxPro. **SOLO LECTURA, SIEMPRE.**

GesRuta es el sistema con el que Roberto factura hoy. Aquí no se escribe ni un
byte: se abre el fichero en modo binario de lectura, se lee la cabecera, se
recorren los registros y se cierra. No se instala nada (nada de ``dbfread`` ni
``pandas``): el formato está documentado y cabe en doscientas líneas.

Tres cosas que hay que saber del formato y que están resueltas aquí:

* **cp1252**: los nombres gallegos llevan eñes y acentos. Con UTF-8 salen rotos.
* **Los memos viven en el ``.fpt``**, no en el ``.dbf``: el campo de tipo ``M``
  guarda un número de bloque de 4 bytes, no el texto. Sin leer el ``.fpt``, las
  observaciones de los albaranes llegarían como basura binaria.
* **El borrado de FoxPro es lógico**: el primer byte del registro vale ``*``.
  Esos registros existen físicamente pero no cuentan, y por defecto se saltan.

Mayúsculas y minúsculas: ``EMPTR21`` guarda los ficheros en MAYÚSCULAS y
``EMPAG21`` en minúsculas. ``abrir()`` prueba las dos formas.
"""

import datetime
import os
import struct


class DBF(object):
    """Un fichero DBF abierto para leer. Se usa como contexto o suelto."""

    def __init__(self, ruta, encoding="cp1252"):
        self.ruta = ruta
        self.encoding = encoding
        self.f = open(ruta, "rb")
        cabecera = self.f.read(32)
        self.version = cabecera[0]
        self.numrec = struct.unpack("<I", cabecera[4:8])[0]
        self.headerlen = struct.unpack("<H", cabecera[8:10])[0]
        self.reclen = struct.unpack("<H", cabecera[10:12])[0]

        self.fields = []
        pos = 32
        while pos < self.headerlen:
            self.f.seek(pos)
            b = self.f.read(32)
            if not b or b[0] in (0x0D, 0x00):
                break
            nombre = b[0:11].split(b"\x00")[0].decode("ascii", "replace")
            self.fields.append((nombre, chr(b[11]), b[16], b[17]))
            pos += 32

        self.offsets = {}
        off = 1  # el byte 0 es la marca de borrado
        for (n, t, l, d) in self.fields:
            self.offsets[n] = (off, l, t, d)
            off += l

        # ---- memos: .fpt, y también .frt / .sct / .mnt ---------------------
        #
        # QUÉ PASABA (25/08/2026, y tenía 1.752 informes detrás). Aquí sólo se
        # buscaba `.fpt`, que es la extensión del memo de una TABLA. Pero en
        # Visual FoxPro los informes, las pantallas y los menús **también son
        # tablas DBF**, y su memo lleva otra extensión:
        #
        #     tabla    .dbf  ->  .fpt
        #     informe  .frx  ->  .frt      <-- éste faltaba
        #     pantalla .scx  ->  .sct
        #     menú     .mnx  ->  .mnt
        #
        # Y todo el contenido de verdad de un informe vive en el memo: los
        # campos `EXPR`, `NAME`, `STYLE`, `PICTURE` y `COMMENT` son de tipo M,
        # o sea que en el `.frx` sólo hay un número de bloque de 4 bytes. Sin
        # el memo, un informe se leía **entero y vacío**: 144 filas, las bandas
        # bien contadas, y ni una sola expresión. Parecía que el informe no
        # tenía nada dentro, cuando lo tenía todo.
        #
        # Es la avería de la casa otra vez —parece hecho, no da error y no dice
        # nada—, y aquí la coartada era perfecta: el fichero abría, las filas
        # salían y los recuentos cuadraban.
        self._fpt = None
        self._fpt_bloque = 64
        raiz, propia = os.path.splitext(ruta)
        # El memo que toca según lo que se esté abriendo, y detrás los demás
        # por si alguien renombra un fichero.
        pareja = {".frx": ".frt", ".scx": ".sct", ".mnx": ".mnt",
                  ".vcx": ".vct", ".dbc": ".dct", ".pjx": ".pjt"}
        preferida = pareja.get(propia.lower(), ".fpt")
        candidatas = [preferida, preferida.upper()]
        for otra in (".fpt", ".frt", ".sct", ".mnt", ".vct", ".dct", ".pjt"):
            candidatas += [otra, otra.upper()]
        for ext in candidatas:
            candidato = raiz + ext
            if os.path.exists(candidato):
                self._fpt = open(candidato, "rb")
                cab = self._fpt.read(8)
                if len(cab) == 8:
                    self._fpt_bloque = struct.unpack(">H", cab[6:8])[0] or 64
                break

    # ------------------------------------------------------------------
    def cerrar(self):
        try:
            self.f.close()
        finally:
            if self._fpt:
                self._fpt.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.cerrar()

    def nombres(self):
        return [f[0] for f in self.fields]

    def tiene(self, nombre):
        return nombre in self.offsets

    # ------------------------------------------------------------------
    def registros(self, saltar_borrados=True):
        """Recorre el fichero entero. Devuelve los bytes crudos de cada fila."""
        self.f.seek(self.headerlen)
        for _ in range(self.numrec):
            rec = self.f.read(self.reclen)
            if len(rec) < self.reclen:
                break
            if saltar_borrados and rec[0:1] == b"*":
                continue
            yield rec

    # ------------------------------------------------------------------
    def _memo(self, bloque):
        if not self._fpt or not bloque:
            return ""
        try:
            self._fpt.seek(bloque * self._fpt_bloque)
            cab = self._fpt.read(8)
            if len(cab) < 8:
                return ""
            _tipo, largo = struct.unpack(">II", cab)
            if largo <= 0 or largo > 5_000_000:
                return ""
            texto = self._fpt.read(largo).decode(self.encoding, "replace")
            # Los memos de FoxPro traen NUL de relleno. PostgreSQL rechaza en
            # seco cualquier cadena con 0x00, así que si no se limpian aquí el
            # albarán entero se cae al insertarlo (pasó de verdad: el
            # 00017838:01 de Razo).
            return texto.replace("\x00", " ")
        except (OSError, ValueError, struct.error):
            return ""

    def get(self, rec, nombre):
        if nombre not in self.offsets:
            return None
        off, largo, tipo, dec = self.offsets[nombre]
        crudo = rec[off:off + largo]
        if tipo == "C":
            return crudo.decode(self.encoding, "replace").replace("\x00", " ").strip()
        if tipo == "M":
            if largo == 4:
                bloque = struct.unpack("<I", crudo)[0]
            else:
                texto = crudo.decode("ascii", "replace").strip()
                bloque = int(texto) if texto.isdigit() else 0
            return self._memo(bloque)
        if tipo in ("N", "F"):
            s = crudo.decode("ascii", "replace").strip()
            if not s:
                return None
            try:
                return float(s)
            except ValueError:
                return None
        if tipo == "D":
            s = crudo.decode("ascii", "replace").strip()
            if len(s) == 8 and s.isdigit() and s != "00000000":
                try:
                    return datetime.date(int(s[:4]), int(s[4:6]), int(s[6:]))
                except ValueError:
                    return None
            return None
        if tipo == "L":
            return crudo.decode("ascii", "replace").strip().upper() in ("T", "Y")
        if tipo == "I":
            return struct.unpack("<i", crudo[:4])[0]
        if tipo == "B":
            return struct.unpack("<d", crudo[:8])[0]
        if tipo == "Y":
            return struct.unpack("<q", crudo[:8])[0] / 10000.0
        if tipo == "T":
            if len(crudo) == 8:
                jd, ms = struct.unpack("<ii", crudo)
                if not jd:
                    return None
                base = datetime.date.fromordinal(jd - 1721425)
                return "%s %02d:%02d" % (base.isoformat(), ms // 3600000,
                                         (ms // 60000) % 60)
            return None
        return None

    def fila(self, rec, campos=None):
        return {c: self.get(rec, c) for c in (campos or self.nombres())}


def abrir(base, nombre):
    """Abre una tabla probando MAYÚSCULAS y minúsculas.

    ``EMPTR21`` las guarda en mayúsculas y ``EMPAG21`` en minúsculas; el mismo
    guion tiene que servir para las dos.
    """
    for candidato in (nombre, nombre.upper(), nombre.lower()):
        ruta = os.path.join(base, candidato)
        if os.path.exists(ruta):
            return DBF(ruta)
    raise IOError("No encuentro %s en %s" % (nombre, base))
