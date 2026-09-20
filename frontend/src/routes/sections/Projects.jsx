import { useState } from "react";

import { count } from "../../lib/format.js";
import { href, Link } from "../../lib/router.jsx";
import { useWorkspace } from "../../lib/workspace.jsx";
import FileLoader from "../../components/FileLoader.jsx";
import ProjectCard from "../../panels/ProjectCard.jsx";
import Button from "../../ui/Button.jsx";
import { Card, CardHeader } from "../../ui/Card.jsx";
import Callout, { Empty, Failed } from "../../ui/Callout.jsx";
import { Heading, Mono, Note } from "../../ui/Text.jsx";

export default function Projects() {
  const ws = useWorkspace();
  const [creating, setCreating] = useState(false);

  const facts = ws.verify?.data?.facts;
  const cohorts = ws.cohorts.length;

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-6">
        <div className="max-w-xl">
          <Heading level={1} className="text-[24px] leading-tight">
            Projects
          </Heading>
          <Note className="mt-2">
            A project is one concept subtree, the models trained against it, and
            the state of the pipeline around them. Counts are read live from the
            warehouse, never from the response of whatever wrote them.
          </Note>
        </div>
        <Button
          variant="primary"
          className="shrink-0"
          onClick={() => setCreating((c) => !c)}
          aria-expanded={creating}
        >
          {creating ? "Close" : "New project"}
        </Button>
      </div>

      {creating && <NewProject onLoaded={ws.refresh} />}

      {ws.conceptsResult?.error ? (
        <Failed what="the concept list" error={ws.conceptsResult.error} />
      ) : ws.loading ? (
        <Empty>Reading the warehouse…</Empty>
      ) : ws.projects.length === 0 ? (
        <Empty>
          No concepts are loaded, so there is no subtree to scope a project to.
          Load a concepts CSV to create one.
        </Empty>
      ) : (
        <div className="grid grid-cols-1 gap-3.5 lg:grid-cols-2">
          {ws.projects.map((p) => (
            <ProjectCard key={p.id} project={p} facts={facts} cohorts={cohorts} />
          ))}
        </div>
      )}

      {ws.unattributed.length > 0 && (
        <Callout tone="warn" title="models outside every project">
          <Mono className="text-text-2">
            {ws.unattributed.map((m) => m.code).join(", ")}
          </Mono>{" "}
          could not be filed under a concept subtree — their stored config named
          no readable data path.{" "}
          <Link to={href.section("models")} className="text-accent hover:underline">
            see all models
          </Link>
        </Callout>
      )}

      <BenchmarkSuiteCard />
    </div>
  );
}

/**
 * There is no create-project endpoint, because there is no project table. A
 * project comes into existence the moment a concept is loaded under a new
 * top-level path — so "new project" is the loader, with that said out loud.
 */
function NewProject({ onLoaded }) {
  return (
    <Card>
      <CardHeader
        title="New project"
        hint="A project is not a record you create — it is the top-level segment of a concept path. Load a concepts CSV whose paths start with a new root and the project appears here."
      />

      <Callout tone="neutral" className="mt-4">
        <strong className="text-text-2">Concepts CSV</strong> —{" "}
        <Mono>type,path,code</Mono>. One row per column in your data, plus one
        per label. <Mono>path</Mono> is a tree position you invent, e.g.{" "}
        <Mono>/MyData/features/glucose</Mono>; the convention is a{" "}
        <Mono>features/</Mono> subtree and a separate <Mono>label/</Mono>{" "}
        subtree. <Mono>type</Mono> is <Mono>float</Mono> for numbers,{" "}
        <Mono>assertion</Mono> for labels.
        <br />
        <br />
        <strong className="text-text-2">Facts CSV</strong> —{" "}
        <Mono>mrn,code,value,start_date</Mono>. One row per patient per value —
        so a 500-patient, 30-column dataset becomes 15,000 rows. Assertion rows
        leave <Mono>value</Mono> blank.
      </Callout>

      <Callout tone="warn" title="the filename suffix decides everything" className="mt-3">
        Filenames must end <Mono>concepts.csv</Mono> or <Mono>facts.csv</Mono>,
        lowercase. The loader globs by suffix; a name that does not match loads
        nothing and still exits 0. Every load below reports rows actually gained,
        not exit status.
      </Callout>

      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <FileLoader
          endpoint="/load-concepts"
          prompt="Drop a concepts CSV here, or click to browse"
          onLoaded={onLoaded}
        />
        <FileLoader
          endpoint="/load-facts"
          prompt="Drop a facts CSV here, or click to browse"
          params={{ mrn_are_patient_numbers: true }}
          onLoaded={onLoaded}
        />
      </div>
    </Card>
  );
}

function BenchmarkSuiteCard() {
  const { projects } = useWorkspace();
  const withBuilt = projects.filter((p) => p.models.some((m) => m.is_built));

  return (
    <Card className="border-dashed">
      <div className="flex items-center justify-between gap-6">
        <div className="min-w-0">
          <Heading level={2} className="text-[15px]">
            Benchmark suite
          </Heading>
          <Note className="mt-1.5">
            Rank a project&apos;s models against each other on the metrics each
            one stored at build time. There is no endpoint that trains the whole
            registry in one run — models are built one at a time in the train
            step, so a leaderboard compares what has been built, not everything
            that could be.
          </Note>
        </div>
        {withBuilt.length > 0 && (
          <Link to={href.section("benchmarks")} className="shrink-0">
            <span className="inline-flex min-h-[44px] items-center rounded-btn border border-border-strong px-4 text-[13px] text-text-2 hover:border-text-muted hover:text-text">
              Open suite
            </span>
          </Link>
        )}
      </div>
      {withBuilt.length === 0 && (
        <p className="mt-3 text-[12px] text-text-muted">
          Nothing to rank — <Mono>{count(0)}</Mono> projects have a built model.
        </p>
      )}
    </Card>
  );
}
