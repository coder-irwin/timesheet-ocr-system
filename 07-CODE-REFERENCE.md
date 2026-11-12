# 07 — Code Reference

Module by module. Line counts and descriptions are taken directly from the
source in `source-code/app/`, so they cannot drift from the code.

The modules are listed in the order the data flows through them, not
alphabetically. If you are looking for where to make a change, read
`02-HOW-IT-WORKS.md` first to find the right stage, then come here.


---

## Entry point and configuration

### `app/main.py` — 560 lines

FastAPI application: upload -> extract -> validate -> review -> export.

**Public functions:** `index()`, `cloud_cost()`, `cost_page()`, `me()`, `health()`, `create_batch()`, `batches()`, `batch_pages()`, `accuracy()`, `activity_log()`, `export_designs_list()`, `export()` …and 8 more

### `app/config.py` — 83 lines

Central configuration. Everything is env-overridable so the same build runs on the 16GB CPU-only demo laptop and on a bigger box later without code changes.

### `app/db.py` — 320 lines

SQLite persistence + audit log.

**Public functions:** `lock_status()`, `acquire_lock()`, `release_lock()`, `locks_for()`, `db()`, `init()`, `create_batch()`, `list_batches()`, `add_page()`, `set_page_result()`, `set_page_status()`, `get_page()` …and 6 more

### `app/eventlog.py` — 66 lines

A plain-language activity feed for the UI.

**Public functions:** `emit()`, `since()`, `latest_seq()`, `clear()`


---

## Stage 1 — pre-OCR

### `app/preprocess.py` — 322 lines

Page preprocessing: PDF/image in, one normalised PNG per page out.

**Behaviour flags:** `ENHANCE_MEDIAN`, `ENHANCE_FLATTEN`, `ENHANCE_CLAHE`  
Several of these encode measured decisions. See `06-ACCURACY-AND-TESTING.md` before changing any of them.

**Public functions:** `file_sha256()`, `bytes_sha256()`, `split_pdf()`, `hires_path()`, `ensure_hires()`, `render_hires()`, `normalise_page()`, `prepare()`


---

## Stage 2 — reading text and structure

### `app/ocr_engine.py` — 418 lines

OCR + spatial layout reconstruction.

**Public functions:** `run_ocr()`, `confidence_profile()`, `route_from_profile()`, `detect_grid()`, `detect_row_rules()`, `detect_row_rules_in()`, `build_cells()`, `assign_boxes()`, `cluster_rows()`, `analyse()`, `cx()`, `cy()` …and 2 more

### `app/aarvi_form.py` — 2405 lines

Anchor-based field extraction for the AARVI ENCON timesheet family.

**Behaviour flags:** `STRIP_PERIOD_FROM_NAME`, `STRIP_DESIGNATION_FROM_NAME`, `MERGED_CELL_SPANS_ROWS`, `GRID_BOTTOM_FROM_DATES`, `CLEAN_RULES_BEAT_LADDER`, `ZERO_HOURS_WEEKEND_IS_OFF`, `HEADER_RULE_TOLERANT`, `HEADER_FROM_DATES`, `BARE_INLINE_LABELS`, `DATE_BOTTOM_CAPS_GRID`, `ANCHOR_RIVAL_CAP`, `WEEKDAY_WORD_OFF`, `SUMMARY_NEAREST_LINE`, `SUMMARY_BOUND_BY_NEXT_LABEL`, `COMPOFF_FUZZY`, `EXACT_ANNOTATION_FIRST`, `DATE_COL_TO_LEFT_EDGE`, `COLUMN_HEADERS_IN_BAND`, `SPLIT_TWO_DATE_BANDS`, `FOOTER_RULE_INCLUSIVE`, `INFER_COL_CAP_WIDTH`, `YEAR_IS_NOT_HOURS`, `LONE_LETTER_STATUS`, `STATUS_COLUMN`, `WORKED_BEATS_CALENDAR_REMARK`  
Several of these encode measured decisions. See `06-ACCURACY-AND-TESTING.md` before changing any of them.

**Public functions:** `find_anchor()`, `value_right_of()`, `strip_period_from_name()`, `strip_designation_from_name()`, `inline_value()`, `find_bracket_identity()`, `extract_header()`, `summary_band_start()`, `date_column_bottom()`, `grid_bottom()`, `extract_summary()`, `learn_columns()` …and 13 more

### `app/generic_grid.py` — 578 lines

Find the day grid on ANY timesheet, without knowing the client.

**Behaviour flags:** `NUMERIC_CELL_IS_PRESENT`, `NAME_NEAREST_BLOCK`, `CROSS_MONTH_RUN`  
Several of these encode measured decisions. See `06-ACCURACY-AND-TESTING.md` before changing any of them.

