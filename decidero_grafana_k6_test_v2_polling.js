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

export const options = {
  scenarios: {
    polling_storm: {
      executor: "constant-vus",
      exec: "pollingStorm",
      vus: 90,
      duration: "3m",
    },
  },
};

function loginAndSetCookie() {
  const res = http.post(
    `${BASE}/api/auth/token`,
    JSON.stringify({ username: ADMIN_LOGIN, password: ADMIN_PASSWORD }),
    { headers: { "Content-Type": "application/json" } },
  );
  check(res, { "login 200": (r) => r.status === 200 });

  const token =
    res.cookies.access_token && res.cookies.access_token[0]
      ? res.cookies.access_token[0].value
      : null;

  if (token) {
    http.cookieJar().set(BASE, "access_token", token);
  }
  return token;
}

export function pollingStorm() {
  const token = loginAndSetCookie();
  if (!token) return;

  const res = http.get(`${BASE}/api/meetings/${MEETING_ID}/state`);
  check(res, {
    "state 200": (r) => r.status === 200,
  });

  sleep(2 + Math.random() * 3);
}
