import XCTest
@testable import Logica

/// Las mismas comprobaciones que `foco.py --selftest`, más la sesión completa que en
/// escritorio recorre `--guitest`: aquí el tiempo se inyecta, sin esperar.
final class FocoTests: XCTestCase {
    let t0 = fecha(2026, 10, 9, 9, 0)

    func testTemporizador() {
        var tm = Temporizador()
        XCTAssertFalse(tm.corriendo)
        XCTAssertFalse(tm.terminado(ahora: t0))
        tm.iniciar(25 * 60, ahora: t0)
        XCTAssertEqual(tm.restante(ahora: t0 + 600), 900, "a los 10 min quedan 15")
        tm.pausar(ahora: t0 + 600)
        XCTAssertEqual(tm.restante(ahora: t0 + 4200), 900, "en pausa no corre aunque pase una hora")
        tm.pausar(ahora: t0 + 4200)
        XCTAssertEqual(tm.restante(ahora: t0 + 4200), 900, "pausar dos veces no descuenta nada")
        tm.reanudar(ahora: t0 + 4200)
        XCTAssertFalse(tm.terminado(ahora: t0 + 5099))
        XCTAssertEqual(tm.restante(ahora: t0 + 5099), 1)
        XCTAssertTrue(tm.terminado(ahora: t0 + 5100))
        XCTAssertEqual(tm.restante(ahora: t0 + 5150), 0)
        XCTAssertEqual(tm.transcurrido(ahora: t0 + 5150), 1550)
        tm.extender(20 * 60)
        XCTAssertEqual(tm.restante(ahora: t0 + 5150), 1150, "extender convierte el arranque en bloque largo")
        XCTAssertEqual(tm.fin(ahora: t0 + 5150), t0 + 5150 + 1150)

        tm.iniciar(5 * 60, ahora: t0)
        tm.pausar(ahora: t0 + 3 * 3600)  // el teléfono estuvo bloqueado 3 horas
        XCTAssertEqual(tm.transcurrido(ahora: t0 + 3 * 3600), 300, "al pausar tarde, no cuenta más que la duración")
        tm.extender(20 * 60)
        tm.reanudar(ahora: t0 + 3 * 3600)
        XCTAssertFalse(tm.terminado(ahora: t0 + 3 * 3600))
        XCTAssertEqual(tm.restante(ahora: t0 + 3 * 3600), 1200, "«Seguir» tras una suspensión da los 20 min")
    }

    func testFormatos() {
        XCTAssertEqual(formatoMMSS(25 * 60), "25:00")
        XCTAssertEqual(formatoMMSS(1499.2), "25:00", "24:59,2 se muestra 25:00")
        XCTAssertEqual(formatoMMSS(0), "00:00")
        XCTAssertEqual(formatoMMSS(0.4), "00:01", "no marca 00:00 antes de tiempo")
        XCTAssertEqual(formatoMMSS(3725), "1:02:05")
        XCTAssertEqual(formatoMinutos(125), "2 h 5 min")
        XCTAssertEqual(formatoMinutos(60), "1 h")
        XCTAssertEqual([1, 2, 3, 4, 5, 8].map { siguienteDescanso($0, cada: 4) },
                       [.descanso, .descanso, .descanso, .descansoLargo, .descanso, .descansoLargo])
        XCTAssertEqual(siguienteDescanso(0, cada: 4), .descanso)
    }

    func testIntencionYConfig() {
        XCTAssertNotNil(intencionVaga("estudiar"))
        XCTAssertNotNil(intencionVaga("avanzar informe T2"))
        XCTAssertNil(intencionVaga("resolver ejercicios 1 a 3 de la guía"))
        XCTAssertNil(intencionVaga(""), "vacía no se juzga aquí: la bloquea empezar()")

        var c = ConfigFoco()
        c.focoMin = 50
        c.descansoMin = 0
        c.arranqueMin = 10
        let v = c.validada()
        XCTAssertEqual([v.focoMin, v.descansoMin, v.arranqueMin], [50, 5, 10])
        c = ConfigFoco()
        c.focoMin = 6
        c.arranqueMin = 10
        XCTAssertLessThan(c.validada().arranqueMin, 6, "el arranque nunca es más largo que el bloque")
    }

