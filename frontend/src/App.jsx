import { AlertTriangle, Check, RefreshCw, Scissors, Search, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import Header from "./components/Header.jsx";
import PreviewPanel from "./components/PreviewPanel.jsx";
import { useSpotify } from "./hooks/useSpotify.js";

function normalizePreviewTrack(track) {
  return {
    id: track.id,
    uri: track.uri,
    name: track.name,
    artist: track.artist,
    year: track.year,
    image: track.image,
    previewUrl: "",
  };
}

export default function App() {
  const spotify = useSpotify();
  const [playlists, setPlaylists] = useState([]);
  const [playlistId, setPlaylistId] = useState("");
  const [mode, setMode] = useState("exact");
  const [analysis, setAnalysis] = useState(null);
  const [status, setStatus] = useState("idle");
  const [message, setMessage] = useState("");
  const [previewTrack, setPreviewTrack] = useState(null);

  const selectedPlaylist = useMemo(() => playlists.find((playlist) => playlist.id === playlistId), [playlists, playlistId]);

  useEffect(() => {
    if (!spotify.user) return;
    loadPlaylists();
  }, [spotify.user]);

  const loadPlaylists = async () => {
    setStatus("loading");
    setMessage("Loading playlists");
    try {
      const payload = await spotify.playlists();
      setPlaylists(payload.playlists || []);
      setPlaylistId((current) => current || payload.playlists?.[0]?.id || "");
      setStatus("idle");
      setMessage("");
    } catch (err) {
      setStatus("error");
      setMessage(err.message);
    }
  };

  const scan = async () => {
    if (!playlistId) return;
    setStatus("loading");
    setMessage("Scanning playlist");
    setAnalysis(null);
    try {
      const payload = await spotify.duplicates(playlistId, mode);
      setAnalysis(payload);
      setStatus("idle");
      setMessage("");
    } catch (err) {
      setStatus("error");
      setMessage(err.message);
    }
  };

  const remove = async () => {
    if (!playlistId || !analysis?.duplicateCount) return;
    const confirmed = window.confirm(`Remove ${analysis.duplicateCount} duplicate tracks from "${analysis.playlist.name}"?`);
    if (!confirmed) return;
    setStatus("loading");
    setMessage("Removing duplicate tracks");
    try {
      const payload = await spotify.removeDuplicates(playlistId, mode);
      setStatus("success");
      setMessage(`Removed ${payload.removedCount} duplicates`);
      await scan();
    } catch (err) {
      setStatus("error");
      setMessage(err.message);
    }
  };

  return (
    <main className="min-h-screen bg-bg pb-8 font-mono text-ink">
      <Header user={spotify.user} loading={spotify.loading} onConnect={spotify.connect} onLogout={spotify.logout} />

      <section className="mx-auto grid w-full max-w-[1500px] gap-4 px-4 py-4 lg:grid-cols-[420px_1fr] lg:px-6">
        <aside className="workspace-panel p-4">
          <div className="mb-4 border-b-2 border-ink pb-3">
            <p className="font-display text-6xl leading-none">CONTROL</p>
            <p className="text-xs uppercase text-muted">Pick a playlist, inspect duplicates, then remove extras</p>
          </div>

          {!spotify.user && (
            <p className="empty-state">
              <ShieldCheck size={18} /> Connect Spotify to load your playlists.
            </p>
          )}

          {spotify.user && (
            <div className="control-stack">
              <label className="control-label">
                Playlist
                <select value={playlistId} onChange={(event) => setPlaylistId(event.target.value)}>
                  {playlists.map((playlist) => (
                    <option key={playlist.id} value={playlist.id}>
                      {playlist.name} ({playlist.tracksTotal})
                    </option>
                  ))}
                </select>
              </label>

              <div className="mode-tabs">
                <button className={mode === "exact" ? "active" : ""} onClick={() => setMode("exact")} type="button">
                  Exact
                </button>
                <button className={mode === "soft" ? "active" : ""} onClick={() => setMode("soft")} type="button">
                  Soft
                </button>
                <button onClick={loadPlaylists} type="button">
                  Refresh
                </button>
              </div>

              <button className="action-button" onClick={scan} disabled={!playlistId || status === "loading"} type="button">
                <Search size={22} strokeWidth={3} /> Scan
              </button>
              <button className="action-button danger-button" onClick={remove} disabled={!analysis?.duplicateCount || status === "loading"} type="button">
                <Scissors size={22} strokeWidth={3} /> Remove Extras
              </button>

              <p className="status-line">
                Exact mode matches identical Spotify tracks. Soft mode matches normalized title and primary artist.
              </p>
            </div>
          )}
        </aside>

        <section className="workspace-panel min-h-[620px] p-4">
          <div className="mb-3 flex items-baseline justify-between border-b-2 border-ink pb-2">
            <h2 className="font-display text-5xl">Duplicate Report</h2>
            <span className="text-xs uppercase text-muted">{analysis ? `${analysis.duplicateCount} extras` : "No scan"}</span>
          </div>

          {status === "loading" && (
            <div className="loading-card">
              <div className="loading-bar">
                <span />
              </div>
              <p className="font-display text-3xl">{message || "Working"}</p>
            </div>
          )}
          {status === "error" && <p className="status-error">{message}</p>}
          {status === "success" && <p className="status-line">{message}</p>}

          {!analysis && status !== "loading" && (
            <p className="empty-state">
              <RefreshCw size={18} /> Scan a playlist to see duplicate groups before anything is changed.
            </p>
          )}

          {analysis && analysis.duplicateCount === 0 && (
            <p className="status-line">
              <Check size={18} /> No duplicates found in {analysis.playlist.name}.
            </p>
          )}

          {analysis?.duplicateCount > 0 && (
            <div className="control-stack">
              <div className="report-strip">
                <span>{analysis.playlist.name}</span>
                <span>{analysis.groupCount} groups</span>
                <span>{analysis.duplicateCount} removable</span>
                <span>{analysis.skippedCount} skipped</span>
              </div>
              {analysis.groups.map((group) => (
                <DuplicateGroup key={group.key} group={group} onPreview={(track) => setPreviewTrack(normalizePreviewTrack(track))} />
              ))}
              <p className="status-line">
                <AlertTriangle size={18} /> The earliest playlist position is kept automatically; later copies are removed.
              </p>
            </div>
          )}
        </section>
      </section>

      <PreviewPanel track={previewTrack} onClose={() => setPreviewTrack(null)} />
    </main>
  );
}

function DuplicateGroup({ group, onPreview }) {
  return (
    <div className="duplicate-group">
      <div className="duplicate-header">
        <span>{group.keep.track.name}</span>
        <span>{group.count} copies</span>
      </div>
      <Occurrence label="Keep" occurrence={group.keep} onPreview={onPreview} keep />
      {group.remove.map((occurrence) => (
        <Occurrence key={`${occurrence.track.uri}-${occurrence.position}`} label="Remove" occurrence={occurrence} onPreview={onPreview} />
      ))}
    </div>
  );
}

function Occurrence({ label, occurrence, onPreview, keep = false }) {
  const track = occurrence.track;
  return (
    <div className={`occurrence-row ${keep ? "keep" : ""}`}>
      <span className="track-check selected">{keep ? "K" : "X"}</span>
      {track.image ? <img src={track.image} alt="" /> : <span className="track-image-fallback" />}
      <span className="min-w-0">
        <span className="block truncate font-bold">{track.name}</span>
        <span className="block truncate text-xs uppercase text-muted">
          {track.artist} {track.year ? ` / ${track.year}` : ""} / #{occurrence.position + 1} / {label}
        </span>
      </span>
      <button className="preview-button" onClick={() => onPreview(track)} type="button">
        <Search size={16} />
      </button>
    </div>
  );
}
