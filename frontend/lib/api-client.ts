import axios, { type AxiosError, type InternalAxiosRequestConfig } from "axios";

import { getAccessToken, setAccessToken } from "./token-store";

/**
 * Base URL points at the Next.js rewrite proxy (/api/backend/*) rather than
 * the FastAPI origin directly, so the refresh-token cookie stays same-site
 * in the browser regardless of where the backend is actually deployed.
 * See next.config.mjs `rewrites()`.
 */
export const apiClient = axios.create({
  baseURL: "/api/backend",
  withCredentials: true, // send the httpOnly refresh-token cookie
  headers: { "Content-Type": "application/json" },
  // Axios defaults to NO timeout (0 = wait forever). The insights endpoint
  // can legitimately take 30-90s on a cold LLM call, so the ceiling sits
  // above that — but not at infinity, or a wedged backend leaves the UI
  // spinning indefinitely with no error the user can act on.
  timeout: 120_000,
});

apiClient.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = getAccessToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

let refreshPromise: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  // De-dupe concurrent 401s into a single refresh call.
  if (!refreshPromise) {
    refreshPromise = axios
      .post("/api/backend/auth/refresh", null, { withCredentials: true })
      .then((res) => {
        const token = res.data?.access_token ?? null;
        setAccessToken(token);
        return token;
      })
      .catch(() => {
        setAccessToken(null);
        return null;
      })
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as (InternalAxiosRequestConfig & { _retry?: boolean }) | undefined;

    if (error.response?.status === 401 && originalRequest && !originalRequest._retry) {
      originalRequest._retry = true;
      const newToken = await refreshAccessToken();
      if (newToken) {
        originalRequest.headers.Authorization = `Bearer ${newToken}`;
        return apiClient(originalRequest);
      }
      // Refresh failed — the session is truly gone; let the caller/UI
      // redirect to /login rather than forcing a hard navigation here.
    }

    return Promise.reject(error);
  }
);
