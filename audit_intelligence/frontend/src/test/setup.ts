import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";
import { setConfigForTests } from "../config";

setConfigForTests({ stage: "test", region: "eu-west-1", authMode: "local", apiBasePath: "/api" });

afterEach(() => {
  cleanup();
  localStorage.clear();
});
