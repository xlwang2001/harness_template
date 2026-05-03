.PHONY: validate test runtime-check integration-test codex-schema-test stale-design-check package-check

validate:
	python3 -m harness.cli validate --target templates/repo

test:
	python3 -m unittest discover -s tests

runtime-check:
	python3 -m unittest discover -s tests/runtime

integration-test:
	python3 -m unittest tests.runtime.test_integration_profile

codex-schema-test:
	HARNESS_CODEX_GENERATE_SCHEMA=1 python3 -m unittest tests.runtime.test_codex_schema

stale-design-check:
	python3 -m unittest tests.test_stale_design

package-check:
	python3 -m harness.package_check
