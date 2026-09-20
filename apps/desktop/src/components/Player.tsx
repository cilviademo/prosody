import { useEffect, useRef, useState } from "react";
import { shell } from "../lib/api";
import { clock } from "../lib/format";
import { Note } from "./ui";

/**
 * Preview transport for a generated render.
 *
 * Audio is read through the shell rather than a file:// URL so it works
 * wherever the user's export folder lives.
 */
export function Player({ path }: { path: string }) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [volume, setVolume] = useState(0.85);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let created: string | null = null;
    let cancelled = false;
    setError(null);
    setUrl(null);

    shell
      .readMedia(path)
      .then((data) => {
        if (cancelled) return;
        const type = path.toLowerCase().endsWith(".mp3") ? "audio/mpeg" : "audio/wav";
        created = URL.createObjectURL(new Blob([new Uint8Array(data)], { type }));
        setUrl(created);
      })
      .catch((e) => !cancelled && setError(String(e)));

    return () => {
      cancelled = true;
      if (created) URL.revokeObjectURL(created);
    };
  }, [path]);

  useEffect(() => {
    if (audioRef.current) audioRef.current.volume = volume;
  }, [volume, url]);

  const toggle = () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (playing) audio.pause();
    else void audio.play().catch((e) => setError(String(e)));
  };

  if (error) return <Note heading="Preview unavailable">{error}</Note>;

  return (
    <div className="player">
      <button className="transport" onClick={toggle} disabled={!url} type="button"
              aria-label={playing ? "Pause" : "Play"}>
        {playing ? "❚❚" : "▶"}
      </button>

      <input
        className="seek"
        type="range"
        min={0}
        max={duration || 0}
        step={0.05}
        value={time}
        disabled={!duration}
        aria-label="Seek"
        onChange={(e) => {
          const next = Number(e.target.value);
          setTime(next);
          if (audioRef.current) audioRef.current.currentTime = next;
        }}
      />

      <span className="time">{clock(time)} / {clock(duration)}</span>

      <input
        className="vol"
        type="range"
        min={0}
        max={1}
        step={0.01}
        value={volume}
        aria-label="Volume"
        onChange={(e) => setVolume(Number(e.target.value))}
      />

      {url && (
        <audio
          ref={audioRef}
          src={url}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
          onEnded={() => { setPlaying(false); setTime(0); }}
          onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
          onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
        />
      )}
    </div>
  );
}
