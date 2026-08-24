"use client";

import * as React from "react";

import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

interface ComboboxProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "list"> {
  options: readonly string[];
  /** Unique id for the underlying <datalist>. Auto-generated if omitted. */
  listId?: string;
}

/**
 * A typeable + selectable dropdown.
 *
 * Built on the native <input list="..."> + <datalist> pair rather than a
 * custom Radix/cmdk combobox, so it needs no extra dependency: the user
 * can click the field to see a native dropdown of `options`, OR type
 * freely to filter it live (built into every modern browser), OR type a
 * value that isn't in the list at all — all three are genuine browser
 * behavior, not simulated.
 */
export const Combobox = React.forwardRef<HTMLInputElement, ComboboxProps>(
  ({ options, listId, className, ...props }, ref) => {
    const generatedId = React.useId();
    const id = listId ?? generatedId;

    return (
      <>
        <Input ref={ref} list={id} autoComplete="off" className={cn(className)} {...props} />
        <datalist id={id}>
          {options.map((option) => (
            <option key={option} value={option} />
          ))}
        </datalist>
      </>
    );
  }
);
Combobox.displayName = "Combobox";