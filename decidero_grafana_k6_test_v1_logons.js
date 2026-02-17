import http from "k6/http";
import { check } from "k6";

const BASE = __ENV.BASE_URL;
const ADMIN_LOGIN = __ENV.ADMIN_LOGIN;
const ADMIN_PASSWORD = __ENV.ADMIN_PASSWORD;

if (!BASE) throw new Error("Missing BASE_URL");
if (!ADMIN_LOGIN) throw new Error("Missing ADMIN_LOGIN");
if (!ADMIN_PASSWORD) throw new Error("Missing ADMIN_PASSWORD");

export const options = {
  scenarios: {
    late_student_login: {
      executor: "ramping-arrival-rate",
      exec: "lateStudentLogin",
      timeUnit: "1s",
      preAllocatedVUs: 60,
      maxVUs: 90,
      stages: [
        { target: 10, duration: "10s" },
        { target: 0, duration: "5s" },
      ],
    },
  },
};

export function lateStudentLogin() {
  const res = http.post(
    `${BASE}/api/auth/token`,
    JSON.stringify({ username: ADMIN_LOGIN, password: ADMIN_PASSWORD }),
    { headers: { "Content-Type": "application/json" } },
  );
  check(res, {
    "login 200": (r) => r.status === 200,
  });
}
