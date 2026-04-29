.PHONY: validate test symphony-status symphony-update

validate:
	python3 -m harness.cli validate --target templates/repo

test:
	python3 -m unittest discover -s tests

symphony-status:
	git submodule status vendor/symphony

symphony-update:
	git submodule update --init --recursive vendor/symphony
