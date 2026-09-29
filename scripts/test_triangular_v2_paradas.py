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


class TestVisitasPlantasNoFusionaSiHuboRecorridoReal(unittest.TestCase):
    # 1865NNH, 15/07/2026 (Roberto/Claude 29/09/2026): visitas_plantas() fundia paradas consecutivas en la MISMA
    # planta sin comprobar si hubo un recorrido real entre medias (114 km, 39 km de reparto real), al reves que
    # ciclos_geo() para aridos, que ya exige < KM_MISMA_CARGA (3 km) antes de fundir dos paradas del mismo origen.
    # Con solo 1 visita en vez de 3, el dia entero se veia como un unico ciclo planta->obra->planta.
    planta = ("Razo", "A")
    plantas = {planta: {"lat": 42.000, "lon": -8.000, "radio_m": 450}}

    def test_dos_visitas_con_una_ronda_real_entre_medias_no_se_funden(self):
        t0 = ep('2026-09-21T08:00')
        pts = (tramo(t0 - 3 * 60, 3, 41.980, 42.000, 60)
               + tramo(t0, 10, 42.000, 42.000, 0)                  # visita 1 a la planta
               + tramo(t0 + 10 * 60, 10, 42.000, 42.100, 60)       # ronda real: se aleja ~11 km
               + tramo(t0 + 20 * 60, 10, 42.100, 42.100, 0)        # parada en la obra (fuera de la planta)
               + tramo(t0 + 30 * 60, 10, 42.100, 42.000, 60)       # y vuelve
               + tramo(t0 + 40 * 60, 10, 42.000, 42.000, 0)        # visita 2 a la planta (recarga)
               + tramo(t0 + 50 * 60, 3, 42.000, 42.020, 60))
        jor = t2.jornadas_de(pts, t2.paradas_flujo(pts), 8 * 3600)
        vis = t2.visitas_plantas(jor[0], self.plantas)
        self.assertEqual(len(vis), 2, "dos rondas reales de planta deben salir como DOS visitas, no fundidas en una")

    def test_dos_paradas_seguidas_sin_recorrido_si_se_funden(self):
        # cola / cargadero: la traza rompe la parada en dos por un punto suelto en movimiento, pero sin alejarse de
        # la planta. Esto SIGUE fundiendose en una sola visita, como antes del arreglo (no se ha roto nada).
        t0 = ep('2026-09-21T08:00')
        pts = (tramo(t0 - 3 * 60, 3, 41.980, 42.000, 60)
               + tramo(t0, 10, 42.000, 42.000, 0)
               + [dict(tramo(t0 + 10 * 60, 1, 42.000, 42.000, 10)[0])]  # un punto suelto moviendose, mismo sitio
               + tramo(t0 + 11 * 60, 10, 42.000, 42.000, 0)
               + tramo(t0 + 21 * 60, 3, 42.000, 42.020, 60))
        jor = t2.jornadas_de(pts, t2.paradas_flujo(pts), 8 * 3600)
        vis = t2.visitas_plantas(jor[0], self.plantas)
        self.assertEqual(len(vis), 1, "sin recorrido real entre medias, sigue siendo una sola visita (cola/cargadero)")


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

    def test_un_frenazo_suelto_no_confirma_t_parado_in(self):
        # 5003MBV 09/07/2026: un unico punto a 2 km/h en plena zona (no en el borde) marcaba la llegada 11 min antes
        # de la parada real, con el camion circulando a 35-65 km/h justo antes y despues. t_parado_in solo debe
        # confirmarse cuando el "parado" se sostiene >= DWELL_S seguidos; un frenazo de un solo punto se descarta.
        t0 = ep('2026-09-10T10:00')
        pts = (tramo(t0, 3, 43.0, 43.0, 60)                                  # circulando
               + [dict(tramo(t0 + 180, 1, 43.0, 43.0, 2.0)[0])]              # frenazo suelto, 1 punto a 2 km/h
               + tramo(t0 + 240, 10, 43.0, 43.0, 50)                        # vuelve a circular de verdad
               + tramo(t0 + 840, 12, 43.0, 43.0, 0))                        # parada real, sostenida
        ts = [p['t'] for p in pts]
        vis = t2.visitas_zona(pts, ts, self.zona, t0, t0 + 3600)
        self.assertEqual(len(vis), 1)
        self.assertEqual(vis[0]['t_parado_in'], t0 + 840, "la llegada real, no el frenazo suelto de t0+180")


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


