import bisect
import collections
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


class TestReposoContradichoPorMovimientoReal(unittest.TestCase):
    # 8026KDV, agosto 2026 (Roberto/Claude 28/09/2026): un SOLO punto Locatel con "parada_min" erroneo (3.739 min =
    # 62,3 h) afirmaba un reposo que tapaba dos jornadas reales de conduccion (~215 km GPS reales en esos dias). El
    # motor se fiaba de ese reposo sin comprobarlo: al solaparse con un hueco sin señal mas corto y posterior, el
    # cierre de la jornada quedaba con c0 (fin del reposo ancho) POR DELANTE de c1 (inicio del hueco corto) -
    # invertidos - y j["pts"] = pts[i0:i1] salia VACIA (i0 > i1): km=0 y duracion=0 en una ventana de 58 horas.
    def punto_locatel(self, t, parada_min, lat=42.21, lon=-8.65):
        return {"t": t, "f": "locatel", "s": 0.0, "lat": lat, "lon": lon, "parada_min": parada_min,
                "kmc": None, "litc": None, "rec": None}

    def test_reposo_de_un_punto_con_movimiento_real_dentro_se_descarta(self):
        t0 = ep('2026-08-03T07:00')
        bogus = self.punto_locatel(t0 + 22 * 60, 3739)  # 07:22, afirma 62,3 h de reposo
        dia1 = tramo(t0 + 23 * 60, 30, 42.0, 42.05, 40)          # 07:23-07:52, conduciendo de verdad
        dia2_ini = t0 + 23 * 60 + 29 * 60 + 9 * 3600              # 9 h reales sin señal despues de dia1
        dia2 = tramo(dia2_ini, 30, 42.05, 42.1, 40)               # tambien conduciendo de verdad
        pts = sorted([bogus] + dia1 + dia2, key=lambda q: q["t"])
        jor = t2.jornadas_de(pts, t2.paradas_flujo(pts), 8 * 3600)
        # el reposo de 62,3 h queda descartado (movimiento real dentro): dia1 y dia2 salen como DOS jornadas propias,
        # no una sola jornada de mas de 9 h fundiendo el hueco real con el reposo inventado
        self.assertEqual(len(jor), 2)
        for j in jor:
            self.assertLessEqual(j["c0"], j["c1"], "c0 nunca por delante de c1 (jornada invertida = pts vacia)")
            i0, i1 = bisect.bisect_left([q["t"] for q in pts], j["c0"]), bisect.bisect_right([q["t"] for q in pts], j["c1"])
            self.assertGreater(i1 - i0, 0, "la ventana de la jornada no debe quedar vacia")

    def test_reposo_real_sin_movimiento_dentro_no_se_toca(self):
        # caso normal (sin contradiccion): un reposo de dias genuino, sin ningun punto de movimiento dentro, se
        # mantiene igual que antes de este arreglo (no cambia el comportamiento del caso 0063NBM)
        t22 = ep('2025-08-22T17:15')
        pts = (tramo(t22, 60, 43.2, 43.3, 40) + tramo(ep('2025-08-22T18:15'), 345, 43.3, 43.3, 0)
               + tramo(ep('2025-08-24T00:04'), 2154, 43.3, 43.3, 0) + tramo(ep('2025-08-25T11:58'), 60, 43.3, 43.2, 40))
        jor = t2.jornadas_de(pts, t2.paradas_flujo(pts), 8 * 3600)
        self.assertEqual(len(jor), 2)
        self.assertEqual(jor[1]['ini'], ep('2025-08-25T11:58'))
        self.assertEqual(jor[1]['c0'], ep('2025-08-25T11:57'))
        self.assertEqual(jor[0]['c1'], ep('2025-08-22T18:15'))


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


