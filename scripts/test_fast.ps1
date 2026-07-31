# Quick test — excludes slow integration tests, parallel via pytest-xdist (-n auto)
pytest tests/ -q --tb=short --ignore=tests/_archive -n auto -x
