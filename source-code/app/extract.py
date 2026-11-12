"""Extraction: page image -> structured record.

Two things this module is careful about, both from the project spec:

*   **Provider is swappable.** Everything downstream depends only on
    `ExtractionProvider.extract()`. Replacing the local VLM with a cloud model
    later touches this file and nothing else.

*   **The cache is aggressive and content-addressed.** The key is the hash of
    the *normalised page bytes* plus model plus prompt version -- so the same
    page re-uploaded after a correction, or re-run in a later batch, never pays
    for inference again. On a CPU-only laptop where a page costs 2-5 minutes,
    this is the difference between a usable system and an unusable one.

The independent-summary pass is the other load-bearing detail: the monthly
totals are read by a call that never sees the day grid. If one call produced
both, the model would derive the total from the rows it just wrote, and the
row-sum checksum in validate.py would be checking the model against itself.
"""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any, Protocol

import httpx

from . import config
from .templates_spec import (
    TemplateSpec,
    STATUS_VALUES,
    classifier_menu,
    get as get_template,
    json_shape,
)

# Bump when a prompt changes -- it is part of the cache key, so old results are
# invalidated automatically rather than silently reused against a new prompt.
PROMPT_VERSION = "v1"


# ---------------------------------------------------------------------------
# Provider interface
# ---------------------------------------------------------------------------

class ExtractionProvider(Protocol):
    name: str

    def classify(self, image_path: Path) -> str: ...

    def extract(self, image_path: Path, spec: TemplateSpec) -> dict: ...

    def extract_summary(self, image_path: Path, spec: TemplateSpec) -> dict: ...


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_COMMON_RULES = """\
You are reading a handwritten timesheet that was photographed on a phone. Read
only what is actually written. Follow these rules exactly:

- Transcribe what you see. Do NOT calculate, infer, correct, or fill in a value
  that is not legibly written on the page.
- If a cell is blank, use null. If a cell is written but you cannot read it,
  use the string "?" so a human is asked rather than a wrong value guessed.
- Never compute a total from other cells. Totals must be read from the page.
- Times must be copied in the form they appear (e.g. "9:00", "0900", "9 AM").
- Status codes mean: P=present, A=absent, L=leave, W=weekly off, H=holiday.
- Output valid JSON only. No commentary, no markdown fences."""


def _classify_prompt() -> str:
    return f"""{_COMMON_RULES}

Identify which timesheet template this page uses.

Templates:
{classifier_menu()}

Look at: the number of day rows, whether separate in-time and out-time columns
exist, whether an overtime column exists, and whether allowance columns exist.

Return exactly: {{"template": "<key>", "period_days": <int>, "reason": "<short>"}}"""


def _grid_prompt(spec: TemplateSpec) -> str:
    fields = ", ".join(spec.day_fields())
    return f"""{_COMMON_RULES}

Read the DAY-BY-DAY GRID from this {spec.period_days}-day timesheet, and the
header identity fields. Ignore the totals/summary block entirely -- another
step reads that separately.

For every day row that exists on the page, output an object with these keys:
{fields}

"day" is the day number as an integer. "status" is one of {', '.join(STATUS_VALUES)}
or null.

Return exactly this JSON shape:
{{
  "employee_name": "<as written>",
  "employee_code": "<as written>",
  "project": "<as written>",
  "period_start": "<as written or null>",
  "period_end": "<as written or null>",
  "days": [ {{ {', '.join(f'"{f}": ...' for f in spec.day_fields())} }} ]
}}"""


def _summary_prompt(spec: TemplateSpec) -> str:
    fields = "\n".join(f"  - {f}" for f in spec.summary_fields())
    return f"""{_COMMON_RULES}

Read ONLY the totals / summary block of this timesheet -- the box or row that
states the monthly totals. Do NOT read the day-by-day grid, and do NOT add up
the daily rows. Copy the printed or handwritten total figures exactly as they
appear on the page.

If a total is not written on the page, use null. Do not compute it.

Read these fields:
{fields}

Return exactly:
{{ {', '.join(f'"{f}": ...' for f in spec.summary_fields())} }}"""


# ---------------------------------------------------------------------------
# JSON recovery
# ---------------------------------------------------------------------------

_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S)


def parse_json_loose(text: str) -> dict | None:
    """VLMs at 4B occasionally wrap or prefix their JSON despite instructions.
    Recover rather than fail the page -- a retry costs minutes on this hardware.
    """
    if not text:
        return None
    text = text.strip()
    m = _FENCE.search(text)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Fall back to the outermost balanced {...}
    start = text.find("{")
    if start == -1:
        return None
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


# ---------------------------------------------------------------------------
# Ollama provider
# ---------------------------------------------------------------------------

