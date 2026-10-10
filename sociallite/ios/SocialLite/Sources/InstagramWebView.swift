import SwiftUI
import UIKit
import WebKit

/// Pedido de navegación desde SwiftUI: un id nuevo carga la ruta aunque se repita.
struct NavRequest: Equatable {
    let id: UUID
    let path: String
}

/// WKWebView con instagram.com y el filtro de shared/filter.js inyectado.
///
/// La sesión de Instagram vive solo en `WKWebsiteDataStore.default()` de este iPhone.
/// El filtro corre en un mundo de JavaScript aparte (`WKContentWorld.defaultClient`):
/// ve el mismo DOM, pero los scripts de Instagram no ven ni pueden falsificar sus mensajes.
struct InstagramWebView: UIViewRepresentable {
    let configJSON: String
    let lockedToDMs: Bool
    let navRequest: NavRequest?
    let onBlocked: (String) -> Void
    let onRoute: (String) -> Void

    static let startURL = URL(string: "https://www.instagram.com/direct/inbox/")!
    static let handlerName = "sociallite"
    static let world = WKContentWorld.defaultClient

    func makeCoordinator() -> Coordinator { Coordinator(parent: self) }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default()
        config.allowsInlineMediaPlayback = true
        // Para que Instagram sirva la web móvil completa.
        config.applicationNameForUserAgent = "Version/18.0 Mobile/15E148 Safari/604.1"

        let contenido = WKUserContentController()
        Self.installScripts(on: contenido, configJSON: configJSON, locked: lockedToDMs)
        contenido.add(context.coordinator, contentWorld: Self.world, name: Self.handlerName)
        config.userContentController = contenido

        let web = WKWebView(frame: .zero, configuration: config)
        web.navigationDelegate = context.coordinator
        web.uiDelegate = context.coordinator
        web.allowsBackForwardNavigationGestures = true

        context.coordinator.lastLocked = lockedToDMs
        // Un pedido que ya existía al crear el WebView (p. ej. tras cambiar un filtro) no se repite.
        context.coordinator.lastNavId = navRequest?.id
        // Siempre se abre primero en Mensajes.
        web.load(URLRequest(url: Self.startURL))
        return web
    }

    func updateUIView(_ web: WKWebView, context: Context) {
        let c = context.coordinator
        c.parent = self

        if c.lastLocked != lockedToDMs {
            c.lastLocked = lockedToDMs
            let contenido = web.configuration.userContentController
            contenido.removeAllUserScripts()
            // Para las próximas cargas…
            Self.installScripts(on: contenido, configJSON: configJSON, locked: lockedToDMs)
            // …y en vivo, sin recargar la página actual.
            web.evaluateJavaScript(
                "window.SocialLiteFilter && window.SocialLiteFilter.update({lockToDMs: \(lockedToDMs)})",
                in: nil, in: Self.world, completionHandler: nil)
        }

        if let nav = navRequest, nav.id != c.lastNavId {
            c.lastNavId = nav.id
            if let url = URL(string: "https://www.instagram.com" + nav.path) {
                web.load(URLRequest(url: url))
            }
        }
    }

    static func dismantleUIView(_ web: WKWebView, coordinator: Coordinator) {
        // Sin esto, WKUserContentController retiene al coordinador y queda un ciclo.
        web.configuration.userContentController.removeScriptMessageHandler(forName: handlerName, contentWorld: world)
        web.navigationDelegate = nil
        web.uiDelegate = nil
    }

    /// Dos scripts en .atDocumentStart, solo en el frame principal: la config y el filtro.
    static func installScripts(on contenido: WKUserContentController, configJSON: String, locked: Bool) {
        let arranque = "window.__SOCIALLITE_CONFIG__ = Object.assign(\(configJSON), { lockToDMs: \(locked) });"
        contenido.addUserScript(WKUserScript(source: arranque, injectionTime: .atDocumentStart,
                                             forMainFrameOnly: true, in: world))
        contenido.addUserScript(WKUserScript(source: FilterScript.source, injectionTime: .atDocumentStart,
                                             forMainFrameOnly: true, in: world))
    }

    /// Dominios que se quedan dentro del WebView; el resto se abre afuera.
    static let allowedHosts = ["instagram.com", "cdninstagram.com", "fbcdn.net", "facebook.com", "fbsbx.com"]

    static func isAllowedHost(_ host: String?) -> Bool {
        guard let h = host?.lowercased() else { return false }
        return allowedHosts.contains { h == $0 || h.hasSuffix("." + $0) }
    }

    @MainActor
    final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandler {
        var parent: InstagramWebView
        var lastLocked = false
        var lastNavId: UUID?

        init(parent: InstagramWebView) {
            self.parent = parent
        }

        // MARK: mensajes del filtro

        func userContentController(_ userContentController: WKUserContentController,
                                   didReceive message: WKScriptMessage) {
            guard message.name == InstagramWebView.handlerName,
                  let body = message.body as? [String: Any],
                  let tipo = body["type"] as? String else { return }
            let motivo = body["reason"] as? String ?? ""
            switch tipo {
            case "blocked": parent.onBlocked(motivo)
            case "route": parent.onRoute(motivo)
            default: break
            }
        }

        // MARK: política de navegación

        func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                     decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            guard let url = navigationAction.request.url else {
                decisionHandler(.allow)
                return
            }
            let esquema = (url.scheme ?? "").lowercased()
            if ["about", "blob", "data"].contains(esquema) {
                decisionHandler(.allow)
                return
            }
            if esquema == "http" || esquema == "https" {
                // targetFrame nil = ventana nueva (target=_blank): se trata como principal.
                let principal = navigationAction.targetFrame?.isMainFrame ?? true
                if principal && !InstagramWebView.isAllowedHost(url.host) {
                    UIApplication.shared.open(url)
                    decisionHandler(.cancel)
                    return
                }
                decisionHandler(.allow)
                return
            }
            // instagram://, mailto:, tel:… se abren afuera.
            UIApplication.shared.open(url)
            decisionHandler(.cancel)
        }

        // target=_blank: si es de Instagram se carga en el mismo WebView; si no, afuera.
        func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                     for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
            if let url = navigationAction.request.url {
                if InstagramWebView.isAllowedHost(url.host) {
                    webView.load(navigationAction.request)
                } else {
                    UIApplication.shared.open(url)
                }
            }
            return nil
        }
    }
}
