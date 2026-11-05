// agentmeter menu bar app for macOS: a native status item, no SwiftBar.
// Shows tokens used in the current window (config `period`, a week by default) and a
// per-model breakdown. Data comes from `agentmeter --periods 2 --json`; this file knows
// nothing about log formats.
//
// Build (install.sh does this; needs only the Xcode Command Line Tools):
//   swiftc -O -swift-version 5 macos/AgentmeterBar.swift -o ~/.local/bin/agentmeter-bar
//
// Config (~/.config/agentmeter/config.json, optional "widget" key):
//   "style":   "stacked" (default: small caption over the number, like the system's compact items)
//              or "icon" (an icon followed by the number)
//   "caption": text above the number in the stacked style (default "TOKENS")
//   "icon":    for the icon style: "chart" (default, drawn here), "none", or any SF Symbol name
//   "refresh_minutes": 15 (default)
import AppKit

let home = FileManager.default.homeDirectoryForCurrentUser
let env = ProcessInfo.processInfo.environment
let configURL = URL(fileURLWithPath: (env["AGENTMETER_CONFIG"] ?? "~/.config/agentmeter/config.json").expandingTilde)
// AGENTMETER_REPORTS: read reports from another folder (e.g. demo data for screenshots)
let reportsURL = env["AGENTMETER_REPORTS"].map { URL(fileURLWithPath: $0.expandingTilde) }
    ?? home.appendingPathComponent(".local/share/agentmeter/reports")

extension String {
    var expandingTilde: String { (self as NSString).expandingTildeInPath }
}

func fmt(_ n: Double) -> String {
    if n >= 1e9 { return String(format: "%.2fB", n / 1e9) }
    if n >= 1e6 { return String(format: "%.2fM", n / 1e6) }
    if n >= 1e3 { return String(format: "%.0fk", n / 1e3) }
    return String(Int(n))
}

func findAgentmeter() -> String? {
    var candidates = [env["AGENTMETER_BIN"], home.appendingPathComponent(".local/bin/agentmeter").path,
                      "/opt/homebrew/bin/agentmeter", "/usr/local/bin/agentmeter"].compactMap { $0 }
    candidates += (env["PATH"] ?? "").split(separator: ":").map { "\($0)/agentmeter" }
    return candidates.first { FileManager.default.isExecutableFile(atPath: $0) }
}

func readWidgetConfig() -> [String: Any] {
    guard let data = try? Data(contentsOf: configURL),
          let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return [:] }
    return obj["widget"] as? [String: Any] ?? [:]
}

/// Bar chart on a baseline: "usage over the week". A template image, so it follows light/dark menu bars.
func chartIcon() -> NSImage {
    let img = NSImage(size: NSSize(width: 16, height: 16), flipped: false) { _ in
        NSColor.black.set()
        let base = NSBezierPath()
        base.move(to: NSPoint(x: 1, y: 1.6)); base.line(to: NSPoint(x: 15, y: 1.6))
        base.lineWidth = 1.4; base.lineCapStyle = .round; base.stroke()
        for (i, h) in [CGFloat(6), 11, 4, 8.5].enumerated() {
            NSBezierPath(roundedRect: NSRect(x: 2 + CGFloat(i) * 3.25, y: 3.2, width: 2.3, height: h), xRadius: 0.8, yRadius: 0.8).fill()
        }
        return true
    }
    img.isTemplate = true
    return img
}

func icon(_ name: String) -> NSImage? {
    switch name {
    case "none": return nil
    case "chart", "": return chartIcon()
    default:
        let cfg = NSImage.SymbolConfiguration(pointSize: 13, weight: .regular)
        let img = NSImage(systemSymbolName: name, accessibilityDescription: "agentmeter")?.withSymbolConfiguration(cfg)
        img?.isTemplate = true
        return img ?? chartIcon()
    }
}

