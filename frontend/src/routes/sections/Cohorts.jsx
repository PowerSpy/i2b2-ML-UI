import CohortsPanel from "../../components/CohortsPanel.jsx";
import { count } from "../../lib/format.js";
import { useWorkspace } from "../../lib/workspace.jsx";
import { Card, CardHeader } from "../../ui/Card.jsx";
import Callout, { Failed } from "../../ui/Callout.jsx";
import { Heading, Mono, Note, Num } from "../../ui/Text.jsx";

export default function Cohorts() {
  const { cohorts, cohortsResult, concepts, refresh } = useWorkspace();

  return (
    <div className="space-y-6">
      <div>
        <Heading level={1} className="text-[24px] leading-tight">
          Cohorts
        </Heading>
        <Note className="mt-2">
          Named patient sets. The training engine reads these and never looks at
          your label facts directly, so labelled data still needs one cohort per
          class.
        </Note>
      </div>

      <Callout tone="neutral" title="patient sets are warehouse-wide">
        Cohorts carry no concept path, so nothing scopes them to a project. Every
        project page lists this same set of <Num>{count(cohorts.length)}</Num>.
      </Callout>

      <Card>
        <CardHeader
          title={
            <>
              <Num>{count(cohorts.length)}</Num> patient sets
            </>
          }
          hint="Recorded is the size the set stored when it was built; live counts the members that still have facts. A gap means the data was reloaded underneath it."
        />
        <div className="mt-5">
          {cohortsResult?.error ? (
            <Failed what="the cohort list" error={cohortsResult.error} />
          ) : (
            <CohortsPanel cohorts={cohorts} concepts={concepts} onChange={refresh} />
          )}
        </div>
      </Card>

      <Callout tone="neutral" title="why a cohort at all">
        The labels are already facts, but the training engine only reads patient
        sets. A cohort is every patient who has a fact with the concept code you
        pick — the name is only a lookup label, the <Mono>code</Mono> decides who
        is in it.
      </Callout>
    </div>
  );
}
