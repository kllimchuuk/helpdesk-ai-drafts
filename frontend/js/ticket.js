import { getJson, postAction } from "./api.js";
import {
  el,
  flagBadge,
  formatTime,
  safeHref,
  showError,
  statusBadge,
} from "./format.js";

const content = document.getElementById("content");
const notice = document.getElementById("notice");
const ticketId = new URLSearchParams(window.location.search).get("id") || "";
const path = `/api/tickets/${encodeURIComponent(ticketId)}`;

function field(label, value) {
  return el("div", { className: "mb-3" }, [
    el("div", { className: "text-muted small", text: label }),
    value instanceof Node ? value : el("div", { text: value ?? "—" }),
  ]);
}

function textBlock(text) {
  return el("div", { className: "border rounded bg-white p-3 text-block", text: text ?? "—" });
}

function sourcesList(sources) {
  if (!sources?.length) return el("div", { text: "—" });
  return el(
    "ul",
    { className: "mb-0" },
    sources.map((source) => {
      const href = safeHref(source.url);
      const item = href
        ? el("a", { text: source.title, attrs: { href, target: "_blank", rel: "noopener noreferrer" } })
        : el("span", { text: source.title });
      return el("li", {}, [item]);
    }),
  );
}

function conflictText(error) {
  if (error.code !== "ticket_status_conflict") return error.message;
  if (error.payload.status === "draft_ready") {
    return "A new draft has just arrived. Read it before you approve or reject.";
  }
  return `Someone already changed this ticket (now ${error.payload.status.replaceAll("_", " ")}).`;
}

const ACTIONS = {
  draft_ready: [
    { action: "approve", label: "Approve", className: "btn btn-success me-2" },
    { action: "reject", label: "Reject", className: "btn btn-outline-danger" },
  ],
  send_unknown: [
    { action: "mark-delivered", label: "Mark delivered", className: "btn btn-success me-2" },
    { action: "resend", label: "Resend", className: "btn btn-outline-warning" },
  ],
};

function actions(ticket) {
  const choices = ACTIONS[ticket.status];
  if (!choices) return [];
  const buttons = choices.map(({ label, className }) =>
    el("button", { className, text: label, attrs: { type: "button" } }),
  );
  const run = async (action) => {
    for (const button of buttons) button.disabled = true;
    try {
      await postAction(`${path}/${action}`);
      notice.replaceChildren();
    } catch (error) {
      const text = conflictText(error);
      notice.replaceChildren(el("div", { className: "alert alert-warning", text }));
    }
    await load();
  };
  choices.forEach(({ action }, index) => {
    buttons[index].addEventListener("click", () => run(action));
  });
  return [el("div", { className: "mt-4" }, buttons)];
}

function render(ticket) {
  const flags = [];
  if (ticket.low_confidence) flags.push(flagBadge("low confidence: no KB article matched", "text-bg-warning"));
  if (ticket.draft_is_static) flags.push(flagBadge("static reply: the model was not used", "text-bg-light border"));
  const warnings = [];
  if (ticket.status === "send_unknown") {
    warnings.push(
      el("div", {
        className: "alert alert-warning",
        text:
          "The reply may already have reached the customer. Check the helpdesk: " +
          "Mark delivered if it is there, Resend only if it is not.",
      }),
    );
  }
  content.replaceChildren(
    el("h1", { className: "h4 mb-3" }, [
      el("span", { className: "me-2", text: `Ticket ${ticket.ticket_id}` }),
      statusBadge(ticket.status),
      ...flags,
    ]),
    ...warnings,
    el("div", { className: "row" }, [
      el("div", { className: "col-md-4" }, [
        field("Customer", ticket.customer_email),
        field("Event", ticket.event_id),
        field("Received", formatTime(ticket.created_at)),
        field("Reviewed", formatTime(ticket.reviewed_at)),
        field("Sent", formatTime(ticket.sent_at)),
        field("Attempts", `generation ${ticket.gen_attempts}, sending ${ticket.send_attempts}`),
        field("Last error", ticket.last_error),
      ]),
      el("div", { className: "col-md-8" }, [
        field("Customer message", textBlock(ticket.message)),
        field("Draft reply", textBlock(ticket.draft_text)),
        field("Sources", sourcesList(ticket.draft_sources)),
        ...actions(ticket),
      ]),
    ]),
  );
}

async function load() {
  try {
    render(await getJson(path));
  } catch (error) {
    showError(content, error);
  }
}

load();
