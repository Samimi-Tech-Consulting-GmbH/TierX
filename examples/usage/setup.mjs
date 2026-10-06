import { randomBytes } from "node:crypto";
import { readFile, writeFile, rename } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const directory = fileURLToPath(new URL(".", import.meta.url));
const releaseIndex = process.argv.indexOf("--release");
const release = releaseIndex >= 0 ? process.argv[releaseIndex + 1] : undefined;
if (release && !/^v\d+\.\d+\.\d+$/.test(release)) throw new Error("Use --release vMAJOR.MINOR.PATCH");
let contents;
try { contents = await readFile(`${directory}.env`, "utf8"); }
catch (error) {
  if (error.code !== "ENOENT") throw error;
  contents = await readFile(`${directory}.env.example`, "utf8");
}
function existing(key) { return contents.match(new RegExp(`^${key}=(.*)$`, "m"))?.[1]; }
function fill(key, value) {
  if (existing(key)?.trim()) return;
  if (existing(key) !== undefined) contents = contents.replace(new RegExp(`^${key}=.*$`, "m"), `${key}=${value}`);
  else contents += `\n${key}=${value}\n`;
}
fill("TIERX_RELEASE", release?.slice(1) || "");
if (!/^\d+\.\d+\.\d+$/.test(existing("TIERX_RELEASE") || "")) throw new Error("Supply the released installer version with --release vX.Y.Z (image tags omit v)");
for (const key of ["TIERX_MONGO_ROOT_PASSWORD", "TIERX_JWT_SECRET_KEY", "TIERX_WEBHOOK_SECRET_ENCRYPTION_KEY"]) {
  fill(key, randomBytes(32).toString("base64url"));
}
const temporary = `${directory}.env.${randomBytes(8).toString("hex")}.tmp`;
await writeFile(temporary, contents, { mode: 0o600, flag: "wx" });
await rename(temporary, `${directory}.env`);
console.log("Prepared .env (0600). Existing nonempty values preserved. Start the chosen Compose variant.");
