# 本機實際主機/金鑰/路徑放 local.mk（gitignored），範例見 local.mk.example
-include local.mk
PI ?= pi@deskbar.local
KEY ?= ~/.ssh/id_ed25519
DEST ?= /home/pi/deskbar

.PHONY: test dev deploy add-account claude-login

test:
	.venv/bin/python -m pytest -q

dev:
	DESKBAR_DEV=1 DESKBAR_FAKE=1 .venv/bin/python -m deskbar

deploy:
	rsync -az --delete -e "ssh -i $(KEY)" --exclude .git --exclude .venv --exclude __pycache__ --exclude .superpowers --exclude docs --exclude tests ./ $(PI):$(DEST)/
	ssh -i $(KEY) $(PI) "bash $(DEST)/deploy/install.sh && sudo systemctl restart deskbar"

add-account:
	.venv/bin/python tools/add_account.py

# 在 Pi 上互動登入 Claude 帳號（usage 唯讀 OAuth）。使用者自己在終端機貼授權碼，
# 不是 AI 代跑——見 tools/claude_login.py 檔頭說明。
claude-login:
	ssh -i $(KEY) $(PI) "cd $(DEST) && .venv/bin/python tools/claude_login.py"
