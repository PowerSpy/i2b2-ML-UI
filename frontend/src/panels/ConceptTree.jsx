import { plural } from "../lib/format.js";
import { under } from "../lib/projects.js";
import Callout, { Empty } from "../ui/Callout.jsx";
import { Pill } from "../ui/Status.jsx";
import { Mono, Note, SectionLabel } from "../ui/Text.jsx";

/**
 * The project's concept subtree, with the role each path plays.
 *
 * Roles are not stored on a concept — they come from the models. A path is
 * marked "features" because some model's data_paths claim it and "outcome"
 * because some model's label_paths do, which is the only sense in which a
 * concept has a role at all. A path can carry both, since the label subtree is
 * usually nested inside the data subtree.
 */
export default function ConceptTree({ project }) {
  const tree = buildTree(project.concepts, project.root);
  const unused = unclaimed(project);

  return (
    <div className="space-y-4">
      <div>
        <SectionLabel className="mb-2">Concept tree</SectionLabel>
        <Note>
          Pick a subtree, not individual columns. Feature and label paths must
          not overlap unless the label paths claim every outcome concept inside.
        </Note>
      </div>

      {project.concepts.length === 0 ? (
        <Empty>This subtree has no concepts.</Empty>
      ) : (
        <ul className="space-y-0.5">
          <TreeNode node={tree} roles={project.roles} depth={0} />
        </ul>
      )}

      {unused.length > 0 && (
        <Callout tone="warn" title={`${unused.length} ${plural(unused.length, "concept")} unused`}>
          <Mono className="text-text-2">
            {unused.slice(0, 6).map((c) => c.code).join(", ")}
            {unused.length > 6 && `, +${unused.length - 6} more`}
          </Mono>{" "}
          {plural(unused.length, "is", "are")} declared in this subtree but no
          model&apos;s data or label paths claim {plural(unused.length, "it", "them")}.
          Nothing reads {plural(unused.length, "it", "them")} at training time.
        </Callout>
      )}

      <p className="border-t border-border-soft pt-3 text-[11px] leading-relaxed text-text-muted">
        Per-concept fill rate is not available — no endpoint reports how many
        patients have a value for a given concept, so sparsity cannot be shown
        here.
      </p>
    </div>
  );
}

function TreeNode({ node, roles, depth }) {
  const children = [...node.children.values()].sort((a, b) =>
    a.name.localeCompare(b.name),
  );

  return (
    <>
      {node.path && (
        <li>
          <div
            className="flex items-center justify-between gap-2 rounded-row px-2 py-1.5 hover:bg-panel-sunk"
            style={{ paddingLeft: 8 + depth * 12 }}
          >
            <Mono
              className={`min-w-0 truncate text-[12px] ${
                node.concept ? "text-text-2" : "text-text"
              }`}
              title={node.path}
            >
              {depth === 0 ? node.path : node.name}
            </Mono>
            <span className="flex shrink-0 gap-1">
              {roles.feature.has(node.path) && <Pill tone="accent">features</Pill>}
              {roles.label.has(node.path) && <Pill tone="warn">outcome</Pill>}
              {node.concept?.type && !roles.feature.has(node.path) && !roles.label.has(node.path) && (
                <span className="font-mono text-[10px] text-text-muted">
                  {node.concept.type}
                </span>
              )}
            </span>
          </div>
        </li>
      )}
      {children.map((child) => (
        <TreeNode
          key={child.path}
          node={child}
          roles={roles}
          depth={node.path ? depth + 1 : depth}
        />
      ))}
    </>
  );
}

/** Nested map of path segments, with the concept attached at its leaf. */
function buildTree(concepts, root) {
  const tree = { name: "", path: "", children: new Map(), concept: null };

  for (const c of concepts) {
    const parts = c.path.replace(/^\/+/, "").split("/");
    let node = tree;
    let path = "";
    for (const part of parts) {
      path += `/${part}`;
      if (!node.children.has(part)) {
        node.children.set(part, {
          name: part,
          path,
          children: new Map(),
          concept: null,
        });
      }
      node = node.children.get(part);
    }
    node.concept = c;
  }

  // Collapse to the project root so the rail starts at /HeartDisease rather
  // than at an empty node above it.
  const rootName = root.replace(/^\//, "");
  return tree.children.get(rootName) ?? tree;
}

/** Concepts no model's paths cover. */
function unclaimed(project) {
  const claimed = [...project.roles.feature, ...project.roles.label];
  if (!claimed.length) return [];
  return project.concepts.filter((c) => !claimed.some((p) => under(c.path, p)));
}
