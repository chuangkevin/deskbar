import AppKit
import SwiftUI

@main
struct DeskbarMenuBarApp: App {
    @StateObject private var client = UsageClient()

    var body: some Scene {
        MenuBarExtra {
            UsageMenuView(client: client)
        } label: {
            Label {
                Text(menuTitle(for: client.usage, lastSuccess: client.lastSuccessAt))
            } icon: {
                Image(nsImage: menuIcon())
            }
        }
        .menuBarExtraStyle(.window)
        .commands {
            CommandGroup(replacing: .appInfo) { }
        }
    }

    init() {
        let usageClient = UsageClient()
        _client = StateObject(wrappedValue: usageClient)
        Task { @MainActor in
            usageClient.startPolling()
        }
    }

    private func menuIcon() -> NSImage {
        NSImage(systemSymbolName: "gauge.with.dots.needle.33percent", accessibilityDescription: "Deskbar")
            ?? NSImage(systemSymbolName: "gauge", accessibilityDescription: "Deskbar")
            ?? NSImage()
    }
}
