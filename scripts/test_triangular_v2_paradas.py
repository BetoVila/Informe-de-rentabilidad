import datetime as dt
import unittest
import triangular_v2 as t2


def ep(s):
    return int(dt.datetime.fromisoformat(s).replace(tzinfo=dt.timezone.utc).timestamp())


def tramo(t0, minutos, lat0, lat1, vel):
    """Un punto por minuto de lat0 a lat1 (lon -8) a velocidad vel."""
    return [{'t': t0 + m*60, 'f': 'wialon', 's': vel, 'lat': lat0 + (lat1 - lat0)*m/max(1, minutos - 1), 'lon': -8.0,
             'kmc': None, 'litc': None, 'rec': None, 'parada_min': None} for m in range(minutos)]


class TestParadasSinSenal(unittest.TestCase):
    def test_hueco_sin_senal_corta_la_parada_pero_no_el_descanso(self):
        # parado 60 min, 2 h sin posicion y otros 60 min en el mismo sitio
        t = ep('2026-09-20T08:00')
        pts = tramo(t, 60, 43.0, 43.0, 0) + tramo(t + 180*60, 60, 43.0, 43.0, 0)
        par = t2.paradas_flujo(pts)
        self.assertEqual([(p['t_in'], p['t_out']) for p in par], [(t, t + 59*60), (t + 180*60, t + 239*60)])
        rep = t2.paradas_flujo(pts, None)
        self.assertEqual([(p['t_in'], p['t_out']) for p in rep], [(t, t + 239*60)])

    def test_dias_sin_senal_y_otro_sitio_son_dos_paradas(self):
        # caso real 1895CNR 09/01/2026: parado en la planta, seis dias sin señal y reaparece parado a 17 km
        t = ep('2026-01-09T18:00')
        pts = tramo(t, 60, 43.0, 43.0, 0) + tramo(ep('2026-01-16T07:00'), 60, 43.157, 43.157, 0)
        par = t2.paradas_flujo(pts)
        self.assertEqual(len(par), 2)
        self.assertAlmostEqual(par[0]['lat'], 43.0)
        self.assertAlmostEqual(par[1]['lat'], 43.157)
        self.assertEqual(par[0]['t_out'] - par[0]['t_in'], 59 * 60)

    def test_ruido_del_gps_sin_hueco_no_parte_la_parada(self):
        # caso real 5003MBV 07/08/2026: parado, el GPS salta cada minuto entre dos puntos a 0,4 km
        t = ep('2026-08-07T17:10')
        pts = [dict(q, lat=43.0 + (0.0036 if k % 2 else 0.0)) for k, q in enumerate(tramo(t, 120, 43.0, 43.0, 0))]
        for hueco in (t2.HUECO_S, None):
            par = t2.paradas_flujo(pts, hueco)
            self.assertEqual([(p['t_in'], p['t_out']) for p in par], [(t, t + 119 * 60)])


class TestJornadaNoArrancaEnElHueco(unittest.TestCase):
    def test_descanso_de_dias_con_un_dia_sin_datos_dentro(self):
        # caso real 0063NBM: aparca el 22/08 18:15, no hay datos del 23, el 24 00:04 vuelve la señal (parado en el mismo
        # sitio) y arranca el 25 a las 11:59. La jornada del 25 empezaba el 24 a las 00:04 (37 h de «espera» en el viaje).
        t22 = ep('2025-08-22T17:15')
        pts = (tramo(t22, 60, 43.2, 43.3, 40) + tramo(ep('2025-08-22T18:15'), 345, 43.3, 43.3, 0)
               + tramo(ep('2025-08-24T00:04'), 2154, 43.3, 43.3, 0) + tramo(ep('2025-08-25T11:58'), 60, 43.3, 43.2, 40))
        jor = t2.jornadas_de(pts, t2.paradas_flujo(pts), 8 * 3600)
        self.assertEqual(len(jor), 2)
        self.assertEqual(jor[1]['ini'], ep('2025-08-25T11:58'))
        self.assertEqual(jor[1]['c0'], ep('2025-08-25T11:57'))
        self.assertEqual(jor[0]['c1'], ep('2025-08-22T18:15'))
        # la parada de dias no entra como parada de ninguna jornada
        self.assertTrue(all(p['t_out'] - p['t_in'] < 8 * 3600 for j in jor for p in j['paradas']))


