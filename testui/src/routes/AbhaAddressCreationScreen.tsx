/**
 * ABHA Address creation for an EXISTING ABHA Number (P1-H) -- Aayush's
 * third top-level entry point, alongside Login and Signup:
 *
 *   1. Login  -- an existing ABHA account.
 *   2. Signup -- no ABHA account yet (AadhaarRegisterScreen, enrol/byAadhaar).
 *   3. THIS SCREEN -- already have an ABHA Number, want an ABHA Address for
 *      it. A different operation from Signup, not a follow-up step of it --
 *      confirmed directly against Aayush's own Postman collection.
 *
 * ONE PARAMETRIZED COMPONENT, TWO METHODS (matching OtpLoginScreen's own
 * precedent for near-identical flows): request/otp -> verify -> straight to
 * suggestion/isExists/enrol, IDENTICAL FOR BOTH METHODS -- corrected,
 * 2026-08-31 (Aayush, directly): an earlier version added a verify/user
 * step (WITH a T-token) for method="mobile" only, based on a step present
 * in the Postman collection's saved "Enrolment via ABHA Number-ABHA OTP"
 * folder. That step is not actually required in practice -- verify's own
 * response already carries everything needed to proceed (see
 * extractAccount() below) -- and was removed rather than kept as an unused
 * option. Lesson: a step existing in a reference collection is not the
 * same as a step being required; don't add one without confirming it's
 * actually needed.
 *
 * DEMOGRAPHICS ARE AUTO-FILLED FROM verify's OWN RESPONSE -- CORRECTED,
 * 2026-08-31, against a real captured live response: an earlier version of
 * this file assumed verify (Aadhaar-OTP variant) does not hand back a
 * profile, so every field here (firstName/lastName/DOB/gender/address/
 * mobile/email/state/district/pincode) was a manually-typed input. Wrong
 * -- the real response carries a full `accounts[]` array with the complete
 * profile (see extractAccount() below), and Aayush's own standing rule is
 * to never re-ask for data a flow already has. Section 3's fields are now
 * auto-filled the moment verify succeeds, in the same onClick that sets
 * txnId -- still rendered as ordinary editable inputs (not locked), since
 * nothing here was told to prevent correcting a stale or wrong value, only
 * to stop demanding it be re-typed from scratch.
 *
 * ⚠ Both request/otp calls send a real OTP (UIDAI or SMS) and count toward
 * ABDM's rate limits. Request once, verify once.
 */

import { useState } from "react";
import { Check, IdCard, Search, Send } from "lucide-react";

import {
  checkAddressExists,
  enrol,
  getAddressSuggestions,
  requestAbhaAddressCreationOtpAadhaar,
  requestAbhaAddressCreationOtpMobile,
  verifyAbhaAddressCreationOtpAadhaar,
  verifyAbhaAddressCreationOtpMobile,
} from "../api/endpoints";
import type { AbdmPassthrough, ApiResult } from "../api/types";
import { extractSuggestions, withSandboxSuffix } from "../addressSuggestion";
import { RawBody } from "../components/RawBody";
import { Button } from "../components/ui/Button";
import { PageHeader } from "../components/ui/PageHeader";

function stringField(body: unknown, key: string): string {
  if (body !== null && typeof body === "object" && key in body) {
    const value = (body as Record<string, unknown>)[key];
    if (typeof value === "string") return value;
  }
  return "";
}

interface AccountProfile {
  firstName: string;
  middleName: string;
  lastName: string;
  dayOfBirth: string;
  monthOfBirth: string;
  yearOfBirth: string;
  gender: string;
  email: string;
  mobile: string;
  address: string;
  stateName: string;
  stateCode: string;
  districtName: string;
  districtCode: string;
  pinCode: string;
}

/**
 * verify's response for THIS flow carries a full `accounts[]` array with
 * the complete demographic profile -- CONFIRMED live, 2026-08-31 (a real
 * captured response, not the M1/enrol_by_aadhaar shape this file's own
 * banner originally assumed didn't apply here). Auto-fills section 3
 * so nothing already known gets re-typed, matching Aayush's own standing
 * rule. Only the first entry is used -- the confirmed example carries
 * exactly one, for the single verified identity.
 *
 * FIELD NAME MISMATCH, HANDLED HERE: the real response uses "pincode"
 * (all lowercase), not "pinCode" -- mapped explicitly rather than assumed
 * to match enrol()'s own phrDetails field name.
 */
