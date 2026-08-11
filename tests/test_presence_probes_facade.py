"""測試 presence_probes 的 Facade 與 re-export identity 一致性。"""

from deskbar import presence, presence_probes


def test_presence_probes_direct_import():
    """驗證 presence_probes 可直接 import 且包含所有硬體探測 API。"""
    assert callable(presence_probes.probe_once)
    assert callable(presence_probes.parse_dbus_rssi)
    assert callable(presence_probes.mac_to_dbus_path)
    assert callable(presence_probes.probe_ble_once)
    assert callable(presence_probes.adapter_healthy)
    assert callable(presence_probes.try_recover_adapter)


def test_presence_reexport_identities():
    """驗證 presence 重組後的 re-export 與 presence_probes 的物件 instance 完全同一。"""
    assert presence.probe_once is presence_probes.probe_once
    assert presence.probe_ble_once is presence_probes.probe_ble_once
    assert presence.parse_dbus_rssi is presence_probes.parse_dbus_rssi
    assert presence.mac_to_dbus_path is presence_probes.mac_to_dbus_path
    assert presence.adapter_healthy is presence_probes.adapter_healthy
    assert presence.try_recover_adapter is presence_probes.try_recover_adapter
    assert presence._PROBE_LOCK is presence_probes._PROBE_LOCK
    assert presence._time is presence_probes._time
    assert presence.PROBE_TIMEOUT_S is presence_probes.PROBE_TIMEOUT_S
    assert presence.BLE_SCAN_SECONDS is presence_probes.BLE_SCAN_SECONDS
    assert presence.BLE_PROBE_TIMEOUT_S is presence_probes.BLE_PROBE_TIMEOUT_S
    assert presence._RSSI_RE is presence_probes._RSSI_RE
    assert presence._MAC_RE is presence_probes._MAC_RE