class TestCiclosGeoLlegadaReal(unittest.TestCase):
    # Auditoria de abril 2026 (Roberto/Claude 29/09/2026): ciclos_geo() tiene su PROPIA deteccion de "visitas" a una
    # zona (bucle "visitas, cur = [], None"), separada de visitas_zona() (arreglada ayer, commit 7d5d705, para
    # nacional de largo recorrido) pero con el MISMO problema: t_in (momento de ENTRAR en la geocerca) se usaba tal
    # cual como hora de carga/descarga en medir_ciclo(), sin exigir que el camion se quedase parado de verdad. Afecta
    # a TODOS los viajes locales que pasan por ciclos_geo() (nacional corto, aridos, banera). Medido en la auditoria:
    # 95-100% de los viajes nacionales LOCALES con parada de carga o descarga registrada la tenian ANTES que la
    # parada real (mediana 5 min, hasta 21 min, siempre en la misma direccion). Casos reales de referencia: 9791JLT
    # 09/04 viaje 00028149 destino Mazaricos (t_descarga publicado 12:48, parada real 13:09) y 5665FXZ 25/05 viaje
    # 00028558 destino POIO (t_descarga publicado 17:56, parada real 18:31).
    casa = "Razo"

    def coords_de(self, cod, lat, lon, fuente="gesruta", radio_m=None):
        c = {"lat": lat, "lon": lon, "fuente": fuente}
        if radio_m is not None:
            c["radio_m"] = radio_m
        return (self.casa, cod), c

    def ticket(self, o, d):
        return {"o": o, "d": d, "v": "00001", "cant": "0001"}

    def test_descarga_llega_tarde_si_el_camion_sigue_circulando_al_entrar_en_la_zona(self):
        # zona ancha (nominatim_localidad, 5 km): el camion entra en ella circulando a velocidad de carretera y solo
        # para de verdad varios minutos despues (igual que el patron medido en abril: geocerca ancha, t_in adelantado).
        t0 = ep('2026-04-09T08:00')
        pts = (tramo(t0 - 3 * 60, 3, 41.980, 42.000, 60)
               + tramo(t0, 10, 42.000, 42.000, 0)                 # carga en A, parado de verdad
               + tramo(t0 + 10 * 60, 8, 42.000, 42.100, 60)       # viaje hacia B, aun fuera de su zona
               + tramo(t0 + 18 * 60, 5, 42.200, 42.200, 60)       # YA dentro de la zona de B (centro exacto), pero sigue circulando
               + tramo(t0 + 23 * 60, 10, 42.200, 42.200, 0)       # ahora si, parado de verdad (descarga real)
               + tramo(t0 + 33 * 60, 3, 42.200, 42.220, 60))
        jor = t2.jornadas_de(pts, t2.paradas_flujo(pts), 8 * 3600)
        self.assertEqual(len(jor), 1)
        (ka, ca), (kb, cb) = self.coords_de('A', 42.000, -8.000, fuente="gesruta"), self.coords_de('B', 42.200, -8.000, fuente="nominatim_localidad")
        coords = {ka: ca, kb: cb}
        ciclos = t2.ciclos_geo(jor[0], [self.ticket('A', 'B')], coords, self.casa, "wialon", None)
        self.assertEqual(len(ciclos), 1)
        c = ciclos[0]
        self.assertIsNotNone(c.get("descarga"))
        self.assertEqual(c["descarga"]["t_in"], t0 + 18 * 60, "t_in crudo = al entrar en la geocerca, aun circulando")
        self.assertEqual(c["descarga"]["t_parado_in"], t0 + 23 * 60, "t_parado_in = la parada real, mas tarde")
        m = t2.medir_ciclo(jor[0], c, 0, 1, "wialon", None, [], [])
        self.assertEqual(m["t_descarga_in"], t0 + 23 * 60, "medir_ciclo debe usar la parada real, no t_in crudo")
        self.assertGreater(m["t_descarga_in"], c["descarga"]["t_in"], "la hora publicada nunca debe adelantarse a la parada real")

    def test_un_frenazo_suelto_dentro_de_la_zona_no_confirma_la_llegada(self):
        # un unico punto a baja velocidad (cruce, rotonda) dentro de la zona de descarga, con el camion circulando a
        # velocidad de carretera justo antes y despues, NO debe confirmar t_parado_in (mismo criterio que
        # visitas_zona(), commit 7d5d705, caso real 5003MBV 09/07/2026).
        t0 = ep('2026-04-09T08:00')
        pts = (tramo(t0 - 3 * 60, 3, 41.980, 42.000, 60)
               + tramo(t0, 10, 42.000, 42.000, 0)                              # carga en A
               + tramo(t0 + 10 * 60, 8, 42.000, 42.100, 60)                    # viaje hacia B
               + [dict(tramo(t0 + 18 * 60, 1, 42.200, 42.200, 2.0)[0])]        # frenazo suelto, 1 punto a 2 km/h en la zona
               + tramo(t0 + 19 * 60, 5, 42.200, 42.200, 60)                    # sigue circulando de verdad
               + tramo(t0 + 24 * 60, 10, 42.200, 42.200, 0)                    # parada real, sostenida
               + tramo(t0 + 34 * 60, 3, 42.200, 42.220, 60))
        jor = t2.jornadas_de(pts, t2.paradas_flujo(pts), 8 * 3600)
        (ka, ca), (kb, cb) = self.coords_de('A', 42.000, -8.000, fuente="gesruta"), self.coords_de('B', 42.200, -8.000, fuente="nominatim_localidad")
        coords = {ka: ca, kb: cb}
        ciclos = t2.ciclos_geo(jor[0], [self.ticket('A', 'B')], coords, self.casa, "wialon", None)
        self.assertEqual(len(ciclos), 1)
        c = ciclos[0]
        self.assertEqual(c["descarga"]["t_parado_in"], t0 + 24 * 60, "la parada sostenida, no el frenazo suelto de t0+18min")

    def test_parada_corta_sin_llegar_a_sostenerse_cae_hacia_t_in_crudo(self):
        # porte muy corto (banera: volcar dura 2-3 min real, pero la traza solo trae 2 puntos parados = 60 s de
        # separacion, sin llegar a los DWELL_S=180s): medir_ciclo() debe seguir dando una hora (el t_in crudo, como
        # antes de este arreglo), no perder el hito por exigir una parada que la traza no puede confirmar.
        t0 = ep('2026-04-09T08:00')
        pts = (tramo(t0 - 3 * 60, 3, 41.980, 42.000, 60)
               + tramo(t0, 5, 42.000, 42.000, 0)
               + tramo(t0 + 5 * 60, 3, 42.000, 42.020, 60)
               + tramo(t0 + 8 * 60, 2, 42.020, 42.020, 0)          # descarga de solo 1 min entre puntos: no sostiene DWELL_S
               + tramo(t0 + 10 * 60, 3, 42.020, 42.040, 60))
        jor = t2.jornadas_de(pts, t2.paradas_flujo(pts), 8 * 3600)
        (ka, ca), (kb, cb) = self.coords_de('A', 42.000, -8.000, fuente="gps_aprendida", radio_m=300), self.coords_de('B', 42.020, -8.000, fuente="gps_aprendida", radio_m=300)
        coords = {ka: ca, kb: cb}
        ciclos = t2.ciclos_geo(jor[0], [self.ticket('A', 'B')], coords, self.casa, "wialon", None)
        self.assertEqual(len(ciclos), 1)
        c = ciclos[0]
        self.assertIsNotNone(c.get("descarga"))
        self.assertIsNone(c["descarga"].get("t_parado_in"), "un porte tan corto no llega a sostener la parada")
        m = t2.medir_ciclo(jor[0], c, 0, 1, "wialon", None, [], [])
        self.assertEqual(m["t_descarga_in"], c["descarga"]["t_in"], "sin parada sostenida, cae hacia t_in crudo (no se pierde el hito)")

    def test_no_cambia_los_limites_del_ciclo_solo_la_hora_publicada(self):
        # el arreglo NO debe tocar t0/t1 del ciclo (siguen fijados por t_out, como siempre): solo cambia t_carga_in /
        # t_descarga_in que salen al JSON. Compara el mismo escenario con y sin el "circulando dentro de la zona" y
        # comprueba que el limite del ciclo (t1) no se mueve.
        t0 = ep('2026-04-09T08:00')
        pts = (tramo(t0 - 3 * 60, 3, 41.980, 42.000, 60)
               + tramo(t0, 10, 42.000, 42.000, 0)
               + tramo(t0 + 10 * 60, 8, 42.000, 42.100, 60)
               + tramo(t0 + 18 * 60, 5, 42.200, 42.200, 60)
               + tramo(t0 + 23 * 60, 10, 42.200, 42.200, 0)
               + tramo(t0 + 33 * 60, 3, 42.200, 42.450, 60))   # se aleja bien fuera del radio de B (5 km) para cerrar la visita
        jor = t2.jornadas_de(pts, t2.paradas_flujo(pts), 8 * 3600)
        (ka, ca), (kb, cb) = self.coords_de('A', 42.000, -8.000, fuente="gesruta"), self.coords_de('B', 42.200, -8.000, fuente="nominatim_localidad")
        coords = {ka: ca, kb: cb}
        ciclos = t2.ciclos_geo(jor[0], [self.ticket('A', 'B')], coords, self.casa, "wialon", None)
        # el ultimo ciclo del dia se extiende al fin de la jornada (comportamiento de siempre, sin tocar por este
        # arreglo): lo que NO debe moverse es el limite real de la descarga, el t_out de su visita.
        self.assertEqual(ciclos[0]["t1"], jor[0]["fin"])
        self.assertEqual(ciclos[0]["descarga"]["t_out"], t0 + 33 * 60, "t_out de la visita de descarga sin tocar por el arreglo")


