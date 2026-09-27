import { useSession } from "../lib/session.jsx";
import Callout from "./Callout.jsx";

/**
 * Hide or explain a control the current role may not use.
 *
 * Which of the two depends on the case, and the choice is not cosmetic:
 *
 * - **Hide** when the whole section is meaningless to this role. A permanently
 *   dead file drop-zone is worse than no drop-zone; it invites someone to
 *   spend a minute finding out that it will never work.
 * - **Explain** when the control sits beside things the role *can* do, so its
 *   absence would read as a bug rather than a boundary.
 *
 * Never used for a suppressed *value* — those keep their place and say they
 * are withheld, because a missing number and a hidden number must not look
 * the same.
 */
export default function CustodianOnly({ children, explain = null }) {
  const { isCustodian } = useSession();

  if (isCustodian) return children;
  if (!explain) return null;

  return (
    <Callout tone="neutral" title="not available to your account">
      {explain}
    </Callout>
  );
}

/** The inverse, for text that only makes sense to a restricted role. */
export function ResearcherOnly({ children }) {
  const { isResearcher } = useSession();
  return isResearcher ? children : null;
}
