import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, getCase, queryAnalytics, runAnalysis, setTokenProvider, uploadDataset } from "./client";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("request", () => {
  it("sends the bearer token the provider returns and surfaces the API's detail on error", async () => {
    setTokenProvider(async () => "tok-123");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse({ detail: "Case X not found" }, 404));
    await expect(getCase("CASE-0001-0001")).rejects.toMatchObject({ status: 404, message: "Case X not found" });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/cases/CASE-0001-0001");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok-123");
  });
});

describe("runAnalysis", () => {
  it("polls the run until it finishes and resolves with the final run", async () => {
    vi.useFakeTimers();
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse({ id: 7, status: "queued", case_count: 0 }, 202))
      .mockResolvedValueOnce(jsonResponse({ id: 7, status: "running", case_count: 0 }))
      .mockResolvedValueOnce(jsonResponse({ id: 7, status: "succeeded", case_count: 91 }));
    const promise = runAnalysis();
    await vi.advanceTimersByTimeAsync(1500);
    await vi.advanceTimersByTimeAsync(1500);
    const run = await promise;
    expect(run.status).toBe("succeeded");
    expect(run.case_count).toBe(91);
    expect(fetchMock.mock.calls.map((c) => c[0])).toEqual(["/api/analysis/run", "/api/analysis/runs/7", "/api/analysis/runs/7"]);
  });

  it("throws the run's error when it fails", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse({ id: 8, status: "failed", error: "bad csv" }, 202));
    const failure = await runAnalysis("ds1").catch((e: unknown) => e);
    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as ApiError).message).toBe("bad csv");
  });
});

describe("queryAnalytics", () => {
  it("returns the job's result once the job succeeds", async () => {
    vi.useFakeTimers();
    const chart = { title: "Cases by severity", chart_type: "bar", data: [{ label: "Critical", value: 5 }] };
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse({ id: "j1", kind: "analytics", status: "queued", result: null, error: null }, 202))
      .mockResolvedValueOnce(jsonResponse({ id: "j1", kind: "analytics", status: "succeeded", result: chart, error: null }));
    const promise = queryAnalytics("cases by severity");
    await vi.advanceTimersByTimeAsync(1500);
    expect(await promise).toEqual(chart);
  });

  it("surfaces a failed job's error message", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      jsonResponse({ id: "j2", kind: "analytics", status: "failed", result: null, error: "AI did not return a valid chart" }, 202),
    );
    await expect(queryAnalytics("?")).rejects.toThrow("AI did not return a valid chart");
  });
});

describe("uploadDataset", () => {
  it("PUTs each file to the URL the API hands out, then finalizes", async () => {
    setTokenProvider(async () => null);
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        jsonResponse({ dataset_id: "d1", uploads: [{ file: "members.csv", url: "/datasets/d1/files/members.csv?token=t", method: "PUT" }] }, 201),
      )
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(jsonResponse({ dataset_id: "d1", status: "ready", errors: [], created_at: "2026-10-19T00:00:00Z" }));
    const file = new File(["member_id,name\n"], "members.csv", { type: "text/csv" });
    const result = await uploadDataset([file]);
    expect(result.status).toBe("ready");
    const putCall = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(putCall[0]).toBe("/api/datasets/d1/files/members.csv?token=t");
    expect(putCall[1].method).toBe("PUT");
    expect(putCall[1].body).toBe(file);
    expect(fetchMock.mock.calls[2]?.[0]).toBe("/api/datasets/d1/finalize");
  });

  it("refuses to start when a required file is missing", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      jsonResponse({ dataset_id: "d2", uploads: [{ file: "loans.csv", url: "https://bucket/loans.csv", method: "PUT" }] }, 201),
    );
    await expect(uploadDataset([])).rejects.toThrow("Missing loans.csv");
  });
});