/// Two-line label in the style of the system's compact status items: a small caption over the value.
func stackedLabel(caption: String, value: String) -> NSImage {
    // sizes and spacing match the compact two-line items other menu bar apps use (e.g. Stats' "GPU / 0%")
    let capFont = NSFont.systemFont(ofSize: 7.5, weight: .medium)
    let valFont = NSFont.monospacedDigitSystemFont(ofSize: 12, weight: .medium)
    let para = NSMutableParagraphStyle(); para.alignment = .center
    let cap = NSAttributedString(string: caption, attributes: [.font: capFont, .paragraphStyle: para])
    let val = NSAttributedString(string: value, attributes: [.font: valFont, .paragraphStyle: para])
    let width = ceil(max(cap.size().width, val.size().width)) + 2
    let height = NSStatusBar.system.thickness
    let img = NSImage(size: NSSize(width: width, height: height), flipped: false) { r in
        let mid = r.height / 2
        cap.draw(in: NSRect(x: 0, y: mid + 0.5, width: r.width, height: cap.size().height))
        val.draw(in: NSRect(x: 0, y: mid - val.size().height + 3, width: r.width, height: val.size().height))
        return true
    }
    img.isTemplate = true
    return img
}

/// Bar colours by rank, most-used model first.
let palette: [NSColor] = [.systemBlue, .systemTeal, .systemPurple, .systemOrange, .systemPink, .systemGreen]

/// "▲ 25%", "▼ 19%", "no change", or "new" when there was nothing before.
func changeLabel(_ cur: Double, _ prev: Double) -> String {
    guard prev > 0 else { return cur > 0 ? "new" : "–" }
    let p = Int((100 * (cur - prev) / prev).rounded())
    return p == 0 ? "no change" : "\(p > 0 ? "▲" : "▼") \(abs(p))%"
}

/// A rounded bar: a faint track with the share filled in the model's colour (at least a sliver when used).
func shareBar(_ share: Double, colour: NSColor, width: CGFloat = 96, height: CGFloat = 7) -> NSImage {
    NSImage(size: NSSize(width: width, height: height), flipped: false) { r in
        NSColor.quaternaryLabelColor.setFill()
        NSBezierPath(roundedRect: r, xRadius: height / 2, yRadius: height / 2).fill()
        if share > 0 {
            let w = max(height, r.width * CGFloat(min(1, share)))
            colour.setFill()
            NSBezierPath(roundedRect: NSRect(x: 0, y: 0, width: w, height: r.height), xRadius: height / 2, yRadius: height / 2).fill()
        }
        return true
    }
}

/// "claude-opus-5-5   [bar]   1.23M": name, the model's share of the window as a bar, the value.
func modelRow(_ model: String, width: Int, share: Double, value: Double, colour: NSColor) -> NSAttributedString {
    let mono = NSFont.monospacedSystemFont(ofSize: 12, weight: .regular)
    let name = model.count > width ? String(model.prefix(width)) : model.padding(toLength: width, withPad: " ", startingAt: 0)
    let v = fmt(value)
    let out = NSMutableAttributedString(string: name + "  ", attributes: [.font: mono, .foregroundColor: NSColor.labelColor])
    let bar = NSTextAttachment()
    bar.image = shareBar(share, colour: colour)
    bar.bounds = NSRect(x: 0, y: 1, width: 96, height: 7)
    out.append(NSAttributedString(attachment: bar))
    out.append(NSAttributedString(string: String(repeating: " ", count: max(2, 9 - v.count)) + v,
                                  attributes: [.font: mono, .foregroundColor: NSColor.labelColor]))
    return out
}

struct Row {
    let period, tool, model: String
    let fresh, total: Double
    let sessions: Int
}

struct Snapshot {
    var rows: [Row] = []
    var thisPeriod = "", lastPeriod = "", name = "week"
    var labels: [String: String] = [:]
    var sessionKeys: [String: Set<String>] = [:]   // period -> distinct "tool/session" (a session using two models counts once)
    var error: String?

    func sessions(_ p: String) -> Int { sessionKeys[p]?.count ?? 0 }

    func rows(_ p: String) -> [Row] { rows.filter { $0.period == p }.sorted { $0.fresh > $1.fresh } }
    func fresh(_ p: String) -> Double { rows(p).reduce(0) { $0 + $1.fresh } }
    func total(_ p: String) -> Double { rows(p).reduce(0) { $0 + $1.total } }
}