**Public functions:** `looks_like_label()`, `trim_trailing_label()`, `find_day_axis()`, `read_row_oriented()`, `read_column_oriented()`, `describe()`, `day_of()`

### `app/form_profiles.py` — 234 lines

Template profiles — one anchor set per form family.

**Public functions:** `detect()`, `get()`

### `app/templates_spec.py` — 125 lines

Per-template field schemas.

**Public functions:** `get()`, `classifier_menu()`, `json_shape()`, `day_fields()`, `summary_fields()`

### `app/assignment.py` — 122 lines

2-D assignment of value boxes to label anchors.

**Public functions:** `pair_cost()`, `assign()`

### `app/ordinal_match.py` — 164 lines

Ordinal (sequence) matching of header labels to their values.

**Public functions:** `order_labels()`, `value_window()`, `candidate_values()`, `group_rows()`, `match()`

### `app/field_typing.py` — 325 lines

Content-based field typing.

**Public functions:** `score_month()`, `is_form_phrase()`, `score_designation()`, `score_code()`, `salvage_code()`, `score_name()`, `split_merged()`, `type_assign()`

### `app/split_fields.py` — 118 lines

Multi-value cell parsing.

**Public functions:** `split_numbers()`, `apply_splits()`, `totals_row_values()`

### `app/vocab.py` — 325 lines

Closed-vocabulary correction.

**Public functions:** `normalise_month()`, `empty()`, `normalise()`, `from_csv()`

### `app/vlm_header.py` — 203 lines

VLM fallback for the header block.

**Behaviour flags:** `VLM_CORROBORATE`  
Several of these encode measured decisions. See `06-ACCURACY-AND-TESTING.md` before changing any of them.

**Public functions:** `available()`, `crop_header()`, `read_header()`, `header_needs_help()`, `corroborated()`

### `app/extract.py` — 386 lines

Extraction: page image -> structured record.

**Public functions:** `parse_json_loose()`, `cache_key()`, `cache_get()`, `cache_put()`, `diff_passes()`, `extract_page()`, `classify()`, `extract()`, `extract_summary()`, `health()`, `classify()`, `extract()` …and 1 more


---

## Stage 3 — post-OCR judgement

### `app/pipeline.py` — 1151 lines

The processing pipeline: one page in, a validated record out.

**Behaviour flags:** `DROP_EMPTY_IMPOSSIBLE_DAYS`, `VLM_NEEDS_SHEET`, `CLEAN_PERIOD_LABEL`, `HALF_HOUR_REPAIR`, `GRID_MULTI_EMPLOYEE`, `GRID_FILL_BLANK_DAYS`, `CLOCK_REPAIR`, `CLOCK_CONSENSUS`, `UNIT_SUFFIX_HOURS`, `SPLIT_CELL_IS_UNREADABLE`, `ORIENTATION_RETRY`, `GRID_BEATS_WEAK_PROFILE`, `UNREAD_ROW_BLOCKS_CLEAN`, `GENERIC_GRID_FALLBACK`, `HIRES_RESCUE`  
Several of these encode measured decisions. See `06-ACCURACY-AND-TESTING.md` before changing any of them.

**Public functions:** `cache_get()`, `cache_put()`, `process_page()`, `apply_roster()`, `normalise_hours()`

### `app/reconcile.py` — 807 lines

Repair the day grid using facts the page already states about itself.

**Behaviour flags:** `SUNDAY_DEFAULT_OFF`, `PERIOD_SOURCE_FIRST`, `SNAP_WEEKLY_OFF`, `EVIDENCE_POSITIVE_ONLY`, `WEEKDAY_WORD_SNAP`, `EMPTY_SUNDAY_IS_OFF`, `STATED_P_CONFIRMS_WORK`, `STATED_WO_DEMOTES_INKED`, `MERGED_OFFSET_FOLLOW`  
Several of these encode measured decisions. See `06-ACCURACY-AND-TESTING.md` before changing any of them.

**Public functions:** `parse_period()`, `infer_period_from_source()`, `infer_period_from_grid()`, `weekday_of()`, `reconcile()`, `trusted()`, `hours_of()`, `evidence()`

### `app/validate.py` — 655 lines

Validation engine.

**Behaviour flags:** `UNCOMPUTABLE_IS_NOT_FAILED`  
Several of these encode measured decisions. See `06-ACCURACY-AND-TESTING.md` before changing any of them.

**Public functions:** `validate()`, `status_for()`, `to_dict()`

### `app/rowconf.py` — 227 lines

Per-row confidence and review flags: the post-OCR evaluation layer.

**Behaviour flags:** `NO_DATE_COLUMN_CAPS_OK`, `CROWDED_CELL_REVIEW`  
Several of these encode measured decisions. See `06-ACCURACY-AND-TESTING.md` before changing any of them.

**Public functions:** `score_row()`, `annotate()`

