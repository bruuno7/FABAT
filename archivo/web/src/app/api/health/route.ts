import { loadEnv, envSummary } from "@/lib/env";

export const dynamic = "force-dynamic";

export async function GET() {
  const env = loadEnv();
  return Response.json({
    ok: true,
    service: "mando-web",
    ...envSummary(env),
    time: new Date().toISOString(),
  });
}
