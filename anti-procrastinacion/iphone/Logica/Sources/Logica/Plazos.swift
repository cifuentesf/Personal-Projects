import Foundation

// MARK: - Modelo (mismo JSON que plazos.py: el archivo pasa de un lado a otro sin conversión)

public struct Tarea: Identifiable, Equatable, Codable {
    public var id: String
    public var nombre: String
    public var entrega: Date
    public var horasEstimadas: Double
    public var horasHechas: Double
    public var curso: String
    public var siguientePaso: String
    public var entregada: Bool
    public var creada: String

    public init(nombre: String, entrega: Date, horasEstimadas: Double, horasHechas: Double = 0,
                curso: String = "", siguientePaso: String = "", entregada: Bool = false,
                id: String = Tarea.nuevoId(), creada: String = FechaISO.textoMinutos(Date())) {
        self.id = id
        self.nombre = nombre
        self.entrega = entrega
        self.horasEstimadas = horasEstimadas
        self.horasHechas = horasHechas
        self.curso = curso
        self.siguientePaso = siguientePaso
        self.entregada = entregada
        self.creada = creada
    }

    public static func nuevoId() -> String {
        String(UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased().prefix(8))
    }

    enum CodingKeys: String, CodingKey {
        case nombre, entrega, curso, entregada, id, creada
        case horasEstimadas = "horas_estimadas"
        case horasHechas = "horas_hechas"
        case siguientePaso = "siguiente_paso"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        nombre = try c.decode(String.self, forKey: .nombre).trimmingCharacters(in: .whitespacesAndNewlines)
        let texto = try c.decode(String.self, forKey: .entrega)
        guard let fecha = FechaISO.leer(texto) else {
            throw DecodingError.dataCorruptedError(forKey: .entrega, in: c,
                                                   debugDescription: "fecha inválida: \(texto)")
        }
        entrega = fecha
        horasEstimadas = try c.decode(Double.self, forKey: .horasEstimadas)
        horasHechas = try c.decodeIfPresent(Double.self, forKey: .horasHechas) ?? 0
        curso = try c.decodeIfPresent(String.self, forKey: .curso) ?? ""
        siguientePaso = try c.decodeIfPresent(String.self, forKey: .siguientePaso) ?? ""
        entregada = try c.decodeIfPresent(Bool.self, forKey: .entregada) ?? false
        id = try c.decodeIfPresent(String.self, forKey: .id) ?? Tarea.nuevoId()
        creada = try c.decodeIfPresent(String.self, forKey: .creada) ?? FechaISO.textoMinutos(Date())
        if nombre.isEmpty || horasEstimadas < 0 || horasHechas < 0 {
            throw DecodingError.dataCorrupted(.init(codingPath: c.codingPath,
                                                    debugDescription: "nombre vacío u horas negativas"))
        }
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(nombre, forKey: .nombre)
        try c.encode(FechaISO.textoMinutos(entrega), forKey: .entrega)
        try c.encode(horasEstimadas, forKey: .horasEstimadas)
        try c.encode(horasHechas, forKey: .horasHechas)
        try c.encode(curso, forKey: .curso)
        try c.encode(siguientePaso, forKey: .siguientePaso)
        try c.encode(entregada, forKey: .entregada)
        try c.encode(id, forKey: .id)
        try c.encode(creada, forKey: .creada)
    }
}

public struct RegistroHoras: Codable, Equatable {
    public var fecha: String
    public var tarea: String
    public var horas: Double
    public var inicial: Bool?

    public init(fecha: String, tarea: String, horas: Double, inicial: Bool? = nil) {
        self.fecha = fecha
        self.tarea = tarea
        self.horas = horas
        self.inicial = inicial
    }
}

public struct DatosPlazos: Equatable {
    public var tareas: [Tarea]
    public var registro: [RegistroHoras]
    public init(tareas: [Tarea] = [], registro: [RegistroHoras] = []) {
        self.tareas = tareas
        self.registro = registro
    }
}

/// Decodifica cada elemento por separado: uno dañado se salta con aviso, no arrastra a los demás.
struct Tolerante<T: Decodable>: Decodable {
    let valor: T?
    let error: String?
    init(from decoder: Decoder) throws {
        do {
            valor = try T(from: decoder)
            error = nil
        } catch {
            valor = nil
            self.error = Tolerante.describir(error)
        }
    }