### `app/clocks.py` — 312 lines

Clock-time reading: grammar repair and sheet consensus for in/out times.

**Public functions:** `parse_clock()`, `repair()`, `fmt()`, `apply_to_days()`

### `app/roster.py` — 143 lines

Employee master roster matching.

**Public functions:** `empty()`, `from_csv()`, `match()`, `suggest()`


---

## Output

### `app/export_designs.py` — 679 lines

Six Excel export designs.

**Public functions:** `design_invoice()`, `design_attendance()`, `design_audit()`, `design_payroll()`, `design_dashboard()`, `design_timesheet()`, `export()`

### `app/export_excel.py` — 161 lines

Excel export.

**Public functions:** `export_batch()`

### `app/cloudcost.py` — 147 lines

Hidden cost page: what this project costs on Google Cloud, this month and last.

**Public functions:** `exact()`, `estimate()`, `snapshot()`


---

**Total: 11036 lines across 26 modules.**


---

## Supporting tools (`source-code/tools/`)

78 scripts. Most were written to answer one specific question during
development and are kept because they document how a number was arrived at
and can be re-run to confirm it. The ones you will actually use day to day
are in the first two groups.


### Protecting accuracy — run these

| Script | What it answers |
|---|---|
| `guard.py` | The floor. Run this before shipping anything that touches accuracy. |
| `e2e_prod_test.py` | End-to-end test of a LIVE deployment, through the real HTTP path. |
| `verify_end_to_end.py` | End-to-end verification of the whole system, in one run. |

### Evaluation harnesses

| Script | What it answers |
|---|---|
| `eval_fast.py` | Same score as eval_100.py, but ~100x faster to re-run after a code change. |
| `eval_fast_v2.py` | Fast harness over the corpus-faithful frozen set (decision log D-007). |
| `eval_isgec.py` | Score the pipeline on the horizontal, multi-employee sheets. |
| `eval_sample50.py` | Score a pipeline run against data/_sample50/truth.json (the 50-page hand-graded sample, D-045).   python too |
| `eval_times.py` | Score in/out clock times through the real upload path. |
| `eval_100.py` | Large-scale accuracy evaluation against the client's own typed Excel. |
| `eval_corpus.py` | Full-corpus evaluation across Delhi, HO and Kolkata. |
| `eval_desig.py` | Score the DESIGNATION field end-to-end, in about a second. |
| `measure_accuracy.py` | End-to-end PIPELINE accuracy — the number that actually matters. |

### Building ground truth

| Script | What it answers |
|---|---|
| `truth.py` | Robust ground-truth extraction from the client's typed Excel files. |
| `isgec_truth.py` | Build ground truth for the horizontal multi-employee sheets from the PDF TEXT LAYER. |
| `sample50_truth.py` | Build data/_sample50/truth.json from the v32 manifest + the hand-grade overrides in grades.md. Truth per rea |
| `build_timeset.py` | Build the in/out clock-time test set from PDF text layers. |
| `build_truth_index.py` | Parse every client Excel once and cache the result. |
| `ground_truth.py` | Hand-read ground truth for the benchmark pages. |
| `ground_truth_eval.py` | Accuracy against the client's OWN typed Excel files. |
| `truth_conflicts.py` | How often does the client's own ground truth contradict itself? |
| `truth_coverage.py` | Compare ground-truth recovery: legacy parser vs tools/truth.py. |
| `retruth_timeset.py` | Recompute clock-time truth for the existing pages, without re-rendering. |

### Reference data builders

| Script | What it answers |
|---|---|
| `build_roster.py` | Build the employee master roster from the client's own Excel files. |
| `extend_roster.py` | Extend the roster with identities from the attendance-grid Excels. |
| `build_designations.py` | Harvest a designation vocabulary from the corpus itself. |
| `harvest_designations.py` | Build the designation vocabulary from the CLIENT'S spreadsheets. |

### Diagnostics — why is this wrong?

| Script | What it answers |
|---|---|
| `diag_days.py` | Diagnose WHERE day-status accuracy is lost. |
| `probe_false_alarms.py` | Which validation rule blocks pages that were read perfectly? |
| `probe_nogrid.py` | Why does the generic detector find no day grid on these pages? |
| `probe_orientation.py` | How many failing pages are simply rotated? |
| `probe_generic_coverage.py` | How many of the failing client folders can the generic grid reader reach? |
| `probe_row_rules.py` | Diagnostic: can the PRINTED horizontal rules define the day-row bands? |
| `probe_ocr.py` | Experiment: can OCR confidence route pages better than ink statistics? |
| `probe_preocr.py` | Stage-1 probe: does a pre-OCR technique change day accuracy on handwriting? |
| `probe_crop_vlm.py` | Experiment: VLM on a CROPPED region instead of a whole page. |
| `probe_crop_grid.py` | Experiment: VLM on the cropped DAY GRID. |
| `verify_hires_rescue.py` | Does the on-demand high-resolution rescue recover the pages it should? |

