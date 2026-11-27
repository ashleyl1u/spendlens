import { ApiError } from "./api";

/** The longest question the backend accepts (AskRequest in routers/assistant.py). */
export const MAX_QUESTION = 500;

/** A clear message for a failed question. */
export function askErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 503) {
    return "The assistant is unavailable right now. Please try again in a minute.";
  }
  if (error instanceof ApiError && error.status === 422) {
    return `Questions can be up to ${MAX_QUESTION} characters and can't be blank.`;
  }
  return error instanceof Error ? error.message : "Something went wrong. Please try again.";
}
