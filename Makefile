# 本機實際主機/金鑰/路徑放 local.mk（gitignored），範例見 local.mk.example
-include local.mk
PI ?= pi@deskbar.local
KEY ?= ~/.ssh/id_ed25519
DEST ?= /home/pi/deskbar

.PHONY: test dev deploy add-account

test:
	.venv/bin/python -m pytest -q

dev:
	DESKBAR_DEV=1 DESKBAR_FAKE=1 .venv/bin/python -m deskbar

deploy:
	rsync -az --delete -e "ssh -i $(KEY)" --exclude .git --exclude .venv --exclude __pycache__ --exclude .superpowers --exclude .omo --exclude docs --exclude tests ./ $(PI):$(DEST)/
	ssh -i $(KEY) $(PI) "bash $(DEST)/deploy/install.sh && sudo systemctl restart deskbar"

add-account:
	.venv/bin/python tools/add_account.py
