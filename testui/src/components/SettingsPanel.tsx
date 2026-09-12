/**
 * Manual override for the backend URL and access key.
 *
 * The normal path is: receive link, click, working -- this panel is the
 * escape hatch for when the ngrok host changes and re-sending a link is
 * slower than pasting one field.
 */

import { useState } from "react";
import { Check, ChevronDown, ChevronUp, Eye, EyeOff, Settings } from "lucide-react";

import type { AppConfig } from "../config";
import { Button } from "./ui/Button";
import { PageHeader } from "./ui/PageHeader";

interface Props {
  config: AppConfig;
  onSave: (next: AppConfig) => void;
}

export function SettingsPanel({ config, onSave }: Props): JSX.Element {
  const [open, setOpen] = useState(false);
  const [apiBaseUrl, setApiBaseUrl] = useState(config.apiBaseUrl);
  const [apiKey, setApiKey] = useState(config.apiKey);
  const [revealKey, setRevealKey] = useState(false);
  const [saved, setSaved] = useState(false);

  const save = (): void => {
    onSave({ apiBaseUrl, apiKey });
    setSaved(true);
    window.setTimeout(() => setSaved(false), 1500);
  };

  return (
    <section className="panel">
      <PageHeader
        icon={Settings}
        title="Settings"
        description={`${config.apiBaseUrl === "" ? "no backend URL set" : config.apiBaseUrl} · ${config.apiKey === "" ? "no key set" : "key set"}`}
        actions={
          <Button size="sm" icon={open ? ChevronUp : ChevronDown} onClick={() => setOpen(!open)} aria-expanded={open}>
            {open ? "Hide" : "Edit"}
          </Button>
        }
      />

      {open && (
        <div className="settings">
          <label className="settings__row">
            <span>Backend URL</span>
            <input
              type="text"
              value={apiBaseUrl}
              spellCheck={false}
              placeholder="https://your-tunnel-host.ngrok-free.dev"
              onChange={(event) => setApiBaseUrl(event.target.value)}
            />
          </label>

          <label className="settings__row">
            <span>Access key</span>
            <input
              type={revealKey ? "text" : "password"}
              value={apiKey}
              spellCheck={false}
              autoComplete="off"
              placeholder="X-Aegle-Key value"
              onChange={(event) => setApiKey(event.target.value)}
            />
          </label>

          <div className="settings__actions">
            <label className="checkbox">
              <input type="checkbox" checked={revealKey} onChange={(e) => setRevealKey(e.target.checked)} />
              {revealKey ? <EyeOff size={13} aria-hidden="true" /> : <Eye size={13} aria-hidden="true" />}
              <span>Show key</span>
            </label>
            <Button variant="primary" icon={Check} onClick={save}>{saved ? "Saved" : "Save"}</Button>
          </div>

          <p className="muted settings__hint">
            Stored in this browser only. The usual way to set these is to open the
            link you were sent — it fills both in and then removes them from the URL.
          </p>
        </div>
      )}
    </section>
  );
}