    func testSesionCompleta() throws {
        let cfg = ConfigFoco()
        var s = SesionFoco()
        XCTAssertThrowsError(try s.empezar(.foco, intencion: "   ", config: cfg, ahora: t0), "intención vacía no arranca")
        XCTAssertEqual(s.fase, .listo)

        // Bloque completo con una distracción anotada.
        try s.empezar(.foco, intencion: "  resolver   ejercicios 1 a 3 ", config: cfg, ahora: t0)
        XCTAssertEqual(s.fase, .foco)
        XCTAssertEqual(s.bloque?.intencion, "resolver ejercicios 1 a 3")
        s.anotarDistraccion()
        XCTAssertNil(s.tic(ahora: t0 + 24 * 60))
        XCTAssertEqual(s.tic(ahora: t0 + 25 * 60 + 0.4), .finFoco)
        XCTAssertEqual(s.espera, .resultado)
        let f1 = try XCTUnwrap(s.cerrar(.terminado, config: cfg, ahora: t0 + 25 * 60 + 3))
        XCTAssertEqual([f1.tipo, f1.resultado], ["foco", "terminado"])
        XCTAssertEqual([f1.minutosReales, f1.distracciones], [25, 1])
        XCTAssertEqual(s.fase, .descanso)
        XCTAssertEqual(s.tic(ahora: t0 + 31 * 60), .finDescanso)
        XCTAssertEqual(s.fase, .listo)

        // «Solo 5 minutos» con el teléfono bloqueado 2 horas: al volver, seguir da 20 min reales.
        let t1 = t0 + 3600
        try s.empezar(.arranque, intencion: "leer el paper hasta la sección 3", config: cfg, ahora: t1)
        XCTAssertEqual(s.fase, .arranque)
        XCTAssertEqual(s.tic(ahora: t1 + 2 * 3600), .finArranque)
        XCTAssertEqual(s.espera, .seguir)
        s.seguir(config: cfg, ahora: t1 + 2 * 3600)
        XCTAssertEqual(s.fase, .foco)
        XCTAssertEqual(s.bloque?.tipo, .foco)
        XCTAssertEqual(s.temporizador.restante(ahora: t1 + 2 * 3600), 20 * 60)
        XCTAssertEqual(s.tic(ahora: t1 + 2 * 3600 + 20 * 60), .finFoco)
        let f2 = try XCTUnwrap(s.cerrar(.avance, config: cfg, ahora: t1 + 2 * 3600 + 20 * 60))
        XCTAssertEqual([f2.minutosReales, f2.minutosPlaneados], [25, 25], "no anota las 2 horas bloqueado")
        XCTAssertEqual(s.completados, 2)

        // El cuarto bloque trae descanso largo.
        s.saltarDescanso()
        var t = t1 + 4 * 3600
        for _ in 0..<2 {
            try s.empezar(.foco, intencion: "otra cosa concreta más", config: cfg, ahora: t)
            _ = s.tic(ahora: t + 25 * 60)
            _ = s.cerrar(.terminado, config: cfg, ahora: t + 25 * 60)
            t += 3600
        }
        XCTAssertEqual(s.fase, .descansoLargo)
        XCTAssertEqual(s.temporizador.duracion, 15 * 60)
        s.saltarDescanso()

        // Pausa: una hora en pausa no descuenta.
        try s.empezar(.foco, intencion: "ordenar los apuntes del control", config: cfg, ahora: t)
        s.alternarPausa(ahora: t + 5 * 60)
        XCTAssertTrue(s.enPausa)
        XCTAssertNil(s.tic(ahora: t + 3600))
        s.alternarPausa(ahora: t + 3600)
        XCTAssertEqual(s.temporizador.restante(ahora: t + 3600), 20 * 60)

        // Terminar antes anota lo trabajado.
        s.terminarAntes(ahora: t + 3600 + 5 * 60)
        XCTAssertEqual(s.espera, .resultado)
        XCTAssertEqual(s.cerrar(.terminado, config: cfg, ahora: t + 3600 + 5 * 60)?.minutosReales, 10)

        // Abandonar: menos de un minuto no se anota; más, sí.
        s.saltarDescanso()
        try s.empezar(.foco, intencion: "escribir la conclusión del informe", config: cfg, ahora: t)
        XCTAssertNil(s.abandonar(ahora: t + 20))
        XCTAssertEqual(s.fase, .listo)
        try s.empezar(.foco, intencion: "escribir la conclusión del informe", config: cfg, ahora: t)
        let f3 = try XCTUnwrap(s.abandonar(ahora: t + 10 * 60))
        XCTAssertEqual([f3.resultado, "\(f3.minutosReales)"], ["abandonado", "10"])

        // La sesión se guarda y se recupera igual (si iOS cierra la app a mitad de un bloque).
        try s.empezar(.foco, intencion: "una más para probar el guardado", config: cfg, ahora: t)
        let copia = try JSONDecoder().decode(SesionFoco.self, from: JSONEncoder().encode(s))
        XCTAssertEqual(copia, s)
    }

