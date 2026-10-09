import XCTest
@testable import Logica

/// Las mismas comprobaciones que `plazos.py --selftest`, con los mismos números.
final class PlazosTests: XCTestCase {
    // viernes 9 de octubre de 2026, 15:20
    let ahora = fecha(2026, 10, 9, 15, 20)
    let cap = 4.0

    func tarea(_ nombre: String, _ enHoras: Double, _ est: Double, hechas: Double = 0,
               entregada: Bool = false) -> Tarea {
        Tarea(nombre: nombre, entrega: ahora.addingTimeInterval(enHoras * 3600), horasEstimadas: est,
              horasHechas: hechas, entregada: entregada)
    }

    func testFormatos() {
        XCTAssertEqual(formatoEntrega(fecha(2026, 10, 15, 18, 0), ahora: ahora), "jue 15-10 18:00")
        XCTAssertEqual(formatoEntrega(fecha(2027, 1, 5, 9, 5), ahora: ahora), "mar 05-01-2027 09:05")
        XCTAssertEqual(formatoReloj(76.5), "3 d 4 h")
        XCTAssertEqual(formatoReloj(5 + 20.0 / 60), "5 h 20 min")
        XCTAssertEqual(formatoReloj(0.25), "15 min")
        XCTAssertEqual(formatoReloj(-2), "vencida hace 2 h 0 min")
        XCTAssertEqual(formatoHoras(2.5), "2,5 h")
        XCTAssertEqual(formatoHoras(2.0), "2 h")
        XCTAssertEqual(formatoHoras(0.5), "30 min")
    }

    func testParseHoras() throws {
        let casos: [String: Double] = ["2": 2, "2,5": 2.5, "2.5": 2.5, "1h30": 1.5, "1 h 30 min": 1.5,
                                       "90 min": 1.5, "45m": 0.75, "3 horas": 3]
        for (texto, esperado) in casos {
            XCTAssertEqual(try parseHoras(texto), esperado, accuracy: 1e-9, "horas «\(texto)»")
        }
        for malo in ["", "mucho", "-2", "1h75"] {
            XCTAssertThrowsError(try parseHoras(malo), "horas inválidas «\(malo)»")
        }
    }

    func testHorasEditablesVuelvenExactas() throws {
        for h in [0.0, 0.25, 25.0 / 60, 1.75, 2.0, 7.5, 1.1] {
            XCTAssertEqual(try parseHoras(horasEditables(h)), (h * 60).rounded() / 60, accuracy: 1e-9,
                           "«\(horasEditables(h))»")
        }
        XCTAssertEqual(horasEditables(1.75), "1h45")
    }

    func testAnalisis() throws {
        var a = analizar(tarea("holgada", 240, 10), ahora: ahora, capacidad: cap)
        XCTAssertEqual(a.estado, .verde)
        XCTAssertEqual(a.hoy, 1, accuracy: 1e-9)
        XCTAssertEqual(try XCTUnwrap(a.siPostergas), 10.0 / 9, accuracy: 1e-9)

        a = analizar(tarea("ajustada", 72, 9), ahora: ahora, capacidad: cap)
        XCTAssertEqual(a.estado, .amarillo)
        XCTAssertEqual(a.hoy, 3, accuracy: 1e-9)
        XCTAssertEqual(try XCTUnwrap(a.siPostergas), 4.5, accuracy: 1e-9)

        XCTAssertEqual(analizar(tarea("roja", 48, 10), ahora: ahora, capacidad: cap).estado, .rojo)

        a = analizar(tarea("hoy", 6, 2), ahora: ahora, capacidad: cap)
        XCTAssertEqual(a.hoy, 2, accuracy: 1e-9, "con menos de un día, todo lo que falta toca hoy")
        XCTAssertNil(a.siPostergas, "postergar la pierde")

        XCTAssertEqual(analizar(tarea("imposible", 5, 8), ahora: ahora, capacidad: cap).estado, .imposible)
        a = analizar(tarea("vencida", -3, 5), ahora: ahora, capacidad: cap)
        XCTAssertEqual(a.estado, .vencida)
        XCTAssertLessThan(a.horasReloj, 0)
        XCTAssertEqual(analizar(tarea("lista", 24, 5, hechas: 5), ahora: ahora, capacidad: cap).estado, .lista)
        a = analizar(tarea("pasada", 24, 5, hechas: 7), ahora: ahora, capacidad: cap)
        XCTAssertEqual(a.estado, .lista)
        XCTAssertEqual(a.faltan, 0, "más horas que lo estimado no da faltan negativo")
        XCTAssertEqual(analizar(tarea("frontera", 72, 6), ahora: ahora, capacidad: cap).estado, .verde,
                       "carga exactamente 50 % sigue verde")
        XCTAssertEqual(analizar(tarea("sin capacidad", 72, 6), ahora: ahora, capacidad: 0).estado, .rojo)
    }

