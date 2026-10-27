import Cocoa
import CoreGraphics

let args = CommandLine.arguments
let activate = args.contains("--activate-wechat")
let numeric = args.dropFirst().filter { $0 != "--activate-wechat" }

guard numeric.count >= 2,
      let x = Double(numeric[numeric.startIndex]),
      let y = Double(numeric[numeric.index(after: numeric.startIndex)]) else {
    FileHandle.standardError.write(
        "usage: cgevent_click [--activate-wechat] <x> <y>\n".data(using: .utf8)!
    )
    exit(1)
}

let point = CGPoint(x: x, y: y)

func postClick(at p: CGPoint) {
    let src = CGEventSource(stateID: .hidSystemState)
    let down = CGEvent(
        mouseEventSource: src,
        mouseType: .leftMouseDown,
        mouseCursorPosition: p,
        mouseButton: .left
    )!
    let up = CGEvent(
        mouseEventSource: src,
        mouseType: .leftMouseUp,
        mouseCursorPosition: p,
        mouseButton: .left
    )!
    down.post(tap: .cghidEventTap)
    usleep(80_000)
    up.post(tap: .cghidEventTap)
}

if activate {
    if let app = NSRunningApplication.runningApplications(withBundleIdentifier: "com.tencent.xinWeChat").first {
        app.activate(options: [.activateIgnoringOtherApps])
        Thread.sleep(forTimeInterval: 0.4)
    }
}

postClick(at: point)
print(String(format: "clicked %.1f,%.1f", x, y))
