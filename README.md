# Claims Analysis

A lightweight Python data analyzer for claims exports while the ERP system is unavailable or unreliable.

## Goals

- Load CSV or Excel claim data exports.
- Validate fields against configured categories and rules.
- Detect missing required values, duplicates, invalid statuses, invalid dates, and invalid amounts.
- Produce summary reports for operations review.

## Planned workflow

1. Add field/category rules in `config/field_categories.yaml`.
2. Place exported data files in a local `data/` folder.
3. Run the analyzer from the command line.
4. Review generated validation and summary reports.

## Example command

```bash
python -m claims_analysis analyze data/sample_claims.csv --config config/field_categories.yaml --out reports/
```

## Project structure

```text
claims_analysis/
  __init__.py
  analyzer.py
  cli.py
  config_loader.py
  validators.py
config/
  field_categories.yaml
reports/
  .gitkeep
tests/
  test_validators.py
```
