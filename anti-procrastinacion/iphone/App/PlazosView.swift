import SwiftUI
import UniformTypeIdentifiers
import Logica

struct IdTarea: Identifiable {
    let id: String
}

struct PlazosView: View {
    @EnvironmentObject private var store: PlazosStore
    @State private var ahora = Date()
    @State private var nueva = false
    @State private var detalle: IdTarea?
    @State private var importando = false
    @State private var origenImportar: URL?
    @State private var mensaje: String?
    private let reloj = Timer.publish(every: 30, on: .main, in: .common).autoconnect()

    var body: some View {
        NavigationStack {
            List {
                Section { cabecera }
                Section {
                    let visibles = store.visibles(ahora: ahora)
                    if visibles.isEmpty {
                        Text("Sin entregas. Agrega la primera con +.").foregroundStyle(.secondary)
                    }
                    ForEach(visibles) { t in
                        let a = analizar(t, ahora: ahora, capacidad: store.capacidad)
                        Button { detalle = IdTarea(id: t.id) } label: {
                            FilaTarea(tarea: t, analisis: a, ahora: ahora)
                        }
                        .buttonStyle(.plain)
                        .listRowBackground(colorFondo(t.entregada ? nil : a.estado))
                    }
                }
            }
            .navigationTitle("Plazos")
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) { menu }
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button { nueva = true } label: { Image(systemName: "plus") }
                }
            }
            .sheet(isPresented: $nueva) { TareaForm(tarea: nil) }
            .sheet(item: $detalle) { d in TareaDetalle(id: d.id) }
            .fileImporter(isPresented: $importando, allowedContentTypes: [.json]) { resultado in
                if case .success(let url) = resultado { origenImportar = url }
            }
            .confirmationDialog("¿Reemplazar tus entregas por las del archivo?", isPresented: hayImportacion,
                                titleVisibility: .visible) {
                Button("Reemplazar", role: .destructive) { importar() }
            } message: {
                Text("Lo que tienes ahora queda respaldado en plazos_datos.antes-de-importar.json.")
            }
            .alert("Plazos", isPresented: hayMensaje) {
                Button("OK", role: .cancel) { mensaje = nil }
            } message: {
                Text(mensaje ?? "")
            }
        }
        .onReceive(reloj) { ahora = $0 }
        .onAppear {
            ahora = Date()
            mostrarAvisos()
        }
    }

    private var cabecera: some View {
        let r = resumir(store.tareas, ahora: ahora, capacidad: store.capacidad)
        let (l1, l2) = textoResumen(r)
        let hechas = horasRegistradas(store.datos.registro, el: ahora)
        let textoHechas = hechas > 0 ? "Hoy registraste \(formatoHoras(hechas))." : "Hoy no has registrado horas todavía."
        let textoCapacidad = "Capacidad diaria: \(formatoHoras(store.capacidad))"
        return VStack(alignment: .leading, spacing: 6) {
            Text(l1).font(.headline).foregroundStyle(colorCarga(r))
            if !l2.isEmpty { Text(l2).font(.subheadline) }
            Text(textoHechas).font(.footnote).foregroundStyle(.secondary)
            Stepper(textoCapacidad, value: $store.capacidad, in: 0.5...16, step: 0.5).font(.footnote)
        }
        .padding(.vertical, 4)
    }

    private var menu: some View {
        Menu {
            Toggle("Mostrar entregadas", isOn: $store.mostrarEntregadas)
            ShareLink(item: store.url) {
                Label("Exportar plazos_datos.json", systemImage: "square.and.arrow.up")
            }
            Button { importando = true } label: {
                Label("Importar desde el PC…", systemImage: "square.and.arrow.down")
            }
        } label: {
            Image(systemName: "ellipsis.circle")
        }
    }

    private var hayImportacion: Binding<Bool> {
        Binding(get: { origenImportar != nil }, set: { if !$0 { origenImportar = nil } })
    }

    private var hayMensaje: Binding<Bool> {
        Binding(get: { mensaje != nil }, set: { if !$0 { mensaje = nil } })
    }

    private func importar() {
        guard let u = origenImportar else { return }
        origenImportar = nil
        do {
            let n = try store.importar(desde: u)
            mensaje = "Importé \(n) entrega(s)."
        } catch {
            mensaje = "No pude leer ese archivo: \(error.localizedDescription)"
        }
        mostrarAvisos()
    }

    private func mostrarAvisos() {
        if !store.avisos.isEmpty {
            mensaje = ([mensaje].compactMap { $0 } + store.avisos).joined(separator: "\n\n")
            store.avisos = []
        }
    }
}

