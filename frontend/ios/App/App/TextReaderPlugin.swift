import Capacitor
import UIKit
import Vision

// Reads the text on a screenshot with Apple's Vision framework, on the phone: free, works offline, and the image
// never leaves the device (the web code turns the lines into a trade: src/Transactions/textReader.js and
// tradeTextParser.js). Registered by ZenithBridgeViewController; the web side calls it as "TextReader".
//
//   TextReader.read({image: <base64 JPEG>}) -> {lines: [{text, x, y, w, h}]}
//
// Coordinates are fractions of the image (0...1) with the origin at the top left, like the web code expects; lines
// come top to bottom, and left to right within a row.
@objc(TextReaderPlugin)
public class TextReaderPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "TextReaderPlugin"
    public let jsName = "TextReader"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "read", returnType: CAPPluginReturnPromise)
    ]

    @objc func read(_ call: CAPPluginCall) {
        guard let base64 = call.getString("image"),
              let data = Data(base64Encoded: base64, options: .ignoreUnknownCharacters),
              let image = UIImage(data: data),
              let cgImage = image.cgImage else {
            call.reject("That image couldn't be read.")
            return
        }
        let orientation = TextReaderPlugin.orientation(of: image)

        // off the main thread: recognition takes a moment on a big screenshot
        DispatchQueue.global(qos: .userInitiated).async {
            let request = VNRecognizeTextRequest()
            request.recognitionLevel = .accurate
            // tickers, amounts and dates aren't dictionary words: "correcting" them would change them
            request.usesLanguageCorrection = false
            request.recognitionLanguages = ["en-US", "fr-FR"]

            let handler = VNImageRequestHandler(cgImage: cgImage, orientation: orientation, options: [:])
            do {
                try handler.perform([request])
            } catch {
                call.reject("The text on this screenshot couldn't be read.")
                return
            }
            let observations = request.results ?? []
            call.resolve(["lines": TextReaderPlugin.lines(from: observations)])
        }
    }

    /// The recognised lines in reading order: rows top to bottom (Vision's y grows upwards), left to right in a row.
    static func lines(from observations: [VNRecognizedTextObservation]) -> [[String: Any]] {
        let byHeight = observations.sorted { $0.boundingBox.midY > $1.boundingBox.midY }
        var rows: [[VNRecognizedTextObservation]] = []
        for observation in byHeight {
            // the same row when its middle is within half a line of the row's first item
            if let first = rows.last?.first,
               abs(first.boundingBox.midY - observation.boundingBox.midY)
                   < min(first.boundingBox.height, observation.boundingBox.height) / 2 {
                rows[rows.count - 1].append(observation)
            } else {
                rows.append([observation])
            }
        }
        return rows.flatMap { row in
            row.sorted { $0.boundingBox.minX < $1.boundingBox.minX }.compactMap { observation -> [String: Any]? in
                guard let text = observation.topCandidates(1).first?.string, !text.isEmpty else { return nil }
                let box = observation.boundingBox
                return ["text": text, "x": box.minX, "y": 1 - box.maxY, "w": box.width, "h": box.height]
            }
        }
    }

    /// The image's orientation in Vision's terms (screenshots are always .up; photos from the camera may not be).
    static func orientation(of image: UIImage) -> CGImagePropertyOrientation {
        switch image.imageOrientation {
        case .up: return .up
        case .down: return .down
        case .left: return .left
        case .right: return .right
        case .upMirrored: return .upMirrored
        case .downMirrored: return .downMirrored
        case .leftMirrored: return .leftMirrored
        case .rightMirrored: return .rightMirrored
        @unknown default: return .up
        }
    }
}
