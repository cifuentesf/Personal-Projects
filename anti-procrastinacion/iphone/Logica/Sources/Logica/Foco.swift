import Foundation

// MARK: - Temporizador
//
// En iPhone la app se suspende al bloquear la pantalla: el tiempo se calcula contra
// la hora (Date), no contando tics, así al volver marca lo que corresponde.

public struct Temporizador: Codable, Equatable {
    public var duracion: Double = 0
    public var inicio: Date?
    public var acumulado: Double = 0

    public init() {}

    public var corriendo: Bool { inicio != nil }

    public mutating func iniciar(_ segundos: Double, ahora: Date) {
        duracion = segundos
        acumulado = 0
        inicio = ahora
    }

    /// Acotado a la duración: si el fin se nota tarde (app suspendida), ese tiempo no cuenta;
    /// si no, «Seguir» tras el arranque terminaría el bloque al instante.
    public mutating func pausar(ahora: Date) {
        if let i = inicio {
            acumulado = min(acumulado + ahora.timeIntervalSince(i), duracion)
            inicio = nil
        }
    }

    public mutating func reanudar(ahora: Date) {
        if inicio == nil && duracion > 0 { inicio = ahora }
    }

    public mutating func extender(_ segundos: Double) { duracion += segundos }

    public func transcurrido(ahora: Date) -> Double {
        acumulado + (inicio.map { ahora.timeIntervalSince($0) } ?? 0)
    }

    public func restante(ahora: Date) -> Double { max(0, duracion - transcurrido(ahora: ahora)) }

    public func terminado(ahora: Date) -> Bool { duracion > 0 && transcurrido(ahora: ahora) >= duracion }

    /// Cuándo termina si sigue corriendo (para programar la notificación).
    public func fin(ahora: Date) -> Date? { corriendo ? ahora.addingTimeInterval(restante(ahora: ahora)) : nil }
}

/// 24:59,2 se muestra 25:00: nunca marca 00:00 antes de tiempo.
public func formatoMMSS(_ segundos: Double) -> String {
    let s = Int(max(0, segundos) + 0.999)
    let (m, seg) = (s / 60, s % 60)
    if m >= 60 { return "\(m / 60):\(dos(m % 60)):\(dos(seg))" }
    return "\(dos(m)):\(dos(seg))"
}

public func formatoMinutos(_ m: Int) -> String {
    if m < 60 { return "\(m) min" }
    return m % 60 == 0 ? "\(m / 60) h" : "\(m / 60) h \(m % 60) min"
}

// MARK: - Configuración

public struct ConfigFoco: Codable, Equatable {
    public var focoMin = 25
    public var descansoMin = 5
    public var descansoLargoMin = 15
    public var bloquesHastaLargo = 4
    public var arranqueMin = 5
    public var sonido = true

    public init() {}

    public static let rangoFoco = 5...180
    public static let rangoDescanso = 1...60
    public static let rangoDescansoLargo = 1...90
    public static let rangoBloques = 2...8
    public static let rangoArranque = 1...15

    /// Fuera de rango vuelve al valor por omisión; el arranque siempre más corto que el bloque.
    public func validada() -> ConfigFoco {
        let d = ConfigFoco()
        var c = self
        if !Self.rangoFoco.contains(c.focoMin) { c.focoMin = d.focoMin }
        if !Self.rangoDescanso.contains(c.descansoMin) { c.descansoMin = d.descansoMin }
        if !Self.rangoDescansoLargo.contains(c.descansoLargoMin) { c.descansoLargoMin = d.descansoLargoMin }
        if !Self.rangoBloques.contains(c.bloquesHastaLargo) { c.bloquesHastaLargo = d.bloquesHastaLargo }
        if !Self.rangoArranque.contains(c.arranqueMin) { c.arranqueMin = d.arranqueMin }
        if c.arranqueMin >= c.focoMin { c.arranqueMin = min(d.arranqueMin, c.focoMin - 1) }
        return c
    }
}

// MARK: - Sesión: la máquina de estados de foco.py, sin interfaz

public enum Fase: String, Codable {
    case listo, foco, arranque, descanso
    case descansoLargo = "descanso_largo"

