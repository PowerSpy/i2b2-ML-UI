# Clinical UX Review

A review of what this UI does badly, what it cannot do at all, and what it
should grow next — written from the perspective of a clinical researcher using
it to build and judge a predictive model, not from the perspective of the code.

Based on a full read of `app/` and `frontend/src/` plus live testing against a
running `i2b2-etl` / `i2b2-pg` stack on 2026-09-19, including real model builds
on both loaded datasets.

**Scope note.** Model selection, hyperparameter choice, diagnostic plots and the
estimator-identity readout landed in PR #1 and are on `main`. Items resolved
since are marked *(fixed)*. Everything else is outstanding.

**This document is corrected in place.** Findings were written from a code read
plus live testing, and one of them (1.1) did not survive being tested properly.
Corrections are marked with a dated note rather than quietly edited away, so the
original claim and the evidence against it both stay visible.

---

## How to read this

Severity is about **clinical consequence**, not engineering effort:

| | |
|---|---|
| **Misleading** | The UI can state something false confidently. A user acting on it reaches a wrong conclusion and has no signal anything went wrong. |
| **Blocking** | A reasonable task is impossible without leaving the UI. |
| **Friction** | Possible but tedious, error-prone, or requires remembering things the UI could hold. |

Misleading beats everything. A tool that is merely incomplete gets worked
around. A tool that is confidently wrong gets believed.

---

## 1. Where the UI can mislead — fix first

### 1.1 Outcome concepts can become features — Friction *(fixed)*

> **Corrected 2026-09-19.** This item was first published as *"Nothing prevents
> label leakage — Misleading"*, claiming that overlapping data and label paths
> silently produce a model with ROC-AUC near 1.0. **That does not happen**, and
> the correction matters more than the original claim: the item was ranked the
> most dangerous behaviour in the application on the strength of a leak that was
> never verified. What follows is what testing actually showed.

The build engine resolves both path sets to concept codes and subtracts the
label codes from the data codes
(`build_model_ML_helper.create_data_label_codes`). Overlap is therefore already
handled. Measured on the heart dataset:

| data paths | label paths | result |
| --- | --- | --- |
| `/HeartDisease/HeartDisease_ehr1` | `/HeartDisease/label` | ROC-AUC 0.9301, 7 features |
| `/HeartDisease` (contains the label subtree) | `/HeartDisease/label` | ROC-AUC 0.9301, same 7 features |

Identical. There is no leak to guard against.

The real defect is narrower. When the data paths pull in an **assertion**
concept that the label paths do *not* claim, that concept becomes a feature.
Assertions carry no value, so the column arrives empty and the run dies deep
inside the pipeline:

```
All the 45 fits failed ...
ValueError: The target "y" needs to have more than 1 class. Got 1 class instead
```

That arrives after several minutes of training and names neither the concept
nor the path responsible. Reproduced with `/HeartDisease` as data and
`/HeartDisease/label/target` as label, which leaves `positive` and `negative` in
the feature set. Empty `label_paths` does the same thing and was accepted.

So the severity was wrong in both directions: it does not mislead, but it does
waste a training run on an error nobody can act on.

**Fixed** on `fix/stray-assertion-features`: save is refused immediately, naming
the offending concepts, with the same rule mirrored in `ModelForm` so it appears
while the paths are being picked. Disjoint paths and fully-covered label
subtrees still save.

**Still open:** there is no warning on a suspiciously high ROC-AUC. Leakage
through a *numeric* feature that encodes the outcome — a derived risk score
loaded as a float, say — remains undetectable by path rules, because the engine
excludes by concept code and such a column is a legitimate feature as far as it
can tell. A "this looks too good" flag above ~0.98, next to the feature list,
would catch what path validation structurally cannot.

### 1.2 `/ML` can be chosen as a feature source — Misleading

`PathPicker` offers every prefix in the tree, including `/ML` and `/ML/<dataset>`
— the subtree where trained models are stored. Selecting it feeds serialized
model blobs in as features. The app's own help text says nothing under `/ML`
belongs in either field, which is guidance, not a guardrail.

