import Foundation
import SwiftUI

struct UsageResponse: Codable, Equatable {
    let generatedAt: Date?
    let fetchedAt: Date?
    let theme: UsageTheme?
    let sections: [UsageSection]

    enum CodingKeys: String, CodingKey {
        case generatedAt = "generated_at"
        case fetchedAt = "fetched_at"
        case theme
        case sections
    }

    init(generatedAt: Date?, fetchedAt: Date?, theme: UsageTheme? = nil, sections: [UsageSection]) {
        self.generatedAt = generatedAt
        self.fetchedAt = fetchedAt
        self.theme = theme
        self.sections = sections
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        generatedAt = Self.decodeDateIfPresent(container, forKey: .generatedAt)
        fetchedAt = Self.decodeDateIfPresent(container, forKey: .fetchedAt)
        theme = try container.decodeIfPresent(UsageTheme.self, forKey: .theme)
        sections = try container.decodeIfPresent([UsageSection].self, forKey: .sections) ?? []
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encodeIfPresent(generatedAt, forKey: .generatedAt)
        try container.encodeIfPresent(fetchedAt, forKey: .fetchedAt)
        try container.encodeIfPresent(theme, forKey: .theme)
        try container.encode(sections, forKey: .sections)
    }
}

enum Level: String, Codable, Equatable {
    case normal
    case warn
    case full
}

struct UsageTheme: Codable, Equatable {
    let dark: UsageThemePalette?
    let light: UsageThemePalette?

    static let defaultTheme = UsageTheme(
        dark: UsageThemePalette(
            usageBar: UsageRGB(red: 217, green: 119, blue: 87),
            usageWarn: UsageRGB(red: 255, green: 92, blue: 0),
            usageFull: UsageRGB(red: 255, green: 45, blue: 45),
            muted: UsageRGB(red: 186, green: 186, blue: 186)
        ),
        light: UsageThemePalette(
            usageBar: UsageRGB(red: 184, green: 86, blue: 54),
            usageWarn: UsageRGB(red: 198, green: 68, blue: 0),
            usageFull: UsageRGB(red: 200, green: 28, blue: 28),
            muted: UsageRGB(red: 120, green: 120, blue: 120)
        )
    )

    func palette(for colorScheme: ColorScheme) -> UsageThemePalette {
        switch colorScheme {
        case .dark:
            return dark ?? UsageTheme.defaultTheme.dark!
        default:
            return light ?? UsageTheme.defaultTheme.light!
        }
    }
}

struct UsageThemePalette: Codable, Equatable {
    let usageBar: UsageRGB
    let usageWarn: UsageRGB
    let usageFull: UsageRGB
    let muted: UsageRGB

    enum CodingKeys: String, CodingKey {
        case usageBar = "usage_bar"
        case usageWarn = "usage_warn"
        case usageFull = "usage_full"
        case muted
    }
}

struct UsageRGB: Codable, Equatable {
    let red: Int
    let green: Int
    let blue: Int

    var color: Color {
        Color(
            red: Double(red) / 255,
            green: Double(green) / 255,
            blue: Double(blue) / 255
        )
    }

    init(red: Int, green: Int, blue: Int) {
        self.red = red
        self.green = green
        self.blue = blue
    }

    init(from decoder: Decoder) throws {
        var container = try decoder.unkeyedContainer()
        red = try container.decode(Int.self)
        green = try container.decode(Int.self)
        blue = try container.decode(Int.self)
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.unkeyedContainer()
        try container.encode(red)
        try container.encode(green)
        try container.encode(blue)
    }
}

struct UsageSection: Codable, Equatable, Identifiable {
    var id: String { title }

    let title: String
    let ageS: Double?
    let stale: Bool?
    let muted: Bool?
    let groups: [UsageGroup]

    enum CodingKeys: String, CodingKey {
        case title
        case ageS = "age_s"
        case stale
        case muted
        case groups
    }

    init(title: String, ageS: Double?, stale: Bool? = nil, muted: Bool? = nil, groups: [UsageGroup]) {
        self.title = title
        self.ageS = ageS
        self.stale = stale
        self.muted = muted
        self.groups = groups
    }
}

struct UsageGroup: Codable, Equatable, Identifiable {
    var id: String { label }

    let label: String
    let pct: Double?
    let resetsAt: Date?
    let countdown: String?
    let windowS: Double?
    let overPace: Bool?
    let pacePct: Double?
    let level: Level?
    let isExhausted: Bool?

