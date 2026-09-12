/**
 * Filled-pill two/three-way switcher for page-level tab state -- e.g.
 * ConsentScreen.tsx's Requests/Approved (P14, design_reference/
 * 03_consents.png). Generic over the option type so any string union works.
 */

export interface SegmentedOption<T extends string> {
  value: T;
  label: string;
}

export interface SegmentedControlProps<T extends string> {
  options: SegmentedOption<T>[];
  value: T;
  onChange: (value: T) => void;
}

export function SegmentedControl<T extends string>({ options, value, onChange }: SegmentedControlProps<T>): JSX.Element {
  return (
    <div className="ui-segmented" role="tablist">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="tab"
          aria-selected={option.value === value}
          className={`ui-segmented__option${option.value === value ? " ui-segmented__option--active" : ""}`}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
