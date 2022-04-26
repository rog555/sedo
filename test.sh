#!/bin/bash
set -e
pytest --cov=functions tests/ --cov-report html:/tmp/htmlcov --cov-fail-under 80
flake8 .