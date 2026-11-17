import http from "k6/http";
import { check } from "k6";

// Fixed closed-loop load against the indexed list path.
// 10 virtual users, 30s measurement, 2s graceful stop, no think time.
export const options = {
  summaryTrendStats: ["avg", "min", "med", "max", "p(90)", "p(95)", "p(99)"],
  scenarios: {
    issue_list: {
      executor: "constant-vus",
      vus: 10,
      duration: "30s",
      gracefulStop: "2s",
    },
  },
  thresholds: {
    http_req_failed: ["rate==0"],
    checks: ["rate==1"],
  },
  userAgent: "issue-tracker-bench/1.0",
};

export default function () {
  const url =
    `${__ENV.BASE_URL}/api/v1/issues` +
    `?project_id=${__ENV.PROJECT_ID}&state=${__ENV.STATE}&limit=50&sort=created_at`;
  const response = http.get(url, {
    headers: { "X-API-Key": __ENV.API_KEY },
    tags: { name: "GET /api/v1/issues" },
  });
  check(response, {
    "status is 200": (res) => res.status === 200,
  });
}

export function handleSummary(data) {
  const path = __ENV.SUMMARY_PATH;
  if (!path) {
    throw new Error("SUMMARY_PATH is required");
  }
  const duration = data.metrics.http_req_duration.values;
  const failed = data.metrics.http_req_failed.values;
  const reqs = data.metrics.http_reqs.values;
  const lines = [
    `http_reqs.count=${reqs.count}`,
    `http_reqs.rate=${reqs.rate}`,
    `http_req_failed.rate=${failed.rate}`,
    `http_req_duration.med=${duration.med}`,
    `http_req_duration.p95=${duration["p(95)"]}`,
    `http_req_duration.p99=${duration["p(99)"]}`,
  ];
  return {
    [path]: JSON.stringify(data, null, 2),
    stdout: lines.join("\n") + "\n",
  };
}
