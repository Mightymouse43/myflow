// MyFlow launcher: a real Mach-O executable inside MyFlow.app that spawns the venv Python as a child.
// macOS attributes Microphone and Accessibility permissions to this bundle ("MyFlow"), not to "python3".
import Foundation

let exe = URL(fileURLWithPath: CommandLine.arguments[0]).resolvingSymlinksInPath()
let resources = exe.deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("Resources")
let pythonPathFile = resources.appendingPathComponent("python_path")

guard let pythonPath = try? String(contentsOf: pythonPathFile, encoding: .utf8)
        .trimmingCharacters(in: .whitespacesAndNewlines), !pythonPath.isEmpty else {
    FileHandle.standardError.write("MyFlow: missing Contents/Resources/python_path\n".data(using: .utf8)!)
    exit(1)
}

let proc = Process()
proc.executableURL = URL(fileURLWithPath: pythonPath)
proc.arguments = ["-m", "voz", "run"]
var env = ProcessInfo.processInfo.environment
env["PYTHONUNBUFFERED"] = "1"
proc.environment = env
proc.standardOutput = FileHandle.standardOutput
proc.standardError = FileHandle.standardError
proc.terminationHandler = { p in exit(p.terminationStatus) }

// Forward termination signals (launchctl, Activity Monitor, logout) to the child.
signal(SIGTERM, SIG_IGN)
signal(SIGINT, SIG_IGN)
let term = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .main)
term.setEventHandler { proc.terminate() }
term.resume()
let intr = DispatchSource.makeSignalSource(signal: SIGINT, queue: .main)
intr.setEventHandler { proc.terminate() }
intr.resume()

do {
    try proc.run()
} catch {
    FileHandle.standardError.write("MyFlow: could not start \(pythonPath): \(error)\n".data(using: .utf8)!)
    exit(1)
}
dispatchMain()
