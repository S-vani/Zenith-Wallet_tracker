import Capacitor
import UIKit

// The web view's controller (SceneDelegate makes it the window's root). It exists to register the plugins that live
// in this app instead of in an npm package; Capacitor's way to do that is a CAPBridgeViewController subclass.
class ZenithBridgeViewController: CAPBridgeViewController {
    override func capacitorDidLoad() {
        bridge?.registerPluginInstance(TextReaderPlugin())
    }
}
