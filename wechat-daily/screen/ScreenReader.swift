import CoreGraphics
import Foundation
import ScreenCaptureKit
import Vision

private let weChatBundleID = "com.tencent.xinWeChat"

private struct Settings: Decodable {
    let group: String
    let windowID: UInt32?
    let interval: Double
    let header: [Double]
    let messages: [Double]
}

private struct Event: Encodable {
    let kind: String
    let at: Int
    let lines: [String]?
    let lineCount: Int?

    init(_ kind: String, lines: [String]? = nil, lineCount: Int? = nil) {
        self.kind = kind
        self.at = Int(Date().timeIntervalSince1970)
        self.lines = lines
        self.lineCount = lineCount
    }
}

private enum ReaderError: Error {
    case arguments
    case permission
    case region
    case recognition
}

@main
private struct ScreenReader {
    static func main() async {
        do {
            let args = Array(CommandLine.arguments.dropFirst())
            if args == ["authorize"] {
                if !CGPreflightScreenCaptureAccess() && !CGRequestScreenCaptureAccess() {
                    throw ReaderError.permission
                }
                print("已获得屏幕录制权限")
            } else if args == ["permission-status"] {
                try checkPermission()
                print("已获得屏幕录制权限")
            } else if args == ["list-windows"] {
                try checkPermission()
                for window in try await windows() {
                    print("\(window.windowID)\t\(Int(window.frame.width))×\(Int(window.frame.height))")
                }
            } else if args == ["watch"] || args == ["probe"] {
                let data = FileHandle.standardInput.readDataToEndOfFile()
                let settings = try JSONDecoder().decode(Settings.self, from: data)
                try await watch(settings, once: args == ["probe"])
            } else if args.count == 2, args[0] == "ocr-file" {
                let request = makeRequest()
                let url = URL(fileURLWithPath: args[1])
                try VNImageRequestHandler(url: url, options: [:]).perform([request])
                for line in lines(from: request) { print(line) }
            } else {
                throw ReaderError.arguments
            }
        } catch ReaderError.permission {
            fail("请在本机授权屏幕录制，然后重新打开启动采集器的终端。")
        } catch ReaderError.arguments {
            fail("用法：wechat-screen authorize | permission-status | list-windows | probe | watch | ocr-file 图片路径")
        } catch ReaderError.region {
            fail("截图区域配置无效，请检查 window_id、header_region 和 messages_region。")
        } catch ReaderError.recognition {
            fail("系统 OCR 无法从这张截图识别文字。")
        } catch {
            fail("屏幕读取失败（\((error as NSError).domain) / \((error as NSError).code)）。")
        }
    }

    private static func checkPermission() throws {
        guard CGPreflightScreenCaptureAccess() else { throw ReaderError.permission }
    }

    private static func windows() async throws -> [SCWindow] {
        let content = try await SCShareableContent.excludingDesktopWindows(true, onScreenWindowsOnly: true)
        return content.windows.filter {
            $0.owningApplication?.bundleIdentifier == weChatBundleID && $0.isOnScreen &&
            $0.windowLayer == 0 && $0.frame.width >= 400 && $0.frame.height >= 300
        }
    }

    private static func frame(_ window: SCWindow) async throws -> CGImage {
        let filter = SCContentFilter(desktopIndependentWindow: window)
        let config = SCStreamConfiguration()
        config.capturesAudio = false
        config.showsCursor = false
        config.ignoreShadowsSingleWindow = true
        let scale = max(1, CGFloat(filter.pointPixelScale))
        config.width = Int((filter.contentRect.width * scale).rounded(.up))
        config.height = Int((filter.contentRect.height * scale).rounded(.up))
        return try await SCScreenshotManager.captureImage(contentFilter: filter, configuration: config)
    }

    private static func crop(_ image: CGImage, region: [Double]) throws -> CGImage {
        guard region.count == 4, region.allSatisfy({ $0.isFinite && $0 >= 0 }),
              region[2] > 0, region[3] > 0, region[0] + region[2] <= 1, region[1] + region[3] <= 1 else {
            throw ReaderError.region
        }
        let width = Double(image.width)
        let height = Double(image.height)
        let rect = CGRect(x: region[0] * width, y: region[1] * height,
                          width: region[2] * width, height: region[3] * height).integral
        guard let cropped = image.cropping(to: rect) else { throw ReaderError.region }
        return cropped
    }

    private static func makeRequest() -> VNRecognizeTextRequest {
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.recognitionLanguages = ["zh-Hans", "en-US"]
        return request
    }

    private static func lines(from request: VNRecognizeTextRequest) -> [String] {
        (request.results ?? []).sorted {
            if $0.boundingBox.midY == $1.boundingBox.midY { return $0.boundingBox.minX < $1.boundingBox.minX }
            return $0.boundingBox.midY > $1.boundingBox.midY
        }.compactMap { $0.topCandidates(1).first?.string }
    }

    private static func recognize(_ image: CGImage) throws -> [String] {
        let request = makeRequest()
        do {
            try VNImageRequestHandler(cgImage: image, options: [:]).perform([request])
        } catch {
            throw ReaderError.recognition
        }
        return lines(from: request)
    }

    private static func matchesGroup(_ expected: String, titles: [String]) -> Bool {
        let target = expected.precomposedStringWithCompatibilityMapping.filter { !$0.isWhitespace }
        guard !target.isEmpty else { return false }
        return titles.contains { raw in
            let title = raw.precomposedStringWithCompatibilityMapping.filter { !$0.isWhitespace }
            let withoutCount = title.replacingOccurrences(of: #"\([0-9]+\)$"#, with: "", options: .regularExpression)
            return title == target || withoutCount == target
        }
    }

    private static func watch(_ config: Settings, once: Bool) async throws {
        try checkPermission()
        guard config.interval.isFinite, (2...20).contains(config.interval) else { throw ReaderError.region }
        var pinnedWindow = config.windowID
        repeat {
            let result: Event
            do {
                let available = try await windows()
                let selected = pinnedWindow == nil && available.count == 1
                    ? available.first : available.first { $0.windowID == pinnedWindow }
                if let selected = selected {
                    pinnedWindow = selected.windowID
                    let image = try await frame(selected)
                    if matchesGroup(config.group, titles: try recognize(crop(image, region: config.header))) {
                        result = Event("frame", lines: try recognize(crop(image, region: config.messages)))
                    } else {
                        result = Event("title-mismatch")
                    }
                } else {
                    result = Event("window-unavailable")
                }
            } catch ReaderError.region {
                throw ReaderError.region
            } catch ReaderError.recognition {
                result = Event("ocr-unavailable")
            } catch {
                result = Event("window-unavailable")
            }
            if once {
                emit(Event(result.kind, lineCount: result.lines?.count))
                return
            }
            emit(result)
            try await Task.sleep(nanoseconds: UInt64(config.interval * 1_000_000_000))
        } while !Task.isCancelled
    }

    private static func emit(_ entry: Event) {
        guard var data = try? JSONEncoder().encode(entry) else { return }
        data.append(10)
        FileHandle.standardOutput.write(data)
    }

    private static func fail(_ message: String) -> Never {
        FileHandle.standardError.write(Data((message + "\n").utf8))
        exit(1)
    }
}
