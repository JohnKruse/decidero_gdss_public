import http from "k6/http";
import { check, sleep } from "k6";
import exec from "k6/execution";

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

const TARGET_USERS = toInt("TARGET_USERS", 75);
const USER_PREFIX = __ENV.USER_PREFIX || "participant";
const USER_START = toInt("USER_START", 1);
const USER_PAD_WIDTH = toInt("USER_PAD_WIDTH", 2);
const USER_PASSWORD = __ENV.USER_PASSWORD || ADMIN_PASSWORD;
const TEST_TAG = __ENV.TEST_TAG || `CLASSROOM-${Date.now()}`;
const ENSURE_USERS = (__ENV.ENSURE_USERS || "1") === "1";
const WAVE_PERIOD_SEC = toInt("WAVE_PERIOD_SEC", 40);
const IDEA_MAX_CHARS = toInt("IDEA_MAX_CHARS", 320);
const COMMENT_MAX_CHARS = toInt("COMMENT_MAX_CHARS", 220);
const PHASE1_RATE_MIN = Number.parseFloat(__ENV.PHASE1_RATE_MIN || "1.5");
const PHASE1_RATE_MAX = Number.parseFloat(__ENV.PHASE1_RATE_MAX || "2.0");
const PHASE2_RATE_PER_MIN = Number.parseFloat(__ENV.PHASE2_RATE_PER_MIN || "1.0");

const LENGTH_SHORT_MIN = 10;
const LENGTH_SHORT_MAX = 50;
const LENGTH_MEDIUM_MIN = 51;
const LENGTH_MEDIUM_MAX = 250;
const LENGTH_LONG_MIN = 251;
const LENGTH_LONG_MAX = 400;

const USER_PREFIX_BASE = __ENV.USER_PREFIX_BASE || USER_PREFIX;
const UNIQUE_SUFFIX = (String(__ENV.USER_SUFFIX || TEST_TAG || Date.now()))
  .toLowerCase()
  .replace(/[^a-z0-9]/g, "")
  .slice(-10);
const RUN_USER_PREFIX = `${USER_PREFIX_BASE}${UNIQUE_SUFFIX ? `_${UNIQUE_SUFFIX}_` : "_"}`;

const PHASE1_START = __ENV.PHASE1_START || "0s";
const PHASE1_DURATION = __ENV.PHASE1_DURATION || "3m";
const PHASE2_START = __ENV.PHASE2_START || "3m";
const PHASE2_DURATION = __ENV.PHASE2_DURATION || "12m";
const PHASE3_START = __ENV.PHASE3_START || "15m";
const PHASE3_DURATION = __ENV.PHASE3_DURATION || "6m";

export const options = {
  noCookiesReset: true,
  scenarios: {
    phase1_herd: {
      executor: "constant-vus",
      exec: "phase1Herd",
      vus: TARGET_USERS,
      duration: PHASE1_DURATION,
      startTime: PHASE1_START,
      gracefulStop: "20s",
    },
    phase2_plateau: {
      executor: "constant-vus",
      exec: "phase2Plateau",
      vus: TARGET_USERS,
      duration: PHASE2_DURATION,
      startTime: PHASE2_START,
      gracefulStop: "20s",
    },
    phase3_switch_to_voting: {
      executor: "per-vu-iterations",
      exec: "phase3SwitchToVoting",
      vus: 1,
      iterations: 1,
      startTime: PHASE3_START,
      maxDuration: "2m",
    },
    phase3_convergence: {
      executor: "constant-vus",
      exec: "phase3Convergence",
      vus: TARGET_USERS,
      duration: PHASE3_DURATION,
      startTime: PHASE3_START,
      gracefulStop: "20s",
    },
  },
  thresholds: {
    checks: ["rate>0.9"],
    http_req_failed: ["rate<0.1"],
    http_req_duration: ["p(95)<2000"],
  },
};

function jsonPost(url, body, extraHeaders = {}) {
  return http.post(url, JSON.stringify(body), {
    headers: { "Content-Type": "application/json", ...extraHeaders },
    timeout: "60s",
  });
}

function loginAs(username, password) {
  const res = jsonPost(`${BASE}/api/auth/token`, { username, password });
  const ok = check(res, { "login 200": (r) => r.status === 200 });
  const token =
    res.cookies.access_token && res.cookies.access_token[0]
      ? res.cookies.access_token[0].value
      : null;
  if (token) http.cookieJar().set(BASE, "access_token", token);
  return ok;
}