    func testResumenYOrden() {
        let tareas = [tarea("A", 240, 10), tarea("B", 72, 9), tarea("C", 6, 2), tarea("D", -3, 5),
                      tarea("E", 24, 5, hechas: 5), tarea("F", 48, 4, entregada: true)]
        let r = resumir(tareas, ahora: ahora, capacidad: cap)
        XCTAssertEqual(r.hoyTotal, 6, accuracy: 1e-9, "total de hoy suma solo entregas vivas")
        XCTAssertEqual(r.mananaTotal, 10.0 / 9 + 4.5, accuracy: 1e-9)
        XCTAssertEqual([r.sePierden, r.vencidas, r.activas], [1, 1, 3])
        let (l1, l2) = textoResumen(r)
        XCTAssertTrue(l1.contains("6 h") && l1.contains("4 h"), l1)
        XCTAssertTrue(l2.contains("1 entrega(s) vencerían") && l2.contains("5,6 h"), l2)
        let vacio = textoResumen(resumir([], ahora: ahora, capacidad: cap))
        XCTAssertTrue(vacio.0.contains("Nada pendiente") && vacio.1.contains("+"))
        XCTAssertEqual(ordenar(tareas, ahora: ahora, capacidad: cap).map(\.nombre), ["D", "C", "B", "A", "E", "F"])
    }

    func testSiguientePaso() {
        XCTAssertNotNil(pasoVago(""))
        XCTAssertNotNil(pasoVago("avanzar T2"))
        XCTAssertNotNil(pasoVago("Estudiar"))
        XCTAssertNotNil(pasoVago("Avanzar informe T2"))
        XCTAssertNil(pasoVago("leer paper CLRNet"))
        XCTAssertNil(pasoVago("revisar la ecuación 3 del enunciado"))
    }

    func testLeeElJSONDeEscritorio() throws {
        let (datos, avisos) = try ArchivoPlazos.decodificar(Escritorio.plazosJSON)
        XCTAssertEqual(avisos, [])
        XCTAssertEqual(datos.tareas.count, 2)
        let t = datos.tareas[0]
        XCTAssertEqual(t.nombre, "Informe T2 «redes»")
        XCTAssertEqual(t.entrega, fecha(2026, 10, 12, 18, 0))
        XCTAssertEqual(t.horasEstimadas, 9)
        XCTAssertEqual(t.horasHechas, 1.5)
        XCTAssertEqual(t.curso, "IEE2544")
        XCTAssertEqual(t.siguientePaso, "escribir intro; sección \"1\"")
        XCTAssertEqual(t.id, "a1b2c3d4")
        XCTAssertEqual(t.creada, "2026-10-01T10:00")
        XCTAssertTrue(datos.tareas[1].entregada)
        XCTAssertEqual(datos.tareas[1].horasHechas, 1.75)
        XCTAssertEqual(datos.registro, [RegistroHoras(fecha: "2026-10-09T15:20", tarea: "a1b2c3d4", horas: 1.5)])

        // Lo que escribe el iPhone lo vuelve a leer igual, y con las mismas claves que escritorio.
        let salida = try ArchivoPlazos.codificar(datos)
        let (otra, _) = try ArchivoPlazos.decodificar(salida)
        XCTAssertEqual(otra, datos)
        let crudo = try XCTUnwrap(JSONSerialization.jsonObject(with: salida) as? [String: Any])
        XCTAssertEqual(crudo["version"] as? Int, 1)
        let primera = try XCTUnwrap((crudo["tareas"] as? [[String: Any]])?.first)
        XCTAssertEqual(Set(primera.keys), ["nombre", "entrega", "horas_estimadas", "horas_hechas", "curso",
                                           "siguiente_paso", "entregada", "id", "creada"])
        XCTAssertEqual(primera["entrega"] as? String, "2026-10-12T18:00")
    }

