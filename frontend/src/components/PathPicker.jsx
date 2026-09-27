import { useState } from "react";

import { under } from "../lib/projects.js";
import { Mono } from "../ui/Text.jsx";

const FILTER_AT = 12;

/**
 * Collapsible tree over concept path prefixes. Each selection becomes a SQL
 * LIKE, so picking a folder already covers everything beneath it — those rows
 * show as included rather than as separately selectable.
 */
export default function PathPicker({ label, tree, values, onChange, hint, id }) {
  const [open, setOpen] = useState(() => initialOpen(tree, values));
  const [filter, setFilter] = useState("");

  function toggle(p) {
    onChange(values.includes(p) ? values.filter((v) => v !== p) : [...values, p]);
  }

  function flip(p) {
    setOpen((prev) => {
      const next = new Set(prev);
      next.has(p) ? next.delete(p) : next.add(p);
      return next;
    });
  }

  const roots = buildTree(tree);
  const needle = filter.trim().toLowerCase();
  const visible = needle ? matching(tree, needle) : null;

  return (
    <div>
      {label && (
        <p className="mb-1.5 text-[12px] text-text-3" id={id}>
          {label}
        </p>
      )}
      {tree.length === 0 ? (
        <p className="text-[12px] text-text-muted">no concept paths loaded</p>
      ) : (
        <div className="space-y-2">
          {values.length > 0 && (
            <ul className="flex flex-wrap gap-2">
              {values.map((p) => (
                <li key={p}>
                  <button
                    type="button"
                    onClick={() => toggle(p)}
                    aria-label={`remove ${p}`}
                    className="min-h-[44px] rounded-btn border border-accent bg-accent/10 px-3 text-[12px] text-text transition-colors hover:border-danger"
                  >
                    <Mono>{p}</Mono>
                    <span aria-hidden="true" className="ml-2 text-text-muted">
                      ×
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {tree.length > FILTER_AT && (
            <input
              type="search"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="filter paths"
              aria-label={label ? `filter ${label}` : "filter paths"}
              className="min-h-[44px] w-full rounded-btn border border-border-strong bg-panel-sunk px-3 font-mono text-[13px] text-text placeholder:text-text-muted"
            />
          )}
          <ul
            className="max-h-80 overflow-y-auto rounded-btn border border-border-strong bg-panel-sunk py-1"
            role="tree"
            aria-labelledby={id}
            aria-multiselectable="true"
          >
            {roots.map((node) => (
              <Node
                key={node.path}
                node={node}
                depth={0}
                values={values}
                // A filter shows every match with its ancestors, all expanded.
                isOpen={(p) => (visible ? true : open.has(p))}
                isVisible={(p) => !visible || visible.has(p)}
                onToggle={toggle}
                onFlip={flip}
              />
            ))}
            {visible && visible.size === 0 && (
              <li className="px-3 py-2 text-[12px] text-text-muted">no path matches</li>
            )}
          </ul>
        </div>
      )}
      {hint && <p className="mt-2 text-[12px] leading-relaxed text-text-muted">{hint}</p>}
    </div>
  );
}

function Node({ node, depth, values, isOpen, isVisible, onToggle, onFlip }) {
  if (!isVisible(node.path)) return null;

  const on = values.includes(node.path);
  // Covered by a selected ancestor: the LIKE already reaches it.
  const covered = !on && values.some((v) => v !== node.path && under(node.path, v));
  const expanded = node.children.length > 0 && isOpen(node.path);

  return (
    <li role="treeitem" aria-selected={on} aria-expanded={node.children.length ? expanded : undefined}>
      <div className="flex items-center" style={{ paddingLeft: 4 + depth * 16 }}>
        {node.children.length > 0 ? (
          <button
            type="button"
            onClick={() => onFlip(node.path)}
            aria-label={`${expanded ? "collapse" : "expand"} ${node.path}`}
            className="flex min-h-[44px] w-8 shrink-0 items-center justify-center text-text-muted hover:text-text"
          >
            <span aria-hidden="true" className={`transition-transform ${expanded ? "rotate-90" : ""}`}>
              ▸
            </span>
          </button>
        ) : (
          <span className="w-8 shrink-0" />
        )}
        <button
          type="button"
          aria-pressed={on}
          disabled={covered}
          onClick={() => onToggle(node.path)}
          title={covered ? "already included by a selected parent folder" : node.path}
          className={`flex min-h-[44px] min-w-0 flex-1 items-center gap-2.5 rounded-btn px-2 text-left text-[12px] transition-colors ${
            on
              ? "bg-accent/10 text-text"
              : covered
                ? "text-text-3"
                : "text-text-2 hover:bg-panel hover:text-text"
          }`}
        >
          <span
            aria-hidden="true"
            className={`flex size-4 shrink-0 items-center justify-center rounded-sm border text-[10px] ${
              on
                ? "border-accent bg-accent text-panel"
                : covered
                  ? "border-accent/50 bg-accent/30 text-panel"
                  : "border-border-strong"
            }`}
          >
            {(on || covered) && "✓"}
          </span>
          <Mono className="min-w-0 truncate">{depth === 0 ? node.path : node.name}</Mono>
          {covered && <span className="shrink-0 text-[11px] text-text-muted">included</span>}
        </button>
      </div>
      {expanded && (
        <ul role="group">
          {node.children.map((child) => (
            <Node
              key={child.path}
              node={child}
              depth={depth + 1}
              values={values}
              isOpen={isOpen}
              isVisible={isVisible}
              onToggle={onToggle}
              onFlip={onFlip}
            />
          ))}
        </ul>
      )}
    </li>
  );
}

/** Nests the flat prefix list; any prefix without a listed parent is a root. */
function buildTree(prefixes) {
  const nodes = new Map();
  for (const p of [...prefixes].sort()) {
    nodes.set(p, { path: p, name: p.slice(p.lastIndexOf("/") + 1), children: [] });
  }
  const roots = [];
  for (const node of nodes.values()) {
    const parent = nodes.get(node.path.slice(0, node.path.lastIndexOf("/")));
    (parent ? parent.children : roots).push(node);
  }
  return roots;
}

/** Roots start open, as do the ancestors of anything already selected. */
function initialOpen(prefixes, values) {
  const open = new Set(prefixes.filter((p) => p.lastIndexOf("/") === 0));
  for (const v of values) {
    for (const p of prefixes) if (p !== v && under(v, p)) open.add(p);
  }
  return open;
}

/** Paths containing the needle, plus their ancestors so the match is reachable. */
function matching(prefixes, needle) {
  const hits = prefixes.filter((p) => p.toLowerCase().includes(needle));
  const keep = new Set();
  for (const h of hits) {
    for (const p of prefixes) if (p === h || under(h, p)) keep.add(p);
  }
  return keep;
}
