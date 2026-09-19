/**
 * Vercel serverless entry (Framework Preset: Other).
 * All routes rewrite here: /telegram/webhook, /hr/events, /health
 */
import { createApp } from "../motor/server/src/app.js";

export default createApp();
