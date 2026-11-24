/*
 * Failure types shared by the HTTP layer and the views.
 */

/** Normalised failure carrying the C1 error code so views can map it to copy. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;
  readonly details: Record<string, unknown>;

  constructor(
    status: number,
    code: string,
    message: string,
    requestId: string | null = null,
    details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.details = details;
  }
}

/** Raised when a request was cancelled by the caller (route change, unmount). */
export class AbortedError extends Error {
  constructor() {
    super("request aborted");
    this.name = "AbortedError";
  }
}
