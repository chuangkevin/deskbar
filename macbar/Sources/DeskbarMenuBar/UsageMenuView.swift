import AppKit
import ServiceManagement
import SwiftUI

struct UsageMenuView: View {
    @Environment(\.colorScheme) private var colorScheme
    @ObservedObject var client: UsageClient
    @State private var launchAtLogin = SMAppService.mainApp.status == .enabled
    @State private var showingURLSettings = false
    @State private var draftURL = ""
    @State private var localError: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let sections = client.usage?.sections, !sections.isEmpty {
                ForEach(sections) { section in
                    sectionView(section)
                }
            } else {
                Text(client.lastError ?? "尚無資料")
                    .foregroundStyle(.secondary)
            }

            Divider()
            footer
        }
        .padding(14)
        .frame(width: 420)
        .onAppear {
            draftURL = client.baseURLString
            launchAtLogin = SMAppService.mainApp.status == .enabled
            Task { await client.refresh() }
        }
    }

    private func sectionView(_ section: UsageSection) -> some View {
        let palette = (client.usage?.theme ?? UsageTheme.defaultTheme).palette(for: colorScheme)
        let isMuted = section.muted ?? false

        return VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 4) {
                Text(section.title)
                    .font(.caption)
                    .foregroundStyle(isMuted ? palette.muted.color : Color.secondary)
                if let age = ageText(ageS: section.ageS, stale: section.stale) {
                    Text(age)
                        .font(.caption2)
                        .foregroundStyle(isMuted ? palette.muted.color : Color.secondary)
                }
            }

            ForEach(section.groups) { group in
                let level = levelFor(group: group)
                let barColor = usageColor(level: level, palette: palette, isMuted: isMuted)
                let textColor = isMuted ? palette.muted.color : Color.primary

                HStack(spacing: 8) {
                    Text(group.label)
                        .foregroundStyle(textColor)
                        .frame(width: 96, alignment: .leading)
                    UsageBar(
                        pct: group.pct,
                        pacePct: isMuted ? nil : group.pacePct,
                        barColor: barColor
                    )
                    Text(percentText(group.pct))
                        .foregroundStyle(percentColor(level: level, palette: palette, isMuted: isMuted))
                        .frame(width: 44, alignment: .trailing)
                    Text(countdownText(group.countdown))
                        .foregroundStyle(.secondary)
                        .frame(width: 64, alignment: .trailing)
                }
                .font(.callout)
            }
        }
    }

    private func usageColor(level: Level, palette: UsageThemePalette, isMuted: Bool) -> Color {
        if isMuted { return palette.muted.color }
        switch level {
        case .normal:
            return palette.usageBar.color
        case .warn:
            return palette.usageWarn.color
        case .full:
            return palette.usageFull.color
        }
    }

    private func percentColor(level: Level, palette: UsageThemePalette, isMuted: Bool) -> Color {
        if isMuted { return palette.muted.color }
        return level == .full ? palette.usageFull.color : .primary
    }

    private func countdownText(_ countdown: String?) -> String {
        guard let countdown, !countdown.isEmpty, countdown != "—" else { return "剩 —" }
        return "剩 \(countdown)"
    }

    private var footer: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(statusText)
                    .font(.caption)
                    .foregroundStyle(client.lastSuccessAt == nil && client.lastError != nil ? .red : .secondary)
                Spacer()
                Button("重新整理") {
                    Task { await client.refresh() }
                }
            }

            Toggle("登入時啟動", isOn: Binding(
                get: { launchAtLogin },
                set: { enabled in
                    setLaunchAtLogin(enabled)
                }
            ))

            if showingURLSettings {
                TextField("Deskbar URL", text: $draftURL)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit(updateURL)
                Button("套用 URL") {
                    updateURL()
                }
            }

            HStack {
                Button(showingURLSettings ? "收合 URL 設定" : "設定 URL…") {
                    showingURLSettings.toggle()
                }
                Spacer()
                Button("結束") {
                    NSApplication.shared.terminate(nil)
                }
            }

            if let error = localError ?? client.lastError, client.lastSuccessAt != nil {
                Text(error)
                    .font(.caption)
                    .foregroundStyle(.red)
            }
        }
    }

    private var statusText: String {
        if let lastSuccessAt = client.lastSuccessAt {
            let seconds = max(0, Int(Date().timeIntervalSince(lastSuccessAt)))
            return "更新於 \(seconds) 秒前"
        }
        return client.lastError ?? "尚未成功更新"
    }

    private func updateURL() {
        client.baseURLString = draftURL.trimmingCharacters(in: .whitespacesAndNewlines)
        Task { await client.refresh() }
    }

    private func setLaunchAtLogin(_ enabled: Bool) {
        do {
            if enabled {
                try SMAppService.mainApp.register()
            } else {
                try SMAppService.mainApp.unregister()
            }
            launchAtLogin = enabled
            localError = nil
        } catch {
            launchAtLogin = SMAppService.mainApp.status == .enabled
            localError = error.localizedDescription
        }
    }
}

private struct UsageBar: View {
    let pct: Double?
    let pacePct: Double?
    let barColor: Color

    var body: some View {
        GeometryReader { geometry in
            let fillWidth = geometry.size.width * clampedFraction(pct)
            let paceX = geometry.size.width * clampedFraction(pacePct)

            ZStack(alignment: .leading) {
                Capsule()
                    .fill(Color.secondary.opacity(0.18))
                    .frame(height: 6)
                Capsule()
                    .fill(barColor)
                    .frame(width: fillWidth, height: 6)
                if pacePct != nil {
                    Rectangle()
                        .fill(Color.secondary)
                        .frame(width: 1, height: 12)
                        .offset(x: paceX)
                }
            }
            .frame(maxHeight: .infinity, alignment: .center)
        }
        .frame(height: 12)
    }

    private func clampedFraction(_ value: Double?) -> Double {
        min(max((value ?? 0) / 100, 0), 1)
    }
}
