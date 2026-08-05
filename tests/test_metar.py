from datetime import datetime, timezone
from deskbar.metar import fetch_metar, metar_to_code, parse_metar_json


def test_metar_to_code_wx_string_rules():
    # TS -> 95 (雷雨)
    assert metar_to_code("TS", None) == 95
    # SN -> 73 (雪)
    assert metar_to_code("SN", None) == 73
    # 順序陷阱：SHRA 同時包含 RA 與 SH，必須回 81 (陣雨) 而不是 63 (雨)
    assert metar_to_code("SHRA", None) == 81
    assert metar_to_code("+SHRA", None) == 81
    assert metar_to_code("SH", None) == 81
    # DZ -> 53 (毛毛雨)
    assert metar_to_code("DZ", None) == 53
    # 強度前綴不影響 substring 比對：-RA -> 63 (雨), +TSRA -> 95 (雷雨)
    assert metar_to_code("-RA", None) == 63
    assert metar_to_code("+TSRA", None) == 95
    # FG -> 45 (霧)
    assert metar_to_code("FG", None) == 45


def test_metar_to_code_br_and_visibility():
    # BR 且能見度 < 5000 -> 45
    assert metar_to_code("BR", None, visibility_m=3000) == 45
    # BR 且能見度 >= 5000 -> 跳過 45 走雲量分支（此處無雲，故回 0）
    assert metar_to_code("BR", None, visibility_m=9999) == 0
    # BR 且能見度 9999 但有多雲 (SCT) -> 走雲量分支回 2
    assert metar_to_code("BR", [{"cover": "SCT"}], visibility_m=9999) == 2


def test_metar_to_code_cloud_cover_rules():
    # wx_string=None 且 clouds=[{"cover":"FEW"}] -> 1
    assert metar_to_code(None, [{"cover": "FEW"}]) == 1
    # wx_string=None 且 clouds=[] -> 0
    assert metar_to_code(None, []) == 0
    # wx_string=None 且 clouds 含 OVC 與 FEW -> 取最高 cover 回 3
    clouds = [{"cover": "FEW", "base": 2500}, {"cover": "OVC", "base": 8000}]
    assert metar_to_code(None, clouds) == 3
    # SKC / CLR / CAVOK / 空字串 -> 0
    assert metar_to_code(None, [{"cover": "SKC"}]) == 0
    assert metar_to_code(None, [{"cover": "CLR"}]) == 0
    assert metar_to_code(None, [{"cover": "CAVOK"}]) == 0


def test_parse_metar_json_real_fixture():
    fixture = [
        {"rawOb": "METAR RCSS 050500Z 28007KT 250V310 9999 FEW025 35/27 Q1002 NOSIG RMK A2961",
         "reportTime": "2026-08-05T05:00:00.000Z", "temp": 35, "dewp": 27,
         "wxString": None, "visib": "6+", "clouds": [{"cover": "FEW", "base": 2500}]}
    ]
    res = parse_metar_json(fixture)
    assert res is not None
    assert res["temp"] == 35.0
    assert res["code"] == 1
    assert res["raw"] == "METAR RCSS 050500Z 28007KT 250V310 9999 FEW025 35/27 Q1002 NOSIG RMK A2961"
    assert res["observed_at"] == datetime(2026, 8, 5, 5, 0, 0, tzinfo=timezone.utc)


def test_parse_metar_json_edge_cases():
    # 空清單 -> None
    assert parse_metar_json([]) is None
    assert parse_metar_json(None) is None
    # 缺 temp 欄位 -> None，不拋例外
    assert parse_metar_json([{"reportTime": "2026-08-05T05:00:00Z"}]) is None
    # visib 為 "10+" 字串 -> 不拋例外，預設為 9999
    res = parse_metar_json([
        {"temp": 30, "reportTime": "2026-08-05T05:00:00Z", "visib": "10+", "wxString": "BR"}
    ])
    assert res is not None
    # 能見度當 9999，BR 被跳過，雲量 0 -> code 為 0
    assert res["code"] == 0


class FakeResp:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json_data = json_data or []

    def json(self):
        return self._json_data


def test_fetch_metar_handles_http_errors_and_exceptions():
    # http_get 拋例外 -> 回 None
    def bad_get(*a, **k):
        raise RuntimeError("network down")

    assert fetch_metar("RCSS", http_get=bad_get) is None

    # HTTP 非 200 -> 回 None
    def status_500_get(*a, **k):
        return FakeResp(status_code=500)

    assert fetch_metar("RCSS", http_get=status_500_get) is None

    # HTTP 200 -> 正常回傳解析結果
    fixture = [
        {"rawOb": "METAR RCSS ...", "reportTime": "2026-08-05T05:00:00Z",
         "temp": 32, "wxString": None, "clouds": []}
    ]

    def ok_get(*a, **k):
        return FakeResp(status_code=200, json_data=fixture)

    res = fetch_metar("RCSS", http_get=ok_get)
    assert res is not None and res["temp"] == 32.0 and res["code"] == 0
