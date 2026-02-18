import http from "k6/http";
import { check } from "k6";

const BASE = __ENV.BASE_URL;
const ADMIN_LOGIN = __ENV.ADMIN_LOGIN;
const ADMIN_PASSWORD = __ENV.ADMIN_PASSWORD;

if (!BASE) throw new Error("Missing BASE_URL");
if (!ADMIN_LOGIN) throw new Error("Missing ADMIN_LOGIN");
if (!ADMIN_PASSWORD) throw new Error("Missing ADMIN_PASSWORD");

function toInt(name, fallback) {
  const raw = __ENV[name];
  if (!raw) return fallback;
  const parsed = Number.parseInt(raw, 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

const USER_PREFIX = __ENV.USER_PREFIX || "participant";
const USER_PASSWORD = __ENV.USER_PASSWORD || ADMIN_PASSWORD;
const USER_COUNT = toInt("USER_COUNT", 75);
const USER_START = toInt("USER_START", 1);
const USER_PAD_WIDTH = toInt("USER_PAD_WIDTH", 2);
const TEST_TAG = __ENV.TEST_TAG || `WAVEWRITE-${Date.now()}`;

export const options = {
  noCookiesReset: true,
  scenarios: {
    wave_writes_and_comments: {
      executor: "ramping-arrival-rate",
      exec: "waveBrainstorm",
      timeUnit: "1s",
      preAllocatedVUs: 40,
      maxVUs: 120,
      stages: [
        { target: 6, duration: "20s" },
        { target: 30, duration: "20s" },
        { target: 8, duration: "20s" },
        { target: 35, duration: "20s" },
        { target: 10, duration: "20s" },
        { target: 40, duration: "20s" },
        { target: 0, duration: "20s" },
      ],
      gracefulStop: "20s",
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
  if (token) http.cookieJar().set(BASE, "access_token", token);
  return token;
}

function createMeeting() {
  const title = `LOADTEST-WAVE-${TEST_TAG}`;
  const payload = {
    title: title,
    description: `Wave load test ${TEST_TAG}`,
    agenda: [
      {
        tool_type: "brainstorming",
        title: "Wave Brainstorm",
        order_index: 1,
        config: {
          allow_subcomments: true,
          allow_anonymous: false,
        },
      },
    ],
  };
  const res = http.post(`${BASE}/api/meetings/`, JSON.stringify(payload), {
    headers: { "Content-Type": "application/json" },
  });
  check(res, { "meeting create 200": (r) => r.status === 200 });
  if (res.status !== 200) throw new Error(`Meeting create failed: ${res.status}`);
  const body = res.json();
  const meetingId = body.meeting_id || body.meetingId;
  const activityId =
    body.agenda && body.agenda[0]
      ? body.agenda[0].activity_id || body.agenda[0].activityId
      : null;
  if (!meetingId || !activityId) throw new Error("Missing meeting/activity id from create response");
  return { meetingId, activityId, title };
}

function addParticipants(meetingId) {
  let added = 0;
  for (let i = 0; i < USER_COUNT; i += 1) {
    const n = USER_START + i;
    const login = `${USER_PREFIX}${String(n).padStart(USER_PAD_WIDTH, "0")}`;
    const res = http.post(
      `${BASE}/api/meetings/${meetingId}/participants`,
      JSON.stringify({ login }),
      { headers: { "Content-Type": "application/json" } },
    );
    if (res.status === 200) added += 1;
  }
  return added;
}

function startBrainstorm(meetingId, activityId) {
  const payload = {
    action: "start_tool",
    tool: "brainstorming",
    activityId: activityId,
  };
  const res = http.post(`${BASE}/api/meetings/${meetingId}/control`, JSON.stringify(payload), {
    headers: { "Content-Type": "application/json" },
  });
  check(res, { "start brainstorm 200": (r) => r.status === 200 || r.status === 409 });
}

function vuUsername(vu) {
  const offset = ((vu - 1) % USER_COUNT) + USER_START;
  return `${USER_PREFIX}${String(offset).padStart(USER_PAD_WIDTH, "0")}`;
}

let loggedIn = false;
let cachedUsername = null;

function participantLogin(username) {
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
  if (token) http.cookieJar().set(BASE, "access_token", token);
  return token;
}

export function setup() {
  const token = adminLoginAndSetCookie();
  if (!token) throw new Error("Admin login failed");
  const meeting = createMeeting();
  const added = addParticipants(meeting.meetingId);
  startBrainstorm(meeting.meetingId, meeting.activityId);
  return {
    meetingId: meeting.meetingId,
    activityId: meeting.activityId,
    title: meeting.title,
    testTag: TEST_TAG,
    participantsAdded: added,
  };
}

function postIdeaOrComment(data) {
  const listRes = http.get(
    `${BASE}/api/meetings/${data.meetingId}/brainstorming/ideas?activity_id=${encodeURIComponent(data.activityId)}`,
  );
  const ideas = listRes.status === 200 ? listRes.json() : [];
  const topLevel = Array.isArray(ideas) ? ideas.filter((x) => x.parent_id === null) : [];
  const doComment = topLevel.length > 0 && Math.random() < 0.45;

  const body = {
    content: `${data.testTag} ${doComment ? "comment" : "idea"} by ${cachedUsername} vu=${__VU} iter=${__ITER}`,
    submitted_name: cachedUsername,
    metadata: { source: "k6_wave", test_tag: data.testTag, type: doComment ? "comment" : "idea" },
  };
  if (doComment) {
    const parent = topLevel[Math.floor(Math.random() * topLevel.length)];
    body.parent_id = parent.id;
  }

  const idem = `${data.testTag}-${cachedUsername}-${__VU}-${__ITER}-${Date.now()}`;
  const submitRes = http.post(
    `${BASE}/api/meetings/${data.meetingId}/brainstorming/ideas?activity_id=${encodeURIComponent(data.activityId)}`,
    JSON.stringify(body),
    {
      headers: {
        "Content-Type": "application/json",
        "X-Idempotency-Key": idem,
      },
    },
  );

  check(submitRes, {
    "submit 201": (r) => r.status === 201,
    "submit no auth error": (r) => r.status !== 401,
    "submit no 5xx": (r) => r.status < 500,
  });
}

export function waveBrainstorm(data) {
  if (!loggedIn) {
    cachedUsername = vuUsername(__VU);
    loggedIn = Boolean(participantLogin(cachedUsername));
  }
  if (!loggedIn) return;
  postIdeaOrComment(data);
}
