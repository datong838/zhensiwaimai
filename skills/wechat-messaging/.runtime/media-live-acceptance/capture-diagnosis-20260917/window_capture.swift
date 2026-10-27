import AppKit
import ScreenCaptureKit
import Foundation

@main struct WindowCapture {
    @MainActor static func main() async {
        _ = NSApplication.shared
        do {
            guard CommandLine.arguments.count == 3, let wanted = UInt32(CommandLine.arguments[1]) else {
                throw NSError(domain: "capture-arguments-invalid", code: 1)
            }
            let content = try await SCShareableContent.excludingDesktopWindows(true, onScreenWindowsOnly: false)
            let mains = content.windows.filter {
                $0.owningApplication?.bundleIdentifier == "com.tencent.xinWeChat" && $0.title == "微信"
                    && $0.frame.width >= 900 && $0.frame.height >= 560 && $0.windowLayer == 0
            }
            guard mains.count == 1, let window = mains.first, window.windowID == wanted else {
                throw NSError(domain: "capture-main-window-identity-mismatch", code: 2)
            }
            let filter = SCContentFilter(desktopIndependentWindow: window)
            let config = SCStreamConfiguration()
            config.width = Int(filter.contentRect.width * CGFloat(filter.pointPixelScale))
            config.height = Int(filter.contentRect.height * CGFloat(filter.pointPixelScale))
            config.ignoreShadowsSingleWindow = true
            config.showsCursor = false
            let image = try await SCScreenshotManager.captureImage(contentFilter: filter, configuration: config)
            let bitmap = NSBitmapImageRep(cgImage: image)
            guard let data = bitmap.representation(using: .png, properties: [:]) else {
                throw NSError(domain: "capture-png-invalid", code: 3)
            }
            try data.write(to: URL(fileURLWithPath: CommandLine.arguments[2]), options: .atomic)
            print("{\"ok\":true,\"windowId\":\(wanted),\"width\":\(image.width),\"height\":\(image.height)}")
        } catch {
            fputs("\(error)\n", stderr)
            exit(1)
        }
    }
}
