import SwiftUI

@main
struct SocialLiteApp: App {
    @StateObject private var settings = FilterSettings()
    @StateObject private var stats = UsageStats()

    var body: some Scene {
        WindowGroup {
            if SelfTest.isRequested {
                SelfTestView()
            } else {
                ContentView()
                    .environmentObject(settings)
                    .environmentObject(stats)
            }
        }
    }
}
