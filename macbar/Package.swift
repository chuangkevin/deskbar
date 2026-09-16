// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "DeskbarMenuBar",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "DeskbarMenuBar", targets: ["DeskbarMenuBar"]),
    ],
    targets: [
        .executableTarget(
            name: "DeskbarMenuBar",
            path: "Sources/DeskbarMenuBar"
        ),
        .testTarget(
            name: "DeskbarMenuBarTests",
            dependencies: ["DeskbarMenuBar"],
            path: "Tests/DeskbarMenuBarTests",
            swiftSettings: [
                .unsafeFlags([
                    "-F",
                    "/Library/Developer/CommandLineTools/Library/Developer/Frameworks",
                ]),
            ],
            linkerSettings: [
                .unsafeFlags([
                    "-F",
                    "/Library/Developer/CommandLineTools/Library/Developer/Frameworks",
                    "-Xlinker",
                    "-rpath",
                    "-Xlinker",
                    "/Library/Developer/CommandLineTools/Library/Developer/Frameworks",
                    "-Xlinker",
                    "-rpath",
                    "-Xlinker",
                    "/Library/Developer/CommandLineTools/Library/Developer/usr/lib",
                ]),
            ]
        ),
    ]
)