struct FilaTarea: View {
    let tarea: Tarea
    let analisis: Analisis
    let ahora: Date

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(alignment: .firstTextBaseline) {
                Text(tarea.nombre).font(.headline)
                if !tarea.curso.isEmpty {
                    Text(tarea.curso).font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Text(estado).font(.caption.bold())
            }
            Text(lineaTiempo).font(.subheadline)
            Text(paso)
                .font(.footnote)
                .foregroundStyle(tarea.siguientePaso.recortado.isEmpty ? Color.orange : Color.secondary)
                .lineLimit(2)
        }
        .padding(.vertical, 4)
    }

    private var estado: String { tarea.entregada ? "entregada" : analisis.estado.texto }

    private var paso: String {
        tarea.siguientePaso.recortado.isEmpty ? "⚠ define el siguiente paso" : tarea.siguientePaso
    }

    private var lineaTiempo: String {
        var partes = [formatoEntrega(tarea.entrega, ahora: ahora)]
        if !tarea.entregada {
            partes.append(formatoReloj(analisis.horasReloj))
            if analisis.faltan > 0 { partes.append("faltan \(formatoHoras(analisis.faltan))") }
            if analisis.estado != .lista && analisis.estado != .vencida {
                partes.append("hoy \(formatoHoras(analisis.hoy))")
            }
        }
        return partes.joined(separator: " · ")
    }
}

func colorFondo(_ e: Estado?) -> Color {
    guard let e = e else { return Color.gray.opacity(0.08) }
    switch e {
    case .vencida: return Color.gray.opacity(0.18)
    case .imposible: return Color.red.opacity(0.32)
    case .rojo: return Color.red.opacity(0.18)
    case .amarillo: return Color.yellow.opacity(0.25)
    case .verde: return Color.green.opacity(0.18)
    case .lista: return Color.blue.opacity(0.12)
    }
}

func colorCarga(_ r: Resumen) -> Color {
    if r.activas == 0 { return Color.primary }
    if r.hoyTotal <= r.capacidad * 0.5 { return Color.green }
    return r.hoyTotal <= r.capacidad ? Color.orange : Color.red
}

// MARK: - Detalle

struct TareaDetalle: View {
    @EnvironmentObject private var store: PlazosStore
    @Environment(\.dismiss) private var dismiss
    let id: String
    @State private var editando = false
    @State private var pasoHecho = false
    @State private var confirmarBorrar = false