    func testCSVDeEscritorio() throws {
        let filas = RegistroFoco.leer(texto: try XCTUnwrap(String(data: Escritorio.focoCSV, encoding: .utf8)))
        XCTAssertEqual(filas.count, 2)
        XCTAssertEqual(filas[0].intencion, "informe; sección \"2\", con comas,\ny salto")
        XCTAssertEqual(filas[0].inicio, fecha(2026, 10, 9, 9, 0))
        XCTAssertEqual([filas[0].minutosReales, filas[0].distracciones], [25, 1])
        XCTAssertEqual(filas[1].intencion, "ñandú ü áéí")
        XCTAssertEqual([filas[1].tipo, filas[1].resultado], ["arranque", "avance"])

        // Escribir esas mismas filas desde el iPhone da exactamente los mismos bytes que Python.
        let url = carpetaTemporal().appendingPathComponent("foco_registro.csv")
        for f in filas { try RegistroFoco.anotar(f, en: url) }
        XCTAssertEqual(try Data(contentsOf: url), Escritorio.focoCSV)

        // Filas dañadas al final se saltan sin romper la lectura.
        let h = try FileHandle(forWritingTo: url)
        try h.seekToEnd()
        try h.write(contentsOf: Data("basura;sin;sentido\r\n2026-10-09T12:00:00;roto\r\n".utf8))
        try h.close()
        XCTAssertEqual(RegistroFoco.leer(url).count, 2)
        XCTAssertEqual(RegistroFoco.leer(carpetaTemporal().appendingPathComponent("no-existe.csv")), [])
    }

    func testEstadisticas() {
        let hoy = fecha(2026, 10, 9)
        func fila(_ diasAtras: Int, _ hora: Int, _ minutos: Int, _ resultado: String, tipo: String = "foco",
                  dist: Int = 0) -> Bloque {
            let ini = Calendar.current.date(byAdding: .day, value: -diasAtras, to: hoy)! + Double(hora * 3600)
            return Bloque(inicio: ini, fin: ini + Double(minutos * 60), tipo: tipo, minutosPlaneados: 25,
                          minutosReales: minutos, intencion: "x", resultado: resultado, distracciones: dist)
        }
        let filas = [fila(0, 9, 25, "terminado"), fila(0, 10, 25, "avance", dist: 2), fila(0, 11, 3, "abandonado"),
                     fila(1, 23, 25, "sin_avance"), fila(2, 18, 5, "avance", tipo: "arranque"),
                     fila(4, 18, 25, "terminado"), fila(9, 18, 25, "terminado")]
        let e = estadisticas(filas, hoy: hoy + 15 * 3600)
        XCTAssertEqual(e.minutosHoy, 53, "incluye el abandonado")
        XCTAssertEqual(e.bloquesHoy, 2, "el abandonado no cuenta como bloque")
        XCTAssertEqual(e.racha, 3, "hoy, ayer y anteayer")
        XCTAssertEqual(e.distraccionesHoy, 2)
        XCTAssertEqual(e.resultadosSemana, ["terminado": 2, "avance": 2, "sin_avance": 1, "abandonado": 1])
        XCTAssertEqual(e.ultimos7.map(\.minutos), [0, 0, 25, 0, 5, 25, 53])
        XCTAssertEqual(e.ultimos7.last?.dia, hoy)
        let manana = estadisticas(filas, hoy: hoy + 86400 + 3600)
        XCTAssertEqual([manana.racha, manana.minutosHoy], [3, 0], "la racha sigue viva mientras el día no termina")
        XCTAssertEqual(estadisticas(filas, hoy: hoy + 2 * 86400 + 3600).racha, 0)
        let txt = textoEstadisticas(e)
        XCTAssertTrue(txt.contains("53 min en 2 bloque(s)") && txt.contains("racha: 3"), txt)
    }

    func testParaDespues() throws {
        let url = carpetaTemporal().appendingPathComponent("foco_para_despues.txt")
        try Pendientes.anotar("  revisar   correo del profe ", ahora: fecha(2026, 10, 9, 15, 20), en: url)
        try Pendientes.anotar("   ", ahora: fecha(2026, 10, 9, 15, 21), en: url)
        try Pendientes.anotar("comprar café", ahora: fecha(2026, 10, 9, 15, 22), en: url)
        let lineas = Pendientes.leer(url)
        XCTAssertEqual(lineas, ["2026-10-09 15:20  revisar correo del profe", "2026-10-09 15:22  comprar café"])
        try Pendientes.guardar(Array(lineas.dropFirst()), en: url)
        XCTAssertEqual(Pendientes.leer(url), ["2026-10-09 15:22  comprar café"])
    }
}
