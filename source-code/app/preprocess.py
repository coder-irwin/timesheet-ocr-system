"""Page preprocessing: PDF/image in, one normalised PNG per page out.

Input is phone photos taken inside a refinery -- skewed, shadowed, sometimes
curved. Every step here exists to remove a specific failure we cannot fix later:
shadow gradients make thresholding eat pencil strokes, skew makes row bands
overlap, and oversized images blow up VLM prefill time on a CPU-only laptop.

Kept intentionally cheap: this runs on the same 16GB laptop that runs the model,
so anything expensive here is stolen from inference.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import cv2
import numpy as np

from . import config


def file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def bytes_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def split_pdf(pdf_path: str | Path, out_dir: Path, stem: str) -> list[Path]:
    """Rasterise a PDF to one PNG per page. Imported lazily so a machine with no
    PDF work never pays the import."""
    import pypdfium2 as pdfium

    out: list[Path] = []
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        for i in range(len(pdf)):
            page = pdf[i]
            # scale=2 -> ~144dpi off a 72dpi page; enough for handwriting
            # without producing an image we then have to shrink again.
            #
            # But a LANDSCAPE sheet carries thirty day-columns across its
            # width instead of down its length, so each cell is a few pixels
            # wide at that scale and OCR cannot resolve it. Resolution has to
            # be won here, at rasterisation -- upscaling the raster afterwards
            # interpolates and recovers nothing. Measured on a SHELL sheet,
            # reading the printed day-number header 1..30:
            #
            #     scale 2 (long edge 1684)  ->   4 of 30 correct
            #     scale 3 (long edge 2526)  ->  30 of 30 correct
            #
            # and the stated PRESENT total went from 'B3' to '23'.
            scale = 2
            try:
                w_pt, h_pt = page.get_size()
                if w_pt > h_pt * config.LANDSCAPE_ASPECT_MIN:
                    need = config.LANDSCAPE_LONG_EDGE / max(w_pt, h_pt)
                    scale = max(scale, min(need, 4.0))
            except Exception:                                   # noqa: BLE001
                pass
            bitmap = page.render(scale=scale)
            img = bitmap.to_pil()
            dest = out_dir / f"{stem}_p{i + 1:03d}.png"
            img.save(dest)
            out.append(dest)
    finally:
        pdf.close()
    return out


def hires_path(page_png: Path) -> Path:
    """Where the high-resolution twin of a normalised page lives."""
    return page_png.with_name(f"{page_png.stem}__hires.png")


def ensure_hires(page_png: Path, pdf_path: str | Path | None) -> Path | None:
    """Produce the high-resolution twin of ONE page, on demand.

    Rendering every page twice at upload costs prep time and disk on the large
    majority of pages that never need it. The rescue path is the only consumer,
    so the twin is made only when that path actually runs -- same accuracy, and
    a 500-document batch does not pay for it up front.

    The page index is recovered from the normalised page's own filename, which
    split_pdf writes as `<stem>_pNNN.png`.
    """
    dest = hires_path(page_png)
    if dest.exists():
        return dest
    if not pdf_path:
        return None
    src = Path(pdf_path)
    if src.suffix.lower() != ".pdf" or not src.exists():
        return None
    m = re.search(r"_p(\d{1,4})$", page_png.stem)
    if not m:
        return None
    idx = int(m.group(1)) - 1
    try:
        made = render_hires(src, page_png.parent, page_png.stem[:m.start()],
                            only=idx)
    except Exception:                                           # noqa: BLE001
        return None
    return dest if dest.exists() else (made[0] if made else None)


def render_hires(pdf_path: str | Path, out_dir: Path, stem: str,
                 only: int | None = None) -> list[Path]:
    """Render PDF pages again, large, for the extraction rescue path."""
    import pypdfium2 as pdfium

    out: list[Path] = []
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        for i in range(len(pdf)):
            if only is not None and i != only:
                continue
            page = pdf[i]
            dest = out_dir / f"{stem}_p{i + 1:03d}__hires.png"
            if dest.exists():
                out.append(dest)
                continue
            try:
                w_pt, h_pt = page.get_size()
                scale = min(max(config.HIRES_LONG_EDGE / max(w_pt, h_pt), 2.0),
                            5.0)
            except Exception:                                   # noqa: BLE001
                scale = 3.0
            img = page.render(scale=scale).to_pil()
            img.save(dest)
            # Same clean-up as a normal page, but keeping the resolution.
            raw = cv2.imdecode(np.fromfile(str(dest), dtype=np.uint8),
                               cv2.IMREAD_COLOR)
            if raw is not None:
                gray = cv2.cvtColor(raw, cv2.COLOR_BGR2GRAY)
                deskewed, _ang = _deskew(gray)
                enhanced = _flatten_illumination(deskewed)
                sized = _resize_long_edge(enhanced, config.HIRES_LONG_EDGE)
                ok, buf = cv2.imencode(".png", sized)
                if ok:
                    buf.tofile(str(dest))
            out.append(dest)
    finally:
        pdf.close()
    return out


def _deskew(gray: np.ndarray) -> tuple[np.ndarray, float]:
    """Estimate skew from the dominant near-horizontal ruling lines.

    Ruled forms give a much more stable estimate than text-baseline methods,
    and these sheets are always ruled. Falls back to no rotation rather than
    guessing when it cannot find lines -- a wrong rotation is worse than none.
    """
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=120,
                            minLineLength=gray.shape[1] // 3, maxLineGap=20)
    if lines is None:
        return gray, 0.0

    # OpenCV 4.x returns shape (N, 1, 4); OpenCV 5.0 returns (N, 4). We must
    # support both -- the deployment laptop may install either, and the failure
    # mode is a hard TypeError on every single page, not a degraded result.
    arr = np.asarray(lines)
    segments = arr.reshape(-1, 4)

    angles: list[float] = []
    for x1, y1, x2, y2 in segments:
        if x2 == x1:
            continue
        ang = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        if abs(ang) <= config.MAX_DESKEW_DEG:      # keep near-horizontal only
            angles.append(ang)
    if not angles:
        return gray, 0.0

    angle = float(np.median(angles))
    if abs(angle) < 0.2:                            # not worth resampling
        return gray, 0.0
    # D-058: five segments are not evidence of page skew. s05 (50-page
    # sample): 4 of 5 lines came from one slanted signature stroke, the page
    # was rotated 0.93 deg, and the printed rules doubled from 38 to 52 --
    # 11 day rows lost. Require a real population of rulings that AGREE.
    if DESKEW_MIN_LINES and len(angles) < DESKEW_MIN_LINES:
        return gray, 0.0
    spread = float(np.percentile(angles, 75) - np.percentile(angles, 25))
    if DESKEW_MAX_IQR and spread > DESKEW_MAX_IQR:
        return gray, 0.0

    h, w = gray.shape
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    rotated = cv2.warpAffine(gray, m, (w, h), flags=cv2.INTER_CUBIC,
                             borderMode=cv2.BORDER_REPLICATE)
    return rotated, angle


def _flatten_illumination(gray: np.ndarray) -> np.ndarray:
    """Remove the shadow gradient a phone camera leaves across the page.

    Divide by a heavily blurred copy of itself: the blur approximates the
    lighting field, so dividing it out leaves reflectance. This is what keeps
    faint pencil in a shadowed corner from disappearing.
    """
    blur = cv2.GaussianBlur(gray, (0, 0), sigmaX=max(gray.shape) / 20.0)
    flat = cv2.divide(gray, blur, scale=255)
    return flat


ENHANCE_MEDIAN = False  # D-058: measured OFF on the upload path (see decision log)


DESKEW_MIN_LINES = 12   # D-058
DESKEW_MAX_IQR = 0.6    # D-058 (degrees)
ENHANCE_FLATTEN = True  # D-058
ENHANCE_CLAHE = True    # D-058


def _enhance(gray: np.ndarray) -> np.ndarray:
    if not ENHANCE_FLATTEN and not ENHANCE_CLAHE:
        return cv2.medianBlur(gray, 3) if ENHANCE_MEDIAN else gray
    flat = _flatten_illumination(gray) if ENHANCE_FLATTEN else gray
    # CLAHE rather than global equalisation: local contrast is what separates
    # pencil from paper texture, and global stretching amplifies the texture.
    if ENHANCE_CLAHE:
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        out = clahe.apply(flat)
    else:
        out = flat
    # Gentle denoise. Median beats Gaussian here because photo noise is
    # salt-and-pepper-ish and Gaussian would soften stroke edges.
    # D-058: the 3x3 median blur was measured on the product's own upload
    # path against the 50-page sample; see the decision log. Flag so both
    # states are runnable.
    if ENHANCE_MEDIAN:
        return cv2.medianBlur(out, 3)
    return out


def _resize_long_edge(img: np.ndarray, target: int) -> np.ndarray:
    h, w = img.shape[:2]
    long_edge = max(h, w)
    if long_edge <= target:
        return img
    scale = target / long_edge
    return cv2.resize(img, (int(w * scale), int(h * scale)),
                      interpolation=cv2.INTER_AREA)


def normalise_page(src: str | Path, dest: str | Path) -> dict:
    """Full pipeline for one page. Returns metadata for the audit log."""
    src, dest = Path(src), Path(dest)
    raw = cv2.imdecode(np.fromfile(str(src), dtype=np.uint8), cv2.IMREAD_COLOR)
    if raw is None:
        raise ValueError(f"Could not decode image: {src}")

    gray = cv2.cvtColor(raw, cv2.COLOR_BGR2GRAY)
    deskewed, angle = _deskew(gray)
    enhanced = _enhance(deskewed)
    # Dense landscape grids need more pixels than portrait handwriting.
    #
    # PAGE_LONG_EDGE=1600 was tuned on the AARVI/IOCL sheets, which are
    # portrait with one day per row and large handwriting. The SHELL and BPCL
    # families are landscape with THIRTY day columns across the page, so each
    # cell is a few pixels wide at 1600 and is simply destroyed. Measured on
    # SHELL APR 2026, reading the day-number header:
    #
    #     long edge 1600 ->  4 of 30 correct   ('10'->'20', '15'->'13', 5 lost)
    #     long edge 2400 -> 30 of 30 correct
    #
    # and the stated PRESENT total went from 'B3' to '23'. Portrait pages keep
    # the tested 1600 exactly, so nothing that works today is touched.
    h0, w0 = enhanced.shape[:2]
    long_edge = config.PAGE_LONG_EDGE
    if w0 > h0 * config.LANDSCAPE_ASPECT_MIN:
        long_edge = max(long_edge, config.LANDSCAPE_LONG_EDGE)
    resized = _resize_long_edge(enhanced, long_edge)

    dest.parent.mkdir(parents=True, exist_ok=True)
    # imencode + tofile rather than imwrite: imwrite mangles non-ASCII paths on
    # Windows, and these filenames come from whatever the site spoke typed.
    ok, buf = cv2.imencode(".png", resized)
    if not ok:
        raise ValueError(f"Could not encode normalised page: {dest}")
    buf.tofile(str(dest))

    return {
        "source": src.name,
        "deskew_deg": round(angle, 3),
        "orig_size": [int(raw.shape[1]), int(raw.shape[0])],
        "final_size": [int(resized.shape[1]), int(resized.shape[0])],
    }


def prepare(src: str | Path, out_dir: Path | None = None) -> list[tuple[Path, dict]]:
    """Accept a PDF or an image; return normalised pages with their metadata."""
    src = Path(src)
    out_dir = out_dir or config.PAGE_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = src.stem

    if src.suffix.lower() == ".pdf":
        rasterised = split_pdf(src, out_dir, stem)
        results = []
        for p in rasterised:
            meta = normalise_page(p, p)          # normalise in place
            results.append((p, meta))
        # NOTE: the high-resolution twin used by the extraction rescue is NOT
        # produced here. Rendering every page twice taxes the large majority
        # that never need it, which matters at 500 documents a batch. The
        # pipeline calls preprocess.ensure_hires() for the specific page that
        # failed instead -- same accuracy, cost only where it buys something.
        return results

    dest = out_dir / f"{stem}.png"
    meta = normalise_page(src, dest)
    return [(dest, meta)]
