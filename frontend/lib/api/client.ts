import createClient from "openapi-fetch";

import type { components, paths } from "@/lib/api/schema";

/** Typed API client. Types are generated from the backend's OpenAPI schema (`pnpm gen:api`). */
export const api = createClient<paths>({ baseUrl: "", credentials: "same-origin" });

export type Me = components["schemas"]["MeResponse"];
export type Role = components["schemas"]["Role"];
