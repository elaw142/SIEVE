import { useCallback, useEffect, useState } from "react";

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error?.message || payload.error || "Spotify request failed");
  }
  return payload;
}

export function useSpotify() {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const refreshMe = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const payload = await api("/api/auth/me");
      setUser(payload.user);
    } catch (err) {
      setUser(null);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refreshMe();
  }, [refreshMe]);

  return {
    user,
    loading,
    error,
    connect: () => {
      window.location.href = "/api/auth/login";
    },
    logout: async () => {
      await api("/api/auth/logout", { method: "POST" });
      setUser(null);
    },
    playlists: () => api("/api/playlists"),
    duplicates: (playlistId, mode = "exact") => api(`/api/playlists/${playlistId}/duplicates?mode=${mode}`),
    removeDuplicates: (playlistId, mode = "exact") =>
      api(`/api/playlists/${playlistId}/remove-duplicates`, {
        method: "POST",
        body: JSON.stringify({ mode }),
      }),
  };
}