class OllamaProvider:
    """Local Qwen3-VL through Ollama. No network egress, no per-token cost."""

    name = "ollama"

    def __init__(self, url: str | None = None, model: str | None = None):
        self.url = (url or config.OLLAMA_URL).rstrip("/")
        self.model = model or config.VLM_MODEL

    # -- plumbing ---------------------------------------------------------
    def _call(self, prompt: str, image_path: Path, seed: int | None = None) -> str:
        img_b64 = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
        options: dict[str, Any] = {
            # Low temperature: we want transcription, not composition. Some
            # variation between passes is still produced by the seed, which is
            # what makes the dual-pass disagreement signal meaningful.
            "temperature": 0.1 if seed is None else 0.3,
            "num_predict": 4096,
        }
        if seed is not None:
            options["seed"] = seed

        payload = {
            "model": self.model,
            "prompt": prompt,
            "images": [img_b64],
            "stream": False,
            "format": "json",       # Ollama constrains output to valid JSON
            "options": options,
        }
        with httpx.Client(timeout=config.VLM_TIMEOUT_S) as client:
            r = client.post(f"{self.url}/api/generate", json=payload)
            r.raise_for_status()
            return r.json().get("response", "")

    def health(self) -> dict:
        try:
            with httpx.Client(timeout=5.0) as client:
                r = client.get(f"{self.url}/api/tags")
                r.raise_for_status()
                tags = [m.get("name", "") for m in r.json().get("models", [])]
            base = self.model.split(":")[0]
            return {
                "ok": True,
                "models": tags,
                "model_present": any(t == self.model or t.startswith(base) for t in tags),
                "model": self.model,
            }
        except Exception as exc:                              # noqa: BLE001
            return {"ok": False, "error": str(exc), "model": self.model}

    # -- interface --------------------------------------------------------
    def classify(self, image_path: Path) -> str:
        data = parse_json_loose(self._call(_classify_prompt(), image_path)) or {}
        return str(data.get("template") or "")

    def extract(self, image_path: Path, spec: TemplateSpec, seed: int | None = None) -> dict:
        data = parse_json_loose(self._call(_grid_prompt(spec), image_path, seed))
        return data or {}

    def extract_summary(self, image_path: Path, spec: TemplateSpec,
                        seed: int | None = None) -> dict:
        data = parse_json_loose(self._call(_summary_prompt(spec), image_path, seed))
        return data or {}


# ---------------------------------------------------------------------------
# Content-addressed cache
# ---------------------------------------------------------------------------

def cache_key(page_hash: str, model: str, kind: str, template: str) -> str:
    return f"{page_hash[:32]}__{model.replace(':', '-')}__{kind}__{template}__{PROMPT_VERSION}"


def cache_get(key: str) -> Any | None:
    p = config.CACHE_DIR / f"{key}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def cache_put(key: str, value: Any) -> None:
    p = config.CACHE_DIR / f"{key}.json"
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)     # atomic; a killed run never leaves a half-written cache


# ---------------------------------------------------------------------------
# Consensus
# ---------------------------------------------------------------------------

def _flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(_flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(_flatten(v, f"{prefix}[{i}]"))
    else:
        out[prefix] = obj
    return out


def _norm_cell(v: Any) -> str:
    if v is None:
        return ""
    s = str(v).strip().upper()
    # 8, 8.0 and 8.00 are the same reading; don't report them as disagreement.
    try:
        f = float(s.replace(":", "."))
        return f"{f:.4f}".rstrip("0").rstrip(".")
    except ValueError:
        return s


def diff_passes(a: dict, b: dict) -> dict[str, tuple[Any, Any]]:
    """Fields where the two passes disagree. This is our uncertainty signal --
    a *measured* one, unlike model self-reported confidence."""
    fa, fb = _flatten(a), _flatten(b)
    out: dict[str, tuple[Any, Any]] = {}
    for k in set(fa) | set(fb):
        va, vb = fa.get(k), fb.get(k)
        if _norm_cell(va) != _norm_cell(vb):
            out[k] = (va, vb)
    return out


def extract_page(image_path: Path, page_hash: str,
                 provider: ExtractionProvider | None = None,
                 template_key: str | None = None,
                 force: bool = False) -> dict:
    """Full extraction for one page, cache-first at every step.

    Returns {record, template, disagreements, cached, passes}.
    """
    provider = provider or OllamaProvider()
    model = getattr(provider, "model", provider.name)
    cached_all = True

    # 1. Template ---------------------------------------------------------
    if template_key:
        tkey = template_key
    else:
        ck = cache_key(page_hash, model, "classify", "-")
        tkey = None if force else cache_get(ck)
        if tkey is None:
            tkey = provider.classify(image_path)
            cache_put(ck, tkey)
            cached_all = False
    spec = get_template(tkey)

    # 2. Grid (dual pass) -------------------------------------------------
    passes: list[dict] = []
    seeds = [None, 7] if config.DUAL_PASS else [None]
    for i, seed in enumerate(seeds):
        ck = cache_key(page_hash, model, f"grid{i}", spec.key)
        got = None if force else cache_get(ck)
        if got is None:
            got = provider.extract(image_path, spec, seed=seed) \
                if _accepts_seed(provider) else provider.extract(image_path, spec)
            cache_put(ck, got)
            cached_all = False
        passes.append(got or {})

    record = dict(passes[0])
    disagreements = diff_passes(passes[0], passes[1]) if len(passes) > 1 else {}

    # 3. Summary, read independently of the grid --------------------------
    if config.INDEPENDENT_SUMMARY_PASS:
        ck = cache_key(page_hash, model, "summary", spec.key)
        summary = None if force else cache_get(ck)
        if summary is None:
            summary = provider.extract_summary(image_path, spec)
            cache_put(ck, summary)
            cached_all = False
        record["summary"] = summary or {}
    else:
        record.setdefault("summary", {})

    record.setdefault("days", [])
    return {
        "record": record,
        "template": spec.key,
        "disagreements": disagreements,
        "cached": cached_all,
        "passes": len(passes),
    }


def _accepts_seed(provider: Any) -> bool:
    import inspect
    try:
        return "seed" in inspect.signature(provider.extract).parameters
    except (TypeError, ValueError):
        return False
