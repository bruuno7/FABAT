import { randomBytes } from "node:crypto";
import { spawnSync } from "node:child_process";
import { closeSync, constants, fchmodSync, fstatSync, fsyncSync, openSync, readFileSync, writeSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { parse } from "dotenv";

const keys = [
  "HR_STATE_INGRESS_SECRET",
  "HR_STATE_READ_SECRET",
  "HR_STATE_COMMIT_SECRET",
  "HR_STATE_DELIVERY_SECRET",
];
const file = fileURLToPath(new URL("../.env.test", import.meta.url));
const upload = process.argv.includes("--upload-preview");
const verify = process.argv.includes("--verify") || upload;
let fd: number | undefined;

try {
  fd = openSync(file, constants.O_NOFOLLOW | (verify ? constants.O_RDONLY : constants.O_RDWR | constants.O_CREAT), 0o600);
  const stat = fstatSync(fd);
  if (!stat.isFile() || stat.nlink !== 1 || stat.uid !== process.getuid?.() || stat.size > 65536) {
    throw new Error("unsafe_file");
  }
  const original = readFileSync(fd, "utf8");
  const values = parse(original);
  const additions: string[] = [];
  const used = new Set<string>();
  for (const key of keys) {
    if (Object.hasOwn(values, key)) {
      if (!/^[a-f0-9]{64}$/.test(values[key]) || used.has(values[key])) throw new Error("invalid_existing_secret");
    } else if (!verify) {
      let value: string;
      do { value = randomBytes(32).toString("hex"); } while (used.has(value));
      values[key] = value;
      additions.push(`${key}=${value}`);
    } else {
      throw new Error("missing_secret");
    }
    used.add(values[key]);
  }
  const bypass = process.env.GENERATED_VERCEL_AUTOMATION_BYPASS_SECRET;
  if (bypass && !verify) {
    if (!/^[A-Za-z0-9]{32}$/.test(bypass)) throw new Error("invalid_bypass");
    if (values.VERCEL_AUTOMATION_BYPASS_SECRET && values.VERCEL_AUTOMATION_BYPASS_SECRET !== bypass) {
      throw new Error("existing_bypass_would_change");
    }
    if (!values.VERCEL_AUTOMATION_BYPASS_SECRET) {
      values.VERCEL_AUTOMATION_BYPASS_SECRET = bypass;
      additions.push(`VERCEL_AUTOMATION_BYPASS_SECRET=${bypass}`);
    }
  }
  if (!verify) {
    fchmodSync(fd, 0o600);
    if (additions.length) {
      const content = Buffer.from((original && !original.endsWith("\n") ? "\n" : "") + additions.join("\n") + "\n");
      let offset = 0;
      const start = Buffer.byteLength(original);
      while (offset < content.length) offset += writeSync(fd, content, offset, content.length - offset, start + offset);
      fsyncSync(fd);
    }
  }
  const stored = parse(readFileSync(file, "utf8"));
  if (keys.some((key) => stored[key] !== values[key]) || (fstatSync(fd).mode & 0o777) !== 0o600) {
    throw new Error("verification_failed");
  }
  if (bypass && stored.VERCEL_AUTOMATION_BYPASS_SECRET !== bypass) throw new Error("bypass_not_saved");
  if (upload) {
    for (const key of keys) {
      const child = spawnSync("npm", ["exec", "--yes", "--package=vercel@59.16.0", "--", "vercel", "env", "add", key,
        "preview", "--git-branch", "integracion/coordinacion-multicanal", "--project", "prj_uNJEqq0IJGmVumWtzbUuJZnZjiVe",
        "--scope", "fabat1", "--sensitive", "--yes"], {
        input: stored[key], encoding: "utf8", timeout: 60000, stdio: ["pipe", "pipe", "pipe"],
        env: { ...process.env, VERCEL_TELEMETRY_DISABLED: "1" },
      });
      if (child.status !== 0) {
        console.error(JSON.stringify({ key, uploaded: false, error: "preview_upload_failed", exit_code: child.status }));
        throw new Error("preview_upload_failed");
      }
      console.log(JSON.stringify({ key, uploaded: true, target: "preview", branch: "integracion/coordinacion-multicanal" }));
    }
  }
  console.log(JSON.stringify({
    file: "puente/.env.test", api_secrets: keys.length, added: additions.length,
    bypass_present: Boolean(stored.VERCEL_AUTOMATION_BYPASS_SECRET), permissions: "0600",
  }));
} catch {
  console.error("Secret provisioning failed; no secret values were printed and existing values were not replaced.");
  process.exitCode = 1;
} finally {
  if (fd !== undefined) closeSync(fd);
}
