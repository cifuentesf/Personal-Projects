import Foundation
import Logica

extension String {
    var recortado: String { trimmingCharacters(in: .whitespacesAndNewlines) }
}

/// Las entregas, guardadas en plazos_datos.json (el mismo formato que plazos.py).
final class PlazosStore: ObservableObject {
    static let archivo = "plazos_datos.json"

    @Published private(set) var datos = DatosPlazos()
    @Published var avisos: [String] = []
    @Published var capacidad: Double {
        didSet { if guardarAjustes { UserDefaults.standard.set(capacidad, forKey: "capacidad") } }
    }
    @Published var mostrarEntregadas: Bool {
        didSet { if guardarAjustes { UserDefaults.standard.set(mostrarEntregadas, forKey: "mostrarEntregadas") } }
    }

    let url: URL
    private let guardarAjustes: Bool

    init(carpeta: URL, guardarAjustes: Bool = true) {
        url = carpeta.appendingPathComponent(Self.archivo)
        self.guardarAjustes = guardarAjustes
        let cap = UserDefaults.standard.double(forKey: "capacidad")
        capacidad = (0.25...16).contains(cap) ? cap : 4
        mostrarEntregadas = UserDefaults.standard.bool(forKey: "mostrarEntregadas")
        recargar()
    }

    var tareas: [Tarea] { datos.tareas }

    func tarea(_ id: String) -> Tarea? { datos.tareas.first { $0.id == id } }

    func visibles(ahora: Date) -> [Tarea] {
        ordenar(datos.tareas.filter { mostrarEntregadas || !$0.entregada }, ahora: ahora, capacidad: capacidad)
    }

    func recargar() {
        let (d, a) = ArchivoPlazos.cargar(url)
        datos = d
        avisos += a
    }

    private func guardar() {
        do {
            try ArchivoPlazos.guardar(datos, en: url)
        } catch {
            avisos.append("No se pudo guardar \(Self.archivo): \(error.localizedDescription)")
        }
    }

    /// Nueva o editada. Si una nueva ya trae horas hechas, quedan también en el registro
    /// (como en escritorio): así la entrega y el registro nunca discrepan.
    func guardarTarea(_ t: Tarea) {
        var d = datos
        if let i = d.tareas.firstIndex(where: { $0.id == t.id }) {
            d.tareas[i] = t
        } else {
            d.tareas.append(t)
            if t.horasHechas > 0 {
                d.registro.append(RegistroHoras(fecha: FechaISO.textoMinutos(Date()), tarea: t.id,
                                                horas: t.horasHechas, inicial: true))
            }
        }
        datos = d
        guardar()
    }

    func eliminar(_ id: String) {
        datos.tareas.removeAll { $0.id == id }
        guardar()
    }

    func sumarHoras(_ id: String, _ horas: Double) {
        var d = datos
        guard let i = d.tareas.firstIndex(where: { $0.id == id }) else { return }
        registrarHoras(&d.tareas[i], &d.registro, horas: horas, ahora: Date())
        datos = d
        guardar()
    }

    func pasoHecho(_ id: String, horas: Double, nuevoPaso: String) {
        var d = datos
        guard let i = d.tareas.firstIndex(where: { $0.id == id }) else { return }
        if horas > 0 { registrarHoras(&d.tareas[i], &d.registro, horas: horas, ahora: Date()) }
        d.tareas[i].siguientePaso = nuevoPaso
        datos = d
        guardar()
    }

    func alternarEntregada(_ id: String) {
        guard let i = datos.tareas.firstIndex(where: { $0.id == id }) else { return }
        datos.tareas[i].entregada.toggle()
        guardar()
    }

    /// Reemplaza todo con el archivo elegido (por ejemplo, el plazos_datos.json del PC).
    /// Lo que había queda respaldado al lado. Devuelve cuántas entregas trajo.
    @discardableResult
    func importar(desde origen: URL) throws -> Int {
        let acceso = origen.startAccessingSecurityScopedResource()
        defer { if acceso { origen.stopAccessingSecurityScopedResource() } }
        let (d, a) = try ArchivoPlazos.decodificar(Data(contentsOf: origen))
        let fm = FileManager.default
        if fm.fileExists(atPath: url.path) {
            let respaldo = url.deletingLastPathComponent().appendingPathComponent("plazos_datos.antes-de-importar.json")
            try? fm.removeItem(at: respaldo)
            try? fm.copyItem(at: url, to: respaldo)
        }
        datos = d
        avisos += a
        guardar()
        return d.tareas.count
    }
}

/// Bloques de foco. El registro y la lista «para después» son los mismos archivos que foco.py;
/// la sesión en curso se guarda aparte para sobrevivir si iOS cierra la app a mitad de un bloque.
final class FocoStore: ObservableObject {
    static let archivoRegistro = "foco_registro.csv"
    static let archivoPendientes = "foco_para_despues.txt"
    static let archivoSesion = "foco_sesion.json"

    @Published private(set) var sesion: SesionFoco
    @Published var config: ConfigFoco {
        didSet {
            let v = config.validada()
            if v != config { config = v }
            if guardarAjustes, let d = try? JSONEncoder().encode(config) {
                UserDefaults.standard.set(d, forKey: "configFoco")
            }
        }
    }
    @Published private(set) var filas: [Bloque] = []
    @Published private(set) var pendientes: [String] = []
    @Published var error = ""
    @Published private(set) var ahora = Date()