### Corpus survey and sampling

| Script | What it answers |
|---|---|
| `survey.py` | Survey the client's real data before designing anything further. |
| `inventory_corpus.py` | Count every document and page across the three datasets. |
| `classify_corpus.py` | Classify every PDF page in the corpus into the three processing routes. |
| `route_features.py` | Page-route classifier, v2 — with a labelled validation set. |
| `harvest_handwritten.py` | Find every handwritten page in all three datasets, extract it, keep the OCR. |
| `build_hokol_sample.py` | A random 50-page sample from HO and Kolkata, for hand grading. |
| `freeze_v2.py` | Freeze a corpus-faithful fast set: the clients where the corpus loses. |
| `render_samples.py` | Render representative PDF pages to PNG so they can actually be looked at. |
| `demo_pack.py` | Pick the pages that read best, and stage them as a demo set. |

### Benchmarking and experiments

| Script | What it answers |
|---|---|
| `benchmark_ocr.py` | Comparative OCR benchmark. |
| `grand_experiment.py` | Large-scale, parallel, resumable engine comparison over the real corpus. |
| `sweep_resolution.py` | Does more resolution read HANDWRITING better? |

### Release and packaging

| Script | What it answers |
|---|---|
| `package_release.py` | Assemble the deployable ZIP. |
| `build_tech_doc.py` | Build the full technical documentation as a .docx. |
| `doc_diagrams.py` | Architecture diagrams for the technical documentation. |
| `export_isgec.py` | Re-export the ISGEC horizontal sheets to Excel with the current pipeline. |

### Long-run monitoring

| Script | What it answers |
|---|---|
| `runstate.py` | Live state + log for a long corpus run, so it can be watched while it runs. |
| `runboard.py` | Local dashboard for the corpus accuracy run. |
| `dashboard.py` | Temporary local status dashboard for the v33 end-to-end run.    ./.venv/bin/python tools/dashboard.py   ->   |
| `full_pass_v32.py` | Run EVERY page of all three datasets through the product pipeline (pipeline.process_page: rescue ladder, gen |
| `run_hokol50.py` | Run the 50-page HO/Kolkata sample through the REAL upload path. |

### Other

| Script | What it answers |
|---|---|
| `doc_content_a.py` | Documentation content, part A: orientation and high-level design. |
| `doc_content_b.py` | Documentation content, part B: low-level design, algorithm by algorithm. |
| `doc_content_c.py` | Documentation content, part C: data, accuracy engineering, operations. |
| `doc_content_d.py` | Documentation content, part D: worked example, testing, extension guide. |
| `doc_content_e.py` | Documentation content, part E: foundations primer, from first principles. |
| `doc_content_f.py` | Documentation content, part F: domain reference and decision records. |
| `doc_content_g.py` | Documentation content, part G: appendices and closing (must run LAST). |
| `doc_content_h.py` | Documentation content, part H: the 2026-09-13 revamp addendum (Part XVI). |
| `doc_content_i.py` | Documentation content, part I: Part XVII -- the 50-page sample, v33, and the full corpus run of 20 Sep 2026. |
| `doc_content_j.py` | Documentation content, part J: Part XVIII -- how to use the system, with screenshots of the running applicat |
| `doc_content_k.py` | Documentation content, part K: Part XIX -- the clock times, and three defects found on 6 October 2026. |
| `doc_content_l.py` | Documentation content, part L: Part XX -- what the corpus run taught, the regression it exposed, and the gua |
| `doc_content_perf.py` | Documentation content, part VII: performance, latency and scale. |
| `finalize_report.py` | Fill the revamp report's final corpus rows from data/eval_corpus.json. |
| `inspect_pair.py` | Dump the Excel side of a PDF/Excel pair. |
| `print_sample_page.py` | — |
| `render_sample50_resume.py` | Resume the seeded 50-page sample from a given index (same seed/selection as tools/render_sample50.sh). Pages |
| `scan_timelayer.py` | Find corpus pages whose PDF text layer already contains clock times. |
| `summarize_v33.py` | Summarise the v33 corpus eval (data/eval_corpus.json) and the 9,271-page product pass (data/full_pass_v32.js |

### Shell helpers

- `after_eval_v32.sh` — one-shot sequence used during a specific release run
- `eval_corpus_supervised.sh` — one-shot sequence used during a specific release run
- `finish_v29.sh` — one-shot sequence used during a specific release run
- `finish_v33.sh` — one-shot sequence used during a specific release run
- `release_v29.sh` — one-shot sequence used during a specific release run
- `release_v33.sh` — one-shot sequence used during a specific release run
