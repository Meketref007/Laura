#!/bin/bash
# Parallel tests using pytest-xdist
pytest tests/ -q --tb=short --ignore=tests/_archive -k "not test_memory_summary_command" -n auto
