import http from "k6/http";
import { check, sleep } from "k6";

const BASE = __ENV.BASE_URL;
const ADMIN_LOGIN = __ENV.ADMIN_LOGIN;
const ADMIN_PASSWORD = __ENV.ADMIN_PASSWORD;
const MEETING_ID = __ENV.MEETING_ID;
const USER_PREFIX = __ENV.USER_PREFIX || "participant";
const USER_PASSWORD = __ENV.USER_PASSWORD || ADMIN_PASSWORD;

if (!BASE) throw new Error("Missing BASE_URL");
if (!ADMIN_LOGIN) throw new Error("Missing ADMIN_LOGIN");
if (!ADMIN_PASSWORD) throw new Error("Missing ADMIN_PASSWORD");
if (!MEETING_ID) throw new Error("Missing MEETING_ID");

function toInt(name, fallback) {
  const raw = __ENV[name];
  if (!raw) return fallback;
  const parsed = Number.parseInt(raw, 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

const VUS = toInt("TARGET_VUS", 50);
const ITERATIONS_PER_VU = toInt("ITERATIONS_PER_VU", 2);
const USER_COUNT = toInt("USER_COUNT", VUS);
const USER_START = toInt("USER_START", 1);
const USER_PAD_WIDTH = toInt("USER_PAD_WIDTH", 2);
const THINK_MIN_SECONDS = toInt("THINK_MIN_SECONDS", 1);
const THINK_MAX_SECONDS = toInt("THINK_MAX_SECONDS", 3);
const TEST_TAG = __ENV.TEST_TAG || `WRITEBURST-${Date.now()}`;

export const options = {
  noCookiesReset: true,
  scenarios: {
    brainstorm_write_burst: {
      executor: "per-vu-iterations",
      vus: VUS,
      iterations: ITERATIONS_PER_VU,
      maxDuration: "10m",
      exec: "submitIdeaBurst",
    },
  },
};

function adminLoginAndSetCookie() {
  const res = http.post(
    `${BASE}/api/auth/token`,
    JSON.stringify({ username: ADMIN_LOGIN, password: ADMIN_PASSWORD }),
    { headers: { "Content-Type": "application/json" } },
  );
  check(res, { "admin login 200": (r) => r.status === 200 });
  const token =
    res.cookies.access_token && res.cookies.access_token[0]
      ? res.cookies.access_token[0].value
      : null;
  if (token) {
    http.cookieJar().set(BASE, "access_token", token);
  }
  return token;
}

function findBrainstormActivityId() {
  const meetingRes = http.get(`${BASE}/api/meetings/${MEETING_ID}`);
  check(meetingRes, { "meeting read 200": (r) => r.status === 200 });
  if (meetingRes.status !== 200) return null;

  const body = meetingRes.json();
  const agenda = body.agenda || [];
  for (let i = 0; i < agenda.length; i += 1) {
    const row = agenda[i];
    if ((row.tool_type || "").toLowerCase() === "brainstorming") {
      return row.activity_id || row.activityId || null;
    }
  }
  return null;
}

function ensureBrainstormRunning(activityId) {
  const stateRes = http.get(`${BASE}/api/meetings/${MEETING_ID}/state`);
  check(stateRes, { "admin state 200": (r) => r.status === 200 });
  if (stateRes.status !== 200) return;

  const state = stateRes.json();
  const alreadyRunning =
    (state.currentTool || "").toLowerCase() === "brainstorming" &&
    (state.currentActivity || "") === activityId;
  if (alreadyRunning) return;

  const controlRes = http.post(
    `${BASE}/api/meetings/${MEETING_ID}/control`,
    JSON.stringify({
      action: "start_tool",
      tool: "brainstorming",
      activityId: activityId,
    }),
    { headers: { "Content-Type": "application/json" } },
  );
  check(controlRes, {
    "start brainstorming accepted": (r) => r.status === 200 || r.status === 409,
  });
}

export function setup() {
  const token = adminLoginAndSetCookie();
  if (!token) throw new Error("Admin login failed in setup");

  const activityId = findBrainstormActivityId();
  if (!activityId) throw new Error("No brainstorming activity found in meeting agenda");

  ensureBrainstormRunning(activityId);
  return { activityId, testTag: TEST_TAG };
}

function participantLogin(vu) {
  const offset = ((vu - 1) % USER_COUNT) + USER_START;
  const username = `${USER_PREFIX}${String(offset).padStart(USER_PAD_WIDTH, "0")}`;

  const res = http.post(
    `${BASE}/api/auth/token`,
    JSON.stringify({ username, password: USER_PASSWORD }),
    { headers: { "Content-Type": "application/json" } },
  );
  check(res, { "participant login 200": (r) => r.status === 200 });

  const token =
    res.cookies.access_token && res.cookies.access_token[0]
      ? res.cookies.access_token[0].value
      : null;
  if (token) {
    http.cookieJar().set(BASE, "access_token", token);
  }
  return { token, username };
}

let loggedIn = false;
let cachedUsername = null;

export function submitIdeaBurst(data) {
  if (!loggedIn) {
    const auth = participantLogin(__VU);
    loggedIn = Boolean(auth.token);
    cachedUsername = auth.username;
  }
  if (!loggedIn) return;

  const idem = `${data.testTag}-vu${__VU}-it${__ITER}-${Date.now()}`;
  const payload = {
    content: `${data.testTag} idea from ${cachedUsername} vu=${__VU} it=${__ITER}`,
    submitted_name: cachedUsername,
    metadata: { source: "k6_write_burst", test_tag: data.testTag, vu: __VU, iter: __ITER },
  };

  const res = http.post(
    `${BASE}/api/meetings/${MEETING_ID}/brainstorming/ideas?activity_id=${encodeURIComponent(data.activityId)}`,
    JSON.stringify(payload),
    {
      headers: {
        "Content-Type": "application/json",
        "X-Idempotency-Key": idem,
      },
    },
  );

  check(res, {
    "idea submit 201": (r) => r.status === 201,
    "idea submit no auth errors": (r) => r.status !== 401,
    "idea submit no 5xx": (r) => r.status < 500,
  });

  const min = Math.max(0, THINK_MIN_SECONDS);
  const max = Math.max(min, THINK_MAX_SECONDS);
  sleep(min + Math.random() * (max - min));
}
