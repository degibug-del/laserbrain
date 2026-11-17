from .score import parse_score


def standings(matches):
    rows = {}

    def row(team):
        return rows.setdefault(team, {"played": 0, "points": 0, "gd": 0})

    for m in matches:
        hg, ag = parse_score(m["score"])
        h, a = row(m["home"]), row(m["away"])
        h["played"] += 1
        a["played"] += 1
        h["gd"] += hg - ag
        a["gd"] += ag - hg
        if hg > ag:
            h["points"] += 3
        elif hg < ag:
            a["points"] += 3
        else:
            h["points"] += 1
            a["points"] += 1
    ordered = sorted(rows.items(), key=lambda kv: (-kv[1]["points"], -kv[1]["gd"], kv[0]))
    return [(team, r["played"], r["points"], r["gd"]) for team, r in ordered]


def head_to_head(matches, a, b):
    pa = pb = 0
    for m in matches:
        if {m["home"], m["away"]} != {a, b}:
            continue
        hg, ag = parse_score(m["score"])
        ga, gb = (hg, ag) if m["home"] == a else (ag, hg)
        if ga > gb:
            pa += 3
        elif ga < gb:
            pb += 3
        else:
            pa += 1
            pb += 1
    return pa, pb
