import SwiftUI
import UIKit
import WebKit

/// Autoprueba para la CI: `simctl launch … cl.cifuentes.sociallite --autoprueba`.
///
/// Carga una página falsa de Instagram en un WKWebView real del simulador, con los mismos
/// scripts y el mismo mundo de JavaScript que la app, y revisa que el filtro se inyecte,
/// oculte, redirija y avise por el puente nativo. No toca la red ni la sesión real:
/// usa un almacén de datos no persistente y cancela toda navegación después de la primera.
/// Imprime «AUTOPRUEBA OK» o la lista de fallas, y cierra la app.
@MainActor
final class SelfTest: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
    static let isRequested = CommandLine.arguments.contains("--autoprueba")

    private static let fixture = """
    <!doctype html><html><head></head><body>
    <nav><a href="/reels/">Reels</a><a href="/direct/inbox/">Mensajes</a></nav>
    <main>
      <article id="ad"><span>Publicidad</span><a href="/p/AD1/">x</a></article>
      <article id="ok"><a href="/p/N1/">x</a></article>
      <article id="reel"><a href="/reel/R1/">x</a></article>
    </main>
    </body></html>
    """

    private(set) var web: WKWebView!
    private var messages: [String] = []
    private var navigations: [String] = []
    private var firstLoad = true
    private var failures: [String] = []

    func makeWebView() -> WKWebView {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .nonPersistent()
        let contenido = WKUserContentController()
        InstagramWebView.installScripts(on: contenido, configJSON: FilterSettings().configJSON, locked: false)
        contenido.add(self, contentWorld: InstagramWebView.world, name: InstagramWebView.handlerName)
        config.userContentController = contenido

        web = WKWebView(frame: .zero, configuration: config)
        web.navigationDelegate = self
        web.loadHTMLString(Self.fixture, baseURL: URL(string: "https://www.instagram.com/"))
        Task { await run() }
        // Vigía: si algo se cuelga, la CI no espera para siempre.
        Task {
            await pause(180)
            finish(extra: "se acabó el tiempo")
        }
        return web
    }

    // MARK: pruebas

    private func run() async {
        let pagina = WKContentWorld.page
        let filtro = InstagramWebView.world

        // El primer arranque del simulador es lento: se espera a que el filtro avise la ruta
        // (eso ya prueba la inyección y el puente) y a que pase un escaneo (250 ms).
        let cargo = await waitFor(seconds: 90) { self.messages.contains("route:home") }
        expect(cargo ? "sí" : messages.joined(separator: ","), "sí", "el puente nativo recibe la ruta")
        guard cargo else { return finish(extra: "la página de prueba no cargó") }
        await pause(1.0)

        expect(await js("document.documentElement.getAttribute('data-sl-route')", pagina), "home", "ruta del inicio")
        expect(await js("document.getElementById('ad').getAttribute('data-sl-hidden')", pagina), "ad", "oculta publicidad")
        expect(await js("document.getElementById('reel').getAttribute('data-sl-hidden')", pagina), "reel",
               "oculta reels del inicio")
        expect(await js("document.getElementById('ok').getAttribute('data-sl-hidden')", pagina), "null",
               "deja ver lo normal")
        expect(await js("getComputedStyle(document.querySelector('a[href=\"/reels/\"]')).display", pagina), "none",
               "oculta la pestaña Reels")
        expect(await js("getComputedStyle(document.documentElement).filter", pagina), "grayscale(1)",
               "escala de grises en el inicio")
        expect(await js("typeof window.SocialLiteFilter", pagina), "undefined", "la página no ve el filtro")
        expect(await js("typeof window.SocialLiteFilter", filtro), "object", "el filtro está en su mundo")

        // La página navega sola al feed de reels (como hace la SPA de Instagram).
        _ = await js("history.pushState({}, '', '/reels/')", pagina)
        _ = await waitFor(seconds: 10) { !self.navigations.isEmpty }
        expect(messages.contains("blocked:reels-feed") ? "sí" : messages.joined(separator: ","), "sí",
               "avisa el bloqueo del feed de reels")
        expect(navigations.first ?? "ninguna", "/", "sale del feed de reels hacia el inicio")

        // Se acabó el tiempo del día: el filtro manda a Mensajes en vivo.
        navigations.removeAll()
        _ = await js("window.SocialLiteFilter.update({lockToDMs: true})", filtro)
        _ = await waitFor(seconds: 10) { !self.navigations.isEmpty }
        expect(navigations.first ?? "ninguna", UsageStats.inboxPath, "bloqueo en vivo manda a Mensajes")

        finish(extra: nil)
    }

    private func expect(_ actual: String, _ expected: String, _ name: String) {
        if actual != expected { failures.append("\(name): se esperaba «\(expected)», llegó «\(actual)»") }
    }

    /// Espera hasta que se cumpla la condición o se acabe el plazo; devuelve si se cumplió.
    private func waitFor(seconds: Double, _ condition: () -> Bool) async -> Bool {
        let limite = Date().addingTimeInterval(seconds)
        while !condition() {
            if Date() > limite { return false }
            await pause(0.25)
        }
        return true
    }

    private func pause(_ seconds: Double) async {
        try? await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000))
    }

    /// Evalúa y devuelve siempre un texto (`String(…)` evita resultados nulos del puente).
    private func js(_ code: String, _ world: WKContentWorld) async -> String {
        await withCheckedContinuation { cont in
            web.evaluateJavaScript("String(\(code))", in: nil, in: world) { result in
                switch result {
                case .success(let valor): cont.resume(returning: "\(valor)")
                case .failure(let error): cont.resume(returning: "error: \(error.localizedDescription)")
                }
            }
        }
    }

    private var finished = false

    private func finish(extra: String?) {
        guard !finished else { return }
        finished = true
        if let extra { failures.append(extra) }
        if failures.isEmpty {
            print("AUTOPRUEBA OK")
        } else {
            print("AUTOPRUEBA FALLA")
            failures.forEach { print(" - \($0)") }
        }
        fflush(stdout)
        exit(failures.isEmpty ? 0 : 1)
    }

    // MARK: puente y navegación

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard let body = message.body as? [String: Any] else { return }
        let tipo = body["type"] as? String ?? ""
        let motivo = body["reason"] as? String ?? ""
        messages.append("\(tipo):\(motivo)")
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if firstLoad {
            firstLoad = false
            decisionHandler(.allow)
            return
        }
        // Se anota a dónde quería ir y se cancela: nunca se conecta a Instagram.
        if let url = navigationAction.request.url {
            navigations.append(URLComponents(url: url, resolvingAgainstBaseURL: false)?.path ?? url.path)
        }
        decisionHandler(.cancel)
    }
}

struct SelfTestView: UIViewRepresentable {
    func makeCoordinator() -> SelfTest { SelfTest() }
    func makeUIView(context: Context) -> WKWebView { context.coordinator.makeWebView() }
    func updateUIView(_ web: WKWebView, context: Context) {}
}
