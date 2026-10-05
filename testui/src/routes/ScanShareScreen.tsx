/**
 * P22 -- Scan & Share (spec section 5), the patient's end. The other half
 * of the handshake repo/'s P21 built on the facility side: scan the QR
 * taped to a reception desk, agree to what gets sent, and get an OPD queue
 * token back.
 *
 * ONE CONTINUOUS SCREEN, not several routes -- same standing real-app
 * navigation rule UilLinkScreen.tsx follows: scan -> consent -> waiting ->
 * token, all as phase transitions inside this one component.
 *
 * THREE WAYS IN, ALL BUILT, IN THIS ORDER OF PROMINENCE:
 *   1. Camera      -- getUserMedia + jsQR over video frames on a canvas.
 *   2. Upload      -- the same decoder against a File. THE ONE THAT
 *                     MATTERS FIRST: P21's own test flow writes the counter
 *                     QR out as a PNG, so the whole loop closes on one
 *                     machine with no camera involved at all.
 *   3. Paste       -- a text box. Always works, never blocked.
 *
 * THE CAMERA NEEDS A SECURE CONTEXT. getUserMedia is unavailable on a
 * plain-http origin that is not localhost, which is exactly what a LAN
 * address is. Detected up front (see `cameraBlockedReason`) and said out
 * loud, because a dead button with no explanation is worse than no button.
 *
 * WE PARSE THE QR, WE DO NOT OPEN IT. The URL inside points at ABDM's own
 * hosted page, which is for patients whose PHR app is not this one. Ours
 * reads the hip-id/counter-id out of it and calls the CM directly.
 *
 * THE CONSENT STEP IS THE POINT, not a formality. The patient sees every
 * field that will be sent, labelled, before anything leaves the device --
 * and what is sent is literally the object that was rendered, not a
 * re-fetch that could differ from it.
 *
 * TWO MECHANISMS FOR THE TOKEN COMING BACK, BOTH POLLED HERE. Nobody has
 * documented which is real (see aegle_phr/phr/profile_share.py's banner),
 * so while waiting this screen polls BOTH our own row (which an inbound
 * on-share callback would have written) AND ABDM's getTokenDetails. First
 * one to produce a number wins. If neither does, the timeout says so
 * plainly and names both -- an honest dead end beats a spinner.
 */

import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  Camera,
  CheckCircle2,
  Clipboard,
  Hourglass,
  Loader2,
  QrCode,
  ScanLine,
  Share2,
  Upload,
  X,
} from "lucide-react";

import {
  getProfile,
  getScanShareResult,
  scanShareParse,
  scanShareShare,
  scanShareTokenDetails,
} from "../api/endpoints";
import type { AbdmPassthrough, ApiResult } from "../api/types";
import { RawBody } from "../components/RawBody";
import { Button } from "../components/ui/Button";
import { Callout } from "../components/ui/Callout";
import { Card, CardBody, CardTitle } from "../components/ui/Card";
import { InfoRow } from "../components/ui/InfoRow";
import { PageHeader } from "../components/ui/PageHeader";
import { getSessionAddress, getSessionToken } from "../session";

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

/** ~60s, per the task spec's own budget. Long enough for a real callback, short enough that a genuine dead end does not read as a hang. */
const POLL_INTERVAL_MS = 2000;
const POLL_MAX_ATTEMPTS = 30;

type Phase = "scan" | "consent" | "sharing" | "waiting" | "done" | "timeout";

interface ParsedQr {
  hipId: string;
  counterId: string;
  facilityName: string | null;
  raw: string;
}

/** The exact object that gets both displayed and sent. One source, no drift. */
interface SharePatient {
  abhaAddress: string;
  abhaNumber?: string;
  name?: string;
  gender?: string;
  dayOfBirth?: string;
  monthOfBirth?: string;
  yearOfBirth?: string;
  phoneNumber?: string;
  address?: { line?: string; district?: string; state?: string; pincode?: string };
}

function str(source: unknown, key: string): string {
  if (source !== null && typeof source === "object" && key in source) {
    const value = (source as Record<string, unknown>)[key];
    if (typeof value === "string") return value;
    if (typeof value === "number") return String(value);
  }
  return "";
}