    var body: some View {
        NavigationStack {
            Group {
                if let t = store.tarea(id) {
                    contenido(t)
                } else {
                    Text("Esta entrega ya no existe.").foregroundStyle(.secondary)
                }
            }
            .navigationTitle(store.tarea(id)?.nombre ?? "")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Listo") { dismiss() } }
            }
            .sheet(isPresented: $editando) {
                if let t = store.tarea(id) { TareaForm(tarea: t) }
            }
            .sheet(isPresented: $pasoHecho) { PasoHechoForm(id: id) }
        }
    }

    private func contenido(_ t: Tarea) -> some View {
        let ahora = Date()
        let a = analizar(t, ahora: ahora, capacidad: store.capacidad)
        let viva = !t.entregada && a.estado != .lista && a.estado != .vencida
        let llevas = "\(formatoHoras(t.horasHechas)) de \(formatoHoras(t.horasEstimadas))"
        let siPostergas = a.siPostergas.map { formatoHoras($0) + " al día" } ?? "no alcanza"
        let textoEntregada = t.entregada ? "Reabrir" : "Marcar entregada"
        let preguntaBorrar = "¿Eliminar «\(t.nombre)»? No se puede deshacer."
        return List {
            Section {
                LabeledContent("Entrega", value: formatoEntrega(t.entrega, ahora: ahora))
                LabeledContent("Queda", value: formatoReloj(a.horasReloj))
                LabeledContent("Llevas", value: llevas)
                if viva {
                    LabeledContent("Hoy toca", value: formatoHoras(a.hoy))
                    LabeledContent("Si postergas", value: siPostergas)
                }
                if !t.curso.isEmpty { LabeledContent("Curso", value: t.curso) }
            }
            Section {
                Text(t.siguientePaso.recortado.isEmpty ? "—" : t.siguientePaso)
                if let aviso = consejo(t, a) {
                    Text(aviso).font(.footnote).foregroundStyle(.orange)
                }
            } header: {
                Text("Siguiente paso")
            }
            Section {
                Button("+25 min") { store.sumarHoras(id, 25.0 / 60) }
                Button("+1 h") { store.sumarHoras(id, 1) }
                Button("Paso hecho…") { pasoHecho = true }
            } header: {
                Text("Registrar trabajo")
            }
            Section {
                Button("Editar…") { editando = true }
                Button(textoEntregada) { store.alternarEntregada(id) }
                Button("Eliminar", role: .destructive) { confirmarBorrar = true }
            }
        }
        .confirmationDialog(preguntaBorrar, isPresented: $confirmarBorrar, titleVisibility: .visible) {
            Button("Eliminar", role: .destructive) {
                store.eliminar(id)
                dismiss()
            }
        }
    }

    private func consejo(_ t: Tarea, _ a: Analisis) -> String? {
        if t.entregada || a.estado == .lista { return nil }
        if a.estado == .vencida {
            return "Venció. Si ya la entregaste, márcala; si te dieron prórroga, edita la fecha."
        }
        if a.estado == .imposible {
            return "Con lo que estimaste no alcanza ni trabajando sin parar. Decide hoy qué recortar "
                + "o pide prórroga; esperar no lo arregla."
        }
        return pasoVago(t.siguientePaso)
    }
}

// MARK: - Formularios

struct TareaForm: View {
    @EnvironmentObject private var store: PlazosStore
    @Environment(\.dismiss) private var dismiss
    private let original: Tarea?
    @State private var nombre: String
    @State private var curso: String
    @State private var entrega: Date
    @State private var estimadas: String
    @State private var hechas: String
    @State private var paso: String
    @State private var error = ""

    init(tarea: Tarea?) {
        original = tarea
        _nombre = State(initialValue: tarea?.nombre ?? "")
        _curso = State(initialValue: tarea?.curso ?? "")
        _entrega = State(initialValue: tarea?.entrega ?? TareaForm.entregaPorOmision())
        // horasEditables, no formatoHoras: guardar sin cambios no debe ir redondeando las horas.
        _estimadas = State(initialValue: tarea.map { horasEditables($0.horasEstimadas) } ?? "")
        _hechas = State(initialValue: tarea.map { horasEditables($0.horasHechas) } ?? "0")
        _paso = State(initialValue: tarea?.siguientePaso ?? "")
    }

    static func entregaPorOmision() -> Date {
        let cal = Calendar.current
        let en7 = cal.date(byAdding: .day, value: 7, to: Date()) ?? Date()
        return cal.date(bySettingHour: 23, minute: 59, second: 0, of: en7) ?? en7
    }

    private var titulo: String { original == nil ? "Nueva entrega" : "Editar entrega" }

    private var textoQueda: String {
        "Queda \(formatoReloj(entrega.timeIntervalSinceNow / 3600))."
    }

