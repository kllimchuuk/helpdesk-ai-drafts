import { getJson } from "./api.js";
import {
  STATUSES,
  el,
  flagBadge,
  formatTime,
  showError,
  statusBadge,
} from "./format.js";

const REFRESH_MS = 5000;
const filter = document.getElementById("status-filter");
const counts = document.getElementById("counts");
const rows = document.getElementById("rows");
const message = document.getElementById("message");

function currentStatus() {
  return new URLSearchParams(window.location.search).get("status") || "";
}

function renderFilter(stats) {
  const selected = currentStatus();
  filter.replaceChildren(
    el("option", { text: `all (${stats.total})`, attrs: { value: "" } }),
    ...STATUSES.map((status) =>
      el("option", {
        text: `${status.replaceAll("_", " ")} (${stats.counts[status] ?? 0})`,
        attrs: { value: status },
      }),
    ),
  );
  filter.value = selected;
}

function renderCounts(stats) {
  counts.replaceChildren(
    ...STATUSES.filter((status) => stats.counts[status]).map((status) =>
      el("span", { className: "me-3 text-nowrap" }, [
        statusBadge(status),
        el("span", { className: "ms-1", text: stats.counts[status] }),
      ]),
    ),
  );
}

function renderRow(ticket) {
  const link = el("a", {
    text: ticket.ticket_id,
    attrs: { href: `/ticket.html?id=${encodeURIComponent(ticket.id)}` },
  });
  const flags = [];
  if (ticket.low_confidence) flags.push(flagBadge("low confidence", "text-bg-warning"));
  if (ticket.draft_is_static) flags.push(flagBadge("static", "text-bg-light border"));
  return el("tr", {}, [
    el("td", { className: "text-nowrap", text: formatTime(ticket.created_at) }),
    el("td", {}, [link]),
    el("td", {}, [statusBadge(ticket.status), ...flags]),
    el("td", { className: "preview", text: ticket.message_preview }),
  ]);
}

async function refresh() {
  try {
    const status = currentStatus();
    const query = status ? `?status=${encodeURIComponent(status)}` : "";
    const [stats, list] = await Promise.all([
      getJson("/api/stats"),
      getJson(`/api/tickets${query}`),
    ]);
    renderFilter(stats);
    renderCounts(stats);
    rows.replaceChildren(...list.items.map(renderRow));
    message.replaceChildren(
      list.items.length ? "" : el("p", { className: "text-muted", text: "No tickets." }),
    );
  } catch (error) {
    showError(message, error);
  }
}

filter.addEventListener("change", () => {
  const url = new URL(window.location.href);
  if (filter.value) url.searchParams.set("status", filter.value);
  else url.searchParams.delete("status");
  window.history.replaceState(null, "", url);
  refresh();
});

refresh();
setInterval(refresh, REFRESH_MS);