function usernameForVu(vu) {
  const n = ((vu - 1) % TARGET_USERS) + USER_START;
  return `${RUN_USER_PREFIX}${String(n).padStart(USER_PAD_WIDTH, "0")}`;
}

function waveFactor() {
  const nowSec = Date.now() / 1000;
  const omega = (2 * Math.PI) / Math.max(WAVE_PERIOD_SEC, 10);
  return 0.25 + 0.75 * (0.5 + 0.5 * Math.sin(nowSec * omega));
}

const LOREM_WORDS = (
  "lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor incididunt ut labore et dolore magna aliqua " +
  "ut enim ad minim veniam quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat duis aute irure " +
  "dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur excepteur sint occaecat cupidatat non " +
  "proident sunt in culpa qui officia deserunt mollit anim id est laborum integer posuere erat a ante venenatis dapibus posuere " +
  "velit aliquet aenean eu leo quam pellentesque ornare sem lacinia quam venenatis vestibulum curabitur blandit tempus porttitor"
)
  .trim()
  .split(/\s+/);

function randomInt(min, max) {
  return Math.floor(min + Math.random() * (max - min + 1));
}

function sampleStandardNormal() {
  const u1 = Math.max(Math.random(), Number.EPSILON);
  const u2 = Math.random();
  return Math.sqrt(-2.0 * Math.log(u1)) * Math.cos(2.0 * Math.PI * u2);
}

function sampleLogNormalInt(min, max) {
  const safeMin = Math.max(1, min);
  const safeMax = Math.max(safeMin, max);
  const mu = Math.log(Math.sqrt(safeMin * safeMax));
  const sigma = 0.55;
  const value = Math.exp(mu + sigma * sampleStandardNormal());
  return Math.max(safeMin, Math.min(safeMax, Math.round(value)));
}

function pickLengthBucket(weights) {
  const roll = Math.random() * 100;
  const shortWeight = weights.short || 0;
  const mediumWeight = weights.medium || 0;
  if (roll < shortWeight) return "short";
  if (roll < shortWeight + mediumWeight) return "medium";
  return "long";
}

function generateLoremText(targetChars) {
  const target = Math.max(10, targetChars);
  let text = "";
  while (text.length < target + 16) {
    text += (text ? " " : "") + LOREM_WORDS[randomInt(0, LOREM_WORDS.length - 1)];
  }
  const trimmed = text.slice(0, target).trim();
  return /[.!?]$/.test(trimmed) ? trimmed : `${trimmed}.`;
}

function buildVariableText({ phase }) {
  // Brain dump skews shorter to match faster real-time entry behavior.
  const profile =
    phase === "phase1"
      ? { short: 70, medium: 25, long: 5 }
      : { short: 50, medium: 35, long: 15 };
  const bucket = pickLengthBucket(profile);
  let targetChars = 80;
  if (bucket === "short") {
    targetChars = sampleLogNormalInt(LENGTH_SHORT_MIN, LENGTH_SHORT_MAX);
  } else if (bucket === "medium") {
    targetChars = sampleLogNormalInt(LENGTH_MEDIUM_MIN, LENGTH_MEDIUM_MAX);
  } else {
    targetChars = sampleLogNormalInt(LENGTH_LONG_MIN, LENGTH_LONG_MAX);
  }
  const bounded = Math.min(Math.max(10, targetChars), LENGTH_LONG_MAX);
  return { content: generateLoremText(bounded), lengthBucket: bucket };
}

function sleepForSubmissionRate(minPerMinute, maxPerMinute) {
  const safeMin = Math.max(0.1, minPerMinute);
  const safeMax = Math.max(safeMin, maxPerMinute);
  const rate = safeMin + Math.random() * (safeMax - safeMin);
  const intervalSec = 60 / rate;
  const jittered = intervalSec * (0.85 + Math.random() * 0.3);
  sleep(jittered);
}

function maybeSleep(minSec, maxSec) {
  const span = Math.max(0, maxSec - minSec);
  sleep(minSec + Math.random() * span);
}

