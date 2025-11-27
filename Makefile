.PHONY: docs docs-serve

docs:
	poetry run mkdocs gh-deploy --force

docs-serve:
	poetry run mkdocs serve
