import http from "k6/http";
import { check, sleep } from "k6";

const BASE = __ENV.BASE_URL;
const ADMIN_LOGIN = __ENV.ADMIN_LOGIN;
const ADMIN_PASSWORD = __ENV.ADMIN_PASSWORD;
const MEETING_ID = __ENV.MEETING_ID;

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

const TARGET_VUS = toInt("TARGET_VUS", 75);
const RAMP_UP_SECONDS = toInt("RAMP_UP_SECONDS", 180);
const STEADY_SECONDS = toInt("STEADY_SECONDS", 480);
const RAMP_DOWN_SECONDS = toInt("RAMP_DOWN_SECONDS", 60);
const THINK_MIN_SECONDS = toInt("THINK_MIN_SECONDS", 10);
const THINK_MAX_SECONDS = toInt("THINK_MAX_SECONDS", 30);
const USER_COUNT = toInt("USER_COUNT", 0);
const USER_START = toInt("USER_START", 1);
const USER_PAD_WIDTH = toInt("USER_PAD_WIDTH", 3);
const USER_PREFIX = __ENV.USER_PREFIX || "participant";
const USER_PASSWORD = __ENV.USER_PASSWORD || ADMIN_PASSWORD;
const REL_LOGIN_PERCENT = Number.parseFloat(__ENV.RELOGIN_PERCENT || "0");

if (USER_COUNT === 0) {
  console.warn(
    "USER_COUNT not set; all VUs share ADMIN_LOGIN. This can produce artificial auth/session failures and is not a realistic capacity test.",
  );
}

const ASSETS = [
  "/static/css/dashboard.css",
  "/static/css/components.css",
  "/static/css/layout_v2.css",
  "/static/js/reliable_actions.js",
  "/static/assets/images/logo-180.png",
  "/static/assets/images/favicon_io/favicon.ico",
];

export const options = {
  scenarios: {
    realistic_classroom_mix: {
      executor: "ramping-vus",
      exec: "realisticClassroomMix",
      startVUs: 0,
      stages: [
        { target: TARGET_VUS, duration: `${RAMP_UP_SECONDS}s` },
        { target: TARGET_VUS, duration: `${STEADY_SECONDS}s` },
        { target: 0, duration: `${RAMP_DOWN_SECONDS}s` },
      ],
      gracefulRampDown: "30s",
    },
  },
};

let cookieReady = false;

function vuCredentials() {
  if (USER_COUNT > 0) {
    const offset = ((__VU - 1) % USER_COUNT) + USER_START;
    const username = `${USER_PREFIX}${String(offset).padStart(USER_PAD_WIDTH, "0")}`;
    return { username, password: USER_PASSWORD };
  }
  return { username: ADMIN_LOGIN, password: ADMIN_PASSWORD };
}

function loginAndSetCookie() {
  const creds = vuCredentials();
  const res = http.post(
    `${BASE}/api/auth/token`,
    JSON.stringify({ username: creds.username, password: creds.password }),
    { headers: { "Content-Type": "application/json" } },
  );
  check(res, { "login 200": (r) => r.status === 200 });

  const token =
    res.cookies.access_token && res.cookies.access_token[0]
      ? res.cookies.access_token[0].value
      : null;

  if (token) {
    http.cookieJar().set(BASE, "access_token", token);
    cookieReady = true;
  }
}

function pollMeetingState() {
  const res = http.get(`${BASE}/api/meetings/${MEETING_ID}/state`);
  check(res, { "state 200": (r) => r.status === 200 });
}

function dashboardAndAssets() {
  const dash = http.get(`${BASE}/dashboard`);
  check(dash, { "dashboard 200": (r) => r.status === 200 });

  for (let i = 0; i < 2; i += 1) {
    const idx = Math.floor(Math.random() * ASSETS.length);
    const path = ASSETS[idx];
    const res = http.get(`${BASE}${path}`);
    check(res, { [`asset ${path} 200`]: (r) => r.status === 200 });
  }
}

function thinkTime() {
  const min = Math.max(0, THINK_MIN_SECONDS);
  const max = Math.max(min, THINK_MAX_SECONDS);
  sleep(min + Math.random() * (max - min));
}

export function realisticClassroomMix() {
  if (!cookieReady) loginAndSetCookie();
  if (!cookieReady) return;

  const roll = Math.random();
  const reloginCutoff = Math.max(0, Math.min(0.3, REL_LOGIN_PERCENT));
  if (roll < 0.65) {
    pollMeetingState();
  } else if (roll < 1 - reloginCutoff) {
    dashboardAndAssets();
  } else {
    loginAndSetCookie();
  }

  thinkTime();
}