**Fix:** exclude the configured `ml_root` from `PathPicker` entirely.

### 1.3 "Built" survives deletion of the data — Misleading

`is_built` is a `LIKE '%serialized_model%'` test against the concept blob. The
blob survives *wipe all facts*. So after clearing the warehouse, every model
still reads **(built)** in the picker, step 5 stays unblocked, and a model whose
every feature is gone can be applied to score patients. The only hint is a
warning inside the predictions panel, which appears after the fact.

**Fix:** cross-check `feature_column_codes` against live facts and mark the
model stale in the picker itself.

### 1.4 Job success can be reported for a job that never ran — Misleading

The queue POST returns no job id, so `JobRunner` submits and then reads the
newest row from `/jobs?limit=1`. Two separate round trips. If the row has not
been inserted yet, it reads the *previous* job — which may already be
`COMPLETED` — and reports instant success. If another job is queued in between,
it tracks the wrong one.

Separately, `busy` clears when the POST returns rather than when the job
finishes, so the Build button re-enables immediately. Clicking twice queues a
second build, and because submitting a build deletes every existing fact under
the target path first, the second run destroys the first run's output
mid-flight.

**Fix:** have the queue endpoint return the job id. Failing that, keep the
button disabled until the polled job reaches a terminal state.

### 1.5 Same-named cohorts silently merge at training time — Misleading

The patient-set lookup resolves a cohort *name* to **every** matching
`result_instance_id` and uses all of them. Two cohorts called `positive_heart`
do not compete — they union.

This is not hypothetical. On the review instance, `positive_heart` existed 15
times across several data loads; training on it drew **489 distinct patients**
against a 297-patient dataset, including patient numbers left over from earlier
loads. Every model built that way reported metrics computed on a population
that did not correspond to the data.

The UI blocks creating a duplicate *through this app*, but cohorts made in the
i2b2 webclient or via the API appear in the list as identical entries, and the
pickers submit by name.

**Fix:** detect duplicate names on load and refuse to use them until resolved;
show the resolved patient count at model-definition time, not just the recorded
one.

### 1.6 Pickers show recorded size, not live size — Misleading

`CohortsPanel` correctly computes a live count and flags stale cohorts. The
pickers in steps 3 and 5 display the recorded `size` with no staleness marker —
so the warning lives on one screen and the misleading number on the screens
where the decision is actually made.

### 1.7 "Wipe all concepts" destroys every model, and says otherwise — Misleading

Models are concepts. `delete-concepts` truncates `concept_dimension`, taking
every model config and every trained blob with it. The danger-zone copy
reassures that *"Cohorts survive both"* and never mentions models at all,
implying they do too.

**Fix:** name the consequence in the confirmation, with a count of models about
to be destroyed.

### 1.8 A misnamed CSV loads nothing and reports success — Misleading

The loader globs by `*concepts.csv` / `*facts.csv` suffix and reports `ok` on
exit code 0. A file named `patients.csv` loads zero rows, returns success, and
triggers a refresh that shows unchanged counts. The caveat exists only as prose
inside a collapsed help panel.

**Fix:** report rows actually ingested and fail loudly on zero.

---

## 2. Cannot be done in the UI at all

