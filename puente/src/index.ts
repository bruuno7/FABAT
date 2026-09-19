import "dotenv/config";
import { createApp } from "./app.js";
import { loadEnv } from "./lib/hr-client.js";

const env = loadEnv();
const app = createApp(env);

app.listen(env.port, () => {
  console.info(
    `[mando] listening :${env.port} callback=${env.mandoCallbackUrl}`,
  );
});