    public var nombre: String {
        switch self {
        case .listo: return "Listo para empezar"
        case .foco: return "Foco"
        case .arranque: return "Solo unos minutos"
        case .descanso: return "Descanso"
        case .descansoLargo: return "Descanso largo"
        }
    }
}

public enum Espera: String, Codable {
    case resultado   // terminó el bloque: ¿cómo te fue?
    case seguir      // terminó el arranque: ¿sigues?
}

public enum Resultado: String, Codable, CaseIterable {
    case terminado
    case avance
    case sinAvance = "sin_avance"
    case abandonado

    public var texto: String {
        switch self {
        case .terminado: return "Lo terminé"
        case .avance: return "Avancé"
        case .sinAvance: return "No avancé"
        case .abandonado: return "Abandonado"
        }
    }
}

public func siguienteDescanso(_ completados: Int, cada: Int) -> Fase {
    completados > 0 && completados % max(1, cada) == 0 ? .descansoLargo : .descanso
}

public struct BloqueEnCurso: Codable, Equatable {
    public var inicio: Date
    public var tipo: Fase            // .foco o .arranque
    public var minutosPlaneados: Int
    public var intencion: String
    public var distracciones: Int
}

/// Una fila del registro (mismas columnas que foco_registro.csv de escritorio).
public struct Bloque: Equatable {
    public var inicio: Date
    public var fin: Date
    public var tipo: String
    public var minutosPlaneados: Int
    public var minutosReales: Int
    public var intencion: String
    public var resultado: String
    public var distracciones: Int

    public init(inicio: Date, fin: Date, tipo: String, minutosPlaneados: Int, minutosReales: Int,
                intencion: String, resultado: String, distracciones: Int) {
        self.inicio = inicio
        self.fin = fin
        self.tipo = tipo
        self.minutosPlaneados = minutosPlaneados
        self.minutosReales = minutosReales
        self.intencion = intencion
        self.resultado = resultado
        self.distracciones = distracciones
    }

    public var valido: Bool { resultado != Resultado.abandonado.rawValue && minutosReales >= 5 }
}

public enum EventoFoco: Equatable {
    case finFoco, finArranque, finDescanso
}

public struct SesionFoco: Codable, Equatable {
    public var fase: Fase = .listo
    public var espera: Espera?
    public var temporizador = Temporizador()
    public var bloque: BloqueEnCurso?
    public var completados = 0
    public var mensaje = ""
    public var ultimaIntencion = ""
    /// 60 en uso normal; las pruebas lo bajan para que un «minuto» dure milisegundos.
    public var segundosPorMinuto: Double = 60

    public init(segundosPorMinuto: Double = 60) { self.segundosPorMinuto = segundosPorMinuto }

    public var enBloque: Bool { fase == .foco || fase == .arranque }
    public var enDescanso: Bool { fase == .descanso || fase == .descansoLargo }
    public var enPausa: Bool { enBloque && espera == nil && !temporizador.corriendo }

    public mutating func empezar(_ tipo: Fase, intencion: String, config: ConfigFoco, ahora: Date) throws {
        let texto = unaLinea(intencion)
        guard !texto.isEmpty else {
            throw ErrorEntrada("Escribe qué vas a hacer. Sin eso, al final no sabrás si lo hiciste.")
        }
        let arranque = tipo == .arranque
        let minutos = arranque ? config.arranqueMin : config.focoMin
        bloque = BloqueEnCurso(inicio: ahora, tipo: arranque ? .arranque : .foco, minutosPlaneados: minutos,
                               intencion: texto, distracciones: 0)
        ultimaIntencion = texto
        temporizador.iniciar(Double(minutos) * segundosPorMinuto, ahora: ahora)
        fase = arranque ? .arranque : .foco
        espera = nil
        mensaje = ""
    }

