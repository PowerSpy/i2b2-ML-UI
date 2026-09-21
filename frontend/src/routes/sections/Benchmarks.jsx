import { count, score } from "../../lib/format.js";
import { href, Link } from "../../lib/router.jsx";
import { useWorkspace } from "../../lib/workspace.jsx";
import { Card } from "../../ui/Card.jsx";
import Callout, { Empty } from "../../ui/Callout.jsx";
import { Pill } from "../../ui/Status.jsx";
import { Heading, Mono, Note, Num, SectionLabel } from "../../ui/Text.jsx";

/** One leaderboard per project that has something to rank. */
export default function Benchmarks() {
  const { projects, modelTypes, modelTypesResult } = useWorkspace();
  const rankable = projects.filter((p) => p.models.some((m) => m.is_built));

  return (
    <div className="space-y-6">
      <div>
        <Heading level={1} className="text-[24px] leading-tight">
          Benchmarks
        </Heading>
        <Note className="mt-2">
          A leaderboard per project, built from the metrics each model stored at
          build time. Models are trained one at a time, so a leaderboard ranks
          what has been built rather than the whole registry.
        </Note>
      </div>

      {rankable.length === 0 ? (
        <Empty>
          No project has a built model yet. Define a model config and train it,
          and its project gets a leaderboard.
        </Empty>
      ) : (
        <div className="space-y-3">
          {rankable.map((project) => {
            const built = project.models.filter((m) => m.is_built);
            return (
              <Link
                key={project.id}
                to={href.benchmark(project.id)}
                className="flex items-center justify-between gap-6 rounded-card border border-border bg-panel p-[18px] transition-colors hover:border-border-strong"
              >
                <div className="min-w-0">
                  <Heading level={2} className="text-[15px] leading-tight">
                    {project.name}
                  </Heading>
                  <Mono className="mt-1 block text-[12px] text-text-3">
                    {project.root}
                  </Mono>
                </div>
                <div className="flex shrink-0 items-center gap-8">
                  <div className="text-right">
                    <Num className="block text-[19px] leading-none text-text">
                      {count(built.length)}
                    </Num>
                    <SectionLabel className="mt-1.5">built</SectionLabel>
                  </div>
                  <div className="text-right">
                    <Num className="block text-[19px] leading-none text-positive">
                      {score(project.best?.auc)}
                    </Num>
                    <SectionLabel className="mt-1.5">best roc auc</SectionLabel>
                  </div>
                </div>
              </Link>
            );
          })}
        </div>
      )}

      <Card>
        <SectionLabel className="mb-3">Registry</SectionLabel>
        {modelTypesResult?.error ? (
          <Callout tone="warn" title="registry unreadable">
            {modelTypesResult.error}. The algorithm list cannot be trusted to
            match what the container can build until this clears.
          </Callout>
        ) : (
          <>
            <div className="flex flex-wrap gap-2">
              {modelTypes.map((t) => (
                <Pill key={t.key}>{t.key}</Pill>
              ))}
            </div>
            <Note className="mt-3">
              Read from <Mono>MODEL_REGISTRY</Mono> inside the ETL container at
              request time, so a newly installed algorithm appears here without
              touching this page. An algorithm this list does not contain is not
              rejected by the builder — it silently trains logistic regression
              instead.
            </Note>
          </>
        )}
      </Card>
    </div>
  );
}
