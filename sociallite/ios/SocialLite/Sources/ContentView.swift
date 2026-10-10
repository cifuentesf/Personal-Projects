import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var settings: FilterSettings
    @EnvironmentObject private var stats: UsageStats
    @Environment(\.scenePhase) private var scenePhase

    @State private var now = Date()
    @State private var showIntent = false
    @State private var showSettings = false
    @State private var navRequest: NavRequest?
    @State private var backgroundedAt: Date?
    @State private var nudgeSnoozedUntil: Date?
    @State private var launched = false

    /// Reloj de 10 s: presupuesto, cambio de día y aviso de pausa.
    private let clock = Timer.publish(every: 10, on: .main, in: .common).autoconnect()

    private var budgetSeconds: TimeInterval { TimeInterval(settings.dailyBudgetMinutes * 60) }
    private var feedSeconds: TimeInterval { stats.feedSecondsToday(at: now) }
    private var isLocked: Bool { settings.dailyBudgetMinutes > 0 && feedSeconds >= budgetSeconds }

    private var minutesLeft: Int? {
        guard settings.dailyBudgetMinutes > 0 else { return nil }
        return max(0, Int(((budgetSeconds - feedSeconds) / 60).rounded(.up)))
    }

    private var streakSeconds: TimeInterval {
        guard let inicio = stats.feedStreakStart else { return 0 }
        return max(0, now.timeIntervalSince(inicio))
    }

    private var showNudge: Bool {
        guard settings.nudgeMinutes > 0, !isLocked, !showIntent else { return false }
        if let hasta = nudgeSnoozedUntil, now < hasta { return false }
        return streakSeconds >= TimeInterval(settings.nudgeMinutes * 60)
    }

    var body: some View {
        VStack(spacing: 0) {
            topBar
            ZStack {
                InstagramWebView(
                    configJSON: settings.configJSON,
                    lockedToDMs: isLocked,
                    navRequest: navRequest,
                    onBlocked: { _ in stats.recordBlock() },
                    onRoute: { route in routeChanged(route) }
                )
                .id(settings.configJSON + "#\(settings.reloadEpoch)")

                if showIntent {
                    IntentView(locked: isLocked, minutesLeft: minutesLeft) { path in
                        showIntent = false
                        go(path)
                    }
                } else if showNudge {
                    NudgeView(
                        streakMinutes: Int(streakSeconds / 60),
                        snoozeMinutes: settings.nudgeMinutes,
                        onInbox: { go(UsageStats.inboxPath) },
                        onSnooze: {
                            nudgeSnoozedUntil = Date().addingTimeInterval(TimeInterval(settings.nudgeMinutes * 60))
                        }
                    )
                }
            }
        }
        .sheet(isPresented: $showSettings) { SettingsView() }
        .onAppear(perform: launch)
        .onReceive(clock) { t in tick(t) }
        .onChange(of: scenePhase) { phase in sceneChanged(phase) }
        .onOpenURL { _ in
            // sociallite://inbox (por ejemplo, desde la automatización de Atajos)
            showIntent = false
            go(UsageStats.inboxPath)
        }
    }

    // MARK: barra superior

    private var topBar: some View {
        HStack(spacing: 8) {
            Text("SocialLite").font(.headline)
            Spacer(minLength: 4)
            Text(usageText)
                .font(.footnote.monospacedDigit())
                .foregroundStyle(isLocked ? Color.orange : Color.secondary)
                .lineLimit(1)
                .minimumScaleFactor(0.8)
            Button { showSettings = true } label: {
                Image(systemName: "gearshape")
            }
            .accessibilityLabel("Ajustes")
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 6)
        .background(.bar)
    }

    private var usageText: String {
        let usado = Int(feedSeconds / 60)
        let dm = Int(stats.dmSecondsToday(at: now) / 60)
        let limite = settings.dailyBudgetMinutes > 0 ? "/\(settings.dailyBudgetMinutes)" : ""
        return (isLocked ? "🔒 " : "") + "Inicio \(usado)\(limite) min · DM \(dm) min"
    }

    // MARK: acciones

    private func go(_ path: String) {
        navRequest = NavRequest(id: UUID(), path: path)
    }

    private func launch() {
        guard !launched else { return }
        launched = true
        settings.applyPendingBudgetIfNeeded()
        stats.sessionStarted()
        now = Date()
        if settings.askIntent { showIntent = true }
    }

    private func tick(_ t: Date) {
        now = t
        stats.refreshDay(t)
        settings.applyPendingBudgetIfNeeded()
    }

    private func routeChanged(_ route: String) {
        stats.routeChanged(route)
        if UsageStats.isFree(route) { nudgeSnoozedUntil = nil }
        now = Date()
    }

    private func sceneChanged(_ phase: ScenePhase) {
        switch phase {
        case .active:
            settings.applyPendingBudgetIfNeeded()
            stats.sessionStarted()
            if let fuera = backgroundedAt, Date().timeIntervalSince(fuera) > 5 * 60, settings.askIntent {
                showIntent = true
            }
            backgroundedAt = nil
            now = Date()
        case .background:
            stats.sessionEnded()
            backgroundedAt = Date()
        default:
            break
        }
    }
}
