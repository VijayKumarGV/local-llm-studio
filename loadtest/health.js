// k6 load-test — hot path baseline.
//
// Runs three scenarios in parallel:
//   1. `health`  — high-QPS ping on /api/health (no auth needed).
//                  Baseline for the server's raw throughput without model
//                  work in the loop.
//   2. `rag`     — 1000 sequential /api/rag/query calls against the
//                  provisioned corpus. Target: p95 < 500 ms.
//   3. `sandbox` — 100 concurrent /api/sandbox/run of a trivial script.
//                  Verifies no crash under concurrency + Docker/sandbox-
//                  exec startup cost stays reasonable.
//
// Usage:
//   brew install k6
//   SESSION_TOKEN=$(docker compose exec studio cat /data/token) \
//     k6 run loadtest/health.js
//
// Baselines (target — hardware-dependent; measured on M4 Pro 37 GB):
//   health   p95 <  50 ms
//   rag      p95 < 500 ms
//   sandbox  p95 <   3 s   (Docker cold-start dominates)

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend } from 'k6/metrics';

const BASE = __ENV.STUDIO_URL || 'http://127.0.0.1:8080';
const TOKEN = __ENV.SESSION_TOKEN || '';
const AUTHED_HEADERS = TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {};

const healthLatency = new Trend('studio_health_ms');
const ragLatency = new Trend('studio_rag_ms');
const sandboxLatency = new Trend('studio_sandbox_ms');

export const options = {
  scenarios: {
    health: {
      executor: 'constant-arrival-rate',
      rate: 50, timeUnit: '1s', duration: '30s',
      preAllocatedVUs: 20, maxVUs: 40,
      exec: 'health',
    },
    rag: {
      executor: 'per-vu-iterations',
      vus: 1, iterations: 1000, maxDuration: '5m',
      exec: 'rag',
      startTime: '35s',
    },
    sandbox: {
      executor: 'shared-iterations',
      vus: 100, iterations: 100, maxDuration: '2m',
      exec: 'sandbox',
      startTime: '4m',
    },
  },
  thresholds: {
    studio_health_ms:  ['p(95)<50'],
    studio_rag_ms:     ['p(95)<500'],
    studio_sandbox_ms: ['p(95)<3000'],
    http_req_failed:   ['rate<0.01'],
  },
};

export function health() {
  const res = http.get(`${BASE}/api/health`);
  healthLatency.add(res.timings.duration);
  check(res, { 'health 200': (r) => r.status === 200 });
}

export function rag() {
  const q = ['argon2 password storage', 'MITRE T1055', 'Rust ? operator', 'CSRF defenses'][
    Math.floor(Math.random() * 4)
  ];
  const res = http.get(
    `${BASE}/api/rag/query?q=${encodeURIComponent(q)}&top_k=6`,
    { headers: AUTHED_HEADERS }
  );
  ragLatency.add(res.timings.duration);
  check(res, { 'rag 200': (r) => r.status === 200 });
}

export function sandbox() {
  const res = http.post(
    `${BASE}/api/sandbox/run`,
    JSON.stringify({ code: "print(2 + 2)", timeout: 10 }),
    { headers: { ...AUTHED_HEADERS, 'Content-Type': 'application/json' } }
  );
  sandboxLatency.add(res.timings.duration);
  check(res, {
    'sandbox 200':   (r) => r.status === 200,
    'sandbox no error': (r) => JSON.parse(r.body).status !== 'timeout',
  });
  // stagger the 100 concurrent starts so Docker doesn't get 100 launches
  // in the same 10 ms window — realistic user pattern.
  sleep(Math.random() * 2);
}
