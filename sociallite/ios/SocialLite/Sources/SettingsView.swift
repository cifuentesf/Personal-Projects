import SwiftUI
import WebKit

struct SettingsView: View {
    @EnvironmentObject private var settings: FilterSettings
    @EnvironmentObject private var stats: UsageStats
    @Environment(\.dismiss) private var dismiss
    @State private var confirmWipe = false

    private func etiquetaTiempo(_ minutos: Int) -> String {
        minutos == 0 ? "Sin límite" : "\(minutos) min"
    }

    /// El control mueve lo pedido (pendiente si hay); el texto muestra lo vigente.
    private var budgetBinding: Binding<Int> {
        Binding(get: { settings.requestedBudgetMinutes }, set: { settings.requestBudget($0) })
    }

    var body: some View {
        let ahora = Date()
        NavigationStack {
            Form {
                Section {
                    Stepper(value: budgetBinding, in: 0...120, step: 5) {
                        LabeledContent("Tiempo diario", value: etiquetaTiempo(settings.dailyBudgetMinutes))
                    }
                    if let pendiente = settings.pendingBudgetMinutes {
                        LabeledContent("Desde mañana", value: etiquetaTiempo(pendiente))
                            .foregroundStyle(.orange)
                    }
                    Stepper(value: $settings.nudgeMinutes, in: 0...30) {
                        LabeledContent("Aviso de pausa",
                                       value: settings.nudgeMinutes == 0 ? "Nunca" : "cada \(settings.nudgeMinutes) min")
                    }
                    Toggle("Preguntar a qué vienes al abrir", isOn: $settings.askIntent)
                } header: {
                    Text("Fuera de mensajes")
                } footer: {
                    Text("Los mensajes nunca gastan tiempo. Bajar el límite aplica de inmediato; "
                         + "subirlo o quitarlo rige desde mañana, para que no se pueda hacer trampa en caliente.")
                }

                Section {
                    Toggle("Bloquear Reels", isOn: $settings.blockReels)
                    Toggle("Ocultar reels del inicio", isOn: $settings.hideFeedReels)
                    Toggle("Ocultar la cuadrícula de Explorar", isOn: $settings.blockExplore)
                    Toggle("Ocultar publicidad", isOn: $settings.hideAds)
                    Toggle("Ocultar sugerencias", isOn: $settings.hideSuggested)
                    Toggle("Escala de grises fuera de mensajes", isOn: $settings.grayscale)
                    Stepper(value: $settings.feedLimit, in: 0...60, step: 5) {
                        LabeledContent("Publicaciones del inicio por día",
                                       value: settings.feedLimit == 0 ? "Sin límite" : "\(settings.feedLimit)")
                    }
                } header: {
                    Text("Filtros")
                } footer: {
                    Text("Cambiar un filtro recarga Instagram.")
                }

                Section {
                    Toggle("Solo mensajes", isOn: $settings.dmOnlyMode)
                } header: {
                    Text("Modo solo mensajes")
                } footer: {
                    Text("Todo lo que no sea un mensaje (o algo que te enviaron por mensaje) vuelve a la bandeja de entrada.")
                }

                Section {
                    LabeledContent("En mensajes", value: "\(Int(stats.dmSecondsToday(at: ahora) / 60)) min")
                    LabeledContent("En inicio y resto", value: "\(Int(stats.feedSecondsToday(at: ahora) / 60)) min")
                    LabeledContent("Intentos bloqueados", value: "\(stats.blocksToday)")
                } header: {
                    Text("Hoy")
                }

                Section {
                    Button("Recargar Instagram") {
                        settings.reloadEpoch += 1
                        dismiss()
                    }
                    Button("Cerrar sesión y borrar datos", role: .destructive) {
                        confirmWipe = true
                    }
                } header: {
                    Text("Datos")
                } footer: {
                    Text("Todo se guarda solo en este iPhone: la app no tiene servidor, cuentas propias ni analítica. "
                         + "Borrar datos cierra la sesión de Instagram y olvida las publicaciones vistas hoy; "
                         + "el tiempo usado hoy se mantiene hasta medianoche para que no sirva de atajo.")
                }
            }
            .navigationTitle("Ajustes")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Listo") { dismiss() }
                }
            }
            .confirmationDialog("¿Cerrar la sesión de Instagram y borrar sus datos en esta app?",
                                isPresented: $confirmWipe, titleVisibility: .visible) {
                Button("Cerrar sesión y borrar", role: .destructive) { wipe() }
                Button("Cancelar", role: .cancel) {}
            }
        }
    }

    private func wipe() {
        let tipos = WKWebsiteDataStore.allWebsiteDataTypes()
        WKWebsiteDataStore.default().removeData(ofTypes: tipos, modifiedSince: .distantPast) {
            settings.reloadEpoch += 1
            dismiss()
        }
    }
}
