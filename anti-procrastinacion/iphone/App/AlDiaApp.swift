import SwiftUI
import UIKit
import UserNotifications
import Logica

@main
struct AlDiaApp: App {
    @UIApplicationDelegateAdaptor(Delegado.self) private var delegado
    @StateObject private var plazos: PlazosStore
    @StateObject private var foco: FocoStore
    @State private var pestana: Pestana

    init() {
        let args = ProcessInfo.processInfo.arguments
        if args.contains("--autoprueba") {
            exit(Autoprueba.correr())
        }
        // --demo: datos de ejemplo en una carpeta aparte (para capturas), sin tocar los tuyos.
        let demo = args.contains("--demo")
        let dir = demo ? Almacen.carpetaDemo() : Almacen.carpetaDocumentos()
        if demo { Almacen.sembrarDemo(en: dir) }
        _plazos = StateObject(wrappedValue: PlazosStore(carpeta: dir, guardarAjustes: !demo))
        _foco = StateObject(wrappedValue: FocoStore(carpeta: dir, guardarAjustes: !demo))
        _pestana = State(initialValue: args.contains("--foco") ? .foco : .plazos)
    }

    var body: some Scene {
        WindowGroup {
            TabView(selection: $pestana) {
                PlazosView()
                    .tabItem { Label("Plazos", systemImage: "calendar") }
                    .tag(Pestana.plazos)
                FocoView()
                    .tabItem { Label("Foco", systemImage: "timer") }
                    .tag(Pestana.foco)
            }
            .environmentObject(plazos)
            .environmentObject(foco)
        }
    }
}

enum Pestana: Hashable {
    case plazos, foco
}

/// Muestra el aviso de fin de bloque también con la app abierta (iOS lo oculta por omisión).
final class Delegado: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
    func application(_ application: UIApplication,
                     didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        UNUserNotificationCenter.current().delegate = self
        return true
    }

    // Versión async: la de completionHandler cambió de firma (@Sendable) entre SDKs, y si no
    // calza exacta iOS la ignora sin avisar.
    func userNotificationCenter(_ center: UNUserNotificationCenter,
                                willPresent notification: UNNotification) async -> UNNotificationPresentationOptions {
        [.banner, .sound]
    }
}
