import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import {
  apiGet,
  apiPost,
  setCsrfToken,
  setUnauthenticatedHandler,
} from "./api.js";

/**
 * Who is signed in.
 *
 * Sits above WorkspaceProvider deliberately. `workspace.jsx` fires seven
 * requests the moment it mounts; rendering it before the session is known
 * means seven 401s racing the login form onto the screen.
 *
 * `status` is three-valued and the distinction matters: "checking" is not
 * "signed out". Treating them the same flashes the login form on every reload
 * for anyone who is already signed in.
 */
const SessionContext = createContext(null);

const CHECKING = "checking";
const ANON = "anon";
const SIGNED_IN = "signed-in";

export function SessionProvider({ children }) {
  const [state, setState] = useState({ status: CHECKING, user: null });
  // Set when the backend has no accounts at all. The app is unusable rather
  // than open, and the message names the command that fixes it.
  const [setupNeeded, setSetupNeeded] = useState(null);

  const check = useCallback(async () => {
    try {
      const user = await apiGet("/auth/me");
      setCsrfToken(user.csrf_token);
      setState({ status: SIGNED_IN, user });
      setSetupNeeded(null);
    } catch (e) {
      // 503 means no accounts exist yet — a different problem from being
      // signed out, and one no amount of logging in will fix.
      if (/no accounts exist/i.test(e.message)) setSetupNeeded(e.message);
      setCsrfToken(null);
      setState({ status: ANON, user: null });
    }
  }, []);

  useEffect(() => {
    check();
  }, [check]);

  // Any 401 anywhere in the app drops straight back to the login screen,
  // rather than leaving a signed-out session rendering stale data.
  useEffect(() => {
    setUnauthenticatedHandler(() => {
      setCsrfToken(null);
      setState({ status: ANON, user: null });
    });
    return () => setUnauthenticatedHandler(null);
  }, []);

  const login = useCallback(async (username, password) => {
    const user = await apiPost("/auth/login", { username, password });
    setCsrfToken(user.csrf_token);
    setState({ status: SIGNED_IN, user });
    setSetupNeeded(null);
    return user;
  }, []);

  const logout = useCallback(async () => {
    try {
      await apiPost("/auth/logout", {});
    } finally {
      // Local state is cleared whatever the server said. A logout that leaves
      // the app looking signed in because the request failed is worse than one
      // that clears optimistically.
      setCsrfToken(null);
      setState({ status: ANON, user: null });
    }
  }, []);

  const value = useMemo(
    () => ({
      status: state.status,
      user: state.user,
      setupNeeded,
      isChecking: state.status === CHECKING,
      isSignedIn: state.status === SIGNED_IN,
      role: state.user?.role ?? null,
      isCustodian: state.user?.role === "custodian",
      isResearcher: state.user?.role === "researcher",
      login,
      logout,
      recheck: check,
    }),
    [state, setupNeeded, login, logout, check],
  );

  return (
    <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
  );
}

export function useSession() {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession outside SessionProvider");
  return value;
}
