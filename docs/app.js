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
  </article>`;
}

function renderCard(tweet) {
  return `<article class="card">
    <div class="card-meta">${escapeHtml(tweet.date)} · ${formatCounts(tweet.likes, tweet.rts)}</div>
    <p class="card-text">${linkify(tweet.text)}</p>
    ${mediaHtml(tweet.media || [])}
  </article>`;
}

function formatNumber(value) {
  return Number(value).toLocaleString("en-US");
}

async function renderIntro() {
  const box = el("intro");
  if (!box) return;
  const stats = await loadJson("data/stats.json");
  box.innerHTML = `
    <p>I started posting on Twitter in December of 2015. I wrote ${formatNumber(stats.tweets)} tweets. ${formatNumber(stats.non_thread_replies)} were non-thread replies. ${formatNumber(stats.dms)} DMs with ${formatNumber(stats.dm_people)} people. Total likes ${formatNumber(stats.likes)}. Total retweets ${formatNumber(stats.retweets_received)}. I posted ${formatNumber(stats.pictures)} pictures, replied to ${formatNumber(stats.people_replied_to)} people, and ${formatNumber(stats.followers)} people followed along. And I met countless friends.</p>
    <p>I'm currently writing a newsletter at <a href="https://cutlefish.substack.com/" rel="noreferrer">cutlefish.substack.com</a>.</p>
    <p>Here are some of the more popular threads and standalone tweets.</p>
  `;
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
  const years = [...new Set(index.threads.map((t) => t.year))].sort((a, b) => a - b);
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
      .sort((a, b) => a.date.localeCompare(b.date) || a.id.localeCompare(b.id));
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
      const shell = readerEl.closest(".thread-shell");
      if (shell && (shell.getBoundingClientRect().top < 0 || window.innerWidth < 841)) {
        shell.scrollIntoView({ block: "start" });
      }
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
  const years = index.years.slice().sort((a, b) => a - b);
  let year = Number((index.default || "").split("-")[0] || years[0]);
  let month = Number((index.default || "").split("-")[1] || 1);
  const requested = hashValue();
  const match = requested.match(/^(\d{4})-(\d{2})$/);
  if (match && years.includes(Number(match[1]))) {
    year = Number(match[1]);
    month = Number(match[2]);
  }

  const yearEl = el("tweet-years");
  const monthEl = el("month-list");
  const list = el("tweet-list");
  const sortRow = el("sort-row");
  let currentTweets = [];
  let sortBy = "date";

  function monthsForYear() {
    return index.calendar[String(year)] || [];
  }

  function firstMonthWithPosts() {
    const found = monthsForYear().findIndex((info) => info.count);
    return found >= 0 ? found + 1 : 1;
  }

  function drawNav() {
    yearEl.innerHTML = years
      .map(
        (y) =>
          `<button type="button" data-year="${y}" class="${y === year ? "active" : ""}">${y}</button>`
      )
      .join("");
    monthEl.innerHTML = monthsForYear()
      .map((info, i) => {
        const empty = !info.count;
        const active = !empty && i + 1 === month;
        const count = empty ? "" : `<span class="n">${info.count}</span>`;
        return `<button type="button" data-month="${i + 1}" class="${active ? "active" : ""}" ${empty ? "disabled" : ""}>
          ${MONTHS[i]}${count}
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
    drawNav();
    list.innerHTML = `<p class="status">Loading…</p>`;
    const payload = await loadJson(`data/tweets-${key}.json`);
    currentTweets = payload.tweets;
    drawList();
    const nav = document.querySelector(".tweet-nav");
    if (nav && nav.getBoundingClientRect().top < 0) {
      nav.scrollIntoView({ block: "start" });
    }
  }

  yearEl.addEventListener("click", (event) => {
    const btn = event.target.closest("button");
    if (!btn) return;
    year = Number(btn.dataset.year);
    openMonth(year, firstMonthWithPosts());
  });

  monthEl.addEventListener("click", (event) => {
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

  const cell = monthsForYear()[month - 1];
  if (cell && cell.count) {
    openMonth(year, month);
  } else {
    drawNav();
    list.innerHTML = `<p class="status">Pick a month with posts.</p>`;
  }
}

const page = document.body.dataset.page;
renderIntro().catch(() => {});
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
