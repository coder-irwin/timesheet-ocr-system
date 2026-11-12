# Timesheet Extraction & Validation -- production container
#
# Design notes for whoever maintains this:
#
#  * Python 3.12 because requirements.txt records 3.11/3.12 as the versions
#    verified end-to-end. (Development happens on 3.14; the pinned wheels
#    resolve on both, but we ship the verified one.)
#  * The OCR models are downloaded AT BUILD TIME and baked into the image, so a
#    running container never needs network access. This is what makes the
#    offline deployment possible.
#  * opencv-python-headless is deliberate: no GUI libs, so no libGL in the
#    image. Do not swap it for plain opencv-python.
#  * Everything the app writes lives under /data, which is a mounted volume.
#    The image itself is read-only in practice and can be recreated at will.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TS_DATA_DIR=/data

WORKDIR /app

# libglib2.0-0 is the one system lib opencv-headless still links against.
# curl is used by the container healthcheck below.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libglib2.0-0 curl \
 && rm -rf /var/lib/apt/lists/*

# Dependencies first, so application edits do not invalidate this layer.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# rapidocr declares a dependency on the FULL opencv-python, so pip installs it
# alongside the headless build this project pins. Both ship the same `cv2`
# module into the same directory, and the full one wins -- which then fails at
# import with "libxcb.so.1: cannot open shared object file", because the GUI
# libraries it links against are deliberately not in this image.
#
# Removing both and reinstalling only headless is the fix that matches the
# project's intent (see the note in requirements.txt). --no-deps stops pip from
# dragging the full build back in.
RUN pip uninstall -y opencv-python opencv-python-headless \
 && pip install --no-cache-dir --no-deps opencv-python-headless==5.0.0.93 \
 && python -c "import cv2; print('cv2', cv2.__version__, '(headless)')"

# Application code.
COPY app/ ./app/
COPY web/ ./web/

# Bake the OCR models in. Constructing RapidOCR() downloads PP-OCRv6 det/rec and
# the classifier (~32 MB) into site-packages. Without this line the first upload
# on an offline server would fail.
RUN python -c "from rapidocr import RapidOCR; RapidOCR()" \
 && python -c "import pathlib,glob; \
p=glob.glob('/usr/local/lib/python3.12/site-packages/rapidocr/models/*.onnx'); \
assert len(p) >= 3, 'OCR models were not baked into the image: %r' % p; \
print('baked OCR models:', [pathlib.Path(x).name for x in p])"

RUN mkdir -p /data

# Fail the build rather than ship an image whose imports are broken. Safe with
# no roster present: Roster.from_csv returns an empty roster for a missing file.
RUN python -c "import app.main; print('app imports OK')"

EXPOSE 8077

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8077/api/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8077"]