    private var pistaHoras: String {
        if let h = try? parseHoras(estimadas) {
            return "En total: \(formatoHoras(h)). Súmale un tercio a lo que creas: casi todo toma más."
        }
        return "Tu mejor estimación. Ej.: 6 · 2,5 · 1h30. Súmale un tercio: casi todo toma más."
    }

    private var pistaPaso: String { pasoVago(paso) ?? "Bien: concreto y empezable." }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("Entrega (ej. Informe T2)", text: $nombre)
                    TextField("Curso (opcional)", text: $curso)
                }
                Section {
                    DatePicker("Fecha y hora", selection: $entrega)
                } header: {
                    Text("Entrega")
                } footer: {
                    Text(textoQueda)
                }
                Section {
                    TextField("Horas de trabajo en total", text: $estimadas)
                        .keyboardType(.numbersAndPunctuation)
                    TextField("Horas ya trabajadas", text: $hechas)
                        .keyboardType(.numbersAndPunctuation)
                } header: {
                    Text("Horas")
                } footer: {
                    Text(pistaHoras)
                }
                Section {
                    TextField("Lo primero que harías al sentarte", text: $paso, axis: .vertical)
                } header: {
                    Text("Siguiente paso")
                } footer: {
                    Text(pistaPaso)
                }
                if !error.isEmpty {
                    Section { Text(error).foregroundStyle(.red) }
                }
            }
            .navigationTitle(titulo)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancelar") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) { Button("Guardar") { guardar() } }
            }
        }
    }

    private func guardar() {
        let n = nombre.recortado
        guard !n.isEmpty else {
            error = "Ponle nombre a la entrega."
            return
        }
        let est: Double
        let hh: Double
        do {
            est = try parseHoras(estimadas)
            hh = try parseHoras(hechas.recortado.isEmpty ? "0" : hechas)
        } catch {
            self.error = error.localizedDescription
            return
        }
        guard est > 0 else {
            error = "Las horas totales tienen que ser más que cero."
            return
        }
        let fecha = Calendar.current.dateInterval(of: .minute, for: entrega)?.start ?? entrega
        var t = original ?? Tarea(nombre: n, entrega: fecha, horasEstimadas: est)
        t.nombre = n
        t.curso = curso.recortado
        t.entrega = fecha
        t.horasEstimadas = est
        t.horasHechas = hh
        t.siguientePaso = paso.recortado
        store.guardarTarea(t)
        dismiss()
    }
}

struct PasoHechoForm: View {
    @EnvironmentObject private var store: PlazosStore
    @Environment(\.dismiss) private var dismiss
    let id: String
    @State private var tiempo = ""
    @State private var paso = ""
    @State private var error = ""

    private var pistaTiempo: String {
        if tiempo.recortado.isEmpty { return "Si no lo registraste antes. Ej.: 45 min · 1h30" }
        if let h = try? parseHoras(tiempo) { return "Se suman \(formatoHoras(h))." }
        return "Ej.: 45 min · 1h30"
    }

    private var pistaPaso: String { pasoVago(paso) ?? "Bien: concreto y empezable." }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("Tiempo (opcional)", text: $tiempo).keyboardType(.numbersAndPunctuation)
                } header: {
                    Text("¿Cuánto le dedicaste?")
                } footer: {
                    Text(pistaTiempo)
                }
                Section {
                    TextField("Lo primero que harías al sentarte", text: $paso, axis: .vertical)
                } header: {
                    Text("¿Cuál es el siguiente paso?")
                } footer: {
                    Text(pistaPaso)
                }
                if !error.isEmpty {
                    Section { Text(error).foregroundStyle(.red) }
                }
            }
            .navigationTitle("Paso hecho")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancelar") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) { Button("Guardar") { guardar() } }
            }
        }
    }

    private func guardar() {
        var horas = 0.0
        if !tiempo.recortado.isEmpty {
            do {
                horas = try parseHoras(tiempo)
            } catch {
                self.error = error.localizedDescription
                return
            }
        }
        store.pasoHecho(id, horas: horas, nuevoPaso: paso.recortado)
        dismiss()
    }
}
