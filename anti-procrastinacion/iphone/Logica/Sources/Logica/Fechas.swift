import Foundation

/// Fechas en el mismo formato que usan las apps de escritorio (hora local, sin zona):
/// «2026-10-15T18:00» en plazos y «2026-10-15T18:00:00» en foco.
public enum FechaISO {
    private static func formateador(_ formato: String) -> DateFormatter {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.calendar = Calendar(identifier: .gregorian)
        f.timeZone = TimeZone.current
        f.dateFormat = formato
        return f
    }

    private static let fmtMinutos = formateador("yyyy-MM-dd'T'HH:mm")
    private static let fmtSegundos = formateador("yyyy-MM-dd'T'HH:mm:ss")
    private static let fmtMicro = formateador("yyyy-MM-dd'T'HH:mm:ss.SSSSSS")
    private static let fmtDia = formateador("yyyy-MM-dd")
    private static let fmtPendiente = formateador("yyyy-MM-dd HH:mm")

    public static func textoMinutos(_ d: Date) -> String { fmtMinutos.string(from: d) }
    public static func textoSegundos(_ d: Date) -> String { fmtSegundos.string(from: d) }
    static func textoPendiente(_ d: Date) -> String { fmtPendiente.string(from: d) }

    /// Lee lo que escribe Python con isoformat(): con minutos, segundos o microsegundos.
    public static func leer(_ s: String) -> Date? {
        let t = s.trimmingCharacters(in: .whitespaces)
        // Del más específico al menos: así nunca se pierden segundos por una lectura parcial.
        for f in [fmtMicro, fmtSegundos, fmtMinutos, fmtDia] {
            if let d = f.date(from: t) { return d }
        }
        return nil
    }
}

let diasCortos = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]

/// Índice lunes = 0 … domingo = 6 (Calendar cuenta domingo = 1).
func indiceDia(_ d: Date, _ cal: Calendar) -> Int {
    (cal.component(.weekday, from: d) + 5) % 7
}

public func diaCorto(_ d: Date, calendario: Calendar = .current) -> String {
    diasCortos[indiceDia(d, calendario)]
}

/// «jue 15-10 18:00», con el año solo si no es el actual.
public func formatoEntrega(_ d: Date, ahora: Date, calendario cal: Calendar = .current) -> String {
    let c = cal.dateComponents([.year, .month, .day, .hour, .minute], from: d)
    var base = "\(diasCortos[indiceDia(d, cal)]) \(dos(c.day ?? 0))-\(dos(c.month ?? 0))"
    if c.year != cal.component(.year, from: ahora) { base += "-\(c.year ?? 0)" }
    return "\(base) \(dos(c.hour ?? 0)):\(dos(c.minute ?? 0))"
}