func loadSnapshot() -> Snapshot {
    guard let bin = findAgentmeter() else {
        return Snapshot(error: "agentmeter not found in ~/.local/bin, Homebrew or PATH")
    }
    let p = Process()
    p.executableURL = URL(fileURLWithPath: bin)
    p.arguments = ["--periods", "2", "--json"]
    p.environment = env.merging(["AGENTMETER_NO_WIZARD": "1"]) { $1 }
    let out = Pipe(), err = Pipe()
    p.standardOutput = out; p.standardError = err
    do { try p.run() } catch { return Snapshot(error: "could not run \(bin): \(error.localizedDescription)") }
    let data = out.fileHandleForReading.readDataToEndOfFile()
    let errText = String(data: err.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
    p.waitUntilExit()
    guard p.terminationStatus == 0,
          let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
        return Snapshot(error: "agentmeter failed: \(errText.trimmingCharacters(in: .whitespacesAndNewlines).prefix(140))")
    }
    var s = Snapshot()
    let cfg = obj["config"] as? [String: Any] ?? [:]
    s.thisPeriod = cfg["this_period"] as? String ?? ""
    s.lastPeriod = cfg["last_period"] as? String ?? ""
    s.name = (cfg["period"] as? [String: Any])?["name"] as? String ?? "week"
    s.labels = cfg["labels"] as? [String: String] ?? [:]
    for r in obj["periods"] as? [[String: Any]] ?? [] {
        s.rows.append(Row(period: r["period"] as? String ?? "", tool: r["tool"] as? String ?? "",
                          model: r["model"] as? String ?? "?",
                          fresh: (r["fresh"] as? NSNumber)?.doubleValue ?? 0,
                          total: (r["total"] as? NSNumber)?.doubleValue ?? 0,
                          sessions: (r["sessions"] as? NSNumber)?.intValue ?? 0))
    }
    for r in obj["sessions"] as? [[String: Any]] ?? [] where (r["auto"] as? Bool) != true {
        let p = r["period"] as? String ?? ""
        s.sessionKeys[p, default: []].insert("\(r["tool"] as? String ?? "")/\(r["session"] as? String ?? "")")
    }
    return s
}

final class App: NSObject, NSApplicationDelegate, NSMenuDelegate {
    let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    var snap = Snapshot()
    var loading = false
    var timer: Timer?
    var stacked = true
    var shotTaken = false
    var caption = "TOKENS"

    func applicationDidFinishLaunching(_ n: Notification) {
        let w = readWidgetConfig()
        stacked = (w["style"] as? String ?? "stacked") != "icon"
        caption = (w["caption"] as? String ?? "TOKENS").uppercased()
        if !stacked {
            item.button?.image = icon(w["icon"] as? String ?? "chart")
            item.button?.imagePosition = .imageLeading
        }
        setTitle("…")
        let menu = NSMenu()
        menu.autoenablesItems = false   // info lines have no action; without this macOS greys them out
        menu.delegate = self
        item.menu = menu
        refresh()
        offerSetupOnce()
        let minutes = max(1, (w["refresh_minutes"] as? NSNumber)?.doubleValue ?? 15)
        timer = Timer.scheduledTimer(withTimeInterval: minutes * 60, repeats: true) { [weak self] _ in self?.refresh() }
    }

    func setTitle(_ s: String) {
        if stacked {
            item.button?.title = ""
            item.button?.image = stackedLabel(caption: caption, value: s)
            item.button?.imagePosition = .imageOnly
            return
        }
        let font = NSFont.monospacedDigitSystemFont(ofSize: NSFont.systemFontSize, weight: .regular)
        item.button?.attributedTitle = NSAttributedString(string: " " + s, attributes: [.font: font, .baselineOffset: 0.5])
    }

