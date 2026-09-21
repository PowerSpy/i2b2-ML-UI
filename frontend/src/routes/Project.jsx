import { useEffect, useMemo, useState } from "react";

import { CohortsTable } from "../components/CohortsPanel.jsx";
import { Centre, LeftRail, RightRail } from "../layout/Shell.jsx";
import { count } from "../lib/format.js";
import { findProject } from "../lib/projects.js";
import { href, Link } from "../lib/router.jsx";
import { useWorkspace } from "../lib/workspace.jsx";
import ConceptTree from "../panels/ConceptTree.jsx";
import DataHealthCard from "../panels/DataHealthCard.jsx";
import ModelsList from "../panels/ModelsList.jsx";
import PipelineRail from "../panels/PipelineRail.jsx";
import { Card, CardHeader } from "../ui/Card.jsx";
import Callout, { Empty } from "../ui/Callout.jsx";
import { Heading, Mono, Num } from "../ui/Text.jsx";
import {
  ApplyStep,
  CohortsStep,
  DefineStep,
  LoadStep,
  stepSummaries,
  TrainStep,
} from "./ProjectSteps.jsx";

export default function Project({ id }) {
  const ws = useWorkspace();
  const project = findProject(ws.projects, id);

  const [step, setStep] = useState("overview");
  const [selectedModel, setSelectedModel] = useState(null);
  const [targetCohort, setTargetCohort] = useState(null);
  const [eventPaths, setEventPaths] = useState([]);
  const [editingCode, setEditingCode] = useState(null);

  // Apply reads prediction_event_paths from the job rather than from the blob,
  // so this seeds them from the model's own label paths instead of making the
  // user guess. The config is already loaded for every model.
  const labelPaths = selectedModel
    ? ws.configs[selectedModel]?.data?.label_paths
    : null;
  useEffect(() => {
    setEventPaths(labelPaths ?? []);
  }, [labelPaths]);

  const facts = ws.verify?.data?.facts;

  const steps = useMemo(() => {
    if (!project) return [];
    const summaries = stepSummaries({
      project,
      facts,
      cohorts: ws.cohorts,
      jobs: ws.jobs,
    });

    const done = [
      project.concepts.length > 0 && (facts ?? 0) > 0,
      ws.cohorts.length > 0,
      project.models.length > 0,
      project.models.some((m) => m.is_built),
      // Nothing reports whether an apply has run: the job row does not record
      // which model it scored, and prediction counts are per model. Never
      // marked done rather than guessed at.
      false,
    ];
    const currentIndex = done.indexOf(false);

    const titles = ["Load", "Cohorts", "Define", "Train", "Apply"];
    const keys = ["load", "cohorts", "define", "train", "apply"];

    return titles.map((title, i) => ({
      n: i + 1,
      title,
      summary: summaries[keys[i]],
      state: done[i] ? "done" : i === currentIndex ? "current" : "idle",
    }));
  }, [project, facts, ws.cohorts, ws.jobs]);

  if (!project) {
    return (
      <>
        <LeftRail width={258} />
        <Centre>
          {ws.loading ? (
            <Empty>Reading the warehouse…</Empty>
          ) : (
            <Card>
              <CardHeader
                title="No such project"
                hint="A project is the top-level segment of a concept path. This one has no concepts under it, so nothing in the warehouse matches."
              />
              <Link
                to={href.workspace()}
                className="mt-4 inline-flex min-h-[44px] items-center rounded-btn border border-border-strong px-4 text-[13px] text-text-2 hover:border-text-muted hover:text-text"
              >
                Back to projects
              </Link>
            </Card>
          )}
        </Centre>
        <RightRail width={300} />
      </>
    );
  }

  return (
    <>
      <LeftRail width={258}>
        <PipelineRail
          project={project}
          steps={steps}
          selected={step}
          onSelect={setStep}
        />
      </LeftRail>

      <Centre>
        {step === "overview" ? (
          <Overview project={project} />
        ) : step === 1 ? (
          <LoadStep project={project} />
        ) : step === 2 ? (
          <CohortsStep />
        ) : step === 3 ? (
          <DefineStep
            project={project}
            editingCode={editingCode}
            onEdit={setEditingCode}
            onCreated={(code) => {
              setSelectedModel(code);
              setEditingCode(null);
              setStep(4);
            }}
          />
        ) : step === 4 ? (
          <TrainStep
            project={project}
            selected={selectedModel}
            onSelect={setSelectedModel}
          />
        ) : (
          <ApplyStep
            project={project}
            selected={selectedModel}
            onSelect={setSelectedModel}
            targetCohort={targetCohort}
            onTarget={setTargetCohort}
            eventPaths={eventPaths}
            onEventPaths={setEventPaths}
          />
        )}
      </Centre>

      <RightRail width={300}>
        <ConceptTree project={project} />
      </RightRail>
    </>
  );
}

function Overview({ project }) {
  const ws = useWorkspace();
  const built = project.models.filter((m) => m.is_built);

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-6">
        <div className="min-w-0">
          <Heading level={1} className="text-[22px] leading-tight">
            {project.name}
          </Heading>
          <Mono className="mt-1.5 block text-[12px] text-text-3">{project.root}</Mono>
        </div>
      </div>

      <DataHealthCard project={project} />

      <Card>
        <CardHeader
          title="Cohorts"
          hint="Recorded is the size the set stored when it was built; live counts members that still have facts. The two disagree after a reload."
        >
          <Link
            to={href.section("cohorts")}
            className="text-[12px] text-accent hover:underline"
          >
            manage →
          </Link>
        </CardHeader>
        <div className="mt-4">
          <CohortsTable
            cohorts={ws.cohorts}
            definitions={ws.cohortDefs}
            loading={ws.loading}
          />
        </div>
        <p className="mt-3 text-[11px] leading-relaxed text-text-muted">
          Patient sets are warehouse-wide — nothing scopes them to a concept
          subtree, so this is the same list on every project.
        </p>
      </Card>

      <Card>
        <CardHeader
          title={
            <>
              Models in this project{" "}
              <Num className="text-text-muted">
                {count(ws.loading ? undefined : project.models.length)}
              </Num>
            </>
          }
          hint="One AUC hides the reasons an AUC might be wrong, so the flags sit on the row."
        >
          {built.length > 0 && (
            <Link
              to={href.benchmark(project.id)}
              className="text-[12px] text-accent hover:underline"
            >
              compare all →
            </Link>
          )}
        </CardHeader>
        <div className="mt-4">
          <ModelsList
            models={project.models}
            empty="No models point at this subtree yet. Step 3 defines one."
          />
        </div>
      </Card>

      {project.models.length > 0 && built.length === 0 && (
        <Callout tone="warn" title="nothing built yet">
          Every model here is config only. Defining one trains nothing — step 4
          queues the job that does.
        </Callout>
      )}
    </div>
  );
}