| Missing | Consequence |
|---|---|
| **Delete one model** *(fixed)* | `DELETE /api/ml-concepts/{code}` now wraps the ETL's own per-concept delete, with the result read back because that endpoint answers 200 either way. Originally: The only removal path is *wipe all concepts*, which destroys every model and every loaded concept. Clearing test models currently requires going around the app to the ETL API. |
| **View a saved model's config** *(fixed)* | The model page shows cohorts, feature and label paths, algorithm, estimator class, test size, seed and hyperparameters. Originally: the config endpoint was called once and all but `label_paths` is discarded. A model's cohorts, feature paths, algorithm and hyperparameters are invisible after saving. |
| **Edit a model** *(fixed)* | The define step loads a model's stored config back into the form, including its hyperparameter grid, and says what a re-save replaces before the write rather than after. Originally: no load-into-form. Changing one hyperparameter means retyping code, description, both cohort sets, both path sets and the algorithm from memory. Re-saving overwrites the config outright; the "no history is kept" notice is returned *after* the write, as a receipt rather than a confirmation. |
| **Export predictions** *(fixed)* | The panel asks for the whole set and offers a CSV download. Originally: at most 100 patient numbers as comma-joined text. No pagination, no CSV. A 5,000-patient result set is not retrievable. |
| **See job history** *(fixed)* | The job queue rail lists the last 20 with status, age and the first line of any stack trace. Originally: the jobs endpoint supports 20 rows; the UI uses it only to find the newest id. A failed build from ten minutes ago is unreachable. |
| **Read the watcher log** *(fixed)* | A collapsible log panel on Data health calls it. Originally: `/watcher/log` existed and was never called. When a job sits at PENDING, the one artifact that explains why cannot be opened. |
| **Recover a stranded job** *(fixed)* | A PROCESSING row offers *reset to pending*, with a warning about resetting a job that is genuinely running. Originally: `/jobs/{id}/reset` existed and was never called. A job left PROCESSING by a killed watcher is permanently stuck from the UI. |
| **Stop or restart the watcher** *(not fixed — no endpoint)* | Start only; nothing can stop one. The UI now reports "no watcher" rather than "watcher stopped", because the probe cannot tell a stopped daemon from a stopped container. Originally: The banner can detect multiple watchers racing for the same queue and tell the user about it, while offering no way to fix it. |

---

## 3. What to build next, clinically

### 3.1 Project / study folders *(fixed)*

The strongest structural gap. Every model lands at a hardcoded
`/ML/Diagnosis/<code>` path the user never sees or chooses. Two unrelated
studies share one flat namespace, distinguishable only by naming discipline in
the code field.

A project should be a first-class object: a named container holding its own
cohorts, models, and loaded datasets, with the model list scoped to it. This
also gives a natural home for the provenance and comparison features below, and
makes "delete this study" a safe operation instead of a global wipe.

### 3.2 Model provenance *(fixed, minus timestamps)*

Nothing records how a model came to exist. After the fact there is no way to
answer: which cohorts trained this, how many patients, which features survived
selection, when was it built, against which data load, by whom.

Most of this is already in the blob and simply not surfaced. A model card
showing config, data snapshot, metrics and plots in one exportable view would
make results reportable and reproducible — which is the difference between a
demo and something usable in a study.

### 3.3 Model comparison *(fixed)*

The reference webclient builds several algorithms in one submit and presents a
metrics table, a grouped bar chart and CSV export. This UI trains one model at a
time and shows one model's metrics.

"Which algorithm performs best on my cohort" is the central question a
researcher brings to this tool, and answering it currently means building
models one by one and comparing numbers by hand across screens.

### 3.4 Operating-point selection *(blocked — needs container changes)*

Blocked without container changes: per-patient probabilities are not stored
anywhere, so no threshold slider here could be honest. The model page shows the
confusion matrix at both thresholds side by side, which is the whole of what is
recorded.

Metrics are reported at the F1-optimal threshold while the stored model predicts
at 0.5. The UI states this in a footnote, and the two disagree materially — on
one verified build, 10 false positives versus 8 for the same model.

Clinically, F1 is rarely the right operating point. Screening wants
sensitivity; a costly confirmatory workup wants specificity. The user should be
able to move the threshold, see the confusion matrix and PPV/NPV update, and
have the chosen point saved with the model so prediction honours it.

### 3.5 Subgroup performance *(blocked — needs container changes)*

Blocked without container changes: the build records one set of metrics over
the whole held-out split and no endpoint re-scores a slice. The model page marks
the panel as not reported rather than leaving it out.

A model can look strong overall and fail badly in a subgroup. The tool reports
only pooled metrics, so there is no way to notice. Per-stratum performance
(sex, age band, or any chosen assertion concept) would surface it.