    let carpeta: URL
    private let guardarAjustes: Bool
    private let avisar: Bool

    init(carpeta: URL, guardarAjustes: Bool = true, segundosPorMinuto: Double = 60, avisar: Bool = true) {
        self.carpeta = carpeta
        self.guardarAjustes = guardarAjustes
        self.avisar = avisar
        var cfg = ConfigFoco()
        if let d = UserDefaults.standard.data(forKey: "configFoco"),
           let guardada = try? JSONDecoder().decode(ConfigFoco.self, from: d) {
            cfg = guardada.validada()
        }
        config = cfg
        var s = SesionFoco(segundosPorMinuto: segundosPorMinuto)
        if let d = try? Data(contentsOf: carpeta.appendingPathComponent(Self.archivoSesion)),
           let guardada = try? JSONDecoder().decode(SesionFoco.self, from: d) {
            s = guardada
            s.segundosPorMinuto = segundosPorMinuto
        }
        sesion = s
        filas = RegistroFoco.leer(urlRegistro)
        pendientes = Pendientes.leer(urlPendientes)
        tic()
    }

    var urlRegistro: URL { carpeta.appendingPathComponent(Self.archivoRegistro) }
    var urlPendientes: URL { carpeta.appendingPathComponent(Self.archivoPendientes) }
    var urlSesion: URL { carpeta.appendingPathComponent(Self.archivoSesion) }

    var estadisticasHoy: Estadisticas { estadisticas(filas, hoy: ahora) }

    var sugerenciaPrevia: String { sesion.ultimaIntencion }

    // MARK: acciones

    func tic() {
        let t = Date()
        ahora = t
        var s = sesion
        _ = s.tic(ahora: t)
        if s != sesion {
            sesion = s
            persistir()
        }
    }

    @discardableResult
    func empezar(_ tipo: Fase, intencion: String) -> Bool {
        var s = sesion
        do {
            try s.empezar(tipo, intencion: intencion, config: config, ahora: Date())
        } catch {
            self.error = error.localizedDescription
            return false
        }
        self.error = ""
        sesion = s
        persistir()
        if avisar { Avisos.pedirPermiso() }
        programarAviso()
        return true
    }

    func alternarPausa() { mutar { s, t in s.alternarPausa(ahora: t) } }
    func terminarAntes() { mutar { s, t in s.terminarAntes(ahora: t) } }
    func saltarDescanso() { mutar { s, _ in s.saltarDescanso() } }

    func seguir() {
        let cfg = config
        mutar { s, t in s.seguir(config: cfg, ahora: t) }
    }

    func cerrar(_ resultado: Resultado) {
        let cfg = config
        var fila: Bloque?
        mutar { s, t in fila = s.cerrar(resultado, config: cfg, ahora: t) }
        if let f = fila { anotar(f) }
    }

    func abandonar() {
        var fila: Bloque?
        mutar { s, t in fila = s.abandonar(ahora: t) }
        if let f = fila { anotar(f) }
    }

    func anotarDistraccion(_ texto: String) {
        guard !unaLinea(texto).isEmpty else { return }
        do {
            try Pendientes.anotar(texto, ahora: Date(), en: urlPendientes)
        } catch {
            self.error = "No se pudo anotar: \(error.localizedDescription)"
            return
        }
        pendientes = Pendientes.leer(urlPendientes)
        mutar { s, _ in s.anotarDistraccion() }
    }

    func borrarPendiente(_ i: Int) {
        var l = pendientes
        guard l.indices.contains(i) else { return }
        l.remove(at: i)
        try? Pendientes.guardar(l, en: urlPendientes)
        pendientes = Pendientes.leer(urlPendientes)
    }

    func vaciarPendientes() {
        try? Pendientes.guardar([], en: urlPendientes)
        pendientes = []
    }

    // MARK: internos

    private func mutar(_ cambio: (inout SesionFoco, Date) -> Void) {
        let t = Date()
        ahora = t
        var s = sesion
        cambio(&s, t)
        sesion = s
        persistir()
        programarAviso()
    }

    private func anotar(_ f: Bloque) {
        do {
            try RegistroFoco.anotar(f, en: urlRegistro)
            filas.append(f)
        } catch {
            self.error = "No se pudo guardar el registro: \(error.localizedDescription)"
        }
    }

    private func persistir() {
        if let d = try? JSONEncoder().encode(sesion) { try? d.write(to: urlSesion, options: .atomic) }
    }

    /// Un solo aviso pendiente a la vez: el del fin de lo que esté corriendo ahora.
    private func programarAviso() {
        guard avisar else { return }
        guard let fin = sesion.temporizador.fin(ahora: Date()) else {
            Avisos.cancelar()
            return
        }
        let titulo: String
        let cuerpo: String
        switch sesion.fase {
        case .foco:
            titulo = "Terminó el bloque"
            cuerpo = "¿Cómo te fue con «\(sesion.bloque?.intencion ?? "")»?"
        case .arranque:
            titulo = "Pasaron los \(config.arranqueMin) minutos"
            cuerpo = "Lo difícil era empezar, y ya empezaste. ¿Sigues?"
        case .descanso, .descansoLargo:
            titulo = "Terminó el descanso"
            cuerpo = "¿Qué sigue?"
        case .listo:
            Avisos.cancelar()
            return
        }
        Avisos.programar(para: fin, titulo: titulo, cuerpo: cuerpo, sonido: config.sonido)
    }
}
