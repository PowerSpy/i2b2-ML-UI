import Shell, { Centre, LeftRail, RightRail } from "./layout/Shell.jsx";
import { href, Link, Router, useRoute } from "./lib/router.jsx";
import { WorkspaceProvider } from "./lib/workspace.jsx";
import Benchmark from "./routes/Benchmark.jsx";
import Model from "./routes/Model.jsx";
import Project from "./routes/Project.jsx";
import Workspace from "./routes/Workspace.jsx";
import { Card, CardHeader } from "./ui/Card.jsx";

/**
 * Nine routes over one set of loaded data.
 *
 * The provider sits above the shell because the top bar reads the same engine
 * and watcher state the pages do — a stopped watcher has to be visible from
 * every route, not just the one that queued the job.
 */
export default function App() {
  return (
    <Router>
      <WorkspaceProvider>
        <Shell>
          <Route />
        </Shell>
      </WorkspaceProvider>
    </Router>
  );
}

function Route() {
  const route = useRoute();

  switch (route.name) {
    case "workspace":
    case "concepts":
    case "cohorts":
    case "models":
    case "benchmarks":
    case "data-health":
      return <Workspace section={route.name} />;
    case "project":
      return <Project id={route.params.id} />;
    case "project-benchmark":
      return <Benchmark id={route.params.id} />;
    case "model":
      return <Model code={route.params.code} />;
    default:
      return <NotFound path={route.path} />;
  }
}

function NotFound({ path }) {
  return (
    <>
      <LeftRail width={216} />
      <Centre>
        <Card>
          <CardHeader
            title="No such page"
            hint={`Nothing is routed at ${path}.`}
          />
          <Link
            to={href.workspace()}
            className="mt-4 inline-flex min-h-[44px] items-center rounded-btn border border-border-strong px-4 text-[13px] text-text-2 hover:border-text-muted hover:text-text"
          >
            Back to projects
          </Link>
        </Card>
      </Centre>
      <RightRail width={330} />
    </>
  );
}
