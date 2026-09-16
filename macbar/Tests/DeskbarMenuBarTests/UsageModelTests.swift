import Foundation
import Testing
@testable import DeskbarMenuBar

@Suite
struct UsageModelTests {
    let exampleJSON = """
    {
      "generated_at": "2026-09-16T11:20:03+08:00",
      "fetched_at": "2026-09-16T11:19:30+08:00",
      "sections": [
        {
          "title": "CLAUDE CODE",
          "age_s": 33.0,
          "groups": [
            {"label": "5H SESSION", "pct": 23.0, "resets_at": "2026-09-16T14:00:00+08:00", "countdown": "2h 39m", "window_s": 18000, "over_pace": false},
            {"label": "本週", "pct": 16.0, "resets_at": null, "countdown": "—", "window_s": 604800, "over_pace": false}
          ]
        },
        {"title": "OPENAI · KEVIN.SYSTEMCOM", "age_s": 40.0, "groups": [{"label": "本週", "pct": 100.0, "resets_at": "2026-09-19T16:00:00+08:00", "countdown": "3d 5h", "window_s": 604800, "over_pace": true}]}
      ]
    }
    """

    @Test
    func decodesExampleJSON() throws {
        let usage = try decode(exampleJSON)
        #expect(usage.sections.count == 2)
        #expect(usage.sections[0].groups[1].resetsAt == nil)
    }

    @Test
    func menuTitleFromExampleJSON() throws {
        let usage = try decode(exampleJSON)
        #expect(menuTitle(for: usage, lastSuccess: Date(timeIntervalSince1970: 100), now: Date(timeIntervalSince1970: 101)) == "C 23·16  X 100")
    }

    @Test
    func menuTitleAveragesTwoOpenAIAccounts() throws {
        let usage = UsageResponse(generatedAt: nil, fetchedAt: nil, sections: [
            claudeSection(first: 23, second: 16),
            openAISection(pct: 73),
            openAISection(title: "OPENAI · OTHER", pct: 67),
        ])
        #expect(menuTitle(for: usage, lastSuccess: nil) == "C 23·16  X 70")
    }

    @Test
    func menuTitleIgnoresNilOpenAIPercent() throws {
        let usage = UsageResponse(generatedAt: nil, fetchedAt: nil, sections: [
            claudeSection(first: 23, second: 16),
            openAISection(pct: nil),
            openAISection(title: "OPENAI · OTHER", pct: 60),
        ])
        #expect(menuTitle(for: usage, lastSuccess: nil) == "C 23·16  X 60")
    }

    @Test
    func menuTitleHandlesNilClaudeFiveHour() throws {
        let usage = UsageResponse(generatedAt: nil, fetchedAt: nil, sections: [
            claudeSection(first: nil, second: 16),
            openAISection(pct: 100),
        ])
        #expect(menuTitle(for: usage, lastSuccess: nil) == "C —·16  X 100")
    }

    @Test
    func menuTitleHandlesNoOpenAI() throws {
        let usage = UsageResponse(generatedAt: nil, fetchedAt: nil, sections: [claudeSection(first: 23, second: 16)])
        #expect(menuTitle(for: usage, lastSuccess: nil) == "C 23·16  X —")
    }

    @Test
    func menuTitleHandlesEmptySections() throws {
        let usage = UsageResponse(generatedAt: nil, fetchedAt: nil, sections: [])
        #expect(menuTitle(for: usage, lastSuccess: nil) == "C —  X —")
    }

    @Test
    func menuTitleWarnsAfterThreeMinutes() throws {
        let usage = UsageResponse(generatedAt: nil, fetchedAt: nil, sections: [])
        let title = menuTitle(for: usage, lastSuccess: Date(timeIntervalSince1970: 0), now: Date(timeIntervalSince1970: 181))
        #expect(title.hasPrefix("⚠︎"))
    }

    @Test
    func parsesDatesWithAndWithoutFractionalSeconds() {
        #expect(UsageResponse.parseDate("2026-09-16T11:20:03+08:00") != nil)
        #expect(UsageResponse.parseDate("2026-09-16T11:20:03.123+08:00") != nil)
    }

    private func decode(_ string: String) throws -> UsageResponse {
        try UsageResponse.decode(data: Data(string.utf8))
    }

    private func claudeSection(first: Double?, second: Double?) -> UsageSection {
        UsageSection(title: "CLAUDE CODE", ageS: 0, groups: [
            UsageGroup(label: "5H SESSION", pct: first, resetsAt: nil, countdown: "—", windowS: 18000, overPace: false),
            UsageGroup(label: "本週", pct: second, resetsAt: nil, countdown: "—", windowS: 604800, overPace: false),
        ])
    }

    private func openAISection(title: String = "OPENAI · KEVIN.SYSTEMCOM", pct: Double?) -> UsageSection {
        UsageSection(title: title, ageS: 0, groups: [
            UsageGroup(label: "本週", pct: pct, resetsAt: nil, countdown: "—", windowS: 604800, overPace: false),
        ])
    }
}
