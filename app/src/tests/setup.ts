import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

// `server-only` is a Next.js build-time guard that throws in non-server contexts.
// Vitest runs in jsdom, so the guard fires on any module that imports it.
// Stub the module so server-only-tagged files can be imported by tests.
vi.mock("server-only", () => ({}));
