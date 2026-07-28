import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "../..");
const allowlist = JSON.parse(readFileSync(resolve(root, "security/npm-audit-allowlist.json"), "utf8"));
const today = new Date().toISOString().slice(0, 10);
const allowed = new Map();
for (const item of allowlist.exceptions ?? []) {
  if (!item.id || !item.package || !item.expires_on || !item.reason || !item.owner) {
    throw new Error("npm audit exception metadata is incomplete");
  }
  if (item.expires_on < today) {
    throw new Error(`npm audit exception expired: ${item.id} on ${item.expires_on}`);
  }
  allowed.set(item.id, item);
}

const result = spawnSync("npm", ["audit", "--json", "--omit=dev"], {
  cwd: resolve(root, "frontend"),
  encoding: "utf8",
});
const report = JSON.parse(result.stdout || "{}");
const vulnerabilities = report.vulnerabilities ?? {};
const memo = new Map();

function advisoryIds(name, stack = new Set()) {
  if (memo.has(name)) return memo.get(name);
  if (stack.has(name)) return new Set();
  stack.add(name);
  const ids = new Set();
  for (const via of vulnerabilities[name]?.via ?? []) {
    if (typeof via === "string") {
      for (const id of advisoryIds(via, stack)) ids.add(id);
      continue;
    }
    const match = String(via.url ?? "").match(/GHSA-[a-z0-9-]+/i);
    if (match) ids.add(match[0]);
    else ids.add(`source:${via.source ?? via.title ?? name}`);
  }
  stack.delete(name);
  memo.set(name, ids);
  return ids;
}

const blocked = [];
const accepted = [];
for (const [name, vulnerability] of Object.entries(vulnerabilities)) {
  if (!["high", "critical"].includes(vulnerability.severity)) continue;
  const ids = advisoryIds(name);
  for (const id of ids) {
    const exception = allowed.get(id);
    if (!exception || exception.package !== name && !vulnerability.via?.includes(exception.package)) {
      blocked.push({ package: name, severity: vulnerability.severity, advisory: id });
    } else {
      accepted.push({ package: name, advisory: id, expires_on: exception.expires_on });
    }
  }
}
if (blocked.length) {
  console.error(JSON.stringify({ status: "blocked", blocked, accepted }, null, 2));
  process.exit(1);
}
console.log(JSON.stringify({ status: "passed_with_time_bounded_exceptions", accepted }, null, 2));
