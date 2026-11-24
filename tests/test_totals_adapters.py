"""Offline tests: python -m unittest discover -s tests -p test_totals_adapters.py"""
import copy
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from espn_totals_adapters import adapt_nba, adapt_nfl, attempts, number, load_history
from totals_model_v2 import project
from totals_shadow import build

NOW = datetime(2026, 11, 24, tzinfo=timezone.utc)


def summary(league="NBA", event="e", date="2026-11-20T00:00:00Z"):
    competitors, boxes = [], []
    for tid, drives in (("1", "10"), ("2", "11")):
        competitors.append(dict(team=dict(id=tid), score="110", linescores=[dict(value=v) for v in (25,25,25,25,10)]))
        values = {"fieldGoalsMade-fieldGoalsAttempted": "40-80", "freeThrowsMade-freeThrowsAttempted": "20-25", "offensiveRebounds": "10", "turnovers": "12", "totalDrives": drives}
        boxes.append(dict(team=dict(id=tid), statistics=[dict(name=k, displayValue=v) for k,v in values.items()]))
    return dict(header=dict(id=event, competitions=[dict(date=date, status=dict(type=dict(completed=True)), competitors=competitors)]), boxscore=dict(teams=boxes))


def histories(scored=30, allowed=14, own=10, opponent=7, n=5):
    return [dict(id=str(i), date=f"2026-11-{10+i:02d}T00:00:00Z", scored=scored, allowed=allowed, opportunities=own, opponent_opportunities=opponent, opportunity_scope="final") for i in range(n)]


def fake_get(payload, fail_summary=False):
    calls = []
    game = copy.deepcopy(payload["header"]["competitions"][0])
    event = dict(id=payload["header"]["id"], date=game["date"], competitions=[game])
    def get(url, **params):
        calls.append((url, params))
        if url.endswith("/schedule"):
            return dict(events=[event])
        if url.endswith("/summary"):
            if fail_summary:
                raise RuntimeError("offline fixture failure")
            return payload
        raise AssertionError("Unexpected endpoint")
    return get, calls


class AdapterTests(unittest.TestCase):
    def test_nba(self):
        self.assertEqual(adapt_nba(summary())["records_by_team"]["1"]["opportunities"], 93)
    def test_nfl(self):
        r = adapt_nfl(summary())["records_by_team"]["1"]
        self.assertEqual((r["opportunities"], r["opponent_opportunities"]), (10, 11))
    def test_missing_not_zero(self):
        s=summary(); s["boxscore"]["teams"].pop()
        self.assertIsNone(adapt_nba(s)["records_by_team"]["1"]["opportunities"])
    def test_missing_nfl_opponent(self):
        s=summary(); s["boxscore"]["teams"].pop()
        r=adapt_nfl(s)["records_by_team"]["1"]
        self.assertEqual(r["opportunities"],10); self.assertIsNone(r["opponent_opportunities"])
    def test_overtime(self):
        r=adapt_nba(summary())["records_by_team"]["1"]
        self.assertEqual((r["scored"],r["regulation_scored_metadata"]),(110,100))
        self.assertNotIn("regulation_scored",r); self.assertEqual(r["opportunity_scope"],"final")
    def test_no_mutation(self):
        s=summary(); before=copy.deepcopy(s); adapt_nba(s); self.assertEqual(s,before)
    def test_reordered(self):
        s=summary(); s["boxscore"]["teams"].reverse()
        self.assertEqual(adapt_nfl(s)["records_by_team"]["1"]["opportunities"],10)
    def test_unfinished(self):
        s=summary(); s["header"]["competitions"][0]["status"]["type"]["completed"]=False
        with self.assertRaises(ValueError): adapt_nba(s)
    def test_duplicate_box(self):
        s=summary(); s["boxscore"]["teams"].append(s["boxscore"]["teams"][0])
        with self.assertRaises(ValueError): adapt_nba(s)
    def test_bad_numbers(self):
        for v in (None,True,"NaN","inf","-1","--"): self.assertIsNone(number(v))
        self.assertEqual(number("0"),0)
    def test_pairs(self):
        for v in ("90-80","--","1-2-3","1.5-3"): self.assertIsNone(attempts(v))
        self.assertEqual(attempts("0-0"),0)
    def test_fractional_drives(self):
        s=summary(); s["boxscore"]["teams"][0]["statistics"][-1]["displayValue"]="10.5"
        self.assertIsNone(adapt_nfl(s)["records_by_team"]["1"]["opportunities"])
    def test_nfl_rate_denominators(self):
        r=project("NFL",histories(),histories(21,20,7,10),NOW.isoformat())
        self.assertEqual(r["method"],"drives_efficiency")
        self.assertEqual(r["projection"],dict(home=25.0,away=17.5,total=42.5))
    def test_missing_defensive_denominator(self):
        h=histories(); h[0].pop("opponent_opportunities")
        self.assertEqual(project("NFL",h,histories(),NOW.isoformat())["method"],"score_average_fallback")
    def test_invalid_defensive_denominator(self):
        h=histories(); h[0]["opponent_opportunities"]=0
        with self.assertRaises(ValueError): project("NFL",h,histories(),NOW.isoformat())
    def test_basketball_backward_compatibility(self):
        h=histories(); [r.pop("opponent_opportunities") for r in h]
        self.assertEqual(project("NBA",h,h,NOW.isoformat())["method"],"possessions_efficiency")
    def test_scope_mismatch(self):
        h=histories(); h[0]["opportunity_scope"]="regulation"
        self.assertEqual(project("NFL",h,histories(),NOW.isoformat())["method"],"score_average_fallback")
    def test_insufficient(self):
        self.assertEqual(project("NFL",[],[],NOW.isoformat())["method"],"insufficient_history")
    def test_duplicate_history(self):
        h=histories(); h.append(h[0])
        with self.assertRaises(ValueError): project("NFL",h,histories(),NOW.isoformat())
    def test_loader_and_cache(self):
        get,calls=fake_get(summary()); cache={}
        r=load_history("NBA","basketball/nba","1",12,NOW,get,cache)
        again=load_history("NBA","basketball/nba","2",12,NOW,get,cache)
        self.assertEqual(r[0]["opportunities"],93)
        self.assertEqual(again[0]["opportunities"],93)
        self.assertEqual(sum(url.endswith("/summary") for url,_ in calls),1)
        self.assertTrue(all("espn.com" in url for url,_ in calls))
    def test_loader_summary_failure(self):
        get,_=fake_get(summary(),True)
        r=load_history("NBA","basketball/nba","1",12,NOW,get,{})[0]
        self.assertEqual(r["scored"],110); self.assertNotIn("opportunities",r)
        self.assertTrue(r["input_warnings"])
    def test_shadow_integration_and_restoration(self):
        get,_=fake_get(summary())
        provider=SimpleNamespace(NOW="original",CACHE={"keep":1},SPORTS={"NBA":("","basketball/nba",5,12)},get=get,key=str.lower,team_index=lambda route:{"home":"1","away":"2"})
        saved=dict(leagues=[dict(league="NBA",games=[dict(home="Home",away="Away",start="2026-12-01T00:00:00Z")])])
        original=copy.deepcopy(saved)
        result=build(saved,provider,now=NOW)
        self.assertEqual(result["odds_requests"],0)
        self.assertEqual(result["leagues"][0]["games"][0]["shadow"]["sample"],dict(home=1,away=1))
        self.assertEqual((provider.NOW,provider.CACHE),("original",{"keep":1}))
        self.assertEqual(saved,original)


if __name__ == "__main__":
    unittest.main()
