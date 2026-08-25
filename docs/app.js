const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

function el(id) {
  return document.getElementById(id);
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function linkify(text) {
  const escaped = escapeHtml(text);
  return escaped.replace(
    /(https?:\/\/[^\s<]+)/g,
    '<a href="$1" rel="noreferrer">$1</a>'
  );
}

function liveUrl(id) {
  return `https://twitter.com/johncutlefish/status/${id}`;
}

function formatCounts(likes, rts) {
  return `${likes.toLocaleString()} likes · ${rts.toLocaleString()} RTs`;
}

function mediaHtml(paths) {
  return paths
    .map((src) => {
      const lower = src.toLowerCase();
      if (lower.endsWith(".mp4")) {
        return `<video controls src="${escapeHtml(src)}"></video>`;
      }
      return `<img src="${escapeHtml(src)}" alt="">`;
    })
    .join("");
}

function renderPost(tweet) {
  return `<article class="post">
    <div class="post-meta">${escapeHtml(tweet.date)} · ${formatCounts(tweet.likes, tweet.rts)}</div>
    <p class="post-text">${linkify(tweet.text)}</p>
    ${mediaHtml(tweet.media || [])}
    <a class="live" href="${liveUrl(tweet.id)}">Open on X</a>
  </article>`;
}

function renderCard(tweet) {
  return `<article class="card">
    <div class="card-meta">${escapeHtml(tweet.date)} · ${formatCounts(tweet.likes, tweet.rts)}</div>
    <p class="card-text">${linkify(tweet.text)}</p>
    ${mediaHtml(tweet.media || [])}
    <a class="live" href="${liveUrl(tweet.id)}">Open on X</a>
  </article>`;
}

function hashValue() {
  return decodeURIComponent((location.hash || "").replace(/^#\/?/, ""));
}

async function loadJson(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`Failed to load ${path}`);
  return res.json();
}

async function initThreads() {
  const index = await loadJson("data/threads-index.json");
  const years = [...new Set(index.threads.map((t) => t.year))].sort((a, b) => b - a);
  const requested = hashValue();
  const requestedThread = index.threads.find((t) => t.id === requested);
  let year = (requestedThread || index.threads[0] || {}).year || years[0];

  const yearEl = el("thread-years");
  const pickerEl = el("picker");
  const readerEl = el("reader");

  function threadsInYear() {
    return index.threads
      .filter((t) => t.year === year)
      .slice()
      .sort((a, b) => b.likes - a.likes);
  }

  let loadToken = 0;
  async function openThread(id) {
    const token = ++loadToken;
    if (location.hash !== `#/${id}`) {
      history.replaceState(null, "", `#/${id}`);
    }
    for (const btn of pickerEl.querySelectorAll("button")) {
      btn.classList.toggle("active", btn.dataset.id === id);
    }
    readerEl.innerHTML = `<p class="status">Loading…</p>`;
    try {
      const payload = await loadJson(`data/threads/${id}.json`);
      if (token !== loadToken) return;
      readerEl.innerHTML = payload.tweets.map(renderPost).join("");
    } catch (err) {
      if (token !== loadToken) return;
      readerEl.innerHTML = `<p class="status">${escapeHtml(err.message)}</p>`;
    }
  }

  function drawPicker() {
    yearEl.innerHTML = years
      .map(
        (y) =>
          `<button type="button" data-year="${y}" class="${y === year ? "active" : ""}">${y}</button>`
      )
      .join("");
    pickerEl.innerHTML = threadsInYear()
      .map(
        (t) => `<button type="button" data-id="${t.id}">
          <span class="meta">${t.date} · ${t.n} tweets · ${t.likes.toLocaleString()} likes</span>
          ${escapeHtml(t.excerpt)}
        </button>`
      )
      .join("");
  }

  yearEl.addEventListener("click", (event) => {
    const btn = event.target.closest("button");
    if (!btn) return;
    year = Number(btn.dataset.year);
    drawPicker();
    const first = threadsInYear()[0];
    if (first) openThread(first.id);
  });

  pickerEl.addEventListener("click", (event) => {
    const btn = event.target.closest("button");
    if (!btn) return;
    openThread(btn.dataset.id);
  });

  window.addEventListener("hashchange", () => {
    const id = hashValue();
    const found = index.threads.find((t) => t.id === id);
    if (found) {
      year = found.year;
      drawPicker();
      openThread(found.id);
    }
  });

  drawPicker();
  const initial = requestedThread || index.threads[0];
  if (initial) openThread(initial.id);
}

async function initTweets() {
  const index = await loadJson("data/tweets-index.json");
  const years = index.years;
  let year = Number((index.default || "").split("-")[0] || years[years.length - 1]);
  let month = Number((index.default || "").split("-")[1] || 1);
  const requested = hashValue();
  const match = requested.match(/^(\d{4})-(\d{2})$/);
  if (match && years.includes(Number(match[1]))) {
    year = Number(match[1]);
    month = Number(match[2]);
  }

  const yearLabel = el("year-label");
  const prevBtn = el("prev-year");
  const nextBtn = el("next-year");
  const grid = el("month-grid");
  const list = el("tweet-list");
  const sortRow = el("sort-row");
  let currentTweets = [];
  let sortBy = "date";

  function yearIndex() {
    return years.indexOf(year);
  }

  function drawYear() {
    yearLabel.textContent = String(year);
    prevBtn.disabled = yearIndex() <= 0;
    nextBtn.disabled = yearIndex() >= years.length - 1;
    const months = index.calendar[String(year)] || [];
    grid.innerHTML = months
      .map((info, i) => {
        const empty = !info.count;
        const active = !empty && i + 1 === month;
        const classes = ["month-cell", empty ? "empty" : "", active ? "active" : ""]
          .filter(Boolean)
          .join(" ");
        const count = empty ? "" : `<span class="count">${info.count}</span>`;
        return `<button type="button" class="${classes}" data-month="${i + 1}" ${empty ? "disabled" : ""}>
          <span class="name">${MONTHS[i]}</span>${count}
        </button>`;
      })
      .join("");
  }

  function drawList() {
    const items = currentTweets.slice().sort((a, b) => {
      if (sortBy === "likes") return b.likes - a.likes;
      return b.datetime.localeCompare(a.datetime);
    });
    list.innerHTML = items.map(renderCard).join("") || `<p class="status">No posts this month.</p>`;
    for (const btn of sortRow.querySelectorAll("button")) {
      btn.classList.toggle("active", btn.dataset.sort === sortBy);
    }
  }

  async function openMonth(nextYear, nextMonth) {
    year = nextYear;
    month = nextMonth;
    const key = `${year}-${String(month).padStart(2, "0")}`;
    if (location.hash !== `#/${key}`) {
      history.replaceState(null, "", `#/${key}`);
    }
    drawYear();
    list.innerHTML = `<p class="status">Loading…</p>`;
    const payload = await loadJson(`data/tweets-${key}.json`);
    currentTweets = payload.tweets;
    drawList();
  }

  prevBtn.addEventListener("click", () => {
    const i = yearIndex();
    if (i > 0) {
      year = years[i - 1];
      const months = index.calendar[String(year)] || [];
      const first = months.findIndex((m) => m.count);
      month = first >= 0 ? first + 1 : 1;
      if (first >= 0) openMonth(year, month);
      else drawYear();
    }
  });

  nextBtn.addEventListener("click", () => {
    const i = yearIndex();
    if (i < years.length - 1) {
      year = years[i + 1];
      const months = index.calendar[String(year)] || [];
      const first = months.findIndex((m) => m.count);
      month = first >= 0 ? first + 1 : 1;
      if (first >= 0) openMonth(year, month);
      else drawYear();
    }
  });

  grid.addEventListener("click", (event) => {
    const btn = event.target.closest("button");
    if (!btn || btn.disabled) return;
    openMonth(year, Number(btn.dataset.month));
  });

  sortRow.addEventListener("click", (event) => {
    const btn = event.target.closest("button");
    if (!btn) return;
    sortBy = btn.dataset.sort;
    drawList();
  });

  window.addEventListener("hashchange", () => {
    const next = hashValue().match(/^(\d{4})-(\d{2})$/);
    if (next) openMonth(Number(next[1]), Number(next[2]));
  });

  const cell = (index.calendar[String(year)] || [])[month - 1];
  if (cell && cell.count) {
    openMonth(year, month);
  } else {
    drawYear();
    list.innerHTML = `<p class="status">Pick a month with posts.</p>`;
  }
}

const page = document.body.dataset.page;
if (page === "threads") {
  initThreads().catch((err) => {
    const reader = document.getElementById("reader");
    if (reader) reader.innerHTML = `<p class="status">${escapeHtml(err.message)}</p>`;
  });
}
if (page === "tweets") {
  initTweets().catch((err) => {
    const list = document.getElementById("tweet-list");
    if (list) list.innerHTML = `<p class="status">${escapeHtml(err.message)}</p>`;
  });
}
