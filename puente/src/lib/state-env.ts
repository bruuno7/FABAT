export type StateApiConfig = {
  enabled: boolean;
  namespace?: string;
  url?: string;
  token?: string;
  ingressSecret?: string;
  readSecret?: string;
  commitSecret?: string;
  deliverySecret?: string;
};

export function loadStateApiConfig(env: NodeJS.ProcessEnv): StateApiConfig {
  const value = (key: string) => env[key]?.trim() || undefined;
  return {
    enabled: env.HR_STATE_API_ENABLED === "1",
    namespace: value("HR_STATE_NAMESPACE"),
    url: value("UPSTASH_REDIS_REST_URL"),
    token: value("UPSTASH_REDIS_REST_TOKEN"),
    ingressSecret: value("HR_STATE_INGRESS_SECRET"),
    readSecret: value("HR_STATE_READ_SECRET"),
    commitSecret: value("HR_STATE_COMMIT_SECRET"),
    deliverySecret: value("HR_STATE_DELIVERY_SECRET"),
  };
}
