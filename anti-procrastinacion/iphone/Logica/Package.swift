// swift-tools-version:5.9
// La lógica de la app de iPhone, sin interfaz: se prueba con `swift test`
// en cualquier Mac (y en Linux), sin simulador.
import PackageDescription

let package = Package(
    name: "Logica",
    platforms: [.iOS(.v16), .macOS(.v13)],
    products: [.library(name: "Logica", targets: ["Logica"])],
    targets: [
        .target(name: "Logica"),
        .testTarget(name: "LogicaTests", dependencies: ["Logica"]),
    ]
)
