# This makefile is really for testing Python code.

.PHONY: all
all: lint test

.PHONY: lint
lint:
	mypy xheap.py
	black --check xheap.py

.PHONY: test
test:
	python3 xheap.py
