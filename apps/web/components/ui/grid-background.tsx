import type { HTMLAttributes } from "react";

type GridBackgroundProps = HTMLAttributes<HTMLDivElement> & {
  dense?: boolean;
  extended?: boolean;
};

/** A quiet, token-driven take on Aceternity UI's Grid Background. */
export function GridBackground({
  className = "",
  dense = false,
  extended = false,
  ...props
}: GridBackgroundProps) {
  const gridSize = dense ? "[background-size:24px_24px]" : "[background-size:32px_32px]";
  const mask = extended
    ? "[mask-image:linear-gradient(to_bottom_right,black_0%,black_52%,transparent_94%)]"
    : "[mask-image:linear-gradient(to_bottom_right,black,transparent_74%)]";

  return (
    <div
      aria-hidden="true"
      className={`pointer-events-none absolute inset-0 opacity-55 [background-image:linear-gradient(to_right,color-mix(in_srgb,var(--color-line)_58%,transparent)_1px,transparent_1px),linear-gradient(to_bottom,color-mix(in_srgb,var(--color-line)_58%,transparent)_1px,transparent_1px)] ${gridSize} ${mask} ${className}`}
      {...props}
    />
  );
}
