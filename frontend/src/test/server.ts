import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { API_BASE } from "../lib/api";
import { historyFixture, todayFixture } from "./fixtures";

export const handlers = [
  http.get(`${API_BASE}/v1/regime/today`, () => HttpResponse.json(todayFixture())),
  http.get(`${API_BASE}/v1/regime/history`, ({ request }) => {
    const range = (new URL(request.url).searchParams.get("range") ?? "1y") as "1y";
    return HttpResponse.json(historyFixture(range));
  }),
];

export const server = setupServer(...handlers);