class TestPlantaAjenaNoTapaLaObra(unittest.TestCase):
    # 1533NFJ, 21/09/2026 (Roberto/Claude 28/09/2026): la obra de entrega de esta hormigonera cae a 104-216 m de «OURAL»,
    # una planta APRENDIDA pero de otra ruta (solo 2 dias). visitas_plantas() comprobaba cada parada contra las ~20
    # plantas de TODA la flota: la obra se clasificaba como "visita a OURAL" y dejaba de estar disponible como obra
    # para ciclos_plantas(); el ciclo se quedaba sin descarga y se fundia con el vecino (07:58->13:17, 129,55 km
    # "vacio"). Arreglo: triangular_hormigon() acota `plantas` a las que este camion usa de verdad como origen (sus
    # propios albaranes), antes de pasarlas a ciclos_plantas()/cand_planta().
    casa = "Razo"
    planta_propia = ("Razo", "A")
    planta_ajena = ("Razo", "OURAL")
    coords_planta_propia = {"lat": 42.000, "lon": -8.000, "radio_m": 450}
    coords_planta_ajena = {"lat": 42.100, "lon": -8.000, "radio_m": 450}  # a la MISMA obra que visita esta hormigonera

    def ticket(self, v, cant):
        return {"c": self.casa, "o": "A", "d": "A", "horm": True, "v": v, "cant": cant, "m3": 8.0, "cargas": []}

    def jornada_dos_cargas(self):
        t0 = ep('2026-09-21T08:00')
        # tramos de movimiento antes de la 1a parada y despues de la ultima: si no, jornadas_de() (que marca ini/fin
        # por el primer/ultimo punto EN MOVIMIENTO) deja fuera la 1a y la ultima parada de j["paradas"]
        pts = (tramo(t0 - 3 * 60, 3, 41.980, 42.000, 60)
               + tramo(t0, 10, 42.000, 42.000, 0)                    # carga 1 en la planta propia
               + tramo(t0 + 10 * 60, 10, 42.000, 42.100, 60)         # va a la obra (coincide con la planta ajena)
               + tramo(t0 + 20 * 60, 15, 42.100, 42.100, 0)          # descarga 1 en la obra
               + tramo(t0 + 35 * 60, 10, 42.100, 42.000, 60)         # vuelve a la planta propia
               + tramo(t0 + 45 * 60, 10, 42.000, 42.000, 0)          # carga 2 (recarga)
               + tramo(t0 + 55 * 60, 10, 42.000, 42.100, 60)         # va otra vez a la obra
               + tramo(t0 + 65 * 60, 15, 42.100, 42.100, 0)          # descarga 2 en la obra
               + tramo(t0 + 80 * 60, 3, 42.100, 42.120, 60))
        return t2.jornadas_de(pts, t2.paradas_flujo(pts), 8 * 3600)

    def test_dos_cargas_dan_dos_ciclos_aunque_la_obra_coincida_con_otra_planta(self):
        viajes = [self.ticket('00001', '0001'), self.ticket('00001', '0002')]
        jor = self.jornada_dos_cargas()
        plantas = {self.planta_propia: dict(self.coords_planta_propia, dias=10, visitas=50),
                    self.planta_ajena: dict(self.coords_planta_ajena, dias=2, visitas=32)}
        diag = collections.Counter()
        res = t2.triangular_hormigon(viajes, jor, plantas, {}, "wialon", None, [], [], diag)
        self.assertEqual(len(res), 2)
        for r in res:
            self.assertIsNotNone(r, "las dos cargas deben quedar medidas, no sin_ciclo")
            self.assertIsNotNone(r.get("obra"), "cada ciclo debe encontrar su propia obra, no fundirse con el vecino")
            self.assertGreaterEqual(r["duracion_min"], t2.MIN_MIN_CICLO)
        # las dos cargas van a ciclos DISTINTOS (nunca al mismo, que seria la señal de la fusion)
        self.assertNotEqual(res[0]["t_ini"], res[1]["t_ini"])

    def test_sin_la_planta_ajena_da_el_mismo_resultado(self):
        # la planta ajena no deberia cambiar nada: es solo ruido que el acotado por camion debe neutralizar
        viajes = [self.ticket('00001', '0001'), self.ticket('00001', '0002')]
        diag = collections.Counter()
        con_ajena = t2.triangular_hormigon(list(viajes), self.jornada_dos_cargas(),
                                            {self.planta_propia: dict(self.coords_planta_propia, dias=10, visitas=50),
                                             self.planta_ajena: dict(self.coords_planta_ajena, dias=2, visitas=32)},
                                            {}, "wialon", None, [], [], diag)
        sin_ajena = t2.triangular_hormigon(list(viajes), self.jornada_dos_cargas(),
                                            {self.planta_propia: dict(self.coords_planta_propia, dias=10, visitas=50)},
                                            {}, "wialon", None, [], [], diag)
        self.assertEqual([r["t_ini"] for r in con_ajena], [r["t_ini"] for r in sin_ajena])
        self.assertEqual([r["km"] for r in con_ajena], [r["km"] for r in sin_ajena])


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