function obj(source: unknown, key: string): Record<string, unknown> | null {
  if (source !== null && typeof source === "object" && key in source) {
    const value = (source as Record<string, unknown>)[key];
    if (value !== null && typeof value === "object") return value as Record<string, unknown>;
  }
  return null;
}

/** Builds the share payload out of the profile ABDM already gave us. Blank fields are dropped, not sent empty. */
function buildSharePatient(profileBody: unknown, fallbackAbhaAddress: string): SharePatient {
  const out: SharePatient = { abhaAddress: str(profileBody, "abhaAddress") || fallbackAbhaAddress };

  const maybe = (key: keyof SharePatient, value: string): void => {
    if (value !== "") (out as unknown as Record<string, unknown>)[key] = value;
  };

  maybe("abhaNumber", str(profileBody, "abhaNumber"));
  maybe("name", str(profileBody, "fullName"));
  maybe("gender", str(profileBody, "gender"));
  maybe("dayOfBirth", str(profileBody, "dayOfBirth"));
  maybe("monthOfBirth", str(profileBody, "monthOfBirth"));
  maybe("yearOfBirth", str(profileBody, "yearOfBirth"));
  maybe("phoneNumber", str(profileBody, "mobile"));

  const address = {
    line: str(profileBody, "address"),
    district: str(profileBody, "districtName"),
    state: str(profileBody, "stateName"),
    pincode: str(profileBody, "pinCode"),
  };
  if (Object.values(address).some((v) => v !== "")) out.address = address;

  return out;
}

/**
 * Renders the expiry ABDM sent.
 *
 * ONLY treated as seconds when it is ALL DIGITS. Its semantics are
 * genuinely unresolved upstream -- both Postman samples send "1800" but
 * NHA's own wrapper stringifies a timestamp into the same field on one
 * code path. Printing "valid ~30 minutes" over a timestamp would be a
 * confident lie; printing the raw string is merely unhelpful.
 */
function describeExpiry(expiry: string | null): string {
  if (expiry === null || expiry.trim() === "") return "";
  const trimmed = expiry.trim();
  if (!/^\d+$/.test(trimmed)) return trimmed;
  const seconds = Number(trimmed);
  if (seconds < 60) return `valid ~${seconds} seconds`;
  return `valid ~${Math.round(seconds / 60)} minutes`;
}

/** Digs a token out of getTokenDetails' unknown response shape -- the same three nestings the backend callback handler checks, plus a list. */
function tokenFromDetails(body: unknown, counterId: string): { tokenNumber: string; expiry: string } | null {
  const readOne = (entry: unknown): { tokenNumber: string; expiry: string } | null => {
    if (entry === null || typeof entry !== "object") return null;
    const profile = obj(entry, "profile");
    const tokenNumber =
      str(entry, "tokenNumber") || (profile !== null ? str(profile, "tokenNumber") : "");
    if (tokenNumber === "") return null;
    const expiry = str(entry, "expiry") || (profile !== null ? str(profile, "expiry") : "");
    const context = str(entry, "context") || (profile !== null ? str(profile, "context") : "");
    // When a context is present, only accept the one for THIS counter --
    // the list may well carry older shares.
    if (counterId !== "" && context !== "" && context !== counterId) return null;
    return { tokenNumber, expiry };
  };

  const direct = readOne(body);
  if (direct !== null) return direct;

  const candidates: unknown[] = [];
  if (Array.isArray(body)) candidates.push(...body);
  if (body !== null && typeof body === "object") {
    for (const key of ["data", "tokens", "profiles", "result", "items"]) {
      const value = (body as Record<string, unknown>)[key];
      if (Array.isArray(value)) candidates.push(...value);
      else if (value !== null && typeof value === "object") candidates.push(value);
    }
  }
  for (const entry of candidates) {
    const found = readOne(entry);
    if (found !== null) return found;
  }
  return null;
}

