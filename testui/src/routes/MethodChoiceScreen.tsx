/**
 * Sub-picker for an identifier category that maps to more than one login
 * method. Added in P1-E because the original four top-level /login options
 * (Mobile, ABHA Number, Aadhaar, Password) were mapped before this project
 * had visibility into how many distinct methods the spec actually has per
 * identifier -- ABHA Number alone turned out to be two (Aadhaar OTP,
 * Mobile OTP). Pure navigation, same as LoginScreen itself: nothing here
 * calls the backend.
 */

import type { LucideIcon } from "lucide-react";
import { ListChecks } from "lucide-react";

import { ButtonLink } from "../components/ui/Button";
import { PageHeader } from "../components/ui/PageHeader";

export interface MethodChoiceOption {
  label: string;
  to: string;
  icon?: LucideIcon;
}

export interface MethodChoiceScreenProps {
  title: string;
  prompt: string;
  options: MethodChoiceOption[];
}

export function MethodChoiceScreen({ title, prompt, options }: MethodChoiceScreenProps): JSX.Element {
  return (
    <section className="panel">
      <PageHeader icon={ListChecks} title={title} description={prompt} />

      <div className="method-list">
        {options.map((option) => (
          <ButtonLink key={option.to} variant="secondary" className="method-btn" icon={option.icon} to={option.to}>
            {option.label}
          </ButtonLink>
        ))}
      </div>
    </section>
  );
}
