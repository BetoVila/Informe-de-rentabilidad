# -*- coding: utf-8 -*-
"""Sirve por http las apps publicadas en \\SERVIDOR\\Programas (informe de rentabilidad, tarifas, tacógrafo, carburantes)
para abrirlas «en vivo» con herramientas que no abren ficheros locales ni rutas de red (Codex, navegadores automáticos).

Roberto 24/09/2026: «las apps se pueden abrir en formato http o https? si se puede hazlo para que codex pueda acceder en
vivo, sus herramientas no le dejan abrirlo así como está».

- SOLO LECTURA: GET y HEAD. Nada se escribe en las carpetas publicadas.
- EN VIVO: cada petición lee el fichero del disco, así que siempre se ve la última versión publicada (las nocturnas
  sustituyen los ficheros de forma atómica).
- SOLO ESTE PC por defecto (127.0.0.1). RAZO_APPS_HOST=0.0.0.0 lo abre a la red de la oficina; RAZO_APPS_PORT cambia el
  puerto (8710 por defecto).
- Sin listados de carpetas: solo se sirven ficheros que existen dentro de la carpeta de cada app (no se puede salir de ella).
- Si el puerto ya está ocupado (otra copia en marcha), sale sin error: la tarea programada lo relanza cada pocos minutos y
  así, si el servidor se cae, vuelve solo.

Direcciones: http://127.0.0.1:8710/ (índice) · /rentabilidad/ · /tarifas/ · /tacografo/ · /carburantes/ · /estado.json
"""
import errno, html, http.server, json, mimetypes, os, shutil, socket, sys, time, urllib.parse

