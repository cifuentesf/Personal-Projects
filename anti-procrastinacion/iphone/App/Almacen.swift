import Foundation
import UserNotifications
import Logica

/// Dónde viven los datos. Son los mismos archivos que usan las apps de escritorio:
/// desde la app Archivos (En mi iPhone → Al día) se pueden copiar al PC y de vuelta.
enum Almacen {
    static func carpetaDocumentos() -> URL {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
    }

    static func carpetaDemo() -> URL {
        let d = FileManager.default.temporaryDirectory.appendingPathComponent("demo", isDirectory: true)
        try? FileManager.default.removeItem(at: d)
        try? FileManager.default.createDirectory(at: d, withIntermediateDirectories: true)
        return d
    }

    static func sembrarDemo(en dir: URL) {
        let ahora = Date()
        func en(_ horas: Double) -> Date { ahora.addingTimeInterval(horas * 3600) }
        let tareas = [
            Tarea(nombre: "Informe T2", entrega: en(70), horasEstimadas: 9, horasHechas: 2, curso: "IEE2544",
                  siguientePaso: "escribir la sección de resultados con los 3 gráficos"),
            Tarea(nombre: "Control 2", entrega: en(30), horasEstimadas: 6, horasHechas: 1, curso: "IEE3951",
                  siguientePaso: "hacer los 4 ejercicios de la guía 5"),
            Tarea(nombre: "Tarea 3", entrega: en(200), horasEstimadas: 8, curso: "IEE2544"),
            Tarea(nombre: "Lectura paper", entrega: en(-5), horasEstimadas: 2, siguientePaso: "leer secciones 1 y 2"),
        ]
        let registro = [RegistroHoras(fecha: FechaISO.textoMinutos(ahora), tarea: tareas[0].id, horas: 1.5)]
        try? ArchivoPlazos.guardar(DatosPlazos(tareas: tareas, registro: registro),
                                   en: dir.appendingPathComponent(PlazosStore.archivo))
        let cal = Calendar.current
        let csv = dir.appendingPathComponent(FocoStore.archivoRegistro)
        for (diasAtras, minutos) in [(6, 25), (5, 50), (3, 75), (2, 25), (1, 100), (0, 50)] {
            let dia = cal.date(byAdding: .day, value: -diasAtras, to: cal.startOfDay(for: ahora))!
            for k in 0..<(minutos / 25) {
                let ini = dia.addingTimeInterval(Double((9 + k) * 3600))
                try? RegistroFoco.anotar(Bloque(inicio: ini, fin: ini.addingTimeInterval(1500), tipo: "foco",
                                                minutosPlaneados: 25, minutosReales: 25, intencion: "demo",
                                                resultado: "terminado", distracciones: 0), en: csv)
            }
        }
        try? Pendientes.anotar("responder correo del ayudante", ahora: ahora,
                               en: dir.appendingPathComponent(FocoStore.archivoPendientes))
    }
}

/// Aviso local cuando termina un bloque o un descanso, aunque el iPhone esté bloqueado.
enum Avisos {
    static let id = "foco-fin"

    static func pedirPermiso() {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }
    }

    static func programar(para fin: Date, titulo: String, cuerpo: String, sonido: Bool) {
        let centro = UNUserNotificationCenter.current()
        centro.removePendingNotificationRequests(withIdentifiers: [id])
        let contenido = UNMutableNotificationContent()
        contenido.title = titulo
        contenido.body = cuerpo
        if sonido { contenido.sound = .default }
        let disparador = UNTimeIntervalNotificationTrigger(timeInterval: max(1, fin.timeIntervalSinceNow),
                                                           repeats: false)
        centro.add(UNNotificationRequest(identifier: id, content: contenido, trigger: disparador))
    }

    static func cancelar() {
        UNUserNotificationCenter.current().removePendingNotificationRequests(withIdentifiers: [id])
    }
}
