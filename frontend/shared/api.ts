import axios from "axios";
import type { operations } from "./api-types";

const api = axios.create({
  baseURL: "/api/v1",
  adapter: "xhr",
  headers: { Accept: "application/json" },
  xsrfCookieName: "__Host-se_csrf",
  xsrfHeaderName: "X-CSRF-Token",
  withXSRFToken: ({ method = "get" }) =>
    ["get", "head", "options"].includes(method.toLowerCase()) ? false : undefined,
  timeout: 10_000,
});

type Hello = operations["getHello"]["responses"][200]["content"]["application/json"];

export async function readHello(): Promise<Hello> {
  const { data } = await api.get<Hello>("/hello");
  return data;
}
