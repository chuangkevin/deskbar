import AppKit
import ServiceManagement
import SwiftUI

struct UsageMenuView: View {
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
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 4) {
                Text(section.title)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                if let age = ageText(ageS: section.ageS) {
                    Text(age)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }

            ForEach(section.groups) { group in
                HStack(spacing: 8) {
                    Text(group.label)
                        .frame(width: 96, alignment: .leading)
                    ProgressView(value: (group.pct ?? 0) / 100)
                        .tint(progressTint(overPace: group.overPace))
                    Text(percentText(group.pct))
                        .foregroundStyle(group.overPace ? .red : .primary)
                        .frame(width: 44, alignment: .trailing)
                    Text(group.countdown ?? "—")
                        .foregroundStyle(.secondary)
                        .frame(width: 64, alignment: .trailing)
                }
                .font(.callout)
            }
        }
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