    /// Avanza el reloj. Devuelve qué terminó, si terminó algo.
    public mutating func tic(ahora: Date) -> EventoFoco? {
        guard temporizador.corriendo, temporizador.terminado(ahora: ahora) else { return nil }
        temporizador.pausar(ahora: ahora)
        switch fase {
        case .foco:
            espera = .resultado
            return .finFoco
        case .arranque:
            espera = .seguir
            return .finArranque
        case .descanso, .descansoLargo:
            irAListo("Terminó el descanso. ¿Qué sigue?")
            return .finDescanso
        case .listo:
            return nil
        }
    }

    public mutating func alternarPausa(ahora: Date) {
        guard enBloque, espera == nil else { return }
        if temporizador.corriendo { temporizador.pausar(ahora: ahora) } else { temporizador.reanudar(ahora: ahora) }
    }

    public mutating func terminarAntes(ahora: Date) {
        guard enBloque, bloque != nil else { return }
        temporizador.pausar(ahora: ahora)
        espera = .resultado
    }

    /// Tras «Solo 5 minutos»: el arranque se convierte en un bloque completo.
    public mutating func seguir(config: ConfigFoco, ahora: Date) {
        guard fase == .arranque, espera == .seguir, var b = bloque else { return }
        b.tipo = .foco
        b.minutosPlaneados = config.focoMin
        bloque = b
        temporizador.extender(Double(config.focoMin - config.arranqueMin) * segundosPorMinuto)
        temporizador.reanudar(ahora: ahora)
        fase = .foco
        espera = nil
    }

    /// Acotado a la duración: si el teléfono estuvo bloqueado, no anota horas fantasma.
    public func minutosReales(ahora: Date) -> Int {
        Int((min(temporizador.transcurrido(ahora: ahora), temporizador.duracion) / segundosPorMinuto).rounded())
    }

    private func fila(_ resultado: Resultado, ahora: Date) -> Bloque? {
        guard let b = bloque else { return nil }
        return Bloque(inicio: b.inicio, fin: ahora, tipo: b.tipo.rawValue, minutosPlaneados: b.minutosPlaneados,
                      minutosReales: minutosReales(ahora: ahora), intencion: b.intencion,
                      resultado: resultado.rawValue, distracciones: b.distracciones)
    }

    /// Anota el resultado y empieza el descanso. Devuelve la fila para el registro.
    public mutating func cerrar(_ resultado: Resultado, config: ConfigFoco, ahora: Date) -> Bloque? {
        guard let f = fila(resultado, ahora: ahora) else { return nil }
        completados += 1
        let tipo = siguienteDescanso(completados, cada: config.bloquesHastaLargo)
        let minutos = tipo == .descansoLargo ? config.descansoLargoMin : config.descansoMin
        bloque = nil
        espera = nil
        temporizador.iniciar(Double(minutos) * segundosPorMinuto, ahora: ahora)
        fase = tipo
        switch resultado {
        case .terminado: mensaje = "Bien hecho."
        case .avance: mensaje = "Avanzaste: eso cuenta."
        default: mensaje = "Pasa. Para el próximo, elige algo más chico."
        }
        return f
    }

    /// Menos de un minuto no se anota: fue un inicio por error.
    public mutating func abandonar(ahora: Date) -> Bloque? {
        guard bloque != nil else { return nil }
        let f = minutosReales(ahora: ahora) >= 1 ? fila(.abandonado, ahora: ahora) : nil
        irAListo("Bloque abandonado. Si fue por algo urgente, bien; si no, prueba con «Solo unos minutos».")
        return f
    }

    public mutating func saltarDescanso() {
        guard enDescanso else { return }
        irAListo("Descanso saltado.")
    }

    public mutating func anotarDistraccion() {
        bloque?.distracciones += 1
    }

    mutating func irAListo(_ mensaje: String) {
        temporizador = Temporizador()
        bloque = nil
        espera = nil
        fase = .listo
        self.mensaje = mensaje
    }
}

// MARK: - Registro CSV (el mismo foco_registro.csv de escritorio: «;», BOM, CRLF)

public enum RegistroFoco {
    public static let campos = ["inicio", "fin", "tipo", "minutos_planeados", "minutos_reales", "intencion",
                                "resultado", "distracciones"]

