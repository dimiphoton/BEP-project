# Socle : up demarre Postgres et liste les schemas et les roles.
ifeq ($(OS),Windows_NT)
  VENV_PY := .venv/Scripts/python.exe
else
  VENV_PY := .venv/bin/python
endif

ifeq ($(wildcard $(VENV_PY)),)
  PY ?= python
else
  PY ?= $(VENV_PY)
endif

.PHONY: up ingest build test eval-nace eval-contracts healthcheck metrics figures dbt-docs slides-check

up:
	$(PY) -m observatory.cli ensure-env
	docker compose up -d --wait
	$(PY) -m observatory.cli check

ingest:
	$(PY) -m observatory.cli ingest

build:
	$(PY) -m observatory.cli build

test:
	$(PY) -m pytest

eval-nace:
	$(PY) -m observatory.cli eval-nace

eval-contracts:
	$(PY) -m observatory.cli eval-contracts

healthcheck:
	$(PY) scripts/healthcheck.py

metrics:
	$(PY) scripts/export_metrics.py

figures:
	$(PY) scripts/make_figures.py

dbt-docs:
	$(PY) scripts/export_dbt_docs.py

slides-check:
	$(PY) scripts/check-slides.py
