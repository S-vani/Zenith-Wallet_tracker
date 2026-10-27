import AppIntents
import Capacitor
import UIKit

// Ways into Zenith from outside the app: Home Screen quick actions (press and hold the icon, see Info.plist and
// SceneDelegate.swift) and App Shortcuts, which iOS offers in Siri, Spotlight, the Shortcuts app and the Action
// button with no setup. The web code shows the screen (src/native/screens.js).

// The screens that can be asked for. The web code accepts only these names.
enum ZenithScreen: String {
    case dashboard
    case addTrade = "add-trade"
    case search
    case holdings

    // quick action types are "ca.zenithwalletracker.app.<screen>"
    init?(shortcutItem: UIApplicationShortcutItem) {
        guard let name = shortcutItem.type.split(separator: ".").last else { return nil }
        self.init(rawValue: String(name))
    }
}

enum ScreenRequest {
    // @capacitor/preferences keeps every key in UserDefaults.standard with this prefix, so the web code reads it
    // with Preferences.get({key: "pendingScreen"})
    static let pendingKey = "CapacitorStorage.pendingScreen"

    // Saved first, so a cold start finds it once the web view has loaded; a running web view is told right away
    @MainActor
    static func open(_ screen: ZenithScreen) {
        UserDefaults.standard.set(screen.rawValue, forKey: pendingKey)
        bridgeViewController()?.bridge?.triggerWindowJSEvent(eventName: "zenith:screen")
    }

    @MainActor
    private static func bridgeViewController() -> CAPBridgeViewController? {
        for scene in UIApplication.shared.connectedScenes {
            guard let windowScene = scene as? UIWindowScene else { continue }
            for window in windowScene.windows {
                if let bridge = window.rootViewController as? CAPBridgeViewController { return bridge }
            }
        }
        return nil
    }
}

// MARK: - App Intents (each opens the app on a screen)

struct OpenDashboardIntent: AppIntent {
    static let title: LocalizedStringResource = "Open Dashboard"
    static let openAppWhenRun: Bool = true

    @MainActor
    func perform() async throws -> some IntentResult {
        ScreenRequest.open(.dashboard)
        return .result()
    }
}

struct AddTradeIntent: AppIntent {
    static let title: LocalizedStringResource = "Add a Trade"
    static let openAppWhenRun: Bool = true

    @MainActor
    func perform() async throws -> some IntentResult {
        ScreenRequest.open(.addTrade)
        return .result()
    }
}

struct OpenSearchIntent: AppIntent {
    static let title: LocalizedStringResource = "Search Stocks and Crypto"
    static let openAppWhenRun: Bool = true

    @MainActor
    func perform() async throws -> some IntentResult {
        ScreenRequest.open(.search)
        return .result()
    }
}

struct OpenHoldingsIntent: AppIntent {
    static let title: LocalizedStringResource = "Open Holdings"
    static let openAppWhenRun: Bool = true

    @MainActor
    func perform() async throws -> some IntentResult {
        ScreenRequest.open(.holdings)
        return .result()
    }
}

// MARK: - Portfolio value, answered without opening the app

// "What's my portfolio worth in Zenith": reads out the sentence the app saved the last time the dashboard loaded
// (value, today's change and when it was updated; src/native/screens.js). It stays on the phone. Only with the
// iPhone unlocked, and never while Zenith's own Face ID lock is on: then it only says to open the app.
struct PortfolioValueIntent: AppIntent {
    static let title: LocalizedStringResource = "Portfolio Value"
    static let authenticationPolicy: IntentAuthenticationPolicy = .requiresAuthentication

    private static let snapshotKey = "CapacitorStorage.siriPortfolio"
    private static let lockSettingKey = "CapacitorStorage.biometricLock"

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let defaults = UserDefaults.standard
        if defaults.string(forKey: Self.lockSettingKey) == "on" {
            return .result(dialog: "Zenith is locked with Face ID. Open Zenith to see your portfolio.")
        }
        guard let sentence = defaults.string(forKey: Self.snapshotKey), !sentence.isEmpty else {
            return .result(dialog: "Open Zenith and sign in first, then ask again.")
        }
        return .result(dialog: "\(sentence)")
    }
}

// MARK: - The phrases Siri listens for (each must include the app's name)

struct ZenithAppShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: PortfolioValueIntent(),
            phrases: [
                "What's my portfolio worth in \(.applicationName)",
                "My \(.applicationName) portfolio value",
                "How is my \(.applicationName) portfolio doing",
            ],
            shortTitle: "Portfolio Value",
            systemImageName: "chart.line.uptrend.xyaxis"
        )
        AppShortcut(
            intent: AddTradeIntent(),
            phrases: [
                "Add a trade in \(.applicationName)",
                "Log a trade in \(.applicationName)",
            ],
            shortTitle: "Add Trade",
            systemImageName: "plus.circle"
        )
        AppShortcut(
            intent: OpenDashboardIntent(),
            phrases: [
                "Open my \(.applicationName) dashboard",
                "Show my \(.applicationName) dashboard",
            ],
            shortTitle: "Dashboard",
            systemImageName: "chart.pie"
        )
        AppShortcut(
            intent: OpenHoldingsIntent(),
            phrases: [
                "Show my \(.applicationName) holdings",
            ],
            shortTitle: "Holdings",
            systemImageName: "list.bullet.rectangle"
        )
        AppShortcut(
            intent: OpenSearchIntent(),
            phrases: [
                "Search in \(.applicationName)",
            ],
            shortTitle: "Search",
            systemImageName: "magnifyingglass"
        )
    }
}
