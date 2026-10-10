import Foundation

/// Preferencias, guardadas solo en UserDefaults de este iPhone.
///
/// - Filtros: van al JS como `configJSON`; cambiarlos recrea el WebView.
/// - Hábitos: solo nativos (presupuesto, aviso, intención); no recargan nada.
final class FilterSettings: ObservableObject {
    // MARK: Filtros (§4.2, sin lockToDMs: ese lo decide el presupuesto)

    @Published var blockReels: Bool { didSet { guardar(blockReels, "blockReels") } }
    @Published var hideFeedReels: Bool { didSet { guardar(hideFeedReels, "hideFeedReels") } }
    @Published var blockExplore: Bool { didSet { guardar(blockExplore, "blockExplore") } }
    @Published var hideAds: Bool { didSet { guardar(hideAds, "hideAds") } }
    @Published var hideSuggested: Bool { didSet { guardar(hideSuggested, "hideSuggested") } }
    @Published var grayscale: Bool { didSet { guardar(grayscale, "grayscale") } }
    @Published var feedLimit: Int { didSet { guardar(feedLimit, "feedLimit") } }
    @Published var dmOnlyMode: Bool { didSet { guardar(dmOnlyMode, "dmOnlyMode") } }

    // MARK: Hábitos

    @Published var askIntent: Bool { didSet { guardar(askIntent, "askIntent") } }
    @Published var nudgeMinutes: Int { didSet { guardar(nudgeMinutes, "nudgeMinutes") } }
    @Published private(set) var dailyBudgetMinutes: Int
    @Published private(set) var pendingBudgetMinutes: Int?
    @Published private(set) var pendingBudgetDay: String?

    /// No se persiste: incrementarlo recrea el WebView (recargar, o tras borrar datos).
    @Published var reloadEpoch = 0

    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        blockReels = Self.bool(defaults, "blockReels", true)
        hideFeedReels = Self.bool(defaults, "hideFeedReels", true)
        blockExplore = Self.bool(defaults, "blockExplore", true)
        hideAds = Self.bool(defaults, "hideAds", true)
        hideSuggested = Self.bool(defaults, "hideSuggested", true)
        grayscale = Self.bool(defaults, "grayscale", true)
        feedLimit = Self.int(defaults, "feedLimit", 20)
        dmOnlyMode = Self.bool(defaults, "dmOnlyMode", false)
        askIntent = Self.bool(defaults, "askIntent", true)
        nudgeMinutes = Self.int(defaults, "nudgeMinutes", 5)
        dailyBudgetMinutes = Self.int(defaults, "dailyBudgetMinutes", 15)
        pendingBudgetMinutes = defaults.object(forKey: "pendingBudgetMinutes") as? Int
        pendingBudgetDay = defaults.string(forKey: "pendingBudgetDay")
    }

    /// Configuración del filtro en JSON con claves ordenadas: sirve también de identidad
    /// estable del WebView (`.id(configJSON + …)`), así solo se recrea si algo cambió.
    var configJSON: String {
        let dict: [String: Any] = [
            "blockReels": blockReels,
            "hideFeedReels": hideFeedReels,
            "blockExplore": blockExplore,
            "hideAds": hideAds,
            "hideSuggested": hideSuggested,
            "grayscale": grayscale,
            "feedLimit": feedLimit,
            "dmOnlyMode": dmOnlyMode,
        ]
        guard let data = try? JSONSerialization.data(withJSONObject: dict, options: [.sortedKeys]),
              let json = String(data: data, encoding: .utf8) else { return "{}" }
        return json
    }

    // MARK: Presupuesto con regla anti-trampa

    /// ¿Pasar de `current` a `next` da más tiempo? (0 = sin límite, lo más permisivo).
    static func isMorePermissive(_ next: Int, than current: Int) -> Bool {
        if current == 0 { return false }
        if next == 0 { return true }
        return next > current
    }

    /// Lo que muestra y mueve el control: lo pendiente si hay, si no lo vigente.
    var requestedBudgetMinutes: Int { pendingBudgetMinutes ?? dailyBudgetMinutes }

    /// Bajar (o igualar) aplica de inmediato y descarta lo pendiente.
    /// Subir, o pasar a «sin límite», queda pendiente hasta mañana.
    func requestBudget(_ minutes: Int, today: String = UsageStats.dayKey(Date())) {
        let m = max(0, min(120, minutes))
        if Self.isMorePermissive(m, than: dailyBudgetMinutes) {
            pendingBudgetMinutes = m
            pendingBudgetDay = today
        } else {
            dailyBudgetMinutes = m
            pendingBudgetMinutes = nil
            pendingBudgetDay = nil
        }
        guardarPresupuesto()
    }

    /// Al iniciar, al volver a primer plano y cada 10 s. Solo publica si cambia algo.
    func applyPendingBudgetIfNeeded(today: String = UsageStats.dayKey(Date())) {
        guard let pendiente = pendingBudgetMinutes, let dia = pendingBudgetDay, today > dia else { return }
        dailyBudgetMinutes = pendiente
        pendingBudgetMinutes = nil
        pendingBudgetDay = nil
        guardarPresupuesto()
    }

    // MARK: Persistencia

    private func guardar(_ valor: Any, _ clave: String) {
        defaults.set(valor, forKey: clave)
    }

    private func guardarPresupuesto() {
        defaults.set(dailyBudgetMinutes, forKey: "dailyBudgetMinutes")
        if let p = pendingBudgetMinutes {
            defaults.set(p, forKey: "pendingBudgetMinutes")
        } else {
            defaults.removeObject(forKey: "pendingBudgetMinutes")
        }
        if let d = pendingBudgetDay {
            defaults.set(d, forKey: "pendingBudgetDay")
        } else {
            defaults.removeObject(forKey: "pendingBudgetDay")
        }
    }

    private static func bool(_ d: UserDefaults, _ clave: String, _ omision: Bool) -> Bool {
        d.object(forKey: clave) == nil ? omision : d.bool(forKey: clave)
    }

    private static func int(_ d: UserDefaults, _ clave: String, _ omision: Int) -> Int {
        d.object(forKey: clave) == nil ? omision : d.integer(forKey: clave)
    }
}
