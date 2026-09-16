import Foundation

@MainActor
final class UsageClient: ObservableObject {
    @Published private(set) var usage: UsageResponse?
    @Published private(set) var lastError: String?
    @Published private(set) var lastSuccessAt: Date?
    @Published var baseURLString: String {
        didSet {
            UserDefaults.standard.set(baseURLString, forKey: Self.baseURLKey)
        }
    }

    static let baseURLKey = "deskbarBaseURL"
    static let defaultBaseURL = "http://100.98.35.59:8080"

    private let session: URLSession
    private var pollingTask: Task<Void, Never>?

    init() {
        baseURLString = UserDefaults.standard.string(forKey: Self.baseURLKey) ?? Self.defaultBaseURL
        let configuration = URLSessionConfiguration.default
        configuration.timeoutIntervalForRequest = 5
        configuration.timeoutIntervalForResource = 5
        session = URLSession(configuration: configuration)
    }

    deinit {
        pollingTask?.cancel()
    }

    func startPolling() {
        pollingTask?.cancel()
        pollingTask = Task { [weak self] in
            guard let self else { return }
            await self.refresh()
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(30))
                if !Task.isCancelled {
                    await self.refresh()
                }
            }
        }
    }

    func refresh() async {
        do {
            let response = try await fetchUsage()
            usage = response
            lastSuccessAt = Date()
            lastError = nil
        } catch {
            lastError = error.localizedDescription
        }
    }

    private func fetchUsage() async throws -> UsageResponse {
        guard let baseURL = URL(string: baseURLString) else {
            throw UsageClientError.invalidURL
        }
        let url = baseURL.appending(path: "api/usage")
        let (data, response) = try await session.data(from: url)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw UsageClientError.invalidResponse
        }
        guard httpResponse.statusCode == 200 else {
            throw UsageClientError.httpStatus(httpResponse.statusCode)
        }
        return try UsageResponse.decode(data: data)
    }
}

enum UsageClientError: LocalizedError {
    case invalidURL
    case invalidResponse
    case httpStatus(Int)

    var errorDescription: String? {
        switch self {
        case .invalidURL:
            "Invalid deskbar URL"
        case .invalidResponse:
            "Invalid server response"
        case .httpStatus(let status):
            "HTTP \(status)"
        }
    }
}