function extractAccount(body: unknown): AccountProfile | null {
  if (body === null || typeof body !== "object" || !("accounts" in body)) return null;
  const accounts = (body as { accounts: unknown }).accounts;
  if (!Array.isArray(accounts) || accounts.length === 0) return null;
  const account = accounts[0];
  if (account === null || typeof account !== "object") return null;
  const record = account as Record<string, unknown>;
  const str = (key: string): string => (typeof record[key] === "string" ? (record[key] as string) : "");
  return {
    firstName: str("firstName"),
    middleName: str("middleName"),
    lastName: str("lastName"),
    dayOfBirth: str("dayOfBirth"),
    monthOfBirth: str("monthOfBirth"),
    yearOfBirth: str("yearOfBirth"),
    gender: str("gender"),
    email: str("email"),
    mobile: str("mobile"),
    address: str("address"),
    stateName: str("stateName"),
    stateCode: str("stateCode"),
    districtName: str("districtName"),
    districtCode: str("districtCode"),
    pinCode: str("pincode"),
  };
}

function Text({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }): JSX.Element {
  return (
    <label className="row">
      <span>{label}</span>
      <input type="text" value={value} autoComplete="off" onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}

interface Props {
  method: "aadhaar" | "mobile";
}

export function AbhaAddressCreationScreen({ method }: Props): JSX.Element {
  const [busy, setBusy] = useState(false);
  const [abhaNumber, setAbhaNumber] = useState("");
  const [otp, setOtp] = useState("");
  const [txnId, setTxnId] = useState("");

  const [otpResult, setOtpResult] = useState<ApiResult<AbdmPassthrough> | null>(null);
  const [verifyResult, setVerifyResult] = useState<ApiResult<AbdmPassthrough> | null>(null);

  const [firstName, setFirstName] = useState("");
  const [middleName, setMiddleName] = useState("");
  const [lastName, setLastName] = useState("");
  const [dayOfBirth, setDayOfBirth] = useState("");
  const [monthOfBirth, setMonthOfBirth] = useState("");
  const [yearOfBirth, setYearOfBirth] = useState("");
  const [gender, setGender] = useState("M");
  const [email, setEmail] = useState("");
  const [mobile, setMobile] = useState("");
  const [address, setAddress] = useState("");
  const [stateName, setStateName] = useState("");
  const [stateCode, setStateCode] = useState("");
  const [districtName, setDistrictName] = useState("");
  const [districtCode, setDistrictCode] = useState("");
  const [pinCode, setPinCode] = useState("");

  const [abhaAddress, setAbhaAddress] = useState("");
  const [password, setPassword] = useState("");

  const [suggestResult, setSuggestResult] = useState<ApiResult<AbdmPassthrough> | null>(null);
  const [existsResult, setExistsResult] = useState<ApiResult<AbdmPassthrough> | null>(null);
  const [enrolResult, setEnrolResult] = useState<ApiResult<AbdmPassthrough> | null>(null);

  const run = async (fn: () => Promise<void>): Promise<void> => {
    setBusy(true);
    try {
      await fn();
    } finally {
      setBusy(false);
    }
  };

  const verifySucceeded = verifyResult?.data?.ok === true;
  // Both methods go straight from verify to suggestion -- no verify/user
  // step for either. See file banner: an earlier version added one for the
  // mobile variant based on a Postman-saved step that turned out not to be
  // required in practice.
  const ownershipConfirmed = verifySucceeded;
  const suggestions = extractSuggestions(suggestResult?.data?.body ?? null);

  const requestOtp = method === "aadhaar" ? requestAbhaAddressCreationOtpAadhaar : requestAbhaAddressCreationOtpMobile;
  const verifyOtp = method === "aadhaar" ? verifyAbhaAddressCreationOtpAadhaar : verifyAbhaAddressCreationOtpMobile;
  const title = method === "aadhaar" ? "Create ABHA Address (Aadhaar OTP)" : "Create ABHA Address (Mobile OTP)";
  const otpChannel = method === "aadhaar" ? "real OTP via UIDAI" : "real SMS to the mobile linked to this ABHA Number";

  return (
    <section className="panel">
      <PageHeader icon={IdCard} title={title} />

      <p className="notice notice--warn">
        Requesting an OTP sends a <strong>{otpChannel}</strong> and counts toward ABDM&apos;s rate
        limits. Request it once. If something fails, stop and check the Console rather than
        pressing it again.
      </p>

      <p className="muted">
        This creates an ABHA Address for an ABHA Number you <strong>already have</strong> — not a
        new account. For a brand-new account, use Register instead.
      </p>

      <fieldset className="step" disabled={busy || txnId !== ""}>
        <legend>1 · ABHA Number</legend>
        <label className="row">
          <span>ABHA Number</span>
          <input
            type="text"
            value={abhaNumber}
            autoComplete="off"
            onChange={(event) => setAbhaNumber(event.target.value)}
            placeholder="91-1234-5678-9012"
          />
        </label>
        <Button
          variant="primary"
          icon={Send}
          disabled={busy || abhaNumber === ""}
          onClick={() =>
            void run(async () => {
              const result = await requestOtp({ abhaNumber });
              setOtpResult(result);
              const foundTxnId = stringField(result.data?.body, "txnId");
              if (foundTxnId !== "") setTxnId(foundTxnId);
            })
          }
        >
          Request OTP
        </Button>
        <RawBody label="request/otp" result={otpResult} />
      </fieldset>

      <fieldset className="step" disabled={busy || txnId === "" || ownershipConfirmed}>
        <legend>2 · OTP</legend>
        <label className="row">
          <span>OTP</span>
          <input
            type="password"
            value={otp}
            autoComplete="one-time-code"
            onChange={(event) => setOtp(event.target.value)}
          />
        </label>
        <Button
          variant="primary"
          icon={Check}
          disabled={busy || otp === "" || txnId === ""}
          onClick={() =>
            void run(async () => {
              const result = await verifyOtp({ txnId, otp });
              setVerifyResult(result);
              const foundTxnId = stringField(result.data?.body, "txnId");
              if (foundTxnId !== "") setTxnId(foundTxnId);

              // Auto-fill section 3 from verify's own accounts[] -- see
              // extractAccount()'s own docstring. Never re-ask for data
              // this flow already has.
              const account = extractAccount(result.data?.body);
              if (account !== null) {
                setFirstName(account.firstName);
                setMiddleName(account.middleName);
                setLastName(account.lastName);
                setDayOfBirth(account.dayOfBirth);
                setMonthOfBirth(account.monthOfBirth);
                setYearOfBirth(account.yearOfBirth);
                setGender(account.gender);
                setEmail(account.email);
                setMobile(account.mobile);
                setAddress(account.address);
                setStateName(account.stateName);
                setStateCode(account.stateCode);
                setDistrictName(account.districtName);
                setDistrictCode(account.districtCode);
                setPinCode(account.pinCode);
              }
            })
          }
        >
          Verify OTP
        </Button>
        <RawBody label="verify" result={verifyResult} />
      </fieldset>

      <fieldset className="step" disabled={busy || !ownershipConfirmed}>
        <legend>3 · Details → address suggestions</legend>
        <p className="muted">
          Auto-filled from the verified account — edit anything that's wrong or stale. Only what
          the suggestion API actually needs is shown here; everything else it doesn't use
          (email, mobile, address, gender, state/district, pincode) is still carried through to
          step 5 from the verified account, just not re-shown for this step.
        </p>
        <div className="grid">
          <Text label="First name" value={firstName} onChange={setFirstName} />
          <Text label="Last name" value={lastName} onChange={setLastName} />
          <Text label="Day of birth" value={dayOfBirth} onChange={setDayOfBirth} />
          <Text label="Month of birth" value={monthOfBirth} onChange={setMonthOfBirth} />
          <Text label="Year of birth" value={yearOfBirth} onChange={setYearOfBirth} />
        </div>
        <Button
          variant="primary"
          icon={Search}
          disabled={busy || !ownershipConfirmed}
          onClick={() =>
            void run(async () => {
              const result = await getAddressSuggestions({ txnId, firstName, lastName, dayOfBirth, monthOfBirth, yearOfBirth });
              setSuggestResult(result);
            })
          }
        >
          Get suggestions
        </Button>
        <RawBody label="suggestion" result={suggestResult} />
      </fieldset>

      <fieldset className="step" disabled={busy || !ownershipConfirmed}>
        <legend>4 · Choose an address, check it, set a password</legend>
        {suggestions.length > 0 && (
          <div className="suggestions">
            {suggestions.map((item) => (
              <button
                key={item}
                type="button"
                className={`chip ${abhaAddress === withSandboxSuffix(item) ? "chip--on" : ""}`}
                onClick={() => setAbhaAddress(withSandboxSuffix(item))}
              >
                {withSandboxSuffix(item)}
              </button>
            ))}
          </div>
        )}
        <label className="row">
          <span>ABHA address</span>
          <input
            type="text"
            value={abhaAddress}
            autoComplete="off"
            onChange={(event) => setAbhaAddress(event.target.value)}
            placeholder="johndoe@sbx"
          />
        </label>
        <Button
          size="sm"
          icon={Search}
          disabled={busy || abhaAddress === ""}
          onClick={() => void run(async () => setExistsResult(await checkAddressExists(withSandboxSuffix(abhaAddress))))}
        >
          Check if already taken
        </Button>
        {existsResult?.data?.taken === true && (
          <p className="result result--error">TAKEN — pick a different address.</p>
        )}
        {existsResult?.data?.taken === false && (
          <p className="result">
            <span className="ok">FREE</span> — available to register.
          </p>
        )}
        <RawBody label="isExists (true = taken)" result={existsResult} />

        <label className="row">
          <span>Password</span>
          <input
            type="password"
            value={password}
            autoComplete="new-password"
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
      </fieldset>

      <fieldset className="step" disabled={busy || !ownershipConfirmed}>
        <legend>5 · Create the address</legend>
        <p className="muted">
          Auto-filled from the verified account — edit anything that&apos;s wrong or stale.
          enrol() needs all of these, unlike step 3&apos;s suggestion call.
        </p>
        <div className="grid">
          <Text label="Middle name" value={middleName} onChange={setMiddleName} />
          <label className="row">
            <span>Gender</span>
            <select value={gender} onChange={(e) => setGender(e.target.value)}>
              <option value="M">M</option>
              <option value="F">F</option>
              <option value="O">O</option>
              <option value="U">U</option>
            </select>
          </label>
          <Text label="Email" value={email} onChange={setEmail} />
          <Text label="Mobile" value={mobile} onChange={setMobile} />
          <Text label="Address" value={address} onChange={setAddress} />
          <Text label="State name" value={stateName} onChange={setStateName} />
          <Text label="State code" value={stateCode} onChange={setStateCode} />
          <Text label="District name" value={districtName} onChange={setDistrictName} />
          <Text label="District code" value={districtCode} onChange={setDistrictCode} />
          <Text label="Pin code" value={pinCode} onChange={setPinCode} />
        </div>
        <Button
          variant="primary"
          icon={Check}
          disabled={busy || abhaAddress === "" || password === "" || mobile === ""}
          onClick={() =>
            void run(async () => {
              setEnrolResult(
                await enrol({
                  txnId, mobile, abhaAddress: withSandboxSuffix(abhaAddress), password,
                  firstName, middleName, lastName,
                  dayOfBirth, monthOfBirth, yearOfBirth,
                  gender, email, address,
                  stateName, stateCode, districtName, districtCode, pinCode,
                }),
              );
            })
          }
        >
          Create ABHA Address
        </Button>
        <RawBody label="enrol" result={enrolResult} />
      </fieldset>

      <p className="muted">Every request and response is in the Console below.</p>
    </section>
  );
}