function createMeetingAndAgenda() {
  const payload = {
    title: `LOADTEST-CLASSROOM-${TEST_TAG}`,
    description: `Phased classroom load test ${TEST_TAG}`,
    agenda: [
      {
        tool_type: "brainstorming",
        title: "Brainstorm",
        order_index: 1,
        config: {
          allow_subcomments: true,
          allow_anonymous: false,
        },
      },
      {
        tool_type: "voting",
        title: "Vote",
        order_index: 2,
        config: {
          options: [
            "Top priority A",
            "Top priority B",
            "Top priority C",
            "Top priority D",
            "Top priority E",
          ],
          max_votes: 2,
          show_results_immediately: true,
        },
      },
    ],
  };

  const res = jsonPost(`${BASE}/api/meetings/`, payload);
  check(res, { "meeting create 200": (r) => r.status === 200 });
  if (res.status !== 200) {
    throw new Error(`Meeting create failed: ${res.status} ${res.body}`);
  }

  const body = res.json();
  const meetingId = body.meeting_id || body.meetingId;
  const agenda = Array.isArray(body.agenda) ? body.agenda : [];
  const brainstorming = agenda.find(
    (row) => String(row.tool_type || "").toLowerCase() === "brainstorming",
  );
  const voting = agenda.find((row) => String(row.tool_type || "").toLowerCase() === "voting");
  if (!meetingId || !brainstorming || !voting) {
    throw new Error("Missing meeting or activity IDs from create response");
  }
  return {
    meetingId,
    brainstormingActivityId: brainstorming.activity_id || brainstorming.activityId,
    votingActivityId: voting.activity_id || voting.activityId,
  };
}

function ensureParticipantsExist() {
  if (!ENSURE_USERS) return;
  const payload = {
    prefix: RUN_USER_PREFIX,
    start: USER_START,
    end: USER_START + TARGET_USERS - 1,
    default_password: USER_PASSWORD,
    role: "participant",
    email_domain: "example.com",
    first_name: "Load",
    last_name: "User",
  };
  const res = jsonPost(`${BASE}/api/users/batch/pattern`, payload);
  check(res, {
    "batch users created": (r) => r.status === 200 || r.status === 409,
  });
}

function addParticipantsToMeeting(meetingId) {
  let added = 0;
  for (let i = 0; i < TARGET_USERS; i += 1) {
    const login = `${RUN_USER_PREFIX}${String(USER_START + i).padStart(USER_PAD_WIDTH, "0")}`;
    const res = jsonPost(`${BASE}/api/meetings/${meetingId}/participants`, { login });
    if (res.status === 200) added += 1;
  }
  return added;
}

function startTool(meetingId, tool, activityId) {
  const res = jsonPost(`${BASE}/api/meetings/${meetingId}/control`, {
    action: "start_tool",
    tool,
    activityId,
  });
  check(res, {
    [`start ${tool} ok`]: (r) => r.status === 200 || r.status === 409,
  });
}

function getIdeas(meetingId, activityId) {
  const res = http.get(
    `${BASE}/api/meetings/${meetingId}/brainstorming/ideas?activity_id=${encodeURIComponent(activityId)}`,
    { timeout: "60s" },
  );
  if (res.status !== 200) return [];
  const parsed = res.json();
  return Array.isArray(parsed) ? parsed : [];
}

function postIdea(meetingId, activityId, username, marker) {
  const idem = `${TEST_TAG}-${username}-idea-${__VU}-${__ITER}-${Date.now()}`;
  const built = buildVariableText({ phase: marker });
  const res = jsonPost(
    `${BASE}/api/meetings/${meetingId}/brainstorming/ideas?activity_id=${encodeURIComponent(activityId)}`,
    {
      content: built.content.slice(0, IDEA_MAX_CHARS),
      submitted_name: username,
      metadata: {
        source: "k6_v7",
        phase: marker,
        test_tag: TEST_TAG,
        length_bucket: built.lengthBucket,
      },
    },
    { "X-Idempotency-Key": idem },
  );
  check(res, {
    "idea submit 201": (r) => r.status === 201,
    "idea submit no 5xx": (r) => r.status < 500,
  });
}

function postComment(meetingId, activityId, username, marker) {
  const ideas = getIdeas(meetingId, activityId);
  const topLevel = ideas.filter((x) => x && x.parent_id === null);
  if (!topLevel.length) {
    postIdea(meetingId, activityId, username, marker);
    return;
  }
  const parent = topLevel[Math.floor(Math.random() * topLevel.length)];
  const idem = `${TEST_TAG}-${username}-comment-${__VU}-${__ITER}-${Date.now()}`;
  const built = buildVariableText({ phase: marker });
  const res = jsonPost(
    `${BASE}/api/meetings/${meetingId}/brainstorming/ideas?activity_id=${encodeURIComponent(activityId)}`,
    {
      content: built.content.slice(0, COMMENT_MAX_CHARS),
      parent_id: parent.id,
      submitted_name: username,
      metadata: {
        source: "k6_v7",
        phase: marker,
        test_tag: TEST_TAG,
        type: "comment",
        length_bucket: built.lengthBucket,
      },
    },
    { "X-Idempotency-Key": idem },
  );
  check(res, {
    "comment submit 201": (r) => r.status === 201,
    "comment submit no 5xx": (r) => r.status < 500,
  });
}

