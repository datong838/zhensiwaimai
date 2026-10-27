import Foundation
import Vision
import AppKit
let args=CommandLine.arguments
guard args.count==3, ["全选","复制"].contains(args[2]), let image=NSImage(contentsOfFile:args[1]), let cg=image.cgImage(forProposedRect:nil,context:nil,hints:nil) else { exit(2) }
let request=VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages=["zh-Hans","en-US"]
request.usesLanguageCorrection=false
try VNImageRequestHandler(cgImage:cg,options:[:]).perform([request])
for obs in request.results ?? [] {
 guard let text=obs.topCandidates(1).first,let range=text.string.range(of:args[2]),let region=try text.boundingBox(for:range) else { continue }
 let b=region.boundingBox
 print(String(format:"%.0f,%.0f",b.midX*CGFloat(cg.width),(1-b.midY)*CGFloat(cg.height)))
}