    static func describir(_ error: Error) -> String {
        if case let DecodingError.dataCorrupted(ctx) = error { return ctx.debugDescription }
        if case let DecodingError.keyNotFound(clave, _) = error { return "falta «\(clave.stringValue)»" }
        if case let DecodingError.typeMismatch(_, ctx) = error {
            return "tipo inesperado en «\(ctx.codingPath.map(\.stringValue).joined(separator: "."))»"
        }
        return "\(error)"
    }
}

public enum ArchivoPlazos {
    struct Entrada: Decodable {
        var tareas: [Tolerante<Tarea>]?
        var registro: [Tolerante<RegistroHoras>]?
    }

    struct Salida: Encodable {
        var version = 1
        var tareas: [Tarea]
        var registro: [RegistroHoras]
    }

    /// (datos, avisos). Lanza solo si el JSON entero es ilegible.
    public static func decodificar(_ data: Data) throws -> (DatosPlazos, [String]) {
        let entrada = try JSONDecoder().decode(Entrada.self, from: data)
        var avisos: [String] = []
        var tareas: [Tarea] = []
        for (i, t) in (entrada.tareas ?? []).enumerated() {
            if let v = t.valor { tareas.append(v) } else {
                avisos.append("Tarea \(i + 1) ignorada por datos inválidos: \(t.error ?? "")")
            }
        }
        let registro = (entrada.registro ?? []).compactMap(\.valor)
        return (DatosPlazos(tareas: tareas, registro: registro), avisos)
    }

    public static func codificar(_ datos: DatosPlazos) throws -> Data {
        let e = JSONEncoder()
        e.outputFormatting = [.prettyPrinted, .withoutEscapingSlashes]
        return try e.encode(Salida(tareas: datos.tareas, registro: datos.registro))
    }

    /// Nunca lanza: un archivo dañado se aparta a «.corrupto-…» y se empieza vacío, con aviso.
    public static func cargar(_ url: URL) -> (DatosPlazos, [String]) {
        guard FileManager.default.fileExists(atPath: url.path) else { return (DatosPlazos(), []) }
        do {
            return try decodificar(try Data(contentsOf: url))
        } catch {
            let sello = FechaISO.textoSegundos(Date()).replacingOccurrences(of: ":", with: "")
            let respaldo = url.deletingPathExtension()
                .appendingPathExtension("corrupto-\(sello).json")
            if (try? FileManager.default.moveItem(at: url, to: respaldo)) != nil {
                return (DatosPlazos(), ["\(url.lastPathComponent) estaba dañado; lo moví a "
                                        + "\(respaldo.lastPathComponent) y empecé vacío."])
            }
            return (DatosPlazos(), ["\(url.lastPathComponent) está dañado y no pude moverlo."])
        }
    }

    /// Escritura atómica: nunca queda un JSON a medias.
    public static func guardar(_ datos: DatosPlazos, en url: URL) throws {
        try codificar(datos).write(to: url, options: .atomic)
    }
}

// MARK: - Cálculo de presión (igual que plazos.py)

public enum Estado: String, CaseIterable {
    case vencida, imposible, rojo, amarillo, verde, lista

    public var texto: String {
        switch self {
        case .vencida: return "vencida"
        case .imposible: return "no alcanza"
        case .rojo: return "sobre tu ritmo"
        case .amarillo: return "ajustada"
        case .verde: return "holgada"
        case .lista: return "lista"
        }
    }
}

public struct Analisis: Equatable {
    public var estado: Estado
    public var horasReloj: Double      // horas de calendario hasta la entrega (negativo si venció)
    public var faltan: Double          // horas de trabajo pendientes
    public var hoy: Double             // horas que tocan hoy para ir al día a ritmo parejo
    public var siPostergas: Double?    // h/día desde mañana si hoy no avanzas; nil = vence antes
    public var carga: Double           // hoy / capacidad diaria
}

