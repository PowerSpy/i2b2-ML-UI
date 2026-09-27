import { lazy, Suspense } from "react";

import Shell, { Centre, LeftRail, RightRail } from "./layout/Shell.jsx";
import { href, Link, Router, useRoute } from "./lib/router.jsx";
import { SessionProvider, useSession } from "./lib/session.jsx";
import { WorkspaceProvider } from "./lib/workspace.jsx";
import Benchmark from "./routes/Benchmark.jsx";
import Login from "./routes/Login.jsx";
import Model from "./routes/Model.jsx";
import Project from "./routes/Project.jsx";
import Workspace from "./routes/Workspace.jsx";
import { Empty } from "./ui/Callout.jsx";
import { Card, CardHeader } from "./ui/Card.jsx";

/**
 * Nine routes over one set of loaded data.
 *
 * Provider order is load-bearing. SessionProvider is outermost because
 * WorkspaceProvider fires seven requests the moment it mounts — rendering it
 * before the session is known means seven 401s racing the login form onto the
 * screen. WorkspaceProvider then sits above the shell, because the top bar
 * reads the same engine and watcher state the pages do.
 */
export default function App() {
  return (
    <Router>
      <SessionProvider>
        <Authenticated>
          <WorkspaceProvider>
            <Shell>
              <Route />
            </Shell>
          </WorkspaceProvider>
        </Authenticated>
      </SessionProvider>
    </Router>
  );
}

/**
 * Renders the app, the login screen, or neither.
 *
 * "Checking" gets its own branch rather than falling through to the login
 * form: treating an unanswered /auth/me as signed-out flashes a login screen
 * on every reload for someone who is already signed in.
 */
function Authenticated({ children }) {
  const { isChecking, isSignedIn } = useSession();

  if (isChecking) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-ground">
        <p className="text-[13px] text-text-muted">Checking your session…</p>
      </div>
    );
  }

  return isSignedIn ? children : <Login />;
}

/**
 * CodeMirror is ~370 KB, and only one route uses it. Loaded eagerly it more
 * than doubled the bundle every visitor downloads, including the login page,
 * to carry an editor most sessions never open.
 */
const Transform = lazy(() => import("./routes/Transform.jsx"));

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
    case "transform":
      return (
        <Suspense fallback={<EditorLoading />}>
          <Transform />
        </Suspense>
      );
    default:
      return <NotFound path={route.path} />;
  }
}

/** Shown while the editor chunk downloads. Sits in the same shell so the
 * page does not jump when it arrives. */
function EditorLoading() {
  return (
    <>
      <LeftRail width={258} />
      <Centre>
        <Card>
          <Empty>Loading the editor…</Empty>
        </Card>
      </Centre>
      <RightRail width={300} />
    </>
  );
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
