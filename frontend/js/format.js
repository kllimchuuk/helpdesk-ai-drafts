// Every value from the API is untrusted (customer text, drafts, KB articles), so
// elements are built with textContent and never from HTML strings.

export const STATUSES = [
  "received",
  "generating",
  "draft_ready",
  "approved",
  "sending",
  "sent",
  "rejected",
  "generation_failed",
  "send_failed",
  "send_unknown",
];

const BADGES = {
  received: "text-bg-secondary",
  generating: "text-bg-info",
  draft_ready: "text-bg-primary",
  approved: "text-bg-success",
  sending: "text-bg-info",
  sent: "text-bg-success",
  rejected: "text-bg-dark",
  generation_failed: "text-bg-danger",
  send_failed: "text-bg-danger",
  send_unknown: "text-bg-warning",
};

export function el(tag, { className, text, attrs } = {}, children = []) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  for (const [name, value] of Object.entries(attrs || {})) {
    node.setAttribute(name, value);
  }
  for (const child of children) node.append(child);
  return node;
}

export function statusBadge(status) {
  return el("span", {
    className: `badge ${BADGES[status] || "text-bg-light"}`,
    text: status.replaceAll("_", " "),
  });
}

export function flagBadge(text, className) {
  return el("span", { className: `badge ${className} ms-1`, text });
}

export function formatTime(value) {
  return value ? new Date(value).toLocaleString() : "—";
}

export function safeHref(url) {
  try {
    const parsed = new URL(url, window.location.origin);
    return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : null;
  } catch {
    return null;
  }
}

export function showError(container, error) {
  container.replaceChildren(
    el("div", { className: "alert alert-danger", text: error.message }),
  );
}
