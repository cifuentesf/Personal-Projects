import Foundation
import Logica

/// `--autoprueba`: recorre los almacenes reales dentro del iPhone (o el simulador), sobre una
/// carpeta temporal, y termina con «AUTOPRUEBA OK n/n» o la lista de fallas. La CI la corre en
/// el simulador: así se prueba lo que `swift test` no ve (archivos en el sandbox de iOS,
/// guardar y recuperar entre aperturas, importar el JSON del PC).
enum Autoprueba {
    static func correr() -> Int32 {
        var total = 0
        var fallas: [String] = []
        func check(_ ok: Bool, _ que: String) {
            total += 1
            print((ok ? "ok    " : "FALLA ") + que)
            if !ok { fallas.append(que) }
        }

        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("autoprueba-\(UUID().uuidString)")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)

        // --- plazos: crear, sumar, paso hecho, y que todo vuelva igual al reabrir ---
        let p = PlazosStore(carpeta: dir, guardarAjustes: false)
        let t = Tarea(nombre: "Informe T2", entrega: Date().addingTimeInterval(3 * 86400), horasEstimadas: 9,
                      horasHechas: 1, siguientePaso: "escribir la intro")
        p.guardarTarea(t)
        p.sumarHoras(t.id, 0.5)
        p.pasoHecho(t.id, horas: 0.25, nuevoPaso: "armar los 3 gráficos de resultados")
        let p2 = PlazosStore(carpeta: dir, guardarAjustes: false)
        check(p2.tareas.count == 1, "plazos: la entrega sigue ahí al reabrir")
        check(abs((p2.tarea(t.id)?.horasHechas ?? 0) - 1.75) < 1e-9, "plazos: horas 1 + 0,5 + 0,25 = 1,75")
        check(p2.tarea(t.id)?.siguientePaso == "armar los 3 gráficos de resultados", "plazos: siguiente paso nuevo")
        check(p2.datos.registro.count == 3, "plazos: tres entradas en el registro de horas")
        check(abs(horasRegistradas(p2.datos.registro, el: Date()) - 1.75) < 1e-9, "plazos: horas de hoy")

        // --- importar el plazos_datos.json del PC ---
        let pc = dir.appendingPathComponent("desde-el-pc.json")
        try? Data(base64Encoded: jsonEscritorio)?.write(to: pc)
        let traidas = (try? p2.importar(desde: pc)) ?? -1
        check(traidas == 2, "importar: trae las 2 entregas del archivo del PC (\(traidas))")
        check(p2.tarea("a1b2c3d4")?.nombre == "Informe T2 «redes»", "importar: tildes y comillas intactas")
        check(FileManager.default.fileExists(atPath: dir.appendingPathComponent(
            "plazos_datos.antes-de-importar.json").path), "importar: respalda lo que había")
        check(PlazosStore(carpeta: dir, guardarAjustes: false).tareas.count == 2, "importar: queda guardado")

        // --- foco: un ciclo completo con minutos de 10 ms ---
        let f = FocoStore(carpeta: dir, guardarAjustes: false, segundosPorMinuto: 0.01, avisar: false)
        f.config = ConfigFoco()
        check(!f.empezar(.foco, intencion: "   ") && !f.error.isEmpty, "foco: sin intención no arranca")
        check(f.empezar(.foco, intencion: "resolver ejercicios 1 a 3 de la guía"), "foco: arranca con intención")
        f.anotarDistraccion("responder a Pedro")
        check(esperar(f) { $0.sesion.espera == .resultado }, "foco: el bloque termina solo")
        f.cerrar(.terminado)
        check(f.sesion.fase == .descanso, "foco: después viene el descanso")
        check(esperar(f) { $0.sesion.fase == .listo }, "foco: el descanso termina solo")
        check(f.empezar(.arranque, intencion: "leer el paper hasta la sección 3"), "foco: «solo unos minutos»")
        check(esperar(f) { $0.sesion.espera == .seguir }, "foco: el arranque pregunta si sigues")
        f.seguir()
        check(f.sesion.fase == .foco && f.sesion.temporizador.corriendo, "foco: seguir lo convierte en bloque")
        // Reabrir a mitad de bloque (como si iOS hubiera cerrado la app): la sesión sigue.
        let reabierta = FocoStore(carpeta: dir, guardarAjustes: false, segundosPorMinuto: 0.01, avisar: false)
        check(reabierta.sesion.bloque?.intencion == "leer el paper hasta la sección 3",
              "foco: al reabrir, el bloque en curso sigue ahí")
        check(esperar(f) { $0.sesion.espera == .resultado }, "foco: el bloque largo termina")
        f.cerrar(.avance)
        let filas = RegistroFoco.leer(dir.appendingPathComponent(FocoStore.archivoRegistro))
        check(filas.map(\.resultado) == ["terminado", "avance"], "foco: registro CSV con los dos bloques")
        check(filas.map(\.minutosReales) == [25, 25], "foco: 25 minutos cada uno (\(filas.map(\.minutosReales)))")
        check(filas.first?.distracciones == 1, "foco: la distracción quedó contada")
        let otra = FocoStore(carpeta: dir, guardarAjustes: false, segundosPorMinuto: 0.01, avisar: false)
        check(otra.filas.count == 2 && otra.pendientes.count == 1, "foco: registro y «para después» al reabrir")
        check(otra.estadisticasHoy.bloquesHoy == 2, "foco: estadísticas de hoy")

