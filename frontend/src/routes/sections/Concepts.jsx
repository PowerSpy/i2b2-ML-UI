import { useMemo, useState } from "react";

import { count } from "../../lib/format.js";
import { href, Link } from "../../lib/router.jsx";
import { rootOf } from "../../lib/projects.js";
import { useWorkspace } from "../../lib/workspace.jsx";
import { Card, CardHeader } from "../../ui/Card.jsx";
import { Empty, Failed } from "../../ui/Callout.jsx";
import { Pill } from "../../ui/Status.jsx";
import { Table, Td, Th } from "../../ui/Table.jsx";
import { Heading, Mono, Note, Num } from "../../ui/Text.jsx";

const FIELD =
  "min-h-[44px] w-72 rounded-btn border border-border-strong bg-panel-sunk px-3 text-[13px] text-text placeholder:text-text-muted";

/**
 * Every concept in the warehouse, including the models under /ML — this is the
 * one place that shows the raw table rather than a project's slice of it.
 */
export default function Concepts() {
  const { concepts, conceptsResult, loading, projects } = useWorkspace();
  const [query, setQuery] = useState("");

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return concepts;
    return concepts.filter(
      (c) =>
        c.code.toLowerCase().includes(q) ||
        c.path.toLowerCase().includes(q) ||
        (c.name ?? "").toLowerCase().includes(q),
    );
  }, [concepts, query]);

  const projectFor = (path) => projects.find((p) => p.root === rootOf(path));

  return (
    <div className="space-y-6">
      <div>
        <Heading level={1} className="text-[24px] leading-tight">
          Concepts
        </Heading>
        <Note className="mt-2">
          One row per declared column, straight from{" "}
          <Mono>concept_dimension</Mono>. The path decides which project a
          concept belongs to; the type decides whether it can be a feature.
        </Note>
      </div>

      <Card>
        <CardHeader
          title={
            <>
              <Num>{count(loading ? undefined : rows.length)}</Num>
              {!loading && rows.length !== concepts.length && (
                <span className="text-text-muted">
                  {" "}
                  of <Num>{count(concepts.length)}</Num>
                </span>
              )}{" "}
              concepts
            </>
          }
        >
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="filter by code, path or name"
            className={FIELD}
            aria-label="Filter concepts"
          />
        </CardHeader>

        <div className="mt-4">
          {conceptsResult?.error ? (
            <Failed what="the concept list" error={conceptsResult.error} />
          ) : loading ? (
            <Empty>Reading the warehouse…</Empty>
          ) : rows.length === 0 ? (
            <Empty>
              {concepts.length === 0
                ? "No concepts loaded. A concepts CSV declares them."
                : "No concept matches that filter."}
            </Empty>
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>code</Th>
                  <Th>path</Th>
                  <Th>name</Th>
                  <Th>type</Th>
                  <Th>project</Th>
                </tr>
              </thead>
              <tbody>
                {rows.map((c) => {
                  const project = projectFor(c.path);
                  return (
                    <tr key={`${c.code}-${c.path}`}>
                      <Td>
                        <Mono className="text-text">{c.code}</Mono>
                      </Td>
                      <Td>
                        <Mono className="text-text-3">{c.path}</Mono>
                      </Td>
                      <Td className="text-text-3">{c.name ?? "—"}</Td>
                      <Td>
                        {c.type ? (
                          <Pill tone={c.type === "assertion" ? "accent" : "neutral"}>
                            {c.type}
                          </Pill>
                        ) : (
                          <span className="text-text-muted">—</span>
                        )}
                      </Td>
                      <Td>
                        {project ? (
                          <Link
                            to={href.project(project.id)}
                            className="text-[12px] text-accent hover:underline"
                          >
                            {project.name}
                          </Link>
                        ) : (
                          <span className="text-[12px] text-text-muted">
                            model store
                          </span>
                        )}
                      </Td>
                    </tr>
                  );
                })}
              </tbody>
            </Table>
          )}
        </div>
      </Card>
    </div>
  );
}
