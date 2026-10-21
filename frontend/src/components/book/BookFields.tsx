import { useId } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

export function BookField({ label, value, onChange, type = "text", disabled, min, max, step, multiline = false }: {
  label: string; value: string | number; onChange: (value: string) => void;
  type?: "text" | "number"; disabled?: boolean; min?: number; max?: number; step?: number; multiline?: boolean;
}) {
  const id = useId();
  return <div className="grid min-w-0 gap-1.5">
    <Label htmlFor={id}>{label}</Label>
    {multiline ? <Textarea id={id} value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)} />
      : <Input id={id} type={type} value={value} disabled={disabled} min={min} max={max} step={step} onChange={(event) => onChange(event.target.value)} />}
  </div>;
}
