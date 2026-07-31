# Everything CI runs, runnable locally. If `make check` passes and `make lint`
# is clean, the PR checks should be green.

SHELL := /usr/bin/env bash
PYTHON ?= python3
SKILL_SCRIPTS := $(wildcard skills/*/scripts/*)

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk -F':.*?## ' '{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

.PHONY: check
check: ## Run every structural validation (frontmatter, links, manifests, README, hygiene)
	@$(PYTHON) hack/validate.py all

.PHONY: reviewable
reviewable: check ## Alias for check, matching the Upbound/Crossplane convention

.PHONY: lint
lint: ## Shellcheck the skill scripts
	@if ! command -v shellcheck >/dev/null 2>&1; then \
		echo "shellcheck not installed; skipping (brew install shellcheck)" >&2; \
		exit 0; \
	fi; \
	if [ -z "$(SKILL_SCRIPTS)" ]; then echo "no skill scripts to lint"; exit 0; fi; \
	shellcheck -x -S style $(SKILL_SCRIPTS)

.PHONY: test
test: ## Run the validator's own tests, then the bats suite if present
	@$(PYTHON) -m unittest discover -s hack/tests -v
	@if command -v bats >/dev/null 2>&1 && [ -d hack/tests/bats ]; then \
		bats hack/tests/bats; \
	else \
		echo "bats not installed or no bats suite; skipping"; \
	fi

.PHONY: readme
readme: ## Regenerate the README skills table in place
	@$(PYTHON) hack/validate.py readme --fix

.PHONY: golden
golden: ## Re-record what real YAML does (needs PyYAML; CI asserts against it)
	@$(PYTHON) hack/tests/generate_golden.py

.PHONY: hooks
hooks: ## Install the git hooks (blocks committed credentials and model co-authors)
	@git config core.hooksPath hack/hooks
	@echo "core.hooksPath -> hack/hooks"
	@echo "  pre-commit  blocks staged credentials"
	@echo "  commit-msg  blocks model co-author trailers"
