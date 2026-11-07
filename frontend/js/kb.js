import { getJson } from "./api.js";
import { el, showError } from "./format.js";

const content = document.getElementById("content");
const HEADING = /^(#{2,4})\s+(.*)$/;
const BULLET = /^[-*]\s+(.*)$/;
const NUMBERED = /^\d+[.)]\s+(.*)$/;

function slugFromLocation() {
  const match = window.location.pathname.match(/^\/kb\/([^/]+)$/);
  if (match) return decodeURIComponent(match[1]);
  return new URLSearchParams(window.location.search).get("slug") || "";
}

// Only headings, lists and paragraphs, each built as a DOM node with textContent:
// the article never becomes HTML, so no sanitiser is needed.
function renderMarkdown(text) {
  const blocks = [];
  let list = null;
  let paragraph = [];
  const flushParagraph = () => {
    if (paragraph.length) blocks.push(el("p", { text: paragraph.join(" ") }));
    paragraph = [];
  };
  const addItem = (tag, itemText) => {
    flushParagraph();
    if (!list || list.tagName.toLowerCase() !== tag) {
      list = el(tag, { className: "mb-3" });
      blocks.push(list);
    }
    list.append(el("li", { text: itemText }));
  };
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    const heading = line.match(HEADING);
    const bullet = line.match(BULLET);
    const numbered = line.match(NUMBERED);
    if (heading) {
      flushParagraph();
      list = null;
      blocks.push(el(`h${heading[1].length + 1}`, { className: "h5 mt-4", text: heading[2] }));
    } else if (bullet) {
      addItem("ul", bullet[1]);
    } else if (numbered) {
      addItem("ol", numbered[1]);
    } else if (line) {
      list = null;
      paragraph.push(line);
    } else {
      flushParagraph();
      list = null;
    }
  }
  flushParagraph();
  return blocks;
}

async function load() {
  try {
    const article = await getJson(`/api/kb/${encodeURIComponent(slugFromLocation())}`);
    document.title = article.title;
    content.replaceChildren(
      el("h1", { className: "h3 mb-4", text: article.title }),
      ...renderMarkdown(article.body),
    );
  } catch (error) {
    showError(content, error);
  }
}

load();
