import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export function BookSelect({ id, value, options, onChange, disabled }: {
  id: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  return <Select value={value} items={options} onValueChange={(next) => { if (next !== null) onChange(next); }} disabled={disabled}>
    <SelectTrigger id={id}><SelectValue /></SelectTrigger>
    <SelectContent>{options.map((option) => <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>)}</SelectContent>
  </Select>;
}
