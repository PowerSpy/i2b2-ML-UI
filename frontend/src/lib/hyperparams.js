/*
 * Turns the hyperparameter form's raw strings into the override grid the
 * builder expects.
 *
 * Values are wrapped in arrays because they replace entries in a GridSearchCV
 * param grid, not plain keyword arguments — `clf__C: 1` would make the search
 * iterate the number itself rather than try the single value 1.
 *
 * Mirrors _buildHyperparameterOverrides in the reference webclient
 * (CUSTOM_view_ModelBuilder.js) so both UIs send the same shape.
 */

/** Defaults for a model's fields, as the form's initial string values. */
export function defaultValues(fields) {
  return Object.fromEntries(
    fields.map((f) => [f.id, f.default == null ? "" : String(f.default)]),
  );
}

function readField(field, raw) {
  const text = (raw ?? "").trim();
  if (text === "") {
    // Blank leaves the key out entirely, so the model's own default grid for
    // it still applies. It deliberately does not send null for "unlimited":
    // the ETL stores blobs as Python reprs and repairs them into JSON by
    // swapping quote characters, so a None survives to the parser and breaks
    // the whole blob — the build then fails with "Expecting value".
    if (field.allow_blank) return { ok: true, value: null };
    return { ok: false, error: `${field.label} is required` };
  }
  const num = Number(text);
  if (!Number.isFinite(num)) {
    return { ok: false, error: `${field.label} must be a number` };
  }
  if (num < field.min || num > field.max) {
    return {
      ok: false,
      error: `${field.label} must be between ${field.min} and ${field.max}`,
    };
  }
  return { ok: true, value: num };
}

/**
 * @returns {{ok: true, overrides: object} | {ok: false, errors: string[]}}
 */
export function buildOverrides(modelKey, fields, values) {
  const errors = [];
  const read = {};

  for (const field of fields) {
    const result = readField(field, values[field.id]);
    if (result.ok) read[field.id] = result.value;
    else errors.push(result.error);
  }
  if (errors.length) return { ok: false, errors };

  const overrides = {};

  // The two ANN layer fields have no grid key of their own — they describe one
  // hidden_layer_sizes tuple between them. The extra nesting is deliberate:
  // the grid value is a list of candidate tuples, and here that list has one
  // entry.
  if (modelKey === "ann") {
    const layers =
      read.layer_2 > 0 ? [read.layer_1, read.layer_2] : [read.layer_1];
    overrides["clf__hidden_layer_sizes"] = [layers];
  }

  for (const field of fields) {
    if (!field.grid_key) continue;
    const value = read[field.id];
    // null only ever comes from a blank allow_blank field, which means
    // "no override" — see readField.
    if (value === null) continue;
    overrides[field.grid_key] = [value];
  }

  return { ok: true, overrides };
}