APPS = {  # ruta -> (carpeta publicada, página de inicio, nombre)
    "rentabilidad": (r"\\SERVIDOR\Programas\_RENTABILIDAD", "informe.html", "Informe de rentabilidad"),
    "tarifas": (r"\\SERVIDOR\Programas\_TARIFAS", "Tarifas-Razo.html", "Analizador de tarifas"),
    "tacografo": (r"\\SERVIDOR\Programas\_TACOGRAFO", "panel_tacografo.html", "Panel del tacógrafo"),
    "carburantes": (r"\\SERVIDOR\Programas\Analizador Carburantes", "analizador.html", "Analizador de carburantes"),
}
HOST = os.environ.get("RAZO_APPS_HOST", "127.0.0.1")
PORT = int(os.environ.get("RAZO_APPS_PORT", "8710"))
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "servir_apps.log")
TIPOS = {".mjs": "text/javascript", ".js": "text/javascript", ".json": "application/json", ".gz": "application/gzip",
         ".jsonl": "application/x-ndjson", ".csv": "text/csv", ".svg": "image/svg+xml", ".ico": "image/x-icon",
         ".html": "text/html", ".htm": "text/html", ".css": "text/css", ".txt": "text/plain", ".md": "text/markdown",
         ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".pdf": "application/pdf",
         ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


def anota(msg):
    try:
        if os.path.exists(LOG) and os.path.getsize(LOG) > 2_000_000:   # registro corto: se rota al pasar de 2 MB
            os.replace(LOG, LOG + ".1")
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except OSError:
        pass


def fecha(p):
    try:
        return time.strftime("%d/%m/%Y %H:%M", time.localtime(os.path.getmtime(p)))
    except OSError:
        return None


def dentro(base, rel):
    """Ruta absoluta de rel dentro de base, o None si se sale de la carpeta."""
    base_n = os.path.normcase(os.path.normpath(base))
    ruta = os.path.normpath(os.path.join(base, rel))
    if os.path.normcase(ruta) != base_n and not os.path.normcase(ruta).startswith(base_n + os.sep):
        return None
    return ruta


class Manejador(http.server.BaseHTTPRequestHandler):
    server_version = "RazoApps/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):   # al registro propio, no a la consola
        anota("%s %s" % (self.address_string(), fmt % args))

    def _cabeceras(self, codigo, tipo, largo, extra=None):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(largo))
        self.send_header("Cache-Control", "no-store")          # en vivo: nada de copias viejas
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()

    def _texto(self, codigo, cuerpo, tipo="text/html; charset=utf-8", cuerpo_sn=True):
        b = cuerpo.encode("utf-8")
        self._cabeceras(codigo, tipo, len(b))
        if cuerpo_sn and self.command != "HEAD":
            self.wfile.write(b)

    def _indice(self):
        filas = []
        for k, (carpeta, inicio, nombre) in APPS.items():
            f = fecha(os.path.join(carpeta, inicio))
            filas.append('<tr><td><a href="/%s/">%s</a></td><td><code>/%s/%s</code></td><td>%s</td></tr>' % (
                k, html.escape(nombre), k, html.escape(inicio), ("publicado " + f) if f else "<b>no disponible</b>"))
        return ('<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Apps de Razo</title>'
                '<style>body{font:14px system-ui,Segoe UI,sans-serif;margin:24px;color:#0f1e33}table{border-collapse:collapse}'
                'td{padding:6px 14px;border-bottom:1px solid #dde4ec}code{color:#46576c}</style></head><body>'
                '<h1>Apps de Razo y Agetrans</h1><p>En vivo desde las carpetas publicadas en <code>\\\\SERVIDOR\\Programas</code>; solo lectura.</p>'
                '<table>' + "".join(filas) + '</table><p><a href="/estado.json">estado.json</a></p></body></html>')

    def _estado(self):
        out = {"servidor": "%s:%d" % (HOST, PORT), "hora": time.strftime("%Y-%m-%dT%H:%M:%S"), "apps": {}}
        for k, (carpeta, inicio, nombre) in APPS.items():
            p = os.path.join(carpeta, inicio)
            out["apps"][k] = {"nombre": nombre, "url": "/%s/%s" % (k, inicio), "carpeta": carpeta,
                              "disponible": os.path.isfile(p), "publicado": fecha(p)}
        return json.dumps(out, ensure_ascii=False, indent=1)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        try:
            ruta = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
            partes = [p for p in ruta.split("/") if p]
            if not partes:
                return self._texto(200, self._indice())
            if partes == ["estado.json"]:
                return self._texto(200, self._estado(), "application/json; charset=utf-8")
            app = partes[0].lower()
            if app not in APPS:
                return self._texto(404, "<h1>404</h1><p>No hay ninguna app «%s». <a href=\"/\">Ver las apps</a></p>" % html.escape(partes[0]))
            carpeta, inicio, _ = APPS[app]
            if len(partes) == 1:   # /tarifas → /tarifas/Tarifas-Razo.html
                self.send_response(302)
                self.send_header("Location", "/%s/%s" % (app, urllib.parse.quote(inicio)))
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            destino = dentro(carpeta, os.path.join(*partes[1:]))
            if not destino or not os.path.isfile(destino):
                return self._texto(404, "<h1>404</h1><p>No existe ese fichero en %s. <a href=\"/%s/\">Ir a la app</a></p>" % (html.escape(APPS[app][2]), app))
            ext = os.path.splitext(destino)[1].lower()
            tipo = TIPOS.get(ext) or mimetypes.guess_type(destino)[0] or "application/octet-stream"
            if tipo.startswith("text/") or tipo in ("application/json", "text/javascript"):
                tipo += "; charset=utf-8"
            with open(destino, "rb") as f:
                largo = os.fstat(f.fileno()).st_size
                self._cabeceras(200, tipo, largo)
                if self.command != "HEAD":
                    shutil.copyfileobj(f, self.wfile, 1024 * 1024)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception as e:   # nunca se cae por una petición rara
            anota("ERROR %s: %r" % (self.path, e))
            try:
                self._texto(500, "<h1>500</h1><p>No se pudo leer el fichero.</p>")
            except Exception:
                pass

    def _no(self):
        self._texto(405, "<h1>405</h1><p>Solo lectura.</p>")

    do_POST = do_PUT = do_DELETE = do_PATCH = _no


def main():
    try:
        srv = http.server.ThreadingHTTPServer((HOST, PORT), Manejador)
    except OSError as e:
        if e.errno in (errno.EADDRINUSE, 10048) or getattr(e, "winerror", None) == 10048:
            return 0   # ya hay otra copia sirviendo: la tarea lo relanza sin duplicar
        anota("no arranca: %r" % e)
        return 1
    srv.daemon_threads = True
    anota("en marcha en http://%s:%d/" % (HOST, PORT))
    try:
        srv.serve_forever()
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