/// Supone ritmo parejo: lo que falta se reparte entre los días que quedan.
/// Si queda menos de un día, todo lo que falta toca hoy.
public func analizar(_ t: Tarea, ahora: Date, capacidad: Double) -> Analisis {
    let horasReloj = t.entrega.timeIntervalSince(ahora) / 3600
    let faltan = max(0, t.horasEstimadas - t.horasHechas)
    if faltan < 1e-9 {
        return Analisis(estado: .lista, horasReloj: horasReloj, faltan: 0, hoy: 0, siPostergas: 0, carga: 0)
    }
    if horasReloj <= 0 {
        return Analisis(estado: .vencida, horasReloj: horasReloj, faltan: faltan, hoy: 0, siPostergas: nil,
                        carga: 0)
    }
    let dias = horasReloj / 24
    let hoy = faltan / max(dias, 1)
    let siPostergas: Double? = dias > 1 ? faltan / max(dias - 1, 1) : nil
    let carga = capacidad > 0 ? hoy / capacidad : Double.infinity
    let estado: Estado
    if faltan > horasReloj {
        estado = .imposible
    } else if carga > 1 {
        estado = .rojo
    } else if carga > 0.5 {
        estado = .amarillo
    } else {
        estado = .verde
    }
    return Analisis(estado: estado, horasReloj: horasReloj, faltan: faltan, hoy: hoy,
                    siPostergas: siPostergas, carga: carga)
}

public struct Resumen: Equatable {
    public var hoyTotal: Double
    public var mananaTotal: Double
    public var sePierden: Int
    public var vencidas: Int
    public var activas: Int
    public var capacidad: Double
}

public func resumir(_ tareas: [Tarea], ahora: Date, capacidad: Double) -> Resumen {
    var r = Resumen(hoyTotal: 0, mananaTotal: 0, sePierden: 0, vencidas: 0, activas: 0, capacidad: capacidad)
    for t in tareas where !t.entregada {
        let a = analizar(t, ahora: ahora, capacidad: capacidad)
        switch a.estado {
        case .lista:
            continue
        case .vencida:
            r.vencidas += 1
        default:
            r.activas += 1
            r.hoyTotal += a.hoy
            if let p = a.siPostergas { r.mananaTotal += p } else { r.sePierden += 1 }
        }
    }
    return r
}

/// Primero lo que exige una decisión (vencidas), luego por fecha, al final listas y entregadas.
public func ordenar(_ tareas: [Tarea], ahora: Date, capacidad: Double) -> [Tarea] {
    func clave(_ t: Tarea) -> (Int, Int, Date) {
        let e = analizar(t, ahora: ahora, capacidad: capacidad).estado
        let grupo = e == .vencida ? 0 : (e == .lista ? 5 : 2)
        return (t.entregada ? 1 : 0, grupo, t.entrega)
    }
    return tareas.sorted { clave($0) < clave($1) }
}

/// Las dos líneas de arriba de la pantalla.
public func textoResumen(_ r: Resumen) -> (String, String) {
    if r.activas == 0 {
        var l1 = "Nada pendiente con trabajo por hacer."
        if r.vencidas > 0 { l1 += " Hay \(r.vencidas) vencida(s) sin cerrar." }
        return (l1, r.vencidas > 0 ? "" : "Agrega una entrega con «+».")
    }
    let l1 = "Hoy necesitas \(formatoHoras(r.hoyTotal)) para ir al día con todo "
        + "(tu capacidad: \(formatoHoras(r.capacidad)))"
    var partes: [String] = []
    if r.mananaTotal > 0 { partes.append("desde mañana necesitarías \(formatoHoras(r.mananaTotal)) al día") }
    if r.sePierden > 0 { partes.append("\(r.sePierden) entrega(s) vencerían antes de mañana") }
    let l2 = partes.isEmpty ? "" : "Si hoy no avanzas nada: " + partes.joined(separator: " y ") + "."
    return (l1, l2)
}

func redondear4(_ x: Double) -> Double { (x * 10000).rounded() / 10000 }

public func registrarHoras(_ tarea: inout Tarea, _ registro: inout [RegistroHoras], horas: Double, ahora: Date) {
    tarea.horasHechas = redondear4(tarea.horasHechas + horas)
    registro.append(RegistroHoras(fecha: FechaISO.textoMinutos(ahora), tarea: tarea.id, horas: redondear4(horas)))
}

public func horasRegistradas(_ registro: [RegistroHoras], el dia: Date, calendario: Calendar = .current) -> Double {
    registro.reduce(0) { suma, r in
        guard let f = FechaISO.leer(r.fecha), calendario.isDate(f, inSameDayAs: dia) else { return suma }
        return suma + r.horas
    }
}

/// «siguiente paso — entrega» de las entregas abiertas, la más próxima primero (para foco).
public func sugerenciasDePlazos(_ tareas: [Tarea]) -> [String] {
    tareas
        .filter { !$0.entregada && !$0.siguientePaso.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
        .sorted { $0.entrega < $1.entrega }
        .map { "\($0.siguientePaso.trimmingCharacters(in: .whitespacesAndNewlines)) — \($0.nombre)" }
}
