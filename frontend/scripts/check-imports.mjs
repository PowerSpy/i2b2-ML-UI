/**
 * Fail on a JSX component that is used but never imported or defined.
 *
 * Vite builds this cleanly. Rollup resolves *modules*, not identifiers, so an
 * undefined `<Empty>` or a missing `lazy` is not a build error - it is a blank
 * screen and a ReferenceError the first time that branch renders. Both got
 * through while adding the transform editor, in a file that compiled and
 * shipped.
 *
 * Deliberately crude: a regex sweep, not a parse. It catches the only mistake
 * that actually happens here - a component referenced without its import -
 * and it costs nothing to run.
 *
 *     node scripts/check-imports.mjs
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const ROOT = new URL("../src", import.meta.url).pathname.replace(/^\/([A-Z]:)/, "$1");

// Names that are in scope without an import.
const GLOBALS = new Set([
  "Array", "Boolean", "Date", "Error", "Intl", "JSON", "Map", "Math", "Number",
  "Object", "Promise", "RegExp", "Set", "String", "Symbol", "URL",
  "URLSearchParams", "FormData", "Blob", "File", "Image", "Fragment",
]);

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? walk(path) : [path];
  });
}

const problems = [];

for (const file of walk(ROOT).filter((f) => f.endsWith(".jsx") || f.endsWith(".js"))) {
  const src = readFileSync(file, "utf8");

  const declared = new Set(GLOBALS);
  // import X, { a, b as c } from "..."
  for (const m of src.matchAll(/import\s+([^"';]+?)\s+from\s*["'][^"']+["']/g)) {
    for (const part of m[1].replace(/[{}]/g, ",").split(",")) {
      const name = part.trim().split(/\s+as\s+/).pop().trim();
      if (name && name !== "*") declared.add(name);
    }
  }
  // Locally defined: functions, classes, consts.
  for (const m of src.matchAll(/(?:function|class)\s+([A-Z_$][\w$]*)/g)) declared.add(m[1]);
  for (const m of src.matchAll(/(?:const|let|var)\s+([A-Z_$][\w$]*)/g)) declared.add(m[1]);
  // Renamed destructured bindings, e.g. `{ as: Tag = "section" }` - a real
  // pattern in ui/Card.jsx, and the checker's only false positive without it.
  for (const m of src.matchAll(/[{,]\s*\w+\s*:\s*([A-Z][\w$]*)\s*[=,}]/g)) declared.add(m[1]);

  // Capitalised JSX tags and bare capitalised calls (lazy, Suspense, hooks
  // used as values) are what break at runtime.
  const used = new Map();
  for (const m of src.matchAll(/<([A-Z][\w$]*)/g)) {
    if (!used.has(m[1])) used.set(m[1], lineOf(src, m.index));
  }
  for (const name of ["lazy", "Suspense", "createContext", "useContext",
                      "useState", "useEffect", "useMemo", "useRef", "useCallback"]) {
    const hit = src.match(new RegExp(`(?<![\\w.$])${name}\\s*\\(`));
    if (hit && !declared.has(name)) used.set(name, lineOf(src, hit.index));
  }

  for (const [name, line] of used) {
    // A dotted tag like <Foo.Bar> resolves through its root.
    if (declared.has(name.split(".")[0])) continue;
    problems.push(`${file.replace(ROOT, "src")}:${line}  <${name}> is not imported or defined`);
  }
}

function lineOf(src, index) {
  return src.slice(0, index).split("\n").length;
}

if (problems.length) {
  console.error("Undefined components or hooks:\n" + problems.map((p) => "  " + p).join("\n"));
  process.exit(1);
}
console.log("check-imports: every JSX component and hook resolves.");
