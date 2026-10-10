import Foundation

/// Contadores del día (solo números y fechas), en UserDefaults, con reinicio diario.
///
/// La contabilidad es por tramos: cada cambio de ruta, de primer/segundo plano o de día
/// cierra el tramo en curso y lo suma a su cubo (mensajes o todo lo demás).
final class UsageStats: ObservableObject {
    /// Rutas que nunca gastan presupuesto (las reporta shared/filter.js).
    static let freeRoutes: Set<String> = ["direct", "shared", "auth"]
    static let inboxPath = "/direct/inbox/"

    static func isFree(_ route: String) -> Bool { freeRoutes.contains(route) }

    private static let formatoDia: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.calendar = Calendar(identifier: .gregorian)
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()

    /// Fecha local «yyyy-MM-dd».
    static func dayKey(_ date: Date) -> String {
        formatoDia.timeZone = TimeZone.current
        return formatoDia.string(from: date)
    }

    @Published private(set) var dmSeconds: TimeInterval
    @Published private(set) var feedSeconds: TimeInterval
    @Published private(set) var blocksToday: Int
    /// Inicio del tramo continuo fuera de mensajes (para el aviso de pausa).
    @Published private(set) var feedStreakStart: Date?

    private var day: String
    private var route = "direct"  // la app siempre abre en la bandeja de entrada
    private var segmentStart: Date?
    private var active = false
    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard, now: Date = Date()) {
        self.defaults = defaults
        let hoy = Self.dayKey(now)
        if defaults.string(forKey: "statsDay") == hoy {
            dmSeconds = defaults.double(forKey: "dmSeconds")
            feedSeconds = defaults.double(forKey: "feedSeconds")
            blocksToday = defaults.integer(forKey: "blocksToday")
        } else {
            dmSeconds = 0
            feedSeconds = 0
            blocksToday = 0
        }
        day = hoy
    }

    // MARK: eventos

    func sessionStarted(at now: Date = Date()) {
        refreshDay(now)
        guard !active else { return }
        active = true
        segmentStart = now
        if !Self.isFree(route) && feedStreakStart == nil { feedStreakStart = now }
    }

    func sessionEnded(at now: Date = Date()) {
        closeSegment(now)
        active = false
        segmentStart = nil
        feedStreakStart = nil
        persist()
    }

    func routeChanged(_ newRoute: String, at now: Date = Date()) {
        refreshDay(now)
        closeSegment(now)
        route = newRoute
        if Self.isFree(newRoute) {
            feedStreakStart = nil
        } else if active && feedStreakStart == nil {
            feedStreakStart = now
        }
        persist()
    }

    func recordBlock() {
        blocksToday += 1
        persist()
    }

    /// Reinicia los contadores si cambió la fecha local.
    func refreshDay(_ now: Date = Date()) {
        let hoy = Self.dayKey(now)
        guard hoy != day else { return }
        closeSegment(now)  // lo del tramo anterior queda en el día que termina
        day = hoy
        dmSeconds = 0
        feedSeconds = 0
        blocksToday = 0
        persist()
    }

    // MARK: lecturas (incluyen el tramo en curso)

    func feedSecondsToday(at now: Date) -> TimeInterval {
        feedSeconds + (Self.isFree(route) ? 0 : currentSegment(now))
    }

    func dmSecondsToday(at now: Date) -> TimeInterval {
        dmSeconds + (Self.isFree(route) ? currentSegment(now) : 0)
    }

    // MARK: internos

    private func currentSegment(_ now: Date) -> TimeInterval {
        guard active, let s = segmentStart else { return 0 }
        return max(0, now.timeIntervalSince(s))
    }

    private func closeSegment(_ now: Date) {
        let dt = currentSegment(now)
        if dt > 0 {
            if Self.isFree(route) { dmSeconds += dt } else { feedSeconds += dt }
        }
        segmentStart = active ? now : nil
    }

    private func persist() {
        defaults.set(day, forKey: "statsDay")
        defaults.set(dmSeconds, forKey: "dmSeconds")
        defaults.set(feedSeconds, forKey: "feedSeconds")
        defaults.set(blocksToday, forKey: "blocksToday")
    }
}
