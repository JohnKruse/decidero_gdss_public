import http from "k6/http";
import { check, sleep } from "k6";

const BASE = __ENV.BASE_URL;
const ADMIN_LOGIN = __ENV.ADMIN_LOGIN;
const ADMIN_PASSWORD = __ENV.ADMIN_PASSWORD;

if (!BASE) throw new Error("Missing BASE_URL");
if (!ADMIN_LOGIN) throw new Error("Missing ADMIN_LOGIN");
if (!ADMIN_PASSWORD) throw new Error("Missing ADMIN_PASSWORD");

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
    static_asset_drag: {
      executor: "constant-vus",
      exec: "staticAssetDrag",
      vus: 90,
      duration: "2m",
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

export function staticAssetDrag() {
  const token = loginAndSetCookie();
  if (!token) return;

  const dash = http.get(`${BASE}/dashboard`);
  check(dash, { "dashboard 200": (r) => r.status === 200 });

  for (const path of ASSETS) {
    const res = http.get(`${BASE}${path}`);
    check(res, { [`asset ${path} 200`]: (r) => r.status === 200 });
  }

  sleep(1);
}
