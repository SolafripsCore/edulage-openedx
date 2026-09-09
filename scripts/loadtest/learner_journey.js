// k6 learner-journey load test against the LMS (run from outside the droplet).
//
//   LOAD_PASSWORD=... ~/bin/k6 run -e HOST=https://learn.edulage.org -e USERS=20 \
//       -e STAGES=2m:10,3m:30,3m:60,1m:0 scripts/loadtest/learner_journey.js
//
// Each virtual user signs in as one of the loadtest-NN learners (scripts/loadtest/seed_load_users.py)
// and then loops through the pages a learner actually hits: My learning (plugin dashboard API +
// learner-home init), course outline, a rendered unit (/xblock), progress. Think time 2–5 s.
import http from "k6/http";
import { check, sleep } from "k6";
import { Trend, Rate } from "k6/metrics";

const HOST = __ENV.HOST || "https://learn.edulage.org";
const USERS = parseInt(__ENV.USERS || "20", 10);
const COURSE = __ENV.COURSE || "course-v1:UNIA+CS101+2026";
const PASSWORD = __ENV.LOAD_PASSWORD;

const stages = (__ENV.STAGES || "1m:10,2m:30,1m:0").split(",").map((s) => {
  const [duration, target] = s.split(":");
  return { duration, target: parseInt(target, 10) };
});

export const options = {
  scenarios: { learners: { executor: "ramping-vus", startVUs: 0, stages, gracefulRampDown: "20s" } },
  thresholds: {
    http_req_failed: ["rate<0.01"],
    "http_req_duration{page:dashboard}": ["p(95)<1500"],
    "http_req_duration{page:outline}": ["p(95)<1500"],
    "http_req_duration{page:unit}": ["p(95)<2500"],
    "http_req_duration{page:progress}": ["p(95)<2500"],
  },
};

const pageTrend = {};
for (const p of ["login", "dashboard", "outline", "unit", "progress"]) pageTrend[p] = new Trend(`page_${p}`, true);
const loginOk = new Rate("login_ok");

function login(username) {
  const csrf = http.get(`${HOST}/csrf/api/v1/token`).json("csrfToken");
  const r = http.post(
    `${HOST}/api/user/v2/account/login_session/`,
    { email_or_username: username, password: PASSWORD },
    { headers: { "X-CSRFToken": csrf, Referer: `${HOST}/login` }, tags: { page: "login" } }
  );
  pageTrend.login.add(r.timings.duration);
  const ok = r.status === 200 && r.json("success") === true;
  loginOk.add(ok);
  return ok;
}

// outline lists chapters/sequentials only; the first unit comes from the sequence metadata
// (the same call the learning MFE makes when opening a section)
function firstUnit(outline) {
  const blocks = outline.course_blocks && outline.course_blocks.blocks;
  if (!blocks) return null;
  for (const id in blocks) {
    if (blocks[id].type !== "sequential") continue;
    const r = http.get(`${HOST}/api/courseware/sequence/${id}`, { tags: { page: "outline" } });
    if (r.status === 200 && r.json("items.0.id")) return r.json("items.0.id");
  }
  return null;
}

export default function () {
  const username = `loadtest-${String(((__VU - 1) % USERS) + 1).padStart(2, "0")}`;
  if (!login(username)) {
    sleep(5);
    return;
  }
  let unit = null;
  for (let i = 0; i < 6; i++) {
    let r = http.get(`${HOST}/edulage/api/v1/dashboard/courses/`, { tags: { page: "dashboard" } });
    check(r, { "dashboard 200": (x) => x.status === 200 });
    pageTrend.dashboard.add(r.timings.duration);
    http.get(`${HOST}/api/learner_home/init`, { tags: { page: "dashboard" } });
    sleep(2 + Math.random() * 3);

    r = http.get(`${HOST}/api/course_home/outline/${COURSE}`, { tags: { page: "outline" } });
    check(r, { "outline 200": (x) => x.status === 200 });
    pageTrend.outline.add(r.timings.duration);
    if (r.status === 200 && !unit) unit = firstUnit(r.json());
    sleep(2 + Math.random() * 3);

    if (unit) {
      r = http.get(`${HOST}/xblock/${unit}?show_title=0&show_bookmark_button=0`, { tags: { page: "unit" } });
      check(r, { "unit 200": (x) => x.status === 200 });
      pageTrend.unit.add(r.timings.duration);
      sleep(3 + Math.random() * 4);
    }

    r = http.get(`${HOST}/api/course_home/progress/${COURSE}`, { tags: { page: "progress" } });
    check(r, { "progress 200": (x) => x.status === 200 });
    pageTrend.progress.add(r.timings.duration);
    sleep(2 + Math.random() * 3);
  }
  http.post(`${HOST}/logout`, null, { redirects: 0 });
}

export function handleSummary(data) {
  const m = data.metrics;
  const pct = (name, p) => (m[name] ? Math.round(m[name].values[p]) : null);
  const out = {
    stages,
    users: USERS,
    requests: m.http_reqs.values.count,
    failed_rate: m.http_req_failed.values.rate,
    login_ok: m.login_ok ? m.login_ok.values.rate : null,
    pages: {},
  };
  for (const p of Object.keys(pageTrend)) out.pages[p] = { p50: pct(`page_${p}`, "med"), p95: pct(`page_${p}`, "p(95)"), max: pct(`page_${p}`, "max") };
  return { stdout: JSON.stringify(out, null, 2) + "\n", [`${__ENV.OUT || "/tmp/k6-summary"}.json`]: JSON.stringify(data) };
}
