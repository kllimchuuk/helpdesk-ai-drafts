const OPERATOR_HEADERS = {
  "X-Requested-By": "operator-ui",
  "Content-Type": "application/json",
};

export class ApiError extends Error {
  constructor(status, body) {
    super(body?.message || `Request failed with HTTP ${status}`);
    this.status = status;
    this.code = body?.code;
    this.payload = body?.payload || {};
  }
}

async function parse(response) {
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(response.status, body);
  }
  return body;
}

export async function getJson(path) {
  return parse(await fetch(path, { credentials: "same-origin" }));
}

export async function postAction(path) {
  return parse(
    await fetch(path, {
      method: "POST",
      credentials: "same-origin",
      headers: OPERATOR_HEADERS,
      body: "{}",
    }),
  );
}
