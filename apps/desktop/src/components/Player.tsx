import { useEffect, useRef, useState } from "react";
import { shell } from "../lib/api";
import { clock } from "../lib/format";

/** Preview player for generated WAV/MP3. Loads bytes through the shell so it
 *  works regardless of where the user's export folder lives. */
export function Player({ path, label }: { path: string; label?: string }) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [volume, setVolume] = useState(0.85);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let revoked: string | null = null;
    let cancelled = false;
    setError(null);
    setUrl(null);

    shell
      .readMedia(path)
      .then((data) => {
        if (cancelled) return;
        const type = path.toLowerCase().endsWith(".mp3") ? "audio/mpeg" : "audio/wav";
        const blob = new Blob([new Uint8Array(data)], { type });
        revoked = URL.createObjectURL(blob);
        setUrl(revoked);
      })
      .catch((e) => !cancelled && setError(String(e)));

    return () => {
      cancelled = true;
      if (revoked) URL.revokeObjectURL(revoked);
    };
  }, [path]);

  useEffect(() => {
    if (audioRef.current) audioRef.current.volume = volume;
  }, [volume, url]);

  const toggle = () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (playing) {
      audio.pause();
    } else {
      void audio.play().catch((e) => setError(String(e)));
    }
  };

  if (error) {
    return <div className="notice warn">Preview unavailable: {error}</div>;
  }

  return (
    <div className="player">
      <button className="play" onClick={toggle} disabled={!url} type="button"
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
        onChange={(e) => {
          const next = Number(e.target.value);
          setTime(next);
          if (audioRef.current) audioRef.current.currentTime = next;
        }}
        disabled={!duration}
      />
      <span className="time">
        {clock(time)} / {clock(duration)}
      </span>
      <input
        className="vol"
        type="range"
        min={0}
        max={1}
        step={0.01}
        value={volume}
        onChange={(e) => setVolume(Number(e.target.value))}
        aria-label="Volume"
      />
      {label && <span className="faint mono">{label}</span>}
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
