import Foundation
import SwiftUI

struct UsageResponse: Codable, Equatable {
    let generatedAt: Date?
    let fetchedAt: Date?
    let sections: [UsageSection]

    enum CodingKeys: String, CodingKey {
        case generatedAt = "generated_at"
        case fetchedAt = "fetched_at"
        case sections
    }

    init(generatedAt: Date?, fetchedAt: Date?, sections: [UsageSection]) {
        self.generatedAt = generatedAt
        self.fetchedAt = fetchedAt
        self.sections = sections
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        generatedAt = Self.decodeDateIfPresent(container, forKey: .generatedAt)
        fetchedAt = Self.decodeDateIfPresent(container, forKey: .fetchedAt)
        sections = try container.decodeIfPresent([UsageSection].self, forKey: .sections) ?? []
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encodeIfPresent(generatedAt, forKey: .generatedAt)
        try container.encodeIfPresent(fetchedAt, forKey: .fetchedAt)
        try container.encode(sections, forKey: .sections)
    }
}

struct UsageSection: Codable, Equatable, Identifiable {
    var id: String { title }

    let title: String
    let ageS: Double?
    let groups: [UsageGroup]

    enum CodingKeys: String, CodingKey {
        case title
        case ageS = "age_s"
        case groups
    }
}

struct UsageGroup: Codable, Equatable, Identifiable {
    var id: String { label }

    let label: String
    let pct: Double?
    let resetsAt: Date?
    let countdown: String?
    let windowS: Double?
    let overPace: Bool

    enum CodingKeys: String, CodingKey {
        case label
        case pct
        case resetsAt = "resets_at"
        case countdown
        case windowS = "window_s"
        case overPace = "over_pace"
    }

    init(label: String, pct: Double?, resetsAt: Date?, countdown: String?, windowS: Double?, overPace: Bool) {
        self.label = label
        self.pct = pct
        self.resetsAt = resetsAt
        self.countdown = countdown
        self.windowS = windowS
        self.overPace = overPace
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        label = try container.decode(String.self, forKey: .label)
        pct = try container.decodeIfPresent(Double.self, forKey: .pct)
        resetsAt = UsageResponse.decodeDateIfPresent(container, forKey: .resetsAt)
        countdown = try container.decodeIfPresent(String.self, forKey: .countdown)
        windowS = try container.decodeIfPresent(Double.self, forKey: .windowS)
        overPace = try container.decodeIfPresent(Bool.self, forKey: .overPace) ?? false
    }
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

func ageText(ageS: Double?) -> String? {
    guard let ageS, ageS > 3600 else { return nil }
    return "（\(Int(ageS / 60)) 分前）"
}

func progressTint(overPace: Bool) -> Color {
    overPace ? .red : .accentColor
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
