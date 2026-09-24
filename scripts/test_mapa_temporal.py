import datetime as dt
import unittest
from unittest.mock import patch
import ver_dia_mapa as mapa


def puntos():
    start = int(dt.datetime(2026, 9, 20, 8).timestamp())
    return [{'t': start + d*86400 + m*60, 'f': 'wialon', 's': 40 if m < 30 else 0,
             'lat': 43+m/10000, 'lon': -8, 'ign': 1} for d in range(3) for m in range(60)]


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
