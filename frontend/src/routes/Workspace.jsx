import { Centre, LeftRail, RightRail } from "../layout/Shell.jsx";
import WorkspaceRail from "../layout/WorkspaceRail.jsx";
import JobQueue from "../panels/JobQueue.jsx";
import NeedsAttention from "../panels/NeedsAttention.jsx";
import Callout from "../ui/Callout.jsx";
import Benchmarks from "./sections/Benchmarks.jsx";
import Cohorts from "./sections/Cohorts.jsx";
import Concepts from "./sections/Concepts.jsx";
import DataHealth from "./sections/DataHealth.jsx";
import Models from "./sections/Models.jsx";
import Projects from "./sections/Projects.jsx";

const SECTIONS = {
  workspace: Projects,
  concepts: Concepts,
  cohorts: Cohorts,
  models: Models,
  benchmarks: Benchmarks,
  "data-health": DataHealth,
};

/**
 * Workspace home. The rails are the same for every section — what is wrong
 * right now, and what is queued — because those do not stop being true when
 * you navigate from projects to cohorts.
 */
export default function Workspace({ section = "workspace" }) {
  const Section = SECTIONS[section] ?? Projects;

  return (
    <>
      <LeftRail width={216}>
        <WorkspaceRail />
      </LeftRail>

      <Centre>
        <Section />
      </Centre>

      <RightRail width={330}>
        <NeedsAttention />
        <JobQueue />
        <Callout tone="neutral" title="silent failures are the norm here">
          A step can report success and load nothing. Every count in this app is
          read back from the warehouse after the fact, not from the job&apos;s own
          reply.
        </Callout>
      </RightRail>
    </>
  );
}
