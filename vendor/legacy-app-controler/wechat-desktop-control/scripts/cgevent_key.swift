import Cocoa
import CoreGraphics

let args = CommandLine.arguments
guard args.count == 2 else {
    FileHandle.standardError.write("usage: cgevent_key <paste|send|select-all|delete|search|escape>\n".data(using: .utf8)!)
    exit(1)
}

let action = args[1]
let source = CGEventSource(stateID: .hidSystemState)

func postKey(_ code: CGKeyCode, flags: CGEventFlags = []) {
    guard let down = CGEvent(keyboardEventSource: source, virtualKey: code, keyDown: true),
          let up = CGEvent(keyboardEventSource: source, virtualKey: code, keyDown: false) else {
        exit(2)
    }
    down.flags = flags
    up.flags = flags
    down.post(tap: .cghidEventTap)
    usleep(80_000)
    up.post(tap: .cghidEventTap)
}

switch action {
case "paste": postKey(9, flags: .maskCommand)
case "send": postKey(36)
case "select-all": postKey(0, flags: .maskCommand)
case "delete": postKey(51)
case "search": postKey(3, flags: .maskCommand)
case "escape": postKey(53)
default:
    FileHandle.standardError.write("unsupported action\n".data(using: .utf8)!)
    exit(1)
}

print("key \(action)")