    public static func linea(_ b: Bloque) -> String {
        [FechaISO.textoSegundos(b.inicio), FechaISO.textoSegundos(b.fin), b.tipo, "\(b.minutosPlaneados)",
         "\(b.minutosReales)", b.intencion, b.resultado, "\(b.distracciones)"]
            .map(CSV.campo).joined(separator: ";") + "\r\n"
    }

    public static func anotar(_ b: Bloque, en url: URL) throws {
        let atributos = try? FileManager.default.attributesOfItem(atPath: url.path)
        let tamano = (atributos?[.size] as? NSNumber)?.intValue ?? 0
        if tamano == 0 {
            // BOM solo al crear: así Excel detecta UTF-8; al agregar filas no se repite.
            let texto = "\u{FEFF}" + campos.joined(separator: ";") + "\r\n" + linea(b)
            try Data(texto.utf8).write(to: url, options: .atomic)
            return
        }
        let h = try FileHandle(forWritingTo: url)
        defer { try? h.close() }
        try h.seekToEnd()
        try h.write(contentsOf: Data(linea(b).utf8))
    }

    /// Filas válidas; las dañadas se saltan. Nunca lanza.
    public static func leer(_ url: URL) -> [Bloque] {
        guard let data = try? Data(contentsOf: url), let texto = String(data: data, encoding: .utf8) else { return [] }
        return leer(texto: texto)
    }

    public static func leer(texto: String) -> [Bloque] {
        let filas = CSV.parsear(texto)
        guard let cabecera = filas.first else { return [] }
        var idx: [String: Int] = [:]
        for (i, nombre) in cabecera.enumerated() { idx[nombre] = i }
        func valor(_ f: [String], _ k: String) -> String? {
            guard let i = idx[k], i < f.count else { return nil }
            return f[i]
        }
        return filas.dropFirst().compactMap { f -> Bloque? in
            guard let ini = valor(f, "inicio").flatMap(FechaISO.leer),
                  let fin = valor(f, "fin").flatMap(FechaISO.leer),
                  let tipo = valor(f, "tipo"),
                  let planeados = valor(f, "minutos_planeados").flatMap({ Int($0) }),
                  let reales = valor(f, "minutos_reales").flatMap({ Int($0) }),
                  let resultado = valor(f, "resultado") else { return nil }
            let dist = valor(f, "distracciones").flatMap { Int($0) } ?? 0
            return Bloque(inicio: ini, fin: fin, tipo: tipo, minutosPlaneados: planeados, minutosReales: reales,
                          intencion: valor(f, "intencion") ?? "", resultado: resultado, distracciones: dist)
        }
    }
}

public enum CSV {
    /// Comillas solo cuando hacen falta, como el csv de Python.
    public static func campo(_ s: String) -> String {
        if s.contains(";") || s.contains("\"") || s.contains("\n") || s.contains("\r") {
            return "\"" + s.replacingOccurrences(of: "\"", with: "\"\"") + "\""
        }
        return s
    }

    /// Lector por escalares Unicode: en Swift «\r\n» es un solo Character y confundiría los saltos.
    public static func parsear(_ texto: String, separador: Unicode.Scalar = ";") -> [[String]] {
        var s = Array(texto.unicodeScalars)
        if s.first == "\u{FEFF}" { s.removeFirst() }
        var filas: [[String]] = []
        var fila: [String] = []
        var campo = String.UnicodeScalarView()
        var enComillas = false
        var i = 0
        func cerrarCampo() {
            fila.append(String(campo))
            campo = String.UnicodeScalarView()
        }
        while i < s.count {
            let c = s[i]
            if enComillas {
                if c == "\"" {
                    if i + 1 < s.count && s[i + 1] == "\"" {
                        campo.append("\"")
                        i += 1
                    } else {
                        enComillas = false
                    }
                } else {
                    campo.append(c)
                }
            } else if c == "\"" {
                enComillas = true
            } else if c == separador {
                cerrarCampo()
            } else if c == "\r" || c == "\n" {
                if c == "\r" && i + 1 < s.count && s[i + 1] == "\n" { i += 1 }
                cerrarCampo()
                filas.append(fila)
                fila = []
            } else {
                campo.append(c)
            }
            i += 1
        }
        if !campo.isEmpty || !fila.isEmpty {
            cerrarCampo()
            filas.append(fila)
        }
        return filas
    }
}

