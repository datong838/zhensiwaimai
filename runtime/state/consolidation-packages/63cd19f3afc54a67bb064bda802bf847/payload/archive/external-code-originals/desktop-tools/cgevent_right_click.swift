import Cocoa
import CoreGraphics

let args = CommandLine.arguments
guard args.count >= 3, let x = Double(args[1]), let y = Double(args[2]) else {
    FileHandle.standardError.write("usage: cgevent_right_click <x> <y>\n".data(using: .utf8)!)
    exit(1)
}
let p = CGPoint(x: x, y: y)
let src = CGEventSource(stateID: .hidSystemState)
let down = CGEvent(mouseEventSource: src, mouseType: .rightMouseDown, mouseCursorPosition: p, mouseButton: .right)!
let up = CGEvent(mouseEventSource: src, mouseType: .rightMouseUp, mouseCursorPosition: p, mouseButton: .right)!
down.post(tap: .cghidEventTap)
usleep(100_000)
up.post(tap: .cghidEventTap)
print("right-clicked \(x),\(y)")
