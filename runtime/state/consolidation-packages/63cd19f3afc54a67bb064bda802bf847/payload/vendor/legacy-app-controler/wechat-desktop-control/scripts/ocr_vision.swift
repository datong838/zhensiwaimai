import Foundation
import Vision
import AppKit

// 用法: ocr_vision.swift <image_path> [lang]
// 输出: x,y,w,h<TAB>confidence<TAB>text （y 为从顶部像素坐标）

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

let results = request.results ?? []
for obs in results {
    guard let cand = obs.topCandidates(1).first else { continue }
    // Vision 坐标系: 原点左下, 归一化 → 转为左上原点像素
    let box = obs.boundingBox
    let H = CGFloat(cg.height)
    let W = CGFloat(cg.width)
    let x = box.origin.x * W
    let y = (1 - box.origin.y - box.height) * H
    let w = box.width * W
    let h = box.height * H
    let cx = x + w / 2
    let cy = y + h / 2
    print(String(format: "%.0f,%.0f,%.0f,%.0f\t%.3f\t%@", cx, cy, w, h, cand.confidence, cand.string))
}