// MARK: - Estadísticas

public struct DiaMinutos: Equatable, Identifiable {
    public var dia: Date
    public var minutos: Int
    public var id: Date { dia }
}

public struct Estadisticas: Equatable {
    public var minutosHoy: Int
    public var bloquesHoy: Int
    public var racha: Int
    public var distraccionesHoy: Int
    public var ultimos7: [DiaMinutos]
    public var resultadosSemana: [String: Int]
}

public func estadisticas(_ filas: [Bloque], hoy: Date, calendario cal: Calendar = .current) -> Estadisticas {
    let diaHoy = cal.startOfDay(for: hoy)
    let haceSeis = cal.date(byAdding: .day, value: -6, to: diaHoy) ?? diaHoy
    var minutos: [Date: Int] = [:]
    var validos = Set<Date>()
    var bloquesHoy = 0
    var distraccionesHoy = 0
    var resultados: [String: Int] = [:]
    for r in Resultado.allCases { resultados[r.rawValue] = 0 }
    for f in filas {
        let d = cal.startOfDay(for: f.inicio)  // un bloque que cruza medianoche cuenta el día en que empezó
        minutos[d, default: 0] += f.minutosReales
        if f.valido { validos.insert(d) }
        if d == diaHoy {
            if f.valido { bloquesHoy += 1 }
            distraccionesHoy += f.distracciones
        }
        if d >= haceSeis && d <= diaHoy && resultados[f.resultado] != nil { resultados[f.resultado]! += 1 }
    }
    // La racha sigue viva durante el día de hoy aunque todavía no hayas hecho un bloque.
    var racha = 0
    var dia = validos.contains(diaHoy) ? diaHoy : (cal.date(byAdding: .day, value: -1, to: diaHoy) ?? diaHoy)
    while validos.contains(dia) {
        racha += 1
        guard let anterior = cal.date(byAdding: .day, value: -1, to: dia) else { break }
        dia = anterior
    }
    let ultimos7 = (0..<7).reversed().map { i -> DiaMinutos in
        let d = cal.date(byAdding: .day, value: -i, to: diaHoy) ?? diaHoy
        return DiaMinutos(dia: d, minutos: minutos[d] ?? 0)
    }
    return Estadisticas(minutosHoy: minutos[diaHoy] ?? 0, bloquesHoy: bloquesHoy, racha: racha,
                        distraccionesHoy: distraccionesHoy, ultimos7: ultimos7, resultadosSemana: resultados)
}

public func textoEstadisticas(_ e: Estadisticas) -> String {
    var partes = ["Hoy: \(formatoMinutos(e.minutosHoy)) en \(e.bloquesHoy) bloque(s)"]
    if e.racha > 0 { partes.append("racha: \(e.racha) día(s)") }
    if e.distraccionesHoy > 0 { partes.append("anotaste \(e.distraccionesHoy) distracción(es)") }
    return partes.joined(separator: "  ·  ")
}

// MARK: - Lista «para después» (mismo foco_para_despues.txt)

public enum Pendientes {
    public static func linea(_ texto: String, ahora: Date) -> String? {
        let t = unaLinea(texto)
        return t.isEmpty ? nil : "\(FechaISO.textoPendiente(ahora))  \(t)"
    }

    public static func leer(_ url: URL) -> [String] {
        guard let data = try? Data(contentsOf: url), let texto = String(data: data, encoding: .utf8) else { return [] }
        return texto.components(separatedBy: .newlines)
            .filter { !$0.trimmingCharacters(in: .whitespaces).isEmpty }
    }

    public static func guardar(_ lineas: [String], en url: URL) throws {
        try Data(lineas.map { $0 + "\n" }.joined().utf8).write(to: url, options: .atomic)
    }

    public static func anotar(_ texto: String, ahora: Date, en url: URL) throws {
        guard let l = linea(texto, ahora: ahora) else { return }
        try guardar(leer(url) + [l], en: url)
    }
}
