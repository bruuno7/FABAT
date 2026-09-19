export type StateApiConfig = {
  enabled: boolean;
  namespace?: string;
  url?: string;
  token?: string;
  ingressSecret?: string;
  readSecret?: string;
  commitSecret?: string;
  deliverySecret?: string;
  telegramMode?: "off" | "isolated";
  telegramUsers?: string[];
  deliveryMode?: "sink" | "live";
  allowedTelegramChats?: string[];
  coordinatorHook?: string;
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
    telegramMode: value("HR_STATE_TELEGRAM_MODE") === "isolated" ? "isolated" : "off",
    telegramUsers: (value("HR_STATE_TELEGRAM_USERS") ?? "").split(",").map((id) => id.trim()).filter((id) => /^[1-9][0-9]{0,15}$/.test(id)),
    deliveryMode: value("HR_STATE_DELIVERY_MODE") === "live" ? "live" : "sink",
    allowedTelegramChats: (value("HR_STATE_ALLOWED_TELEGRAM_CHATS") ?? "").split(",").map((id) => id.trim()).filter((id) => /^[1-9][0-9]{0,15}$/.test(id)),
    coordinatorHook: value("HR_STATE_COORDINATOR_HOOK"),
  };
}
