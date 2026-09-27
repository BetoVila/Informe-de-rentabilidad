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
    # entero (primera vuelta) NI por el dia del camion (segunda vuelta: «los viajes se identifican por camion pero el
    # material es por el albaran de carga»). Cada carga corre HOY por su propio motor segun su dato UNIMED/CODCON; en un
    # dia con las dos clases, cada motor enmascara del otro el tramo de traza que ya es suyo (ventanas_de_zona/
    # enmascarar_pts/jornada_enmascarada) y fusionar_jornada junta los dos resultados en la jornada real.
    def ticket(self, mat, dia, horm):
        return {"mat": mat, "dia": dia, "horm": horm}

    def test_clasificar_vehiculo_es_solo_informativo(self):
        dem = [self.ticket("6081FHD", "2026-01-05", True)] * 9 + [self.ticket("6081FHD", "2026-01-05", False)] * 3
        es_hormigonera = t2.clasificar_vehiculo(dem)
        self.assertIn("6081FHD", es_hormigonera, "9 de 12 (75%) es mayoria hormigon en su historico")

    def test_ventanas_de_zona_detecta_la_visita_y_descarta_un_paso_suelto(self):
        casa = "Razo"
        coords = {(casa, "PLANTA"): {"lat": 43.0, "lon": -8.0, "fuente": "gesruta"}}
        t0 = 1000
        # 5 min fuera, 10 min parado en la planta (frenada), 5 min fuera otra vez: la visita real debe salir completa
        pts = ([{"t": t0 + s, "lat": 43.2, "lon": -8.0, "s": 40} for s in range(0, 300, 60)]
               + [{"t": t0 + 300 + s, "lat": 43.0, "lon": -8.0, "s": 0} for s in range(0, 600, 60)]
               + [{"t": t0 + 900 + s, "lat": 43.2, "lon": -8.0, "s": 40} for s in range(0, 300, 60)])
        ventanas = t2.ventanas_de_zona(pts, {"PLANTA"}, coords, casa)
        self.assertEqual(len(ventanas), 1)
        self.assertEqual(ventanas[0], (t0 + 300, t0 + 300 + 540))
        # un paso suelto a velocidad de carretera (1 solo punto dentro del radio, sin frenar) no cuenta como visita
        paso = [{"t": t0, "lat": 43.2, "lon": -8.0, "s": 90}, {"t": t0 + 60, "lat": 43.0, "lon": -8.0, "s": 90},
                {"t": t0 + 120, "lat": 42.8, "lon": -8.0, "s": 90}]
        self.assertEqual(t2.ventanas_de_zona(paso, {"PLANTA"}, coords, casa), [])

    def test_enmascarar_pts_quita_solo_lo_que_cae_en_la_ventana(self):
        pts = [{"t": t, "lat": 0, "lon": 0, "s": 0} for t in range(0, 100, 10)]
        out = t2.enmascarar_pts(pts, [(30, 50)])
        self.assertEqual([p["t"] for p in out], [0, 10, 20, 60, 70, 80, 90])
        self.assertEqual(t2.enmascarar_pts(pts, []), pts, "sin ventanas, no toca nada")

    def test_jornada_enmascarada_copia_sin_tocar_la_real(self):
        j = {"pts": [{"t": t, "lat": 0, "lon": 0, "s": 0} for t in range(0, 100, 10)],
             "paradas": [{"t_in": 30, "t_out": 50}, {"t_in": 70, "t_out": 80}],
             "ciclos": None, "sobrantes": [], "asignados": 0, "modo": None, "ini": 0, "fin": 100}
        jm = t2.jornada_enmascarada(j, [(30, 50)])
        self.assertEqual(len(jm["pts"]), 7, "los puntos de la ventana enmascarada se quitan de la COPIA")
        self.assertEqual(len(j["pts"]), 10, "la jornada real no se toca")
        self.assertEqual(len(jm["paradas"]), 1, "la parada dentro de la ventana enmascarada tambien se quita de la copia")
        self.assertIsNone(jm["ciclos"], "la copia arranca igual de vacia que la real: cada motor pone lo suyo")
        # sin ventanas, sigue copiando (para que cada motor escriba en SU copia y no se pisen aunque no haya nada que tapar)
        jm2 = t2.jornada_enmascarada(j, [])
        self.assertIsNot(jm2, j)
        self.assertEqual(jm2["pts"], j["pts"])

    def test_fusionar_jornada_junta_los_dos_motores_sin_perder_nada(self):
        j = {"ciclos": None, "sobrantes": [], "asignados": 0, "modo": None, "min_sobrantes": 0}
        arido = {"ciclos": [{"t0": 10, "t1": 20}], "sobrantes": [{"t0": 90, "t1": 95}], "asignados": 1, "modo": "geo", "min_sobrantes": 5.0}
        hormigon = {"ciclos": [{"t0": 30, "t1": 40}], "sobrantes": [], "asignados": 1, "modo": "plantas", "min_sobrantes": 0.0}
        t2.fusionar_jornada(j, arido)
        t2.fusionar_jornada(j, hormigon)
        self.assertEqual([c["t0"] for c in j["ciclos"]], [10, 30], "los ciclos de los dos motores, en orden")
        self.assertEqual(j["sobrantes"], [{"t0": 90, "t1": 95}])
        self.assertEqual(j["asignados"], 2)
        self.assertEqual(j["min_sobrantes"], 5.0)
        self.assertEqual(j["modo"], "geo+plantas")


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
