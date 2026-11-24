# NBA/NFL adapter shadow patch

Manual experimental branch only; no workflows, live outputs or odds calls added.

Tests: python -m unittest discover -s tests -p test_totals_adapters.py
Manual run: python totals_shadow.py

The runner reads docs/totals.json and writes only data/totals-shadow.json. NBA/NFL now use ESPN schedule and summary requests, cached per run. Failed summaries retain score-only records with warnings. College leagues retain the previous score-only path. Additional ESPN HTTP requests are expected; no Odds API requests are made.

NBA possessions are estimated as FGA + 0.44*FTA - OREB + TOV and averaged across both teams. NFL uses team totalDrives and requires opponent drives for allowed efficiency. Expected drives are calculated separately for home and away. Final scores include defensive and special-teams scoring, so this is not an offensive-only efficiency model.

Overtime-inclusive scores match full-game stats. Regulation scores are metadata, not applied normalization. No injuries, weather, travel, lineups or other context adjustments have been implemented. Regular-season, current/prior-season selection matches the existing baseline; no postseason expansion.

Validation: 22 offline synthetic/mocked tests passed. Complete live ESPN summaries, workflow execution, backtesting and calibration remain unverified. The patch does not activate or publish the model.