    @objc func refresh() {
        if loading { return }
        loading = true
        DispatchQueue.global(qos: .utility).async {
            let s = loadSnapshot()
            DispatchQueue.main.async {
                self.snap = s
                self.loading = false
                self.setTitle(s.error == nil ? fmt(s.fresh(s.thisPeriod)) : "—")
                #if SCREENSHOT
                // screenshot builds only (swiftc -D SCREENSHOT): open the menu once data has loaded
                if !self.shotTaken { self.shotTaken = true
                    // move the pointer out of the way so no row is highlighted in the picture
                    CGWarpMouseCursorPosition(CGPoint(x: 0, y: NSScreen.main?.frame.height ?? 900))
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) { self.item.button?.performClick(nil) } }
                #endif
                self.item.button?.toolTip = s.error ?? "agentmeter: tokens this \(s.name)"
            }
        }
    }

    func menuWillOpen(_ menu: NSMenu) {
        build(menu)
        refresh()   // the menu shows the last snapshot; the bar title updates when this finishes
    }

    func text(_ s: String, size: CGFloat = 13, color: NSColor = .labelColor, mono: Bool = false, action: Selector? = nil) -> NSMenuItem {
        let it = NSMenuItem(title: s, action: action, keyEquivalent: "")
        if action != nil { it.target = self }
        let font = mono ? NSFont.monospacedSystemFont(ofSize: size, weight: .regular) : NSFont.menuFont(ofSize: size)
        it.attributedTitle = NSAttributedString(string: s, attributes: [.font: font, .foregroundColor: color])
        it.isEnabled = true
        return it
    }

    func action(_ title: String, _ sel: Selector, key: String = "") -> NSMenuItem {
        let it = NSMenuItem(title: title, action: sel, keyEquivalent: key)
        it.target = self
        return it
    }

    func since(_ key: String) -> String {
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"
        guard let d = f.date(from: key) else { return key }
        f.dateFormat = "EEE d MMM"
        return f.string(from: d)
    }

    /// First launch without a config: open the setup questions in Terminal, once. Afterwards the
    /// menu keeps a "Set up" item at the top until a config exists. Defaults work meanwhile.
    func offerSetupOnce() {
        let marker = home.appendingPathComponent(".local/share/agentmeter/.setup-offered")
        if FileManager.default.fileExists(atPath: configURL.path) || FileManager.default.fileExists(atPath: marker.path) { return }
        try? FileManager.default.createDirectory(at: marker.deletingLastPathComponent(), withIntermediateDirectories: true)
        FileManager.default.createFile(atPath: marker.path, contents: nil)
        runSetup()
    }

    /// Open a Terminal window running agentmeter with these arguments. A .command file opens in
    /// Terminal and runs, with no Automation permission prompt.
    func showInTerminal(_ args: String) {
        guard let bin = findAgentmeter() else { return }
        let f = home.appendingPathComponent(".local/share/agentmeter/view.command")
        let body = "#!/bin/bash\nclear\n'\(bin)' \(args)\n"
        try? FileManager.default.createDirectory(at: f.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? body.write(to: f, atomically: true, encoding: .utf8)
        try? FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: f.path)
        NSWorkspace.shared.open(f)
    }

    @objc func showThisPeriod() { showInTerminal("--period this") }

    @objc func showLastPeriod() {
        let report = reportsURL.appendingPathComponent("\(snap.lastPeriod).md")
        if FileManager.default.fileExists(atPath: report.path) {
            NSWorkspace.shared.open(report)
        } else {
            showInTerminal("--period last")
        }
    }

    @objc func runSetup() {
        // a .command file opens in Terminal and runs, with no Automation permission prompt
        guard let bin = findAgentmeter() else { return }
        let f = home.appendingPathComponent(".local/share/agentmeter/setup.command")
        // after setup, close this window: the shell exits first, then Terminal (which owns the script, so
        // there is no permission prompt) closes the window whose title names this file
        let body = """
        #!/bin/bash
        clear
        '\(bin)' init
        sleep 2
        (sleep 0.5; osascript -e 'tell application "Terminal" to close (every window whose name contains "setup.command")') >/dev/null 2>&1 & disown
        exit 0

        """
        try? FileManager.default.createDirectory(at: f.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? body.write(to: f, atomically: true, encoding: .utf8)
        try? FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: f.path)
        NSWorkspace.shared.open(f)
        DispatchQueue.main.asyncAfter(deadline: .now() + 60) { self.refresh() }
    }

    func build(_ menu: NSMenu) {
        menu.removeAllItems()
        let s = snap
        if !FileManager.default.fileExists(atPath: configURL.path) {
            menu.addItem(action("Set up agentmeter… (your tools and week)", #selector(runSetup)))
            menu.addItem(text("Using defaults until then: weeks from Monday", size: 11, color: .secondaryLabelColor))
            menu.addItem(.separator())
        }
        if let e = s.error {
            menu.addItem(text(e, color: .secondaryLabelColor))
            menu.addItem(text("Run install.sh from the agentmeter repo", size: 11, color: .secondaryLabelColor))
        } else {
            let cur = s.fresh(s.thisPeriod), prev = s.fresh(s.lastPeriod)
            let sessions = s.sessions(s.thisPeriod)
            let show = #selector(showThisPeriod)
            menu.addItem(text("This \(s.name) (since \(since(s.thisPeriod)))", size: 12, color: .secondaryLabelColor, action: show))
            menu.addItem(text("\(fmt(cur)) tokens · \(sessions) session\(sessions == 1 ? "" : "s")", size: 15, action: show))
            menu.addItem(text("\(fmt(s.total(s.thisPeriod))) including cache reads", size: 11, color: .secondaryLabelColor, action: show))
            menu.addItem(.separator())
            // one colour per model, the same in this week's rows and last week's submenu
            let rows = s.rows(s.thisPeriod), lastRows = s.rows(s.lastPeriod)
            var colour: [String: NSColor] = [:]
            for r in rows + lastRows where colour[r.model] == nil { colour[r.model] = palette[colour.count % palette.count] }
            let width = min(24, (rows + lastRows).map { $0.model.count }.max() ?? 10)
            if rows.isEmpty { menu.addItem(text("No sessions yet this \(s.name)", color: .secondaryLabelColor, action: show)) }
            for r in rows {
                let it = NSMenuItem(title: r.model, action: show, keyEquivalent: "")
                it.target = self
                it.attributedTitle = modelRow(r.model, width: width, share: cur > 0 ? r.fresh / cur : 0, value: r.fresh, colour: colour[r.model]!)
                it.toolTip = "\(r.tool) · \(r.sessions) session\(r.sessions == 1 ? "" : "s") · click for the full breakdown"
                menu.addItem(it)
            }
            menu.addItem(.separator())
            // last week: total and change here, its models in a submenu
            let last = NSMenuItem(title: "Last \(s.name)", action: nil, keyEquivalent: "")
            let change = prev > 0 ? "   this \(s.name) so far \(changeLabel(cur, prev))" : ""
            last.attributedTitle = NSAttributedString(string: "Last \(s.name): \(fmt(prev))\(change)",
                                                      attributes: [.font: NSFont.menuFont(ofSize: 12), .foregroundColor: NSColor.labelColor])
            let sub = NSMenu()
            sub.autoenablesItems = false
            if let label = s.labels[s.lastPeriod] { sub.addItem(text(label, size: 11, color: .secondaryLabelColor)) }
            for r in lastRows {
                let it = NSMenuItem(title: r.model, action: #selector(showLastPeriod), keyEquivalent: "")
                it.target = self
                it.attributedTitle = modelRow(r.model, width: width, share: prev > 0 ? r.fresh / prev : 0, value: r.fresh, colour: colour[r.model]!)
                sub.addItem(it)
            }
            if lastRows.isEmpty { sub.addItem(text("No sessions", color: .secondaryLabelColor)) }
            sub.addItem(.separator())
            let hasReport = FileManager.default.fileExists(atPath: reportsURL.appendingPathComponent("\(s.lastPeriod).md").path)
            sub.addItem(action(hasReport ? "Open last \(s.name)'s report" : "Show last \(s.name) in Terminal", #selector(showLastPeriod)))
            last.submenu = sub
            menu.addItem(last)
        }
        menu.addItem(.separator())
        let reports = ((try? FileManager.default.contentsOfDirectory(atPath: reportsURL.path)) ?? [])
            .filter { $0.hasSuffix(".md") }.sorted()
        if let latest = reports.last {
            menu.addItem(action("Open latest report (\(since(String(latest.dropLast(3)))))", #selector(openLatest)))
            menu.addItem(action("Open reports folder", #selector(openReports)))
        }
        if FileManager.default.fileExists(atPath: configURL.path) {
            menu.addItem(action("Change setup… (agentmeter init)", #selector(runSetup)))
            menu.addItem(action("Edit settings file", #selector(openConfig)))
        }
        menu.addItem(action("Refresh now", #selector(refresh), key: "r"))
        menu.addItem(action("Quit agentmeter", #selector(quit), key: "q"))
    }

    @objc func openLatest() {
        let reports = ((try? FileManager.default.contentsOfDirectory(atPath: reportsURL.path)) ?? []).filter { $0.hasSuffix(".md") }.sorted()
        if let latest = reports.last { NSWorkspace.shared.open(reportsURL.appendingPathComponent(latest)) }
    }
    @objc func openReports() { NSWorkspace.shared.open(reportsURL) }
    @objc func openConfig() { NSWorkspace.shared.open(configURL) }
    @objc func quit() { NSApp.terminate(nil) }
}

let app = NSApplication.shared
let delegate = App()
app.delegate = delegate
app.setActivationPolicy(.accessory)   // menu bar only: no Dock icon, no app menu
app.run()
