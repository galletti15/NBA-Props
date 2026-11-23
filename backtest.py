"""Walk-forward backtest (no odds needed): tunes K_PRIOR / W_LAST by MAE vs naive baselines.
Run: python backtest.py   (test = 2025-26, history = 2024-25 & 2023-24)"""
import itertools, pandas as pd
import pipeline as P

TEST, HIST = "2025-26", ["2024-25", "2023-24"]
STATS = ["PTS", "REB", "AST", "FG3M"]

def run(test, hist, K, W, players=120):
    P.K_PRIOR, P.W_LAST = K, W
    top = test.groupby("PLAYER_NAME").MIN.sum().nlargest(players).index
    rows = []
    for name in top:
        g = test[test.PLAYER_NAME == name].sort_values("GAME_DATE")
        h = hist[hist.PLAYER_NAME == name]
        if len(g) < 25 or len(h) < 20: continue
        for i in range(10, len(g), 3):
            past, row = g.iloc[:i], g.iloc[i]
            for s in STATS:
                mu, _ = P.project(past, h, s, 1, 1, 1, False, 0, 0)
                rows.append(dict(stat=s, y=row[s], mu=mu, base_season=past[s].mean(), base_l10=past[s].tail(10).mean()))
    return pd.DataFrame(rows)

if __name__ == "__main__":
    test = P.logs(TEST); hist = pd.concat([P.logs(s) for s in HIST])
    res = []
    for K, W in itertools.product([100, 250, 400, 800], [0.2, 0.35, 0.5]):
        d = run(test, hist, K, W)
        res.append(dict(K=K, W=W, mae=(d.mu-d.y).abs().mean(), bias=(d.mu-d.y).mean(),
                        mae_season=(d.base_season-d.y).abs().mean(), mae_l10=(d.base_l10-d.y).abs().mean()))
    out = pd.DataFrame(res).sort_values("mae"); print(out.to_string(index=False))
    b = run(test, hist, out.iloc[0].K, out.iloc[0].W)
    print(b.groupby("stat").apply(lambda x: pd.Series({"mae": (x.mu-x.y).abs().mean(),
          "mae_l10": (x.base_l10-x.y).abs().mean(), "bias": (x.mu-x.y).mean()})))
