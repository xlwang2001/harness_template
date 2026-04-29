.PHONY: validate test runtime-check stale-design-check

validate:
	python3 -m harness.cli validate --target templates/repo

test:
	python3 -m unittest discover -s tests

runtime-check:
	python3 -m unittest discover -s tests/runtime

stale-design-check:
	python3 -m unittest tests.test_stale_design