class TestMotorPorCargaNoPorCamion(unittest.TestCase):
    # Roberto 28/09/2026: «tienes que diferenciar por la carga, lo que es arido y lo que es hormigon», no por el camion
    # entero. Caso real que motivo el cambio: 6081FHD es hormigonera (73% de sus cargas historicas), pero una carga suelta
    # de aridos a otra planta (viaje 00024326, cantera 5063) le salia con el "obra" del motor de hormigon fabricado.
    def ticket(self, mat, dia, horm):
        return {"mat": mat, "dia": dia, "horm": horm}

    def test_dia_de_aridos_de_un_camion_mayoritariamente_hormigonera_va_por_aridos(self):
        dem = ([self.ticket("6081FHD", "2026-01-05", True)] * 9 + [self.ticket("6081FHD", "2026-01-05", False)] * 3
               + [self.ticket("6081FHD", "2026-06-10", False)])
        dia_hormigon, es_hormigonera = t2.clasificar_motor_por_dia(dem)
        self.assertIn("6081FHD", es_hormigonera, "el camion sigue siendo hormigonera en su historico (9 de 13, 69%)")
        self.assertIn(("6081FHD", "2026-01-05"), dia_hormigon, "ese dia concreto tambien es mayoria hormigon (9 de 12)")
        self.assertNotIn(("6081FHD", "2026-06-10"), dia_hormigon,
                          "el dia suelto de aridos (100% arido ese dia) ya NO va por el motor de hormigon")

    def test_dia_mayoria_aridos_de_camion_hormigonera_va_por_aridos_aunque_el_historico_sea_hormigon(self):
        dem = [self.ticket("6081FHD", "2026-02-02", True)] * 8 + [self.ticket("6081FHD", "2026-02-02", False)] * 2
        dia_hormigon, es_hormigonera = t2.clasificar_motor_por_dia(dem)
        self.assertIn("6081FHD", es_hormigonera)
        self.assertIn(("6081FHD", "2026-02-02"), dia_hormigon, "ese dia es 80% hormigon: sigue yendo por hormigon")

    def test_camion_mayoria_aridos_con_un_dia_de_hormigon_va_ese_dia_por_hormigon(self):
        dem = ([self.ticket("2839FKP", "2026-03-01", False)] * 20
               + [self.ticket("2839FKP", "2026-03-15", True)] * 2)
        dia_hormigon, es_hormigonera = t2.clasificar_motor_por_dia(dem)
        self.assertNotIn("2839FKP", es_hormigonera, "camion basicamente de aridos (20 de 22, 91%)")
        self.assertNotIn(("2839FKP", "2026-03-01"), dia_hormigon)
        self.assertIn(("2839FKP", "2026-03-15"), dia_hormigon, "el dia suelto de hormigon va por su motor aunque el camion no sea hormigonera")


class TestRotuloCargaDescarga(unittest.TestCase):
    coords = {('Razo', 'SABO'): {'lat': 43.0, 'lon': -8.0, 'fuente': 'gesruta'}}

    def test_el_lugar_del_albaran_solo_si_la_parada_cae_en_su_radio(self):
        cercano = lambda lat, lon: 'DORNEDA'  # noqa: E731
        self.assertEqual(t2.rotulo_en_lugar({'lat': 43.001, 'lon': -8.0}, 'SABO', self.coords, 'Razo', cercano), 'SABO')
        # hormigon: el albaran repite la planta como destino y el GPS descarga a 14 km
        self.assertEqual(t2.rotulo_en_lugar({'lat': 43.126, 'lon': -8.0}, 'SABO', self.coords, 'Razo', cercano), 'DORNEDA')
        self.assertIsNone(t2.rotulo_en_lugar({'lat': 43.126, 'lon': -8.0}, 'SABO', self.coords, 'Razo', lambda la, lo: None))

    def test_sin_coordenadas_del_lugar_no_se_da_por_bueno(self):
        self.assertEqual(t2.rotulo_en_lugar({'lat': 43.0, 'lon': -8.0}, 'XXX', self.coords, 'Razo', lambda la, lo: 'SABO'), 'SABO')
        self.assertIsNone(t2.rotulo_en_lugar({'lat': 43.0, 'lon': -8.0}, 'XXX', {}, 'Razo', lambda la, lo: None))


if __name__ == '__main__':
    unittest.main()
