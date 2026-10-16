/** Deliberate regression fixture, exercised through Node's native type stripping. */
export function discountedTotal(amountCents: number, discountPercent: number): number {
  if (!Number.isSafeInteger(amountCents) || amountCents < 0) throw new RangeError("Invalid amount");
  if (!Number.isInteger(discountPercent) || discountPercent < 0 || discountPercent > 100) throw new RangeError("Invalid discount");
  return amountCents - discountPercent;
}
