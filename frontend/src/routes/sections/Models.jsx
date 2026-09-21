import { count } from "../../lib/format.js";
import { useWorkspace } from "../../lib/workspace.jsx";
import ModelsList from "../../panels/ModelsList.jsx";
import { Card, CardHeader } from "../../ui/Card.jsx";
import { Failed } from "../../ui/Callout.jsx";
import { Heading, Mono, Note, Num } from "../../ui/Text.jsx";

export default function Models() {
  const { models, modelsResult, loading } = useWorkspace();
  const built = models.filter((m) => m.is_built);

  return (
    <div className="space-y-6">
      <div>
        <Heading level={1} className="text-[24px] leading-tight">
          Models
        </Heading>
        <Note className="mt-2">
          Every model in the warehouse. A model is a concept under{" "}
          <Mono>/ML</Mono> whose blob holds its config; the ones marked{" "}
          <em>config only</em> have been defined but never trained.
        </Note>
      </div>

      <Card>
        <CardHeader
          title={
            <>
              <Num>{count(loading ? undefined : models.length)}</Num> models,{" "}
              <Num>{count(loading ? undefined : built.length)}</Num> built
            </>
          }
          hint="Ranking by one number hides the reasons a number might be wrong, so the flags sit on the row rather than behind it."
        />
        <div className="mt-5">
          {modelsResult?.error ? (
            <Failed what="the model list" error={modelsResult.error} />
          ) : (
            <ModelsList
              models={models}
              showProject
              empty={
                loading
                  ? "Reading the warehouse…"
                  : "No models defined. A model config is created in a project's define step."
              }
            />
          )}
        </div>
      </Card>
    </div>
  );
}
