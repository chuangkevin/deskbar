"""Mac 端：新增 Google 帳號到 deskbar。

前置：~/.config/deskbar/client_secret.json（GCP 桌面應用程式 OAuth client）
用法：python3 tools/add_account.py [--pi kevin@100.98.35.59] [--key ~/.ssh/kevinhome_key]
"""
import argparse
import json
import subprocess
import tempfile
from pathlib import Path

import requests
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly",
          "https://www.googleapis.com/auth/userinfo.email", "openid"]
CFG = Path.home() / ".config" / "deskbar"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pi", default="kevin@100.98.35.59")
    ap.add_argument("--key", default=str(Path.home() / ".ssh" / "kevinhome_key"))
    args = ap.parse_args()

    secret = CFG / "client_secret.json"
    if not secret.exists():
        raise SystemExit(f"找不到 {secret}——先從 GCP Console 下載桌面型 OAuth client JSON 放到該路徑")
    flow = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")

    email = requests.get("https://openidconnect.googleapis.com/v1/userinfo",
                         headers={"Authorization": f"Bearer {creds.token}"},
                         timeout=15).json()["email"]
    cals = requests.get("https://www.googleapis.com/calendar/v3/users/me/calendarList",
                        headers={"Authorization": f"Bearer {creds.token}"},
                        timeout=15).json().get("items", [])
    client = json.loads(secret.read_text(encoding="utf-8"))["installed"]
    token = {
        "email": email,
        "refresh_token": creds.refresh_token,
        "client_id": client["client_id"],
        "client_secret": client["client_secret"],
        "calendars": [{"id": c["id"], "summary": c.get("summary", c["id"]),
                       "primary": bool(c.get("primary"))} for c in cals],
    }
    if not token["refresh_token"]:
        raise SystemExit("Google 未回傳 refresh_token——到 myaccount.google.com/permissions "
                         "移除本應用授權後重跑")
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as f:
        json.dump(token, f, ensure_ascii=False)
        tmp = f.name
    dest = f"/home/kevin/.config/deskbar/accounts/{email}.json"
    subprocess.run(["ssh", "-i", args.key, args.pi,
                    "mkdir -p ~/.config/deskbar/accounts"], check=True)
    subprocess.run(["scp", "-i", args.key, tmp, f"{args.pi}:{dest}"], check=True)
    subprocess.run(["ssh", "-i", args.key, args.pi, f"chmod 600 {dest}"], check=True)
    Path(tmp).unlink()
    print(f"完成：{email} 已部署到 Pi（{len(cals)} 個日曆，5 分鐘內上屏）")


if __name__ == "__main__":
    main()
