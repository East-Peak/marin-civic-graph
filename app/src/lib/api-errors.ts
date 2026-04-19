// app/src/lib/api-errors.ts
export function jsonError(message: string, status = 500) {
  return Response.json({ error: message }, { status });
}
