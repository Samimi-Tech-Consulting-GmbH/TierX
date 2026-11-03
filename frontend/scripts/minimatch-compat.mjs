// Compatibility exports only: all matching uses the pinned upstream v11 engine.
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { createRequire } from "node:module";
const load = createRequire(import.meta.url);

let root;
try {
  root = dirname(load.resolve("minimatch/package.json"));
} catch (error) {
  if (error.code === "MODULE_NOT_FOUND") process.exit(0); // --omit=dev
  throw error;
}
if (JSON.parse(readFileSync(join(root, "package.json"))).version !== "11.0.4") {
  throw new Error("Review minimatch compatibility before changing its pinned version");
}
const patches = [
  ["commonjs", "235c5458355f1449cc100f1cea1a43d45f788a4feb524a83497aa146bea88f32",
    "\n// TierX legacy callable-export compatibility; upstream matching is unchanged.\nObject.assign(exports.minimatch, exports);\nmodule.exports = exports.minimatch;\n"],
  ["esm", "b238ca70371b1f192817ae9516afaacb566d1df2a7a85e47c6c24f41f1707864",
    "\n// TierX legacy default-export compatibility; upstream matching is unchanged.\nexport default minimatch;\n"],
];
// Validate both files before modifying either. Re-running installation is safe.
const checked = patches.map(([kind, expected, suffix]) => {
  const path = join(root, "dist", kind, "index.js");
  const contents = readFileSync(path, "utf8");
  const original = contents.endsWith(suffix) ? contents.slice(0, -suffix.length) : contents;
  if (createHash("sha256").update(original).digest("hex") !== expected) {
    throw new Error(`Unexpected minimatch ${kind} source; refusing compatibility patch`);
  }
  return [path, original + suffix];
});
for (const [path, contents] of checked) writeFileSync(path, contents);
