/**
 * Honest placeholder for a login method whose backend does not exist yet.
 *
 * This is a REAL route, not a fake one — it just tells the truth about what
 * is behind it. No spinner that goes nowhere, no success state that lies.
 * Password login (the next chunk) replaces one of these; Aadhaar and ABHA
 * Number stay exactly this until their own chunks land.
 */

import { ArrowLeft, Info } from "lucide-react";

import { ButtonLink } from "../components/ui/Button";
import { PageHeader } from "../components/ui/PageHeader";

interface Props {
  method: string;
}

export function NotBuiltYetScreen({ method }: Props): JSX.Element {
  return (
    <section className="panel">
      <PageHeader icon={Info} title={`${method} login`} />

      <p className="result result--error">Not built yet.</p>
      <p className="muted">
        The {method} login flow has no backend behind it in this build. This route is
        real; the flow is not — nothing here will call the backend or produce a session.
      </p>

      <ButtonLink size="sm" icon={ArrowLeft} to="/login">Back to login</ButtonLink>
    </section>
  );
}