### 3.6 Data quality panel *(fixed)*

Verification is currently two numbers: total facts and total concepts. It
cannot distinguish a healthy warehouse from a badly polluted one.

On the review instance, 12,549 of 31,912 fact rows were exact duplicates (same
patient, concept, date, value) from repeated loads, and the heart dataset had
been loaded several times over with fresh patient numbers each time. Nothing in
the UI indicated this. A panel showing duplicate rows, per-concept fact counts,
patients per dataset, and concept codes colliding across datasets would have
made it obvious.

### 3.7 Cohort definition transparency *(fixed, as far as the data allows)*

A cohort is stored only as a name and a patient count. The concept it was built
from is not retained, so an unfamiliar cohort cannot be interpreted or rebuilt.

The cohorts table now carries a **built from** column, filled from the query
master's `generated_sql`. It is blank for every set this app created, and that
is deliberate: those go through the ETL's test helper, which writes a fixed
`\i2b2\Diagnoses\ICD10\E11\` item_key into every query it makes. All three
heart cohorts on the review instance carry it, so surfacing it would label them
Type 2 Diabetes. The endpoint detects the placeholder and reports *not
recorded* instead. Recording the real concept needs a change to how the app
creates patient sets.

---

## 4. Environment constraints worth knowing

These are not UI defects, but they shape what the UI can promise.

- **Container changes are not persistent.** `i2b2-etl` has no bind mounts, so
  the model registry and plotting code live in its writable layer. They survive
  `docker restart` and are lost on `docker rm`. See `docker-changes/` on the
  `ml-models-additions` branch.
- **The ETL API is not reachable from the host on its own.** The container
  publishes no ports; a socat sidecar bridges it.
- **Authentication is session-based, not password-based.** The ETL checks for a
  live row in `pm_user_session` and otherwise calls an i2b2 PM SOAP service that
  is not running here, so correct passwords return 401.
- **Missing-value handling is not installed.** The data-cleaning patches from
  `i2b2-ETL-ML-Models` have not been applied, so the loader rejects any `?`,
  `NA`, `null` or empty numeric cell outright. Clean CSVs load and train
  normally — verified end to end on a second dataset — but real-world data with
  gaps will silently lose rows. Applying those two patches is a prerequisite for
  onboarding new datasets.
- **Concept codes are global.** Two datasets already share the codes `age` and
  `label`. Training stays correct because facts are filtered by patient set and
  each load mints distinct patient numbers, but the tree becomes ambiguous and a
  cohort built from a shared code would span datasets. New datasets should use
  codes unique to them.

---

## 5. Engineering debt

Real but not urgent — measured sub-second across all endpoints on the review
instance. Worth addressing before data volume grows.

- **Cohort sizing is N+1**, and each cohort costs two container round trips.
  Re-runs on every refresh.
- **The metrics panel transfers the entire blob** — serialized model plus five
  base64 plot images, several hundred KB — to read six floating-point numbers.
  Trimming happens after the transfer, not before.
- **The job poller has no backoff and no timeout.** If a job id falls outside
  the 20-row window it polls forever, showing `SUBMITTED` with no explanation.
- **Poll errors are discarded.** The hook exposes an error that the component
  does not read, so a backend outage looks like a job that stopped progressing.
- **Delete endpoints discard stdout and stderr**, then the UI advises checking
  backend logs that were thrown away.
- **Every refresh refetches everything**, including the full concept tree, on
  any change anywhere.

---

## Suggested order

1. **Section 1** — the misleading behaviours, particularly the job race (1.4)
   and the surviving "built" flag (1.3). Cheap to fix, and they are the ones
   that produce confidently wrong answers. (1.1 is done, and turned out not to
   be one of them — see the correction there.)
2. **Delete-one-model and view-config** from section 2 — small, and they remove
   the two most common reasons to bypass the UI.
3. **Data-cleaning patches** from section 4 — the prerequisite for any new
   dataset.
4. **Model comparison** (3.3) and **project folders** (3.1) — the features that
   change what the tool is for.
5. Everything else.
