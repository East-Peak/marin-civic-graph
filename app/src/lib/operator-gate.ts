// Runtime gate for the operator-local workbench — defense-in-depth on top of the
// build-time exclusion (the routes shouldn't exist in a public build at all; this is the
// belt for the belt-and-suspenders). A library, not a route: harmless if it ships.
// Closed on any deploy signal; open only when OPERATOR_WORKBENCH=1 locally.
export function operatorEnabled(): boolean {
  if (process.env.VERCEL || process.env.VERCEL_ENV) return false; // never on a deployment
  return process.env.OPERATOR_WORKBENCH === "1";
}
