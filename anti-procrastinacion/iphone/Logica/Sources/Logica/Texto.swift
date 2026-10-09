import Foundation

/// Error con un mensaje listo para mostrar a la persona.
public struct ErrorEntrada: Error, Equatable, LocalizedError {
    public let mensaje: String
    public init(_ mensaje: String) { self.mensaje = mensaje }
    public var errorDescription: String? { mensaje }
}

public func sinTildes(_ s: String) -> String {
    s.folding(options: .diacriticInsensitive, locale: Locale(identifier: "es_CL"))
}

func palabras(_ s: String) -> [String] {
    sinTildes(s.lowercased())
        .components(separatedBy: CharacterSet.alphanumerics.inverted)
        .filter { !$0.isEmpty }
}

let verbosVagos: Set<String> = ["avanzar", "trabajar", "hacer", "estudiar", "ver", "revisar", "terminar",
                                "seguir", "empezar", "continuar", "repasar", "preparar", "ponerse"]

private func esVago(_ ps: [String]) -> Bool {
    ps.count < 3 || (verbosVagos.contains(ps[0]) && ps.count <= 3)
}

/// Consejo si el siguiente paso de una entrega es demasiado general; nil si está bien.
public func pasoVago(_ texto: String) -> String? {
    let ps = palabras(texto)
    if ps.isEmpty { return "Sin siguiente paso. Escribe lo primero que harías al sentarte." }
    if esVago(ps) {
        return "Muy general. Un buen paso dice qué y dónde: «escribir la intro del informe T2», no «avanzar T2»."
    }
    return nil
}

/// Consejo si la intención de un bloque es demasiado general; nil si está bien o vacía.
public func intencionVaga(_ texto: String) -> String? {
    let ps = palabras(texto)
    if ps.isEmpty { return nil }
    if esVago(ps) {
        return "Muy general: al final no sabrás si lo cumpliste. Ej.: «resolver los ejercicios 1 a 3 de la guía»."
    }
    return nil
}

/// Colapsa espacios y saltos de línea: «  a   b\n c » → «a b c».
public func unaLinea(_ s: String) -> String {
    s.split(whereSeparator: { $0.isWhitespace }).joined(separator: " ")
}

// MARK: - Expresiones regulares (NSRegularExpression: funciona igual en iOS, macOS y Linux)

/// Grupos de una coincidencia completa del patrón, o nil si no coincide.
func coincide(_ patron: String, _ texto: String) -> [String?]? {
    guard let re = try? NSRegularExpression(pattern: "^(?:" + patron + ")$") else { return nil }
    let ns = texto as NSString
    guard let m = re.firstMatch(in: texto, range: NSRange(location: 0, length: ns.length)) else { return nil }
    return (0..<m.numberOfRanges).map { i in
        let r = m.range(at: i)
        return r.location == NSNotFound ? nil : ns.substring(with: r)
    }
}

// MARK: - Horas de trabajo

/// «2», «2,5», «2.5», «1h30», «1 h 30 min», «90 min», «45m» → horas.
public func parseHoras(_ texto: String) throws -> Double {
    var t = sinTildes(texto.trimmingCharacters(in: .whitespacesAndNewlines).lowercased())
    t = t.replacingOccurrences(of: ",", with: ".")
    t = t.components(separatedBy: .whitespacesAndNewlines).joined()
    if t.isEmpty { throw ErrorEntrada("Escribe un número de horas, por ejemplo 2 o 1,5.") }
    if let g = coincide(#"(\d+(?:\.\d+)?)(?:h|hrs?|horas?)?"#, t), let v = Double(g[1] ?? "") {
        return v
    }
    if let g = coincide(#"(\d+(?:\.\d+)?)(?:m|min|mins|minutos?)"#, t), let v = Double(g[1] ?? "") {
        return v / 60
    }
    if let g = coincide(#"(\d+)(?:h|hrs?|horas?)(\d{1,2})(?:m|min|mins|minutos?)?"#, t),
       let h = Int(g[1] ?? ""), let m = Int(g[2] ?? ""), m < 60 {
        return Double(h) + Double(m) / 60
    }
    throw ErrorEntrada("No entendí «\(texto.trimmingCharacters(in: .whitespaces))» como horas. "
                       + "Ejemplos: 2, 1,5, 1h30, 90 min.")
}

/// Horas para un campo editable, exactas al minuto: «2», «1h45», «0h25».
/// (formatoHoras redondea a un decimal: al guardar sin cambios, el número iría corriendo.)
public func horasEditables(_ horas: Double) -> String {
    let total = Int((horas * 60).rounded())
    let (h, m) = (total / 60, total % 60)
    return m == 0 ? "\(h)" : "\(h)h\(dos(m))"
}

/// Horas de trabajo: «40 min», «2 h», «2,5 h». Coma decimal, como en Chile.
public func formatoHoras(_ horas: Double) -> String {
    if horas < 1 { return "\(Int((horas * 60).rounded())) min" }
    var txt = String(format: "%.1f", horas).replacingOccurrences(of: ".", with: ",")
    if txt.hasSuffix(",0") { txt.removeLast(2) }
    return "\(txt) h"
}

/// Tiempo de calendario: «3 d 4 h», «5 h 20 min», «vencida hace 2 h 0 min».
public func formatoReloj(_ horas: Double) -> String {
    if horas < 0 { return "vencida hace " + formatoReloj(-horas) }
    let total = Int((horas * 60).rounded())
    let d = total / 1440
    let h = (total % 1440) / 60
    let m = total % 60
    if d > 0 { return "\(d) d \(h) h" }
    if h > 0 { return "\(h) h \(m) min" }
    return "\(m) min"
}

func dos(_ n: Int) -> String { n < 10 ? "0\(n)" : "\(n)" }