class TestVisitasZonaLlegadaReal(unittest.TestCase):
    # Roberto 28/09/2026, medido en septiembre 2026 (nacional, largo recorrido): usar el momento de ENTRAR en la
    # geocerca del destino (hasta 10 km de radio cuando solo se conoce el centro del pueblo) como hora de llegada
    # adelantaba la descarga una mediana de 5-6 min, siempre en la misma direccion, con el camion aun circulando a
    # velocidad de carretera. t_parado_in marca el primer punto YA parado dentro de la zona, no el de entrar en ella.
    zona = (43.0, -8.0, 1.0, 'nominatim_localidad')

    def test_t_parado_in_llega_mas_tarde_que_t_in_si_sigue_circulando_al_entrar(self):
        t0 = ep('2026-09-10T10:00')
        # 5 min circulando ya DENTRO de la zona (velocidad de carretera), luego 12 min parado de verdad
        pts = tramo(t0, 5, 43.0, 43.0, 80) + tramo(t0 + 5 * 60, 12, 43.0, 43.0, 0)
        ts = [p['t'] for p in pts]
        vis = t2.visitas_zona(pts, ts, self.zona, t0, t0 + 3600)
        self.assertEqual(len(vis), 1)
        self.assertEqual(vis[0]['t_in'], t0)
        self.assertEqual(vis[0]['t_parado_in'], t0 + 5 * 60)

    def test_t_parado_in_coincide_con_t_in_si_ya_esta_parado_al_entrar(self):
        t0 = ep('2026-09-10T10:00')
        pts = tramo(t0, 12, 43.0, 43.0, 0)   # parado desde que entra
        ts = [p['t'] for p in pts]
        vis = t2.visitas_zona(pts, ts, self.zona, t0, t0 + 3600)
        self.assertEqual(len(vis), 1)
        self.assertEqual(vis[0]['t_parado_in'], vis[0]['t_in'])

    def test_sin_ninguna_parada_real_no_hay_visita(self):
        t0 = ep('2026-09-10T10:00')
        pts = tramo(t0, 12, 43.0, 43.0, 80)   # nunca para, solo pasa por delante
        ts = [p['t'] for p in pts]
        self.assertEqual(t2.visitas_zona(pts, ts, self.zona, t0, t0 + 3600), [])


class TestDestinoHormigonPorGPS(unittest.TestCase):
    # Roberto 28/09/2026: «en los viajes de hormigon... el lugar de descarga no deberia ser la planta, deberia ser
    # el lugar que te sale en el localizador al triangular el viaje». El albaran de hormigon siempre repite la
    # planta como destino (t["d"]); destino_hormigon lo sustituye por el sitio real que ve el GPS en la obra,
    # SOLO cuando hay coordenada de la obra y un lugar conocido cerca; si no, nunca inventa: se queda como estaba.
    coords = {('Razo', 'SABO'): {'lat': 43.0, 'lon': -8.0, 'fuente': 'gesruta'}}

    def ticket(self, horm=True, d='SABO'):
        return {"c": "Razo", "d": d, "horm": horm}

    def test_resuelve_por_gps_cuando_hay_lugar_conocido_cerca_de_la_obra(self):
        obra = {"lat": 43.126, "lon": -8.0}
        cercano = lambda lat, lon: 'DORNEDA'  # noqa: E731
        self.assertEqual(t2.destino_hormigon(self.ticket(), obra, self.coords, cercano), 'DORNEDA')

    def test_mantiene_la_planta_si_no_hay_obra(self):
        self.assertEqual(t2.destino_hormigon(self.ticket(), None, self.coords, lambda la, lo: 'DORNEDA'), 'SABO')
        self.assertEqual(t2.destino_hormigon(self.ticket(), {"lat": None, "lon": None}, self.coords, lambda la, lo: 'DORNEDA'), 'SABO')

    def test_mantiene_la_planta_si_no_hay_ningun_lugar_conocido_cerca(self):
        obra = {"lat": 43.126, "lon": -8.0}
        self.assertEqual(t2.destino_hormigon(self.ticket(), obra, self.coords, lambda la, lo: None), 'SABO')

    def test_no_toca_arido_ni_nacional(self):
        obra = {"lat": 43.126, "lon": -8.0}
        self.assertEqual(t2.destino_hormigon(self.ticket(horm=False, d='CANTERA'), obra, self.coords, lambda la, lo: 'DORNEDA'), 'CANTERA')


if __name__ == '__main__':
    unittest.main()
