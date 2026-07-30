import type { components, paths } from "./generated/creator";

export type LiveResponse =
  paths["/health/live"]["get"]["responses"][200]["content"]["application/json"];
export type ReadyResponse =
  paths["/health/ready"]["get"]["responses"][200]["content"]["application/json"];
export type RuntimeStatusResponse =
  paths["/v1/runtime/status"]["get"]["responses"][200]["content"]["application/json"];
export type CreatorProjectionEventResponse =
  components["schemas"]["CreatorProjectionEventResponse"];
export type RejectedOutcome = components["schemas"]["RejectedOutcomeResponse"];
export type UnavailableOutcome =
  components["schemas"]["UnavailableOutcomeResponse"];
