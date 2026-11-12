# 08 — API Reference

Generated from `source-code/app/main.py`, so it matches the code exactly.
20 endpoints.

## Authentication

The application itself has **no authentication**. When deployed, the
reverse proxy (Caddy) handles the username/password gate and passes the
signed-in name to the application in an `X-Remote-User` header, which it
**sets** rather than appends — so a browser cannot supply its own and claim
to be someone else. Running locally, there is no gate and actions are
attributed to a default user.

This matters if you put the application behind a different proxy: you must
set that header, and you must strip any client-supplied copy of it.

## Conventions

- Request and response bodies are JSON unless stated otherwise.
- Uploads are `multipart/form-data`.
- Errors use standard HTTP codes with a JSON `detail` field.
- `{page_id}` and `{batch_id}` are integers.

---

## Endpoints

### `GET /`

*Handler:* `main.index()`

### `GET /api/accuracy`

The last benchmark run, scored against the client's own typed Excel.

*Handler:* `main.accuracy()`

### `GET /api/audit`

| Parameter | Type / default |
|---|---|
| `limit` | `int = 300` |

*Handler:* `main.audit_log()`

### `GET /api/batches`

*Handler:* `main.batches()`

### `POST /api/batches`

| Parameter | Type / default |
|---|---|
| `name` | `str = Form(...)` |
| `files` | `list[UploadFile] = File(...)` |

*Handler:* `main.create_batch()`

### `GET /api/batches/{batch_id}/export`

| Parameter | Type / default |
|---|---|
| `batch_id` | `int` |
| `design` | `str = 'all'` |

*Handler:* `main.export()`

### `GET /api/batches/{batch_id}/pages`

| Parameter | Type / default |
|---|---|
| `batch_id` | `int` |
| `status` | `str | None = None` |

*Handler:* `main.batch_pages()`

### `GET /api/cost`

Hidden: what this project costs on Google Cloud (exact when the billing export is on).

*Handler:* `main.cloud_cost()`

### `GET /api/export-designs`

The five presentations the client can choose between.

*Handler:* `main.export_designs_list()`

### `GET /api/health`

*Handler:* `main.health()`

### `GET /api/log`

Live activity feed for the UI. `after` is the last seq the client saw.

| Parameter | Type / default |
|---|---|
| `after` | `int = 0` |

*Handler:* `main.activity_log()`

### `GET /api/me`

*Handler:* `main.me()`

### `GET /api/pages/{page_id}`

| Parameter | Type / default |
|---|---|
| `page_id` | `int` |
| `claim` | `int = 1` |

*Handler:* `main.page_detail()`

### `PUT /api/pages/{page_id}`

Save reviewer corrections, re-validate, and record every changed field.

| Parameter | Type / default |
|---|---|
| `page_id` | `int` |
| `payload` | `dict` |

*Handler:* `main.save_page()`

### `GET /api/pages/{page_id}/image`

| Parameter | Type / default |
|---|---|
| `page_id` | `int` |

*Handler:* `main.page_image()`

### `POST /api/pages/{page_id}/lock`

Renew (or first claim) the lock while the page is on someone's screen.

| Parameter | Type / default |
|---|---|
| `page_id` | `int` |

*Handler:* `main.lock_heartbeat()`

### `DELETE /api/pages/{page_id}/lock`

| Parameter | Type / default |
|---|---|
| `page_id` | `int` |

*Handler:* `main.lock_release()`

### `POST /api/pages/{page_id}/reextract`

Force a fresh extraction, bypassing the cache. Used when a page was misclassified into the wrong template.

| Parameter | Type / default |
|---|---|
| `page_id` | `int` |

*Handler:* `main.reextract()`

### `POST /api/roster`

| Parameter | Type / default |
|---|---|
| `file` | `UploadFile = File(...)` |

*Handler:* `main.upload_roster()`

### `GET /cost`

*Handler:* `main.cost_page()`