    func testTareasInvalidasSeSaltanConAviso() throws {
        let json = """
        {"tareas": [{"nombre": "ok", "entrega": "2026-10-20T10:00", "horas_estimadas": 2},
                    {"nombre": "mala", "entrega": "ayer", "horas_estimadas": 2},
                    {"nombre": "", "entrega": "2026-10-20T10:00", "horas_estimadas": 2}]}
        """
        let (datos, avisos) = try ArchivoPlazos.decodificar(Data(json.utf8))
        XCTAssertEqual(datos.tareas.map(\.nombre), ["ok"])
        XCTAssertEqual(avisos.count, 2, "\(avisos)")
    }

    func testArchivoDanadoSeApartaYNoSePierde() throws {
        let dir = carpetaTemporal()
        let url = dir.appendingPathComponent("plazos_datos.json")
        try Data("{esto no es json".utf8).write(to: url)
        let (datos, avisos) = ArchivoPlazos.cargar(url)
        XCTAssertEqual(datos, DatosPlazos())
        XCTAssertEqual(avisos.count, 1)
        let archivos = try FileManager.default.contentsOfDirectory(atPath: dir.path)
        XCTAssertEqual(archivos.filter { $0.contains("corrupto") }.count, 1, "\(archivos)")
        XCTAssertEqual(ArchivoPlazos.cargar(dir.appendingPathComponent("no-existe.json")).0, DatosPlazos())
    }

    func testGuardarYCargarConHoras() throws {
        let url = carpetaTemporal().appendingPathComponent("plazos_datos.json")
        var t = Tarea(nombre: "Informe", entrega: fecha(2026, 10, 12, 18, 0), horasEstimadas: 9,
                      siguientePaso: "escribir intro")
        var registro: [RegistroHoras] = []
        registrarHoras(&t, &registro, horas: 1.5, ahora: ahora)
        registrarHoras(&t, &registro, horas: 0.5, ahora: ahora.addingTimeInterval(-86400))
        try ArchivoPlazos.guardar(DatosPlazos(tareas: [t], registro: registro), en: url)
        let (datos, avisos) = ArchivoPlazos.cargar(url)
        XCTAssertEqual(avisos, [])
        XCTAssertEqual(datos.tareas, [t])
        XCTAssertEqual(datos.tareas[0].horasHechas, 2)
        XCTAssertEqual(horasRegistradas(datos.registro, el: ahora), 1.5)
    }

    func testSugerenciasParaFoco() {
        let tareas = [
            Tarea(nombre: "T3", entrega: fecha(2026, 10, 20, 23, 59), horasEstimadas: 1, siguientePaso: "leer enunciado"),
            Tarea(nombre: "Informe", entrega: fecha(2026, 10, 12, 18, 0), horasEstimadas: 1,
                  siguientePaso: "escribir intro"),
            Tarea(nombre: "Vieja", entrega: fecha(2026, 10, 1), horasEstimadas: 1, siguientePaso: "x", entregada: true),
            Tarea(nombre: "Sin paso", entrega: fecha(2026, 10, 11), horasEstimadas: 1),
        ]
        XCTAssertEqual(sugerenciasDePlazos(tareas), ["escribir intro — Informe", "leer enunciado — T3"])
    }
}