function pollMeetingState(meetingId) {
  const res = http.get(`${BASE}/api/meetings/${meetingId}/state`, { timeout: "60s" });
  check(res, {
    "state poll 200": (r) => r.status === 200,
    "state poll no 5xx": (r) => r.status < 500,
  });
}

function fetchVotingOptions(meetingId, votingActivityId) {
  const res = http.get(
    `${BASE}/api/meetings/${meetingId}/voting/options?activity_id=${encodeURIComponent(votingActivityId)}`,
    { timeout: "60s" },
  );
  check(res, {
    "voting options no 5xx": (r) => r.status < 500,
  });
  if (res.status !== 200) return [];
  const body = res.json();
  return Array.isArray(body.options) ? body.options : [];
}

function castVote(meetingId, votingActivityId, optionId) {
  const res = jsonPost(`${BASE}/api/meetings/${meetingId}/voting/votes`, {
    activity_id: votingActivityId,
    option_id: optionId,
    action: "add",
  });
  check(res, {
    "vote no 5xx": (r) => r.status < 500,
  });
}

const loginState = { phase1: false, phase2: false, phase3: false };
let cachedUsername = null;

function ensureParticipantLogin(phaseKey) {
  if (!cachedUsername) cachedUsername = usernameForVu(__VU);
  if (loginState[phaseKey]) return true;
  loginState[phaseKey] = loginAs(cachedUsername, USER_PASSWORD);
  return loginState[phaseKey];
}

export function setup() {
  if (!loginAs(ADMIN_LOGIN, ADMIN_PASSWORD)) {
    throw new Error("Admin login failed");
  }

  ensureParticipantsExist();

  const meeting = createMeetingAndAgenda();
  const participantsAdded = addParticipantsToMeeting(meeting.meetingId);
  startTool(meeting.meetingId, "brainstorming", meeting.brainstormingActivityId);

  return {
    ...meeting,
    participantsAdded,
    testTag: TEST_TAG,
    targetUsers: TARGET_USERS,
    userPrefix: RUN_USER_PREFIX,
  };
}

export function phase1Herd(data) {
  if (!ensureParticipantLogin("phase1")) return;

  pollMeetingState(data.meetingId);

  const w = waveFactor();
  if (Math.random() < 0.25 && getIdeas(data.meetingId, data.brainstormingActivityId).length > 0) {
    postComment(data.meetingId, data.brainstormingActivityId, cachedUsername, "phase1");
  } else {
    postIdea(data.meetingId, data.brainstormingActivityId, cachedUsername, "phase1");
  }

  if (Math.random() < 0.85) {
    getIdeas(data.meetingId, data.brainstormingActivityId);
  }

  const minRate = Math.max(0.2, PHASE1_RATE_MIN * (0.9 + 0.2 * w));
  const maxRate = Math.max(minRate, PHASE1_RATE_MAX * (0.9 + 0.2 * w));
  sleepForSubmissionRate(minRate, maxRate);
}

export function phase2Plateau(data) {
  if (!ensureParticipantLogin("phase2")) return;

  const w = waveFactor();
  pollMeetingState(data.meetingId);
  getIdeas(data.meetingId, data.brainstormingActivityId);

  if (Math.random() < 0.35) {
    postIdea(data.meetingId, data.brainstormingActivityId, cachedUsername, "phase2");
  } else {
    postComment(data.meetingId, data.brainstormingActivityId, cachedUsername, "phase2");
  }

  const refinementRate = Math.max(0.2, PHASE2_RATE_PER_MIN * (0.9 + 0.2 * w));
  sleepForSubmissionRate(refinementRate, refinementRate);
}

export function phase3SwitchToVoting(data) {
  if (!loginAs(ADMIN_LOGIN, ADMIN_PASSWORD)) {
    throw new Error("Admin login failed for phase3 switch");
  }
  startTool(data.meetingId, "voting", data.votingActivityId);
}

export function phase3Convergence(data) {
  if (!ensureParticipantLogin("phase3")) return;

  pollMeetingState(data.meetingId);
  const options = fetchVotingOptions(data.meetingId, data.votingActivityId);

  if (options.length > 0 && Math.random() < 0.70 * waveFactor() + 0.20) {
    const selected = options[Math.floor(Math.random() * Math.min(options.length, 2))];
    castVote(data.meetingId, data.votingActivityId, selected.option_id);
  }

  maybeSleep(3.5, 7.5);
}
