PI ?= kevin@100.98.35.59
KEY ?= ~/.ssh/kevinhome_key

test:
	.venv/bin/python -m pytest -q

dev:
	DESKBAR_DEV=1 DESKBAR_FAKE=1 .venv/bin/python -m deskbar

deploy:
	rsync -az --delete -e "ssh -i $(KEY)" --exclude .git --exclude .venv --exclude __pycache__ --exclude .superpowers --exclude docs --exclude tests ./ $(PI):/home/kevin/deskbar/
	ssh -i $(KEY) $(PI) "bash /home/kevin/deskbar/deploy/install.sh && sudo systemctl restart deskbar"

add-account:
	python3 tools/add_account.py
