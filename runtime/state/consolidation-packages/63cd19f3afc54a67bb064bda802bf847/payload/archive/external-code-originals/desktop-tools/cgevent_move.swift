import Cocoa
import CoreGraphics

let args = CommandLine.arguments
guard args.count >= 3,
      let x = Double(args[1]),
      let y = Double(args[2]) else {
    FileHandle.standardError.write("usage: cgevent_move <x> <y>\n".data(using: .utf8)!)
    exit(1)
}

let p = CGPoint(x: x, y: y)
let move = CGEvent(mouseEventSource: nil, mouseType: .mouseMoved, mouseCursorPosition: p, mouseButton: .left)!
move.post(tap: .cghidEventTap)
print(String(format: "moved %.1f,%.1f", x, y))
