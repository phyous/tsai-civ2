// OCR only a supplied local game capture; never reads the desktop or other apps.
import Foundation
import Vision
import AppKit

func recognize(_ path: String) throws -> [[String: Any]] {
    let url = URL(fileURLWithPath: path)
    // Each image still gets its own request and handler. Only framework startup
    // and internal framework caches survive between independent observations.
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = false
    request.recognitionLanguages = ["en-US"]
    let handler = VNImageRequestHandler(url: url)
    try handler.perform([request])
    return (request.results ?? []).compactMap { observation in
        guard let text = observation.topCandidates(1).first else { return nil }
        let b = observation.boundingBox
        return ["text": text.string, "confidence": text.confidence,
                "x": b.origin.x, "y": 1 - b.origin.y - b.height,
                "width": b.width, "height": b.height]
    }
}

func emit(_ value: Any, newline: Bool = false) throws {
    var data = try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
    if newline { data.append(10) }
    FileHandle.standardOutput.write(data)
}

guard CommandLine.arguments.count == 2 else { exit(2) }
if CommandLine.arguments[1] == "--worker" {
    try emit(["ready": 1], newline: true)
    while let line = readLine() {
        // Private stdin/stdout pipes only: no listener, external port, or cache
        // of image results. The Python owner serializes and bounds requests.
        let valid: Bool = autoreleasepool {
            guard line.utf8.count <= 16384,
                  let data = line.data(using: .utf8),
                  let message = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let id = message["id"] as? Int, let path = message["path"] as? String else { return false }
            do { try emit(["id": id, "rows": try recognize(path)], newline: true) }
            catch { try? emit(["id": id, "error": "Game image OCR failed"], newline: true) }
            return true
        }
        if !valid { exit(2) }
    }
} else {
    do { try emit(recognize(CommandLine.arguments[1])) }
    catch {
        FileHandle.standardError.write(Data("Game image OCR failed\n".utf8))
        exit(1)
    }
}
