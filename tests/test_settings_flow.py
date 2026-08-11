from deskbar.ui.settings_flow import SettingsFlowDecision, decide_settings_flow


def test_settings_flow_routes_static_pages():
    assert decide_settings_flow("open_settings") == SettingsFlowDecision("settings")
    assert decide_settings_flow("open_alarms") == SettingsFlowDecision("alarms")
    assert decide_settings_flow("open_screen") == SettingsFlowDecision("screen")
    assert decide_settings_flow("settings_done") == SettingsFlowDecision("dashboard")
    assert decide_settings_flow("close") == SettingsFlowDecision("dashboard")


def test_settings_flow_marks_side_effects_for_adapters():
    assert decide_settings_flow("open_wifi") == SettingsFlowDecision(
        "wifi", rescan_wifi=True)
    assert decide_settings_flow("open_bt") == SettingsFlowDecision(
        "bt", rescan_bt=True)
    assert decide_settings_flow("wifi_back") == SettingsFlowDecision(
        "settings", clear_wifi_message=True)


def test_settings_flow_ignores_non_route_actions():
    assert decide_settings_flow("wifi_rescan") is None
    assert decide_settings_flow("toggle_sleep") is None
    assert decide_settings_flow("toggle_center") is None