        try? FileManager.default.removeItem(at: dir)
        print(fallas.isEmpty ? "AUTOPRUEBA OK \(total)/\(total)"
                             : "AUTOPRUEBA FALLA \(fallas.count) de \(total): \(fallas.joined(separator: "; "))")
        fflush(stdout)
        return fallas.isEmpty ? 0 : 1
    }

    /// Hace correr el reloj hasta que se cumpla la condición (máximo 5 s).
    private static func esperar(_ f: FocoStore, _ cond: (FocoStore) -> Bool) -> Bool {
        let limite = Date().addingTimeInterval(5)
        while Date() < limite {
            f.tic()
            if cond(f) { return true }
            Thread.sleep(forTimeInterval: 0.01)
        }
        return false
    }

    /// plazos_datos.json escrito por plazos.py (el mismo que usan las pruebas de Logica).
    private static let jsonEscritorio = """
    ewogICJ2ZXJzaW9uIjogMSwKICAidGFyZWFzIjogWwogICAgewogICAgICAibm9tYnJlIjogIkluZm9ybWUgVDIgwqtyZWRlc8K7IiwKICAgICAgImVudHJlZ2EiOiAiMjAyNi0xMC0xMlQxODowMCIsCiAgICAgICJob3Jhc19lc3RpbWFkYXMiOiA5LAogICAgICAiaG9yYXNfaGVjaGFzIjogMS41LAogICAgICAiY3Vyc28iOiAiSUVFMjU0NCIsCiAgICAgICJzaWd1aWVudGVfcGFzbyI6ICJlc2NyaWJpciBpbnRybzsgc2VjY2nDs24gXCIxXCIiLAogICAgICAiZW50cmVnYWRhIjogZmFsc2UsCiAgICAgICJpZCI6ICJhMWIyYzNkNCIsCiAgICAgICJjcmVhZGEiOiAiMjAyNi0xMC0wMVQxMDowMCIKICAgIH0sCiAgICB7CiAgICAgICJub21icmUiOiAiQ29udHJvbCAyIiwKICAgICAgImVudHJlZ2EiOiAiMjAyNi0xMC0xMFQyMzo1OSIsCiAgICAgICJob3Jhc19lc3RpbWFkYXMiOiA2LjUsCiAgICAgICJob3Jhc19oZWNoYXMiOiAxLjc1LAogICAgICAiY3Vyc28iOiAiIiwKICAgICAgInNpZ3VpZW50ZV9wYXNvIjogIiIsCiAgICAgICJlbnRyZWdhZGEiOiB0cnVlLAogICAgICAiaWQiOiAiZTVmNmE3YjgiLAogICAgICAiY3JlYWRhIjogIjIwMjYtMTAtMDJUMDk6MzAiCiAgICB9CiAgXSwKICAicmVnaXN0cm8iOiBbCiAgICB7CiAgICAgICJmZWNoYSI6ICIyMDI2LTEwLTA5VDE1OjIwIiwKICAgICAgInRhcmVhIjogImExYjJjM2Q0IiwKICAgICAgImhvcmFzIjogMS41CiAgICB9CiAgXQp9
    """
}
