import assert from "node:assert/strict";
import test from "node:test";

import ResolverPackage, { makeResolver } from "@forge/resolver";

test("uses the ESM-safe makeResolver export", () => {
  assert.equal(typeof makeResolver, "function");
  assert.equal(typeof makeResolver({ ping: () => "pong" }), "function");

  // @forge/resolver 2.0.0 exposes its class under a nested default when loaded
  // by Node 22 ESM. This guards against reintroducing `new ResolverPackage()`.
  assert.equal(typeof ResolverPackage, "object");
  assert.equal(typeof ResolverPackage.default, "function");
});