export function ScanShareScreen(): JSX.Element {
  const navigate = useNavigate();
  const [sessionToken] = useState(() => getSessionToken());
  const [sessionAddress] = useState(() => getSessionAddress());

  const [phase, setPhase] = useState<Phase>("scan");
  const [busy, setBusy] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  const [parsed, setParsed] = useState<ParsedQr | null>(null);
  const [patient, setPatient] = useState<SharePatient | null>(null);
  const [profileResult, setProfileResult] = useState<ApiResult<AbdmPassthrough> | null>(null);
  const [parseResult, setParseResult] = useState<ApiResult<AbdmPassthrough> | null>(null);
  const [shareResult, setShareResult] = useState<ApiResult<AbdmPassthrough> | null>(null);
  const [pollResult, setPollResult] = useState<ApiResult<AbdmPassthrough> | null>(null);
  const [detailsResult, setDetailsResult] = useState<ApiResult<AbdmPassthrough> | null>(null);

  const [requestId, setRequestId] = useState("");
  const [tokenNumber, setTokenNumber] = useState("");
  const [tokenExpiry, setTokenExpiry] = useState<string | null>(null);
  const [tokenSource, setTokenSource] = useState("");

  const [pasted, setPasted] = useState("");
  const [cameraOn, setCameraOn] = useState(false);
  const [cameraError, setCameraError] = useState("");
  // What the decode loop is actually doing. A black <video> with no
  // status line is indistinguishable from a broken one -- this is the
  // difference between the two.
  const [cameraStatus, setCameraStatus] = useState("");

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const scanTimerRef = useRef<number | null>(null);

  /**
   * Why the camera cannot be offered, if it cannot -- computed rather than
   * discovered on click, so the button can say so instead of failing.
   */
  const cameraBlockedReason =
    typeof navigator !== "undefined" && typeof navigator.mediaDevices?.getUserMedia === "function"
      ? ""
      : window.isSecureContext === false
        ? "Your browser only allows camera access over HTTPS (or on localhost). This page is on plain http, so use Upload or Paste below."
        : "This browser does not expose a camera to web pages. Use Upload or Paste below.";

  const stopCamera = (): void => {
    if (scanTimerRef.current !== null) {
      window.clearInterval(scanTimerRef.current);
      scanTimerRef.current = null;
    }
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    setCameraOn(false);
    setCameraStatus("");
  };

  // Release the camera on unmount -- a live track left running keeps the
  // device's recording indicator on after the patient has navigated away,
  // which is both alarming and a real privacy problem.
  useEffect(() => stopCamera, []);

  const run = async (fn: () => Promise<void>): Promise<void> => {
    setBusy(true);
    try {
      await fn();
    } finally {
      setBusy(false);
    }
  };

  /** Shared by all three input paths: parse, load the profile, move to consent. */
  const acceptScanned = (scanned: string): void => {
    void run(async () => {
      setErrorMessage("");
      const result = await scanShareParse({ scanned });
      setParseResult(result);
      if (result.data?.ok !== true) {
        setErrorMessage(result.errorMessage || "That QR code could not be read as a facility counter code.");
        return;
      }
      const body = result.data.body;
      const next: ParsedQr = {
        hipId: str(body, "hipId"),
        counterId: str(body, "counterId"),
        facilityName: str(body, "facilityName") || null,
        raw: str(body, "raw"),
      };
      if (next.hipId === "") {
        setErrorMessage("That QR code carried no facility id.");
        return;
      }
      setParsed(next);
      stopCamera();

      const profile = await getProfile({ xToken: sessionToken });
      setProfileResult(profile);
      if (profile.data?.ok !== true) {
        setErrorMessage("Couldn't load your profile, so there is nothing to share yet. Check the Console.");
        return;
      }
      setPatient(buildSharePatient(profile.data.body, sessionAddress));
      setPhase("consent");
    });
  };

  const startCamera = (): void => {
    void run(async () => {
      setCameraError("");
      setCameraStatus("");
      try {
        let stream: MediaStream;
        try {
          // A PREFERENCE, not a requirement (no `exact`), so a laptop with
          // only a front-facing webcam still gets its camera.
          stream = await navigator.mediaDevices.getUserMedia({
            video: { facingMode: "environment" },
            audio: false,
          });
        } catch {
          // ...except some drivers reject the preference outright rather
          // than falling back. Ask for any camera at all.
          stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
        }
        streamRef.current = stream;
        // Attaching the stream happens in the effect below, NOT here -- see
        // that effect's own comment for why this cost an hour.
        setCameraOn(true);
      } catch (err) {
        setCameraError(
          err instanceof Error && err.name === "NotAllowedError"
            ? "Camera permission was declined. Use Upload or Paste below instead."
            : err instanceof Error && err.name === "NotFoundError"
              ? "No camera was found on this device. Use Upload or Paste below instead."
              : `Couldn't start the camera${err instanceof Error ? ` (${err.name})` : ""}. Use Upload or Paste below instead.`,
        );
      }
    });
  };

  /**
   * Attaches the stream and starts decoding, ONCE THE <video> IS REALLY IN
   * THE DOM.
   *
   * THIS USED TO BE A setTimeout(..., 0) INSIDE startCamera(), AND IT WAS A
   * REAL BUG -- reported live 2026-09-29 as "black screen, isn't scanning".
   * setCameraOn(true) only SCHEDULES a React render; a 0ms macrotask can
   * fire before React commits, so videoRef.current was still null, the
   * function returned early, and nothing ever set srcObject or started the
   * interval. The <video> rendered (black, from its own background) with no
   * source and no way back, because the Start button was already gone. An
   * effect keyed on cameraOn cannot race the commit: it runs after it, by
   * definition.
   */
  useEffect(() => {
    if (!cameraOn) return;
    const video = videoRef.current;
    const stream = streamRef.current;
    if (video === null || stream === null) return;

    video.srcObject = stream;
    let cancelled = false;

    // play() can reject (autoplay policy, a track that ends immediately).
    // The old code swallowed that with `void`, which is precisely how a
    // black frame ends up with no explanation attached to it.
    video.play().catch((err: unknown) => {
      if (cancelled) return;
      setCameraError(
        `The camera stream did not start playing${err instanceof Error ? ` (${err.name})` : ""}. ` +
        "Use Upload or Paste below instead.",
      );
    });

    scanTimerRef.current = window.setInterval(() => void tick(), 250);

    return () => {
      cancelled = true;
      if (scanTimerRef.current !== null) {
        window.clearInterval(scanTimerRef.current);
        scanTimerRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cameraOn]);

  /** One decode attempt against the current video frame. */
  const tick = async (): Promise<void> => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (video === null || canvas === null) return;

    // HAVE_CURRENT_DATA (2) is enough to grab a frame. The old check
    // demanded HAVE_ENOUGH_DATA (4) exactly, which a stream sitting at 3
    // never satisfies -- another way to scan forever and find nothing.
    if (video.readyState < 2 || video.videoWidth === 0 || video.videoHeight === 0) {
      setCameraStatus("Starting the camera…");
      return;
    }

    const context = canvas.getContext("2d", { willReadFrequently: true });
    if (context === null) return;
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    const image = context.getImageData(0, 0, canvas.width, canvas.height);
    const { default: jsQR } = await import("jsqr");
    const code = jsQR(image.data, image.width, image.height, { inversionAttempts: "attemptBoth" });

    if (code !== null && code.data.trim() !== "") {
      stopCamera();
      acceptScanned(code.data);
      return;
    }
    // Says the loop is alive and what it is looking at, so "black screen"
    // and "running but nothing in frame" are never again the same picture.
    setCameraStatus(`Scanning ${video.videoWidth}×${video.videoHeight} — hold the QR steady in frame`);
  };

  /** Decode an uploaded image -- the path that closes the loop with no camera. */
  const onFile = (file: File | null): void => {
    if (file === null) return;
    void run(async () => {
      setErrorMessage("");
      const url = URL.createObjectURL(file);
      try {
        const image = await new Promise<HTMLImageElement>((resolve, reject) => {
          const element = new Image();
          element.onload = () => resolve(element);
          element.onerror = () => reject(new Error("not an image"));
          element.src = url;
        });
        const canvas = document.createElement("canvas");
        canvas.width = image.naturalWidth;
        canvas.height = image.naturalHeight;
        const context = canvas.getContext("2d", { willReadFrequently: true });
        if (context === null) throw new Error("no 2d context");
        context.drawImage(image, 0, 0);
        const data = context.getImageData(0, 0, canvas.width, canvas.height);
        const { default: jsQR } = await import("jsqr");
        const code = jsQR(data.data, data.width, data.height, { inversionAttempts: "attemptBoth" });
        if (code === null || code.data.trim() === "") {
          setErrorMessage("No QR code was found in that image. Try a sharper or larger picture, or paste the URL instead.");
          return;
        }
        acceptScanned(code.data);
      } catch {
        setErrorMessage("That file could not be read as an image.");
      } finally {
        URL.revokeObjectURL(url);
      }
    });
  };

  /**
   * The share itself, then the wait.
   *
   * BOTH mechanisms are polled on every attempt. Our own row is written by
   * an inbound on-share callback if one ever arrives; getTokenDetails is
   * ABDM's own list. Neither is known to work, so neither is trusted alone.
   */
  /**
   * The wait, on its own so "Check again" can re-enter it WITHOUT
   * re-sharing. Sharing twice would put the patient in the queue twice --
   * P21's facility side does guard against that (it reuses an unexpired
   * token for the same patient at the same counter), but relying on the
   * other end to undo our mistake is not a design.
   */
  const pollForToken = async (id: string, counterId: string): Promise<void> => {
    for (let attempt = 0; attempt < POLL_MAX_ATTEMPTS; attempt += 1) {
      await sleep(POLL_INTERVAL_MS);

      // Candidate A -- our own row, written by the callback if it fires.
      const row = await getScanShareResult(id);
      setPollResult(row);
      const rowBody = row.data?.body;
      const rowToken = str(rowBody, "tokenNumber");
      if (rowToken !== "") {
        setTokenNumber(rowToken);
        setTokenExpiry(str(rowBody, "tokenExpiry") || null);
        setTokenSource(str(rowBody, "source") || "CALLBACK");
        setPhase("done");
        return;
      }

      // Candidate B -- ABDM's own list. Polled every other attempt so a
      // 60s wait is ~15 calls, not 30.
      if (attempt % 2 === 1) {
        const details = await scanShareTokenDetails({ xToken: sessionToken, limit: -1 });
        setDetailsResult(details);
        if (details.data?.ok === true) {
          const found = tokenFromDetails(details.data.body, counterId);
          if (found !== null) {
            setTokenNumber(found.tokenNumber);
            setTokenExpiry(found.expiry || null);
            setTokenSource("POLL");
            setPhase("done");
            return;
          }
        }
      }
    }
    setPhase("timeout");
  };

  const share = (): void => {
    if (parsed === null || patient === null) return;
    void run(async () => {
      setErrorMessage("");
      setPhase("sharing");
      const result = await scanShareShare({
        xToken: sessionToken,
        hipId: parsed.hipId,
        counterId: parsed.counterId,
        // The EXACT object rendered on the consent card above.
        patient: patient as unknown as Record<string, unknown>,
      });
      setShareResult(result);

      const id = str(result.data, "requestId");
      if (result.data?.ok !== true || id === "") {
        setErrorMessage(
          result.data?.error || result.errorMessage || "The share was not accepted — check the Console for what ABDM said.",
        );
        setPhase("consent");
        return;
      }
      setRequestId(id);
      setPhase("waiting");
      await pollForToken(id, parsed.counterId);
    });
  };

  /** Re-enters the wait for the share ALREADY sent -- never a second share. */
  const checkAgain = (): void => {
    if (requestId === "") return;
    void run(async () => {
      setPhase("waiting");
      await pollForToken(requestId, parsed?.counterId ?? "");
    });
  };

  const reset = (): void => {
    stopCamera();
    setPhase("scan");
    setParsed(null);
    setPatient(null);
    setRequestId("");
    setTokenNumber("");
    setTokenExpiry(null);
    setTokenSource("");
    setPasted("");
    setErrorMessage("");
  };

  if (sessionToken === "" || sessionAddress === "") {
    return (
      <section>
        <PageHeader icon={ScanLine} title="Scan & Share" />
        <p className="muted">Log in first to share your profile with a facility.</p>
      </section>
    );
  }

  const facilityLabel = parsed?.facilityName || parsed?.hipId || "this facility";

  return (
    <section>
      <PageHeader
        icon={ScanLine}
        title="Scan &amp; Share"
        description="Scan the QR at a hospital's reception desk to share your details and get a queue token — no forms, no typing."
      />

      {errorMessage !== "" && (
        <Callout tone="warning" icon={AlertTriangle}>{errorMessage}</Callout>
      )}

      {/* ---------------------------------------------------------------- */}
      {phase === "scan" && (
        <>
          <Card>
            <CardTitle icon={Camera}>Scan with the camera</CardTitle>
            <CardBody>
              {cameraBlockedReason !== "" ? (
                <Callout tone="warning" icon={AlertTriangle}>{cameraBlockedReason}</Callout>
              ) : cameraOn ? (
                <>
                  {/* autoPlay as well as the explicit play() call: some
                      browsers honour one and not the other, and a muted,
                      playsInline video is allowed to autoplay everywhere. */}
                  <video
                    ref={videoRef}
                    autoPlay
                    playsInline
                    muted
                    style={{ width: "100%", borderRadius: 12, background: "#000" }}
                  />
                  <p className="muted" style={{ marginTop: 8 }}>
                    {cameraStatus || "Starting the camera…"}
                  </p>
                  <div style={{ marginTop: 12 }}>
                    <Button variant="secondary" icon={X} onClick={stopCamera}>Stop camera</Button>
                  </div>
                </>
              ) : (
                <>
                  <p className="muted">Point the camera at the QR code on the reception desk.</p>
                  <Button variant="primary" icon={Camera} onClick={startCamera} disabled={busy}>
                    Start camera
                  </Button>
                </>
              )}
              {cameraError !== "" && <Callout tone="warning" icon={AlertTriangle}>{cameraError}</Callout>}
              <canvas ref={canvasRef} style={{ display: "none" }} />
            </CardBody>
          </Card>

          <Card>
            <CardTitle icon={Upload}>Upload a photo of the QR</CardTitle>
            <CardBody>
              <p className="muted">
                Works with no camera at all — handy for a saved PNG of the counter code.
              </p>
              <input
                type="file"
                accept="image/*"
                disabled={busy}
                onChange={(event) => onFile(event.target.files?.[0] ?? null)}
              />
            </CardBody>
          </Card>

          <Card>
            <CardTitle icon={Clipboard}>Paste the link</CardTitle>
            <CardBody>
              <p className="muted">The address the QR contains, if you already have it as text.</p>
              <input
                type="text"
                value={pasted}
                placeholder="https://…/share-profile?hip-id=…&counter-id=…"
                onChange={(event) => setPasted(event.target.value)}
                style={{ width: "100%" }}
              />
              <div style={{ marginTop: 12 }}>
                <Button
                  variant="primary"
                  icon={QrCode}
                  disabled={busy || pasted.trim() === ""}
                  onClick={() => acceptScanned(pasted)}
                >
                  Read this link
                </Button>
              </div>
            </CardBody>
          </Card>
        </>
      )}

      {/* ---------------------------------------------------------------- */}
      {phase === "consent" && parsed !== null && patient !== null && (
        <>
          <Card>
            <CardTitle icon={Share2}>Share with {facilityLabel}?</CardTitle>
            <CardBody>
              <InfoRow label="Facility" value={parsed.facilityName || parsed.hipId} />
              <InfoRow label="Facility ID" value={parsed.hipId} />
              {parsed.counterId !== "" && <InfoRow label="Counter" value={parsed.counterId} />}
            </CardBody>
          </Card>

          <Card>
            <CardTitle icon={CheckCircle2}>Exactly what will be sent</CardTitle>
            <CardBody>
              <p className="muted">Nothing else leaves your phone. These are the only fields in the request.</p>
              <InfoRow label="ABHA address" value={patient.abhaAddress} />
              {patient.abhaNumber && <InfoRow label="ABHA number" value={patient.abhaNumber} />}
              {patient.name && <InfoRow label="Name" value={patient.name} />}
              {patient.gender && <InfoRow label="Gender" value={patient.gender} />}
              {(patient.dayOfBirth || patient.monthOfBirth || patient.yearOfBirth) && (
                <InfoRow
                  label="Date of birth"
                  value={[patient.dayOfBirth, patient.monthOfBirth, patient.yearOfBirth].filter(Boolean).join(" / ")}
                />
              )}
              {patient.phoneNumber && <InfoRow label="Phone" value={patient.phoneNumber} />}
              {patient.address && (
                <InfoRow
                  label="Address"
                  value={[patient.address.line, patient.address.district, patient.address.state, patient.address.pincode]
                    .filter((v) => v !== undefined && v !== "")
                    .join(", ") || "—"}
                />
              )}
              <div style={{ marginTop: 16, display: "flex", gap: 8 }}>
                <Button variant="primary" icon={Share2} onClick={share} disabled={busy}>
                  Share these details
                </Button>
                <Button variant="secondary" icon={X} onClick={reset} disabled={busy}>
                  Cancel
                </Button>
              </div>
            </CardBody>
          </Card>
        </>
      )}

      {/* ---------------------------------------------------------------- */}
      {(phase === "sharing" || phase === "waiting") && (
        <Card>
          <CardTitle icon={Hourglass}>Waiting for your token</CardTitle>
          <CardBody>
            <p>
              <Loader2 size={16} className="spin" aria-hidden="true" /> {facilityLabel} has your details. Waiting for
              them to issue a queue number.
            </p>
            <p className="muted">This usually takes a few seconds.</p>
          </CardBody>
        </Card>
      )}

      {/* ---------------------------------------------------------------- */}
      {phase === "done" && (
        <Card>
          <CardTitle icon={CheckCircle2}>You are in the queue</CardTitle>
          <CardBody>
            <p style={{ fontSize: "3rem", fontWeight: 700, margin: "8px 0", lineHeight: 1 }}>{tokenNumber}</p>
            <p>{parsed?.facilityName || parsed?.hipId}</p>
            {describeExpiry(tokenExpiry) !== "" && <p className="muted">{describeExpiry(tokenExpiry)}</p>}
            {tokenSource !== "" && (
              <p className="muted" style={{ fontSize: "0.8rem" }}>
                Delivered via {tokenSource === "POLL" ? "ABDM's token list (poll)" : "the on-share callback"}.
              </p>
            )}
            <div style={{ marginTop: 16, display: "flex", gap: 8 }}>
              <Button variant="secondary" onClick={reset}>Scan another</Button>
              <Button variant="secondary" onClick={() => navigate("/home")}>Done</Button>
            </div>
          </CardBody>
        </Card>
      )}

      {/* ---------------------------------------------------------------- */}
      {phase === "timeout" && (
        <Card>
          <CardTitle icon={AlertTriangle}>Shared, but no token came back</CardTitle>
          <CardBody>
            <p>
              {facilityLabel} accepted your details — the share itself went through. No queue number reached this app
              within a minute.
            </p>
            <p className="muted">
              Both routes were tried: the on-share callback ABDM may send us, and ABDM&apos;s own token list
              (getTokenDetails). Neither produced a number. Ask at the desk — they may well have your token on their
              screen already.
            </p>
            <InfoRow label="Request ID" value={requestId || "—"} />
            <div style={{ marginTop: 16, display: "flex", gap: 8 }}>
              <Button variant="secondary" onClick={checkAgain} disabled={busy}>
                Check again
              </Button>
              <Button variant="secondary" onClick={reset}>Scan another</Button>
            </div>
          </CardBody>
        </Card>
      )}

      <RawBody label="Parse QR" result={parseResult} />
      <RawBody label="Profile" result={profileResult} />
      <RawBody label="Share profile" result={shareResult} />
      <RawBody label="Share result (our row)" result={pollResult} />
      <RawBody label="getTokenDetails (ABDM)" result={detailsResult} />
    </section>
  );
}
