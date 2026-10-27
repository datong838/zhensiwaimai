import Foundation
import Vision
import AppKit

let args = CommandLine.arguments
guard args.count >= 2 else {
    FileHandle.standardError.write("usage: ocr <image> [zh-Hans|en-US]\n".data(using: .utf8)!)
    exit(1)
}
let imagePath = args[1]
let lang = args.count >= 3 ? args[2] : "zh-Hans"

guard let image = NSImage(contentsOfFile: imagePath),
      let cg = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    FileHandle.standardError.write("cannot load image\n".data(using: .utf8)!)
    exit(1)
}

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages = [lang, "en-US"]
request.usesLanguageCorrection = false

let handler = VNImageRequestHandler(cgImage: cg, options: [:])
try? handler.perform([request])

for observation in request.results ?? [] {
    guard let candidate = observation.topCandidates(1).first else { continue }
    let box = observation.boundingBox
    let width = CGFloat(cg.width)
    let height = CGFloat(cg.height)
    let x = box.origin.x * width
    let y = (1 - box.origin.y - box.height) * height
    let w = box.width * width
    let h = box.height * height
    print(String(format: "%.0f,%.0f,%.0f,%.0f\t%.3f\t%@",
                 x + w / 2, y + h / 2, w, h, candidate.confidence, candidate.string))
}
