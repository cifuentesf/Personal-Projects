import SwiftUI
import Charts
import Logica

struct FocoView: View {
    @EnvironmentObject private var foco: FocoStore
    @EnvironmentObject private var plazos: PlazosStore
    @Environment(\.scenePhase) private var escena
    @State private var intencion = ""
    @State private var distraccion = ""
    @State private var ajustes = false
    @State private var confirmarAbandono = false
    private let reloj = Timer.publish(every: 0.5, on: .main, in: .common).autoconnect()

    private var s: SesionFoco { foco.sesion }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 20) {
                    encabezado
                    panel
                    if s.fase == .listo || s.enDescanso { ParaDespues() }
                    Divider()
                    EstadisticasFoco()
                }
                .padding()
            }
            .navigationTitle("Foco")
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button { ajustes = true } label: { Image(systemName: "slider.horizontal.3") }
                }
            }
            .sheet(isPresented: $ajustes) { AjustesFocoView() }
        }
        .onReceive(reloj) { _ in foco.tic() }
        .onChange(of: escena) { nueva in
            if nueva == .active { foco.tic() }
        }
    }

    // MARK: encabezado

    private var encabezado: some View {
        VStack(spacing: 8) {
            Text(tituloFase).font(.headline).foregroundStyle(colorFase)
            Text(formatoMMSS(restante))
                .font(.system(size: 76, weight: .bold, design: .rounded).monospacedDigit())
                .minimumScaleFactor(0.5)
                .lineLimit(1)
            ProgressView(value: progreso).tint(colorFase)
            if !textoBajo.isEmpty {
                Text(textoBajo).font(.title3).multilineTextAlignment(.center)
            }
        }
    }

    private var restante: Double {
        s.fase == .listo ? Double(foco.config.focoMin * 60) : s.temporizador.restante(ahora: foco.ahora)
    }

    private var progreso: Double {
        let d = s.temporizador.duracion
        return d > 0 ? min(1, s.temporizador.transcurrido(ahora: foco.ahora) / d) : 0
    }

    private var tituloFase: String {
        var t = s.fase.nombre
        if s.fase == .foco {
            let cada = foco.config.bloquesHastaLargo
            t += " · bloque \(s.completados % cada + 1) de \(cada)"
        }
        if s.enPausa { t += " · en pausa" }
        return t
    }

    private var textoBajo: String { s.bloque?.intencion ?? s.mensaje }

    private var colorFase: Color {
        switch s.fase {
        case .listo: return Color.secondary
        case .foco: return Color.red
        case .arranque: return Color.orange
        case .descanso: return Color.green
        case .descansoLargo: return Color.teal
        }
    }

    // MARK: paneles

    @ViewBuilder private var panel: some View {
        if s.fase == .listo {
            panelListo
        } else if s.espera == .resultado {
            panelResultado
        } else if s.espera == .seguir {
            panelSeguir
        } else if s.enBloque {
            panelCorriendo
        } else {
            panelDescanso
        }
    }

    private var sugerencias: [String] {
        var l = sugerenciasDePlazos(plazos.tareas)
        let previa = s.ultimaIntencion
        if !previa.isEmpty && !l.contains(previa) { l.insert(previa, at: 0) }
        return l
    }

    private var panelListo: some View {
        let lista = sugerencias
        let pista = intencionVaga(intencion)
        return VStack(alignment: .leading, spacing: 10) {
            Text("¿Qué vas a hacer en este bloque?").font(.subheadline.weight(.semibold))
            TextField("Ej.: resolver los ejercicios 1 a 3 de la guía", text: $intencion, axis: .vertical)
                .textFieldStyle(.roundedBorder)
            if let pista = pista {
                Text(pista).font(.footnote).foregroundStyle(.orange)
            }
            if !lista.isEmpty {
                Menu {
                    ForEach(lista, id: \.self) { sug in
                        Button(sug) { intencion = sug }
                    }
                } label: {
                    Label("Elegir un siguiente paso de plazos", systemImage: "list.bullet")
                }
                .font(.subheadline)
            }
            HStack {
                Button { empezar(.foco) } label: {
                    Text("Empezar \(foco.config.focoMin) min").frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                Button { empezar(.arranque) } label: {
                    Text("Solo \(foco.config.arranqueMin) min").frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
            }
            if !foco.error.isEmpty {
                Text(foco.error).font(.footnote).foregroundStyle(.red)
            }
        }
    }

    private func empezar(_ tipo: Fase) {
        if foco.empezar(tipo, intencion: intencion) { intencion = "" }
    }

    private var panelCorriendo: some View {
        let textoPausa = s.enPausa ? "Reanudar" : "Pausar"
        let iconoPausa = s.enPausa ? "play.fill" : "pause.fill"
        let distracciones = s.bloque?.distracciones ?? 0
        return VStack(alignment: .leading, spacing: 12) {
            HStack {
                Button { foco.alternarPausa() } label: { Label(textoPausa, systemImage: iconoPausa) }
                    .buttonStyle(.borderedProminent)
                Button("Terminé antes") { foco.terminarAntes() }
                    .buttonStyle(.bordered)
                Button("Abandonar", role: .destructive) { confirmarAbandono = true }
                    .buttonStyle(.bordered)
            }
            .font(.subheadline)
            Text("¿Se te cruzó otra cosa? Anótala para después y sigue:").font(.subheadline)
            TextField("Ej.: responder a Pedro", text: $distraccion)
                .textFieldStyle(.roundedBorder)
                .submitLabel(.done)
                .onSubmit {
                    foco.anotarDistraccion(distraccion)
                    distraccion = ""
                }
            if distracciones > 0 {
                Text("Van \(distracciones) en este bloque; quedan en la lista para el descanso.")
                    .font(.footnote).foregroundStyle(.secondary)
            }
        }
        .confirmationDialog("¿Abandonar el bloque?", isPresented: $confirmarAbandono, titleVisibility: .visible) {
            Button("Abandonar", role: .destructive) { foco.abandonar() }
        }
    }

    private var panelResultado: some View {
        let pregunta = "¿Cómo te fue con «\(s.bloque?.intencion ?? "")»?"
        return VStack(alignment: .leading, spacing: 10) {
            Text(pregunta).font(.headline)
            HStack {
                ForEach([Resultado.terminado, Resultado.avance, Resultado.sinAvance], id: \.self) { r in
                    Button { foco.cerrar(r) } label: { Text(r.texto).frame(maxWidth: .infinity) }
                        .buttonStyle(.borderedProminent)
                        .tint(colorResultado(r))
                }
            }
        }
    }

    private func colorResultado(_ r: Resultado) -> Color {
        switch r {
        case .terminado: return Color.green
        case .avance: return Color.blue
        default: return Color.gray
        }
    }

    private var panelSeguir: some View {
        let c = foco.config
        let texto = "Pasaron los \(c.arranqueMin) minutos. Lo difícil era empezar, y ya empezaste. "
            + "¿Sigues hasta completar el bloque?"
        let seguir = "Seguir \(c.focoMin - c.arranqueMin) min más"
        return VStack(alignment: .leading, spacing: 10) {
            Text(texto).font(.headline)
            HStack {
                Button { foco.seguir() } label: { Text(seguir).frame(maxWidth: .infinity) }
                    .buttonStyle(.borderedProminent)
                Button { foco.terminarAntes() } label: { Text("Parar aquí").frame(maxWidth: .infinity) }
                    .buttonStyle(.bordered)
            }
        }
    }

    private var panelDescanso: some View {
        VStack(spacing: 10) {
            Text("Levántate, toma agua, mira lejos. Nada de pantallas que enganchen.")
                .multilineTextAlignment(.center)
                .foregroundStyle(.secondary)
            Button("Saltar descanso") { foco.saltarDescanso() }.buttonStyle(.bordered)
        }
    }
}

struct ParaDespues: View {
    @EnvironmentObject private var foco: FocoStore

    var body: some View {
        if !foco.pendientes.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Text("Para después").font(.headline)
                    Spacer()
                    Button("Vaciar", role: .destructive) { foco.vaciarPendientes() }.font(.subheadline)
                }
                ForEach(Array(foco.pendientes.enumerated()), id: \.offset) { i, p in
                    HStack(alignment: .top) {
                        Text(p).font(.subheadline)
                        Spacer()
                        Button { foco.borrarPendiente(i) } label: {
                            Image(systemName: "xmark.circle.fill").foregroundStyle(.secondary)
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
            .padding()
            .background(RoundedRectangle(cornerRadius: 12).fill(Color.gray.opacity(0.12)))
        }
    }
}

struct EstadisticasFoco: View {
    @EnvironmentObject private var foco: FocoStore

    var body: some View {
        let e = foco.estadisticasHoy
        VStack(alignment: .leading, spacing: 8) {
            Text(textoEstadisticas(e)).font(.subheadline)
            Chart(e.ultimos7) { d in
                BarMark(x: .value("Día", diaCorto(d.dia)), y: .value("Minutos", d.minutos))
                    .foregroundStyle(Calendar.current.isDateInToday(d.dia) ? Color.red : Color.red.opacity(0.35))
                    .annotation(position: .top) {
                        if d.minutos > 0 { Text("\(d.minutos)").font(.caption2) }
                    }
            }
            .chartYAxis(.hidden)
            .frame(height: 130)
        }
    }
}

struct AjustesFocoView: View {
    @EnvironmentObject private var foco: FocoStore
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        let c = foco.config
        NavigationStack {
            Form {
                Section {
                    Stepper("Bloque de foco: \(c.focoMin) min", value: $foco.config.focoMin,
                            in: ConfigFoco.rangoFoco, step: 5)
                    Stepper("Descanso: \(c.descansoMin) min", value: $foco.config.descansoMin,
                            in: ConfigFoco.rangoDescanso)
                    Stepper("Descanso largo: \(c.descansoLargoMin) min", value: $foco.config.descansoLargoMin,
                            in: ConfigFoco.rangoDescansoLargo)
                    Stepper("Largo cada \(c.bloquesHastaLargo) bloques", value: $foco.config.bloquesHastaLargo,
                            in: ConfigFoco.rangoBloques)
                    Stepper("Arranque: \(c.arranqueMin) min", value: $foco.config.arranqueMin,
                            in: 1...max(1, c.focoMin - 1))
                } header: {
                    Text("Tiempos")
                } footer: {
                    Text("El arranque es el «Solo unos minutos» para cuando no logras empezar.")
                }
                Section {
                    Toggle("Sonido al terminar", isOn: $foco.config.sonido)
                } footer: {
                    Text("El aviso llega aunque el iPhone esté bloqueado, si le diste permiso de notificaciones.")
                }
            }
            .navigationTitle("Tiempos")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Listo") { dismiss() } }
            }
        }
    }
}
