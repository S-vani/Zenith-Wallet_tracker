import UIKit
import Capacitor

class SceneDelegate: UIResponder, UIWindowSceneDelegate {
    var window: UIWindow?

    // Covers the app the moment it stops being active (app switcher, Control Center, leaving) while the Face ID lock
    // is on. iOS takes the app switcher snapshot right after this, before the web view's own lock screen can paint,
    // so without it the snapshot could show the portfolio.
    private var privacyCover: UIView?

    // Written by @capacitor/preferences (key "biometricLock", see src/native/biometric.js): it stores every key in
    // UserDefaults.standard with the "CapacitorStorage." prefix, and the value is "on" or the key is removed.
    private static let lockSettingKey = "CapacitorStorage.biometricLock"

    func scene(_ scene: UIScene, willConnectTo session: UISceneSession, options connectionOptions: UIScene.ConnectionOptions) {
        guard let windowScene = scene as? UIWindowScene else { return }

        window = UIWindow(windowScene: windowScene)
        window?.rootViewController = CAPBridgeViewController()
        window?.makeKeyAndVisible()

        SceneDelegateProxy.shared.scene(scene, willConnectTo: session, options: connectionOptions)

        // launched from a Home Screen quick action: the web view opens that screen once it has loaded
        if let item = connectionOptions.shortcutItem, let screen = ZenithScreen(shortcutItem: item) {
            ScreenRequest.open(screen)
        }
    }

    // a Home Screen quick action while the app was already running
    func windowScene(_ windowScene: UIWindowScene, performActionFor shortcutItem: UIApplicationShortcutItem,
                     completionHandler: @escaping (Bool) -> Void) {
        guard let screen = ZenithScreen(shortcutItem: shortcutItem) else {
            completionHandler(false)
            return
        }
        ScreenRequest.open(screen)
        completionHandler(true)
    }

    func scene(_ scene: UIScene, openURLContexts URLContexts: Set<UIOpenURLContext>) {
        SceneDelegateProxy.shared.scene(scene, openURLContexts: URLContexts)
    }

    func scene(_ scene: UIScene, continue userActivity: NSUserActivity) {
        SceneDelegateProxy.shared.scene(scene, continue: userActivity)
    }

    func sceneWillResignActive(_ scene: UIScene) {
        guard privacyCover == nil,
              let window = window,
              UserDefaults.standard.string(forKey: SceneDelegate.lockSettingKey) == "on" else { return }

        // the same picture as the launch screen: the navy #060a12 background with the Zenith logo
        let cover = UIImageView(frame: window.bounds)
        cover.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        cover.backgroundColor = UIColor(red: 6 / 255, green: 10 / 255, blue: 18 / 255, alpha: 1)
        cover.image = UIImage(named: "Splash")
        cover.contentMode = .scaleAspectFill
        cover.isUserInteractionEnabled = false
        window.addSubview(cover)
        privacyCover = cover
    }

    // Leaving with the Face ID lock on: a share sheet or the in-app Safari sheet is a native screen above the web
    // view, so it would still be open (and usable) over "Zenith is locked" on the way back. Close it.
    func sceneDidEnterBackground(_ scene: UIScene) {
        guard UserDefaults.standard.string(forKey: SceneDelegate.lockSettingKey) == "on" else { return }
        window?.rootViewController?.presentedViewController?.dismiss(animated: false)
    }

    func sceneDidBecomeActive(_ scene: UIScene) {
        // back on screen: the web view's own lock screen (or the unlocked app) takes over
        privacyCover?.removeFromSuperview()
        privacyCover = nil
    }
}
