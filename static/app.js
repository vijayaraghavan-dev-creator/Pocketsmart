const inr = n => "₹" + Number(n).toLocaleString("en-IN");
function el(t, c, x) { const e = document.createElement(t); if (c) e.className = c; if (x !== undefined) e.textContent = x; return e; }
function renderResult(box, d) {
  box.replaceChildren(el("h3", "", d.summary || "Your plan"));
  if (d.fallback) box.append(el("p", "note", "AI was unavailable, so these are default suggestions."));
  const grid = el("div", "grid");
  (d.items || []).forEach(i => {
    const c = el("div", "card");
    c.append(el("span", "tag", i.category), el("h4", "", i.name), el("p", "price", inr(i.price)), el("p", "note", i.reason));
    const a = el("a", "btn small", "View on " + i.platform); a.href = i.link; a.target = "_blank"; a.rel = "noopener";
    c.append(a); grid.append(c);
  });
  box.append(grid, el("p", "total", `Total ${inr(d.total)} of ${inr(d.budget)} budget · Remaining ${inr(d.budget - d.total)}`));
  (d.tips || []).forEach(t => box.append(el("p", "tip", "💡 " + t)));
}
function initPlanner(formId, endpoint) {
  const f = document.getElementById(formId), box = document.getElementById("result"), btn = f.querySelector("button");
  f.addEventListener("submit", async e => {
    e.preventDefault(); btn.disabled = true; btn.textContent = "Thinking…";
    box.replaceChildren(el("p", "note", "Generating recommendations…"));
    try {
      const r = await fetch(endpoint, { method: "POST", body: new FormData(f) });
      if (r.status === 401) { location = "/login"; return; }
      const d = await r.json();
      if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : "Please fill all fields correctly.");
      renderResult(box, d); box.scrollIntoView({ behavior: "smooth" });
    } catch (err) { box.replaceChildren(el("p", "error", err.message)); }
    finally { btn.disabled = false; btn.textContent = "Get recommendations"; }
  });
}
async function showHistory(id) {
  const box = document.getElementById("result");
  const r = await fetch("/recommendations-details?id=" + id);
  if (r.ok) { renderResult(box, await r.json()); box.scrollIntoView({ behavior: "smooth" }); }
}
