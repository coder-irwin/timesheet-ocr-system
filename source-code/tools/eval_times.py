"""Score in/out clock times through the real upload path.

Separate `truth_hm` and `got_hm` on purpose: an earlier scorer normalised both
sides and so credited an unread cell as correct. A value the pipeline did not
produce is never right here, whatever the truth says.
"""
from __future__ import annotations
import argparse, hashlib, json, os, re, sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from app import pipeline, preprocess                              # noqa: E402

# A/B switch for the clock layer, so both states are runnable from one harness.
if os.getenv("TS_CLOCK_REPAIR") == "0":
    pipeline.CLOCK_REPAIR = False
if os.getenv("TS_CLOCK_CONSENSUS") == "0":
    pipeline.CLOCK_CONSENSUS = False

BASE = Path(__file__).parent.parent
SET = BASE / "data" / "testsets" / "clock-times"
HAND = BASE / "data" / "testsets" / "clock-times-handwritten"
TMP = BASE / "data" / "_eval_tmp" / "times"


def parse_hm(v) -> tuple[int, int] | None:
    """(hour, minute) from a printed clock value, or None if it is not one."""
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    m = re.search(r'(\d{1,2})\s*[:.]\s*(\d{2})', s)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
    else:
        m = re.fullmatch(r'\s*(\d{1,2})\s*(?:a\.?m\.?|p\.?m\.?)?\s*', s, re.I)
        if not m:
            return None
        h, mi = int(m.group(1)), 0
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        return None
    return h, mi


def to24(hm, raw) -> tuple[int, int] | None:
    """Fold a 12-hour value with a meridiem into 24-hour form."""
    if hm is None:
        return None
    h, mi = hm
    s = str(raw).lower()
    if re.search(r'p\.?\s*m', s) and h < 12:
        h += 12
    elif re.search(r'a\.?\s*m', s) and h == 12:
        h = 0
    return h % 24, mi


def run(keys=None, normalise=True, verbose=False, hand=False, dump=None):
    root = HAND if hand else SET
    truth = json.loads((root / "truth.json").read_text())
    TMP.mkdir(parents=True, exist_ok=True)
    tot = Counter()
    bad: list[dict] = []
    per_client: dict[str, Counter] = defaultdict(Counter)
    for key in sorted(truth):
        if keys and key not in keys:
            continue
        t = truth[key]
        img = BASE / t["img"]
        if normalise:
            dst = TMP / f"{key}.png"
            preprocess.normalise_page(img, dst)
            img = dst
        rec = pipeline.process_page(img, hashlib.sha1(img.read_bytes()).hexdigest(),
                                    force=True)["record"]
        got = {str(d.get("day")): d for d in (rec.get("days") or []) if d.get("day")}
        cl = t.get("client", "?")
        for day, want in t["rows"].items():
            g = got.get(day) or {}
            for side, gk in (("in", "in_time"), ("out", "out_time")):
                tot["n"] += 1
                per_client[cl]["n"] += 1
                w_raw, g_raw = want[side], g.get(gk)
                w, gh = parse_hm(w_raw), parse_hm(g_raw)
                ok = w is not None and gh is not None and to24(w, w_raw) == to24(gh, g_raw)
                if ok:
                    tot["ok"] += 1
                    per_client[cl]["ok"] += 1
                else:
                    kind = ("missing" if g_raw in (None, "") else
                            "unparseable" if gh is None else "wrong_value")
                    tot[kind] += 1
                    bad.append({"key": key, "client": cl, "day": day, "side": side,
                                "want": w_raw, "got": g_raw, "kind": kind})
        if verbose:
            n = sum(1 for d in t["rows"] for _ in (0, 1))
            print(f"  {key} {cl[:28]:28} {tot['ok']}/{tot['n']}", flush=True)

    pct = 100.0 * tot["ok"] / max(tot["n"], 1)
    print(f"\nin/out clock times: {tot['ok']}/{tot['n']} = {pct:.1f}%")
    for k in ("wrong_value", "unparseable", "missing"):
        if tot[k]:
            print(f"   {k:12} {tot[k]:5}  ({100.0*tot[k]/tot['n']:.1f}%)")
    print("\nper client:")
    for cl, c in sorted(per_client.items(), key=lambda kv: kv[1]["ok"] / max(kv[1]["n"], 1)):
        print(f"   {100.0*c['ok']/max(c['n'],1):5.1f}%  {c['ok']:4}/{c['n']:<4} {cl}")
    if dump:
        Path(dump).write_text(json.dumps(bad, indent=1))
        print(f"\n{len(bad)} failures -> {dump}")
    return tot, bad


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", action="store_true", help="skip the upload-path preprocessing")
    ap.add_argument("--hand", action="store_true", help="score the handwritten set")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--dump", default=None)
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    run(keys=a.only, normalise=not a.raw, verbose=a.verbose, hand=a.hand, dump=a.dump)
