/**
 * Vercel Node function. Import compiled JS (tsc), not TS sources —
 * importing ../src/*.js from here is what made Production fail (NOT_FOUND).
 */
import { createApp } from "../motor/server/dist/app.js";

export default createApp();
