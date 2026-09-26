import datetime as dt
import json
import unittest
from unittest.mock import patch
import ver_dia_mapa as mapa


def puntos():
    start = int(dt.datetime(2026, 9, 20, 8).timestamp())
    return [{'t': start + d*86400 + m*60, 'f': 'wialon', 's': 40 if m < 30 else 0,
             'lat': 43+m/10000, 'lon': -8, 'ign': 1} for d in range(3) for m in range(60)]


def datos(html):
    """Los datos que pinta la pagina (META, V, L0, P, J, H)."""
    dec = json.JSONDecoder()
    j = html.index('const META=') + len('const META=')
    out = {}
    out['META'], j = dec.raw_decode(html, j)
    for clave in ('V', 'L0', 'P', 'J', 'H'):
        pre = ',%s=' % clave
        assert html[j:j + len(pre)] == pre, clave
        out[clave], j = dec.raw_decode(html, j + len(pre))
    return out


def tramo(t0, minutos, lat0, lat1, vel):
    """Un punto por minuto de lat0 a lat1 (lon -8) a velocidad vel."""
    return [{'t': t0 + m*60, 'f': 'wialon', 's': vel, 'lat': lat0 + (lat1 - lat0)*m/max(1, minutos - 1), 'lon': -8.0}
            for m in range(minutos)]


class TestParadasSinSenal(unittest.TestCase):
    def test_un_hueco_de_dias_no_es_una_parada_de_9565_min(self):
        # caso real 1895CNR 09/01/2026: parado en la planta hasta las 19:39, sin señal seis dias, reaparece a 17 km
        t = mapa.ep('2026-09-20T08:00')
        pts = (tramo(t, 30, 43.0, 43.02, 40) + tramo(t + 30*60, 91, 43.02, 43.02, 0)
               + tramo(mapa.ep('2026-09-26T00:00'), 528, 43.17, 43.17, 0) + tramo(mapa.ep('2026-09-26T08:48'), 20, 43.17, 43.25, 40))
        r = mapa.render_dia('PRUEBA', '2026-09-20', [], pts, None, 8*3600, 120)
        d = datos(r[0])
        paradas = [p for p in d['P'] if p[2] >= t]
        self.assertTrue(paradas, 'la parada de la tarde sale')
        self.assertTrue(all(p[5] <= 24*60 for p in d['P']), 'ninguna parada del dia dura mas que el dia')
        tarde = max(paradas, key=lambda p: p[5])
        self.assertEqual(tarde[5], 90)                                       # 08:30 -> 10:00, lo que se vio parado
        self.assertAlmostEqual(tarde[0], 43.02, places=3)                    # en la planta, no donde reaparece
        self.assertEqual(len(d['H']), 1)
        self.assertIn('días', d['H'][0][3])
        self.assertIn('vuelve a dar posición a 16', d['H'][0][4])            # 0,15 grados de latitud = 16,7 km


class TestCargaDescargaPorGps(unittest.TestCase):
    def setUp(self):
        nombres = {'PLANT': {'nom': 'PLANTA X', 'loc': '', 'pro': ''}}
        coords = {('Razo', 'PLANT'): {'lat': 43.0, 'lon': -8.0, 'fuente': 'gesruta'},
                  ('Razo', 'OBRA1'): {'lat': 43.1, 'lon': -8.0, 'fuente': 'gesruta', 'nombre': 'OBRA UNO'}}
        self.lug = mapa.Lugares(nombres, coords)

    def test_hormigon_planta_a_planta_descarga_donde_la_ve_el_gps(self):
        t = mapa.ep('2026-09-20T08:00')
        pts = (tramo(t, 11, 43.0, 43.0, 0) + tramo(t + 11*60, 19, 43.0, 43.1, 40) + tramo(t + 30*60, 21, 43.1, 43.1, 0)
               + tramo(t + 51*60, 19, 43.1, 43.0, 40) + tramo(t + 70*60, 11, 43.0, 43.0, 0))
        viaje = {'empresa': 'Razo', 'cantera': '1', 'origen': 'PLANT', 'destino': 'PLANT', 'orden_dia': 1,
                 't_ini': '2026-09-20T08:00', 't_fin': '2026-09-20T09:10', 't_carga': '2026-09-20T08:00', 't_carga_fin': '2026-09-20T08:10',
                 't_descarga': '2026-09-20T08:30', 't_descarga_fin': '2026-09-20T08:50', 'km': 25.0, 'km_cargado': 11.0, 'km_vacio': 13.7,
                 'duracion_min': 70, 'metodo': 'geo', 'confianza': 'media', 'motivo': None}
        d = datos(mapa.render_dia('PRUEBA', '2026-09-20', [viaje], pts, None, 8*3600, 120, self.lug)[0])
        v = d['V'][0]
        self.assertEqual((v['on'], v['dn'], v['mismo']), ('PLANTA X', 'PLANTA X', True))   # el albarán, tal cual
        self.assertEqual(v['cl'], 'PLANTA X')                                  # la carga cae en la planta: confirmada
        self.assertEqual(v['dl'], 'OBRA UNO')                                  # la descarga, donde la ve el GPS
        self.assertIsNone(v['dkm'])                                            # no se compara con un destino que no lo es
        self.assertAlmostEqual(v['dc'], 11.1, delta=0.2)                       # en recta de la carga: no 0,0
        self.assertEqual(v['sc'], 0.3)                                         # 25,0 - 11,0 - 13,7: sin clasificar a la vista
        descargas = [p for p in d['P'] if p[9] == 'descarga']
        self.assertTrue(descargas and all(p[8] == 'OBRA UNO' for p in descargas))

    def test_carga_lejos_del_lugar_del_albaran_no_se_da_por_buena(self):
        nombre, ok, km = self.lug.sitio([43.045, -8.0], 'Razo', 'PLANT')
        self.assertFalse(ok)
        self.assertNotEqual(nombre, 'PLANTA X')
        self.assertAlmostEqual(km, 5.0, delta=0.1)


class TestMapaTemporal(unittest.TestCase):
    def test_reutiliza_jornadas_y_conserva_el_html_de_cada_dia(self):
        pts = puntos()
        ctx = mapa.preparar_flujo(pts, 8*3600)
        expected = [mapa.render_dia('PRUEBA', '2026-09-%02d' % d, [], pts, None, 8*3600, 120) for d in (20,21,22)]
        with patch.object(mapa.t2, 'paradas_flujo', side_effect=AssertionError('No debe recalcular')):
            result = [mapa.render_dia('PRUEBA', '2026-09-%02d' % d, [], pts, None, 8*3600, 120, contexto=ctx) for d in (20,21,22)]
        self.assertEqual(result, expected)
        self.assertTrue(all(x and x[0] for x in result))

    def test_sin_traza_no_inventa_un_mapa(self):
        self.assertIsNone(mapa.render_dia('PRUEBA', '2026-09-20', [], [], None, 8*3600, 120))


if __name__ == '__main__':
    unittest.main()
