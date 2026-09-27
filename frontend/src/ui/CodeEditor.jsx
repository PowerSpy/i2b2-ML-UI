import { useEffect, useRef } from "react";

import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
import { python } from "@codemirror/lang-python";
import { HighlightStyle, indentUnit, syntaxHighlighting } from "@codemirror/language";
import { EditorState } from "@codemirror/state";
import { EditorView, keymap, lineNumbers, placeholder as cmPlaceholder } from "@codemirror/view";
import { tags } from "@lezer/highlight";

/**
 * A Python editor, themed from the app's own tokens.
 *
 * CodeMirror rather than Monaco: ~200 KB gzipped against ~2.5 MB, no worker
 * plumbing, and — the reason that matters here — `EditorView.theme()` takes
 * plain CSS values, so the theme can reference `var(--color-panel-sunk)`
 * directly. `index.css` is the single source of every colour in this app and
 * no component carries a hex value; Monaco's theme API wants literal colours
 * and would have been the first thing to break that rule.
 *
 * Monaco's real advantages — a TypeScript service, go-to-definition across
 * files — are irrelevant for a forty-line function with no imports to resolve.
 */

// Every colour here is a token from index.css. Adding a literal hex to this
// file is the mistake it is built to prevent.
const theme = EditorView.theme(
  {
    "&": {
      color: "var(--color-text-2)",
      backgroundColor: "var(--color-panel-sunk)",
      fontSize: "12.5px",
      border: "1px solid var(--color-border-soft)",
      borderRadius: "var(--radius-row)",
      overflow: "hidden",
    },
    "&.cm-focused": {
      outline: "none",
      borderColor: "var(--color-border-strong)",
    },
    ".cm-scroller": {
      fontFamily: "var(--font-mono)",
      lineHeight: "1.65",
    },
    ".cm-content": { padding: "12px 0", caretColor: "var(--color-accent)" },
    ".cm-gutters": {
      backgroundColor: "transparent",
      color: "var(--color-text-muted)",
      border: "none",
      paddingRight: "6px",
    },
    ".cm-activeLine": { backgroundColor: "var(--color-border-soft)" },
    ".cm-activeLineGutter": {
      backgroundColor: "transparent",
      color: "var(--color-text-3)",
    },
    "&.cm-editor .cm-selectionBackground, ::selection": {
      backgroundColor: "var(--color-border-strong)",
    },
    ".cm-cursor": { borderLeftColor: "var(--color-accent)" },
    ".cm-placeholder": { color: "var(--color-text-muted)" },
  },
  { dark: true },
);

const highlight = HighlightStyle.define([
  { tag: tags.keyword, color: "var(--color-accent)" },
  { tag: tags.controlKeyword, color: "var(--color-accent)" },
  { tag: [tags.string, tags.special(tags.string)], color: "var(--color-positive)" },
  { tag: tags.comment, color: "var(--color-text-muted)", fontStyle: "italic" },
  { tag: [tags.number, tags.bool, tags.null], color: "var(--color-warn)" },
  { tag: tags.function(tags.variableName), color: "var(--color-text)" },
  { tag: tags.definition(tags.variableName), color: "var(--color-text)" },
  { tag: tags.propertyName, color: "var(--color-text-2)" },
  { tag: tags.operator, color: "var(--color-text-3)" },
  { tag: tags.invalid, color: "var(--color-danger)" },
]);

export default function CodeEditor({
  value,
  onChange,
  readOnly = false,
  placeholder = "",
  minHeight = 320,
}) {
  const host = useRef(null);
  const view = useRef(null);
  // Held in a ref so changing the handler does not tear down the editor and
  // take the cursor position with it.
  const emit = useRef(onChange);
  emit.current = onChange;

  useEffect(() => {
    const state = EditorState.create({
      doc: value ?? "",
      extensions: [
        lineNumbers(),
        history(),
        python(),
        // Four spaces, and a literal tab inserts them. Python is the only
        // language here and the container will not accept mixed indentation.
        indentUnit.of("    "),
        // `indentWithTab` last: it overrides the default Tab binding, which
        // moves focus. Losing focus-by-Tab is a real accessibility cost, so
        // Escape-then-Tab still leaves the editor.
        keymap.of([...defaultKeymap, ...historyKeymap, indentWithTab]),
        syntaxHighlighting(highlight),
        theme,
        EditorView.lineWrapping,
        EditorState.readOnly.of(readOnly),
        cmPlaceholder(placeholder),
        EditorView.updateListener.of((u) => {
          if (u.docChanged) emit.current?.(u.state.doc.toString());
        }),
        EditorView.theme({ ".cm-content": { minHeight: `${minHeight}px` } }),
      ],
    });

    view.current = new EditorView({ state, parent: host.current });
    return () => {
      view.current?.destroy();
      view.current = null;
    };
    // Deliberately not re-running on `value`: the editor owns the document
    // once it is mounted. A parent that reassigns `value` on every keystroke
    // would otherwise reset the selection on each one.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [readOnly, placeholder, minHeight]);

  // A value replaced from outside — loading a saved transform, or resetting to
  // the template — is applied as a single transaction rather than by
  // rebuilding, so undo history survives.
  useEffect(() => {
    const v = view.current;
    if (!v) return;
    const current = v.state.doc.toString();
    if (value != null && value !== current) {
      v.dispatch({ changes: { from: 0, to: current.length, insert: value } });
    }
  }, [value]);

  return <div ref={host} />;
}
