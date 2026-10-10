import SwiftUI
import UIKit

/// «¿A qué vienes?»: al abrir la app y al volver tras más de 5 min en segundo plano.
struct IntentView: View {
    let locked: Bool
    let minutesLeft: Int?
    let choose: (String) -> Void

    private var subtitle: String {
        if locked { return "Se acabó tu tiempo de hoy fuera de mensajes. Los mensajes siguen libres." }
        guard let m = minutesLeft else { return "Sin límite diario fuera de mensajes." }
        return "Te quedan \(m) min fuera de mensajes hoy."
    }

    var body: some View {
        ZStack {
            Color.black.opacity(0.55).ignoresSafeArea()
            VStack(spacing: 12) {
                Text("¿A qué vienes?").font(.title2.bold())
                Text(subtitle)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .padding(.bottom, 4)
                Button { choose(UsageStats.inboxPath) } label: {
                    Text("Hablar con amigos").frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                Button { choose("/explore/") } label: {
                    Text("Buscar a alguien").frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
                .disabled(locked)
                Button { choose("/") } label: {
                    Text("Ver el inicio").frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
                .disabled(locked)
            }
            .controlSize(.large)
            .padding(22)
            .frame(maxWidth: 360)
            .background(RoundedRectangle(cornerRadius: 20).fill(Color(uiColor: .systemBackground)))
            .padding(24)
        }
    }
}

/// Aviso de pausa tras N min seguidos fuera de mensajes.
/// «Seguir X min más» queda deshabilitado 5 s, con cuenta regresiva.
struct NudgeView: View {
    let streakMinutes: Int
    let snoozeMinutes: Int
    let onInbox: () -> Void
    let onSnooze: () -> Void

    @State private var remaining = 5
    private let timer = Timer.publish(every: 1, on: .main, in: .common).autoconnect()

    private var snoozeLabel: String {
        remaining > 0 ? "Seguir \(snoozeMinutes) min más (\(remaining))" : "Seguir \(snoozeMinutes) min más"
    }

    var body: some View {
        ZStack {
            Color.black.opacity(0.55).ignoresSafeArea()
            VStack(spacing: 12) {
                Text("Llevas \(streakMinutes) min fuera de mensajes")
                    .font(.title3.bold())
                    .multilineTextAlignment(.center)
                Text("¿Estás buscando algo concreto o es scroll?")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .padding(.bottom, 4)
                Button(action: onInbox) {
                    Text("Ir a mensajes").frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                Button(action: onSnooze) {
                    Text(snoozeLabel).frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
                .disabled(remaining > 0)
            }
            .controlSize(.large)
            .padding(22)
            .frame(maxWidth: 360)
            .background(RoundedRectangle(cornerRadius: 20).fill(Color(uiColor: .systemBackground)))
            .padding(24)
        }
        .onReceive(timer) { _ in
            if remaining > 0 { remaining -= 1 }
        }
    }
}
