# Container-side changes

Everything in this folder lives inside the `i2b2-etl` container, not in this
app. It is here because the container has **no bind mounts** — these files sit
in its writable layer, survive `docker restart`, and are lost on `docker rm`.
Without a copy in the repo there is no record of what the running container
actually contains.

```
docker-changes/
├── apply.sh                        reinstall everything + verify
├── apply_build_model_ml.py.orig    the stock file, for reference
├── apply_build_model_ml.patch      what changed, as a unified diff
└── i2b2_cdi/ML/                    mirrors the path inside the container
    ├── apply_build_model_ml.py     patched
    ├── model_registry.py           new — the nine model definitions
    └── model_plots.py              new — diagnostic plot generation
```

`model_registry.py` and `model_plots.py` are copied unchanged from
[i2b2-ETL-ML-Models](https://github.com/PowerSpy/i2b2-ETL-ML-Models). The
patched `apply_build_model_ml.py` is not — see below.

## Reinstalling

```bash
./docker-changes/apply.sh          # CONTAINER=other-name to target another
```

## What changed in apply_build_model_ml.py

The upstream repo ships two patch scripts. `patch_add_model_registry.py`
applied cleanly. `patch_add_model_plots.py` did not, and could not — the
reasons are worth recording because they are not obvious.

**1. Model selection (from `patch_add_model_registry.py`, then edited)**

The stock file hardcodes logistic regression. The patch replaces that with a
registry lookup. Two changes on top of what the patch produces:

- The patch emits `build_model(model_type)`, dropping the caller's
  hyperparameters even though `build_model` accepts them and its own docstring
  documents passing them. Now `build_model(model_type, blob.get("hyperparameters", {}))`.
- Line 261 hardcoded `scores.append(["LogisticRegression", ...])` and the
  summary loop below it used `name` as its loop variable, clobbering the real
  model name. Both fixed; the loop variable is now `score_name`.

**2. Recording what actually trained**

`build_model` falls back to logistic regression for an unrecognised
`model_type` **without raising**. The requested algorithm is therefore not
evidence of what was built. Three fields are now saved with the metrics:

```python
metrics['model_type'] = model_type          # what was asked for
metrics['model_name'] = name                # the registry's display name
metrics['clf_type']   = type(clf).__name__  # the class actually fitted
```

The UI shows `clf_type` next to the model name and flags a mismatch.

**3. Diagnostic plots (hand-written, not `patch_add_model_plots.py`)**

That script fails on this codebase twice over:

- Its anchor search finds the first `}` after `build_time_sec`, which is the
  `f"{name:18s} → {score:.4f}"` f-string **inside the summary loop**. Inserting
  a 4-space block there orphans the next line; the script's own `compile()`
  guard catches it and aborts with exit 3. So it never applies.
- More importantly, it writes plots into `blob`. `blob` is the *input*
  `concept_blob` and is never written back — what reaches the database is
  `save_model_in_concept_blob(ml_code, params, metrics, ...)`, which builds a
  fresh dict from `metrics` alone. Even placed correctly, the plots would be
  silently discarded.

The block here is inserted immediately before `save_model_in_concept_blob` and
writes into `metrics`. It resolves feature importances from
`prediction_pipeline` and `selected_features` (the classifier was fitted on
exactly those columns, so no selector mask is needed) and swallows its own
failures — the model is trained and scored by that point, and a plotting
problem must not cost the caller that work.

Produces `plot_confusion_matrix`, `plot_roc`, `plot_pr`, `plot_calibration`,
`plot_feature_importance` as base64 PNGs, plus `confusion_tp/fp/tn/fn` counts.
Feature importance is absent for KNN, naive Bayes and the dummy baseline, which
expose neither `coef_` nor `feature_importances_`.

> The plot counts are computed at the 0.5 cutoff the stored model predicts at,
> while the headline metrics use the F1-optimal threshold. The two genuinely
> disagree — on one verified build, 10 false positives versus 8. The API keeps
> them in separate fields for this reason.

## Environment notes

Neither of these is a file, so neither is in this folder — but the app does not
work without them.

**The API publishes no ports.** EC2 ran `-p 5000:5000`; the migrated container
exposes 5000 and publishes nothing. A socat sidecar bridges it, and
`config.yaml`'s `etl_url: http://127.0.0.1:5001` depends on it:

```bash
docker run -d --name i2b2-etl-proxy --network i2b2-net \
  --restart unless-stopped -p 5001:5000 \
  alpine/socat TCP-LISTEN:5000,fork,reuseaddr TCP:i2b2-etl:5000
```

**Auth is session-based, not password-based.** `AuthConfig.getUser` looks for a
live row in `i2b2pm.pm_user_session` and only falls back to the i2b2 PM SOAP
service when it finds none. That service is `i2b2-wildfly`, which is not
running here, so every correct password returns 401. The working credential is
a session id inserted directly into that table — it is in `config.yaml`, which
is gitignored. To reissue:

```sql
INSERT INTO i2b2pm.pm_user_session
  (user_id, session_id, entry_date, expired_date, change_date, changeby_char, status_cd)
VALUES ('demo', '<20-char id>', CURRENT_TIMESTAMP - INTERVAL '1 hour',
        CURRENT_TIMESTAMP + INTERVAL '365 days', CURRENT_TIMESTAMP, 'i2b2-ml-ui', 'A');
```

Then set `etl_user: 'Demo\demo'` and `etl_password: '<that id>'`.

**jobWatcher starts itself.** It is in the container's own start command, about
75 seconds after boot. Starting it by hand adds a second daemon racing the
first for queued jobs.
