"""Settings-page route flow decisions.

The App still owns side effects such as Wi-Fi and Bluetooth scans. This module
only answers: given a tapped action, which view should Deskbar show next and
which side effects should the App run after the route changes?
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SettingsFlowDecision:
    view: str
    rescan_wifi: bool = False
    rescan_bt: bool = False
    clear_wifi_message: bool = False


def decide_settings_flow(action: str) -> SettingsFlowDecision | None:
    """Return the settings-route decision for a UI action, if it is one."""
    if action == "open_settings":
        return SettingsFlowDecision("settings")
    if action == "open_alarms":
        return SettingsFlowDecision("alarms")
    if action == "open_wifi":
        return SettingsFlowDecision("wifi", rescan_wifi=True)
    if action == "open_bt":
        return SettingsFlowDecision("bt", rescan_bt=True)
    if action == "open_screen":
        return SettingsFlowDecision("screen")
    if action == "wifi_back":
        return SettingsFlowDecision("settings", clear_wifi_message=True)
    if action in ("close", "settings_done"):
        return SettingsFlowDecision("dashboard")
    return None