class TestCiclosGeoNoUsaPlantaDeHormigonEnDiaMixto(unittest.TestCase):
    # 8803NKR, 22/07/2026 (Roberto/Claude 29/09/2026): la cantera "27150" sirve HORMIGON y ARIDOS con el mismo codigo.
    # Su coordenada aprendida (aprender_plantas) es el centro preciso de la hormigonera (radio_m=450), pero cerca()
    # no distingue fuente="planta_aprendida" de un lugar generico y cae en el radio por defecto (3 km): un punto de
    # la traza a 2-3 km del centro de la planta seguia contando "dentro" de la zona para el TICKET DE ARIDOS que
    # comparte el mismo codigo ese dia, fundiendo rondas y arrastrando km/tiempo de la jornada entera (+15,8% de km
    # medido). Se descarto arreglar cerca()/RADIO_MATCH directamente (28-29/09/2026, commit 7d5d705) porque esos dos
    # se leen tambien en dias SIN hormigon, en canteras que sirven aridos con normalidad a 1-3 km del centro
    # aprendido: acotarlo ahi rompia cientos de viajes de aridos/banera reales (medido_por_viaje -724,
    # carga_por_paso 33->961). El arreglo va en triangular_dia()/ciclos_geo(): en un dia MIXTO, los codigos que hoy
    # son planta de hormigon de ESTE camion se excluyen de las zonas del motor de aridos (ya los mide, con su radio
    # exacto, ciclos_plantas()); fuera de un dia mixto no cambia nada (excluir=None de toda la vida).
    casa = "Razo"

    def coords_de(self, cod, lat, lon, fuente, radio_m=None):
        c = {"lat": lat, "lon": lon, "fuente": fuente}
        if radio_m is not None:
            c["radio_m"] = radio_m
        return (self.casa, cod), c

    def ticket(self, o, d):
        return {"o": o, "d": d, "v": "00001", "cant": "0001"}

    def escenario(self):
        # planta en (42.000, -8.000); la traza pasa a ~2 km (0.018 grados de latitud: dentro del radio generico de
        # 3 km, muy fuera del radio real de la planta de 450 m) -- el punto exacto que arrastraba la ronda.
        t0 = ep('2026-07-22T08:00')
        pts = (tramo(t0, 10, 42.018, 42.018, 0)                 # "carga" a 2 km de la planta, parado de verdad
               + tramo(t0 + 10 * 60, 8, 42.018, 42.100, 60)     # se aleja de verdad (obra)
               + tramo(t0 + 18 * 60, 15, 42.100, 42.100, 0)     # descarga en la obra
               + tramo(t0 + 33 * 60, 8, 42.100, 42.018, 60)     # vuelve
               + tramo(t0 + 41 * 60, 10, 42.018, 42.018, 0))    # "descarga" de vuelta a 2 km de la planta
        jor = t2.jornadas_de(pts, t2.paradas_flujo(pts), 8 * 3600)
        coords = dict([self.coords_de('27150', 42.000, -8.000, fuente="planta_aprendida", radio_m=450)])
        return jor, coords

    def test_sin_excluir_el_punto_a_2_km_cuenta_como_dentro_de_la_planta(self):
        # documenta el comportamiento fuera de un dia mixto (excluir=None): el radio generico de 3 km sigue viendo
        # el punto a 2 km como "dentro" de la planta, tal cual antes de este arreglo.
        jor, coords = self.escenario()
        ciclos = t2.ciclos_geo(jor[0], [self.ticket('27150', '27150')], coords, self.casa, "wialon", None)
        self.assertTrue(any(c.get("o") == '27150' for c in ciclos))

    def test_excluyendo_el_codigo_de_hoy_no_arrastra_la_ronda(self):
        jor, coords = self.escenario()
        ciclos = t2.ciclos_geo(jor[0], [self.ticket('27150', '27150')], coords, self.casa, "wialon", None, excluir={'27150'})
        self.assertEqual(ciclos, [], "en un dia mixto, el codigo de la planta de hormigon de HOY no es zona del motor de aridos")


if __name__ == '__main__':
    unittest.main()
