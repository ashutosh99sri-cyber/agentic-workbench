import test from "node:test";
import assert from "node:assert/strict";
import { discountedTotal } from "../src/app.ts";

test("percentage discounts and bounds", () => {
  assert.equal(discountedTotal(1000, 10), 900);
  assert.equal(discountedTotal(1000, 100), 0);
  assert.equal(discountedTotal(1000, 0), 1000);
  assert.throws(() => discountedTotal(-1, 0), RangeError);
});
