from app.evals.calibrate import search_thresholds, simulate
from app.evals.metrics import fit_platt, wilson


def test_wilson():
    lo, hi = wilson(0, 50)
    assert lo == 0 and 0.05 < hi < 0.09
    assert wilson(0, 0) == (0.0, 1.0)


def test_platt_monotone():
    x = [0.1, 0.2, 0.3, 0.4, 0.6, 0.7, 0.8, 0.9]
    y = [0, 0, 0, 1, 0, 1, 1, 1]
    a, _b = fit_platt(x, y)
    assert a > 0


def _case(exp, raw_good, raw_bad, status="matched", rel_good=0.9, rel_bad=0.2):
    return {"exp": set(exp), "exp_status": status, "oos": False, "exact": None,
            "cands": [{"pid": 1, "raw": raw_good, "rel": rel_good, "sat": True},
                      {"pid": 2, "raw": raw_bad, "rel": rel_bad, "sat": True}]}


def test_search_thresholds_respects_wrong_rate():
    cases = [_case([1], 0.8, 0.3) for _ in range(20)]
    cases += [_case([2], 0.5, 0.45, rel_good=0.2, rel_bad=0.9) for _ in range(5)]
    cases += [{"exp": set(), "exp_status": "no_match", "oos": False, "exact": None,
               "cands": [{"pid": 3, "raw": 0.2, "rel": 0.1, "sat": True}]} for _ in range(5)]
    out = search_thresholds(cases)
    m = out["dev_metrics"]
    assert m["matched_wrong_rate"] <= 0.02
    assert m["status_ok"] >= 25
    again = simulate(cases, out["thresholds"], out["rerank_beta"], 0.6)
    assert again["status_ok"] == m["status_ok"]
