import Foundation

func fecha(_ y: Int, _ m: Int, _ d: Int, _ h: Int = 0, _ mi: Int = 0, _ s: Int = 0) -> Date {
    Calendar.current.date(from: DateComponents(year: y, month: m, day: d, hour: h, minute: mi, second: s))!
}

func carpetaTemporal() -> URL {
    let d = FileManager.default.temporaryDirectory.appendingPathComponent("logica-\(UUID().uuidString)")
    try? FileManager.default.createDirectory(at: d, withIntermediateDirectories: true)
    return d
}

/// Archivos escritos por las apps de escritorio (plazos.py y foco.py), byte a byte.
/// Si estos se leen bien, el mismo archivo sirve en el PC y en el iPhone.
enum Escritorio {
    static let plazosJSON = Data(base64Encoded: """
    ewogICJ2ZXJzaW9uIjogMSwKICAidGFyZWFzIjogWwogICAgewogICAgICAibm9tYnJlIjogIkluZm9ybWUgVDIgwqtyZWRlc8K7IiwKICAgICAgImVudHJlZ2EiOiAiMjAyNi0xMC0xMlQxODowMCIsCiAgICAgICJob3Jhc19lc3RpbWFkYXMiOiA5LAogICAgICAiaG9yYXNfaGVjaGFzIjogMS41LAogICAgICAiY3Vyc28iOiAiSUVFMjU0NCIsCiAgICAgICJzaWd1aWVudGVfcGFzbyI6ICJlc2NyaWJpciBpbnRybzsgc2VjY2nDs24gXCIxXCIiLAogICAgICAiZW50cmVnYWRhIjogZmFsc2UsCiAgICAgICJpZCI6ICJhMWIyYzNkNCIsCiAgICAgICJjcmVhZGEiOiAiMjAyNi0xMC0wMVQxMDowMCIKICAgIH0sCiAgICB7CiAgICAgICJub21icmUiOiAiQ29udHJvbCAyIiwKICAgICAgImVudHJlZ2EiOiAiMjAyNi0xMC0xMFQyMzo1OSIsCiAgICAgICJob3Jhc19lc3RpbWFkYXMiOiA2LjUsCiAgICAgICJob3Jhc19oZWNoYXMiOiAxLjc1LAogICAgICAiY3Vyc28iOiAiIiwKICAgICAgInNpZ3VpZW50ZV9wYXNvIjogIiIsCiAgICAgICJlbnRyZWdhZGEiOiB0cnVlLAogICAgICAiaWQiOiAiZTVmNmE3YjgiLAogICAgICAiY3JlYWRhIjogIjIwMjYtMTAtMDJUMDk6MzAiCiAgICB9CiAgXSwKICAicmVnaXN0cm8iOiBbCiAgICB7CiAgICAgICJmZWNoYSI6ICIyMDI2LTEwLTA5VDE1OjIwIiwKICAgICAgInRhcmVhIjogImExYjJjM2Q0IiwKICAgICAgImhvcmFzIjogMS41CiAgICB9CiAgXQp9
    """)!

    static let focoCSV = Data(base64Encoded: """
    77u/aW5pY2lvO2Zpbjt0aXBvO21pbnV0b3NfcGxhbmVhZG9zO21pbnV0b3NfcmVhbGVzO2ludGVuY2lvbjtyZXN1bHRhZG87ZGlzdHJhY2Npb25lcw0KMjAyNi0xMC0wOVQwOTowMDowMDsyMDI2LTEwLTA5VDA5OjI1OjAwO2ZvY287MjU7MjU7ImluZm9ybWU7IHNlY2Npw7NuICIiMiIiLCBjb24gY29tYXMsCnkgc2FsdG8iO3Rlcm1pbmFkbzsxDQoyMDI2LTEwLTA5VDEwOjAwOjAwOzIwMjYtMTAtMDlUMTA6MDU6MDA7YXJyYW5xdWU7NTs1O8OxYW5kw7ogw7wgw6HDqcOtO2F2YW5jZTswDQo=
    """)!
}