    enum CodingKeys: String, CodingKey {
        case label
        case pct
        case resetsAt = "resets_at"
        case countdown
        case windowS = "window_s"
        case overPace = "over_pace"
        case pacePct = "pace_pct"
        case level
        case isExhausted = "exhausted"
    }

    init(
        label: String,
        pct: Double?,
        resetsAt: Date?,
        countdown: String?,
        windowS: Double?,
        overPace: Bool?,
        pacePct: Double? = nil,
        level: Level? = nil,
        isExhausted: Bool? = nil
    ) {
        self.label = label
        self.pct = pct
        self.resetsAt = resetsAt
        self.countdown = countdown
        self.windowS = windowS
        self.overPace = overPace
        self.pacePct = pacePct
        self.level = level
        self.isExhausted = isExhausted
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        label = try container.decode(String.self, forKey: .label)
        pct = try container.decodeIfPresent(Double.self, forKey: .pct)
        resetsAt = UsageResponse.decodeDateIfPresent(container, forKey: .resetsAt)
        countdown = try container.decodeIfPresent(String.self, forKey: .countdown)
        windowS = try container.decodeIfPresent(Double.self, forKey: .windowS)
        overPace = try container.decodeIfPresent(Bool.self, forKey: .overPace)
        pacePct = try container.decodeIfPresent(Double.self, forKey: .pacePct)
        level = try container.decodeIfPresent(Level.self, forKey: .level)
        isExhausted = try container.decodeIfPresent(Bool.self, forKey: .isExhausted)
    }
}

func levelFor(group: UsageGroup) -> Level {
    if let level = group.level {
        return level
    }
    if group.isExhausted ?? ((group.pct ?? 0) >= 100) {
        return .full
    }
    if group.overPace ?? false {
        return .warn
    }
    return .normal
}

extension UsageResponse {
    static func decode(data: Data) throws -> UsageResponse {
        try JSONDecoder().decode(UsageResponse.self, from: data)
    }

    static func parseDate(_ value: String?) -> Date? {
        guard let value, !value.isEmpty else { return nil }

        let withFractionalSeconds = ISO8601DateFormatter()
        withFractionalSeconds.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = withFractionalSeconds.date(from: value) {
            return date
        }

        let withoutFractionalSeconds = ISO8601DateFormatter()
        withoutFractionalSeconds.formatOptions = [.withInternetDateTime]
        return withoutFractionalSeconds.date(from: value)
    }

    static func decodeDateIfPresent<Key: CodingKey>(_ container: KeyedDecodingContainer<Key>, forKey key: Key) -> Date? {
        guard let value = try? container.decodeIfPresent(String.self, forKey: key) else { return nil }
        return parseDate(value)
    }
}

func menuTitle(for response: UsageResponse?, lastSuccess: Date?, now: Date = Date()) -> String {
    let title = "\(claudeTitle(for: response))  \(codexTitle(for: response))"
    guard let lastSuccess, now.timeIntervalSince(lastSuccess) > 180 else {
        return title
    }
    return "⚠︎ \(title)"
}

func displayPercent(_ pct: Double?) -> String {
    guard let pct else { return "—" }
    return String(Int(pct.rounded()))
}

func percentText(_ pct: Double?) -> String {
    guard let pct else { return "—" }
    return "\(Int(pct.rounded()))%"
}

func ageText(ageS: Double?, stale: Bool?) -> String? {
    guard stale == true, let ageS else { return nil }
    return "（\(Int(ageS / 60)) 分前）"
}

private func claudeTitle(for response: UsageResponse?) -> String {
    guard let section = response?.sections.first(where: { $0.title == "CLAUDE CODE" }) else {
        return "C —"
    }
    let first = section.groups.indices.contains(0) ? displayPercent(section.groups[0].pct) : "—"
    let second = section.groups.indices.contains(1) ? displayPercent(section.groups[1].pct) : "—"
    return "C \(first)·\(second)"
}

private func codexTitle(for response: UsageResponse?) -> String {
    let values = response?.sections
        .filter { $0.title.hasPrefix("OPENAI") }
        .compactMap { $0.groups.first?.pct } ?? []

    guard !values.isEmpty else { return "X —" }
    let average = values.reduce(0, +) / Double(values.count)
    return "X \(Int(average.rounded()))"
}
