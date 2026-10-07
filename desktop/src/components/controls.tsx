import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { Eye, EyeOff, FileSearch, FolderOpen, X } from "lucide-react";

import { openPath, pickDirectory, pickFile } from "../lib/api";
import type { Option } from "../lib/schema";

export function Switch({
  checked,
  onChange,
  disabled,
  label,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  disabled?: boolean;
  label?: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      className={`switch ${checked ? "on" : ""}`}
      disabled={disabled}
      onClick={() => onChange(!checked)}
    />
  );
}

/** Number input that commits on blur/Enter so partial typing never saves. */
export function NumberInput({
  value,
  onChange,
  min,
  max,
  step = 1,
  unit,
  placeholder,
  width = 110,
}: {
  value: number | null | undefined;
  onChange: (value: number | undefined) => void;
  min?: number;
  max?: number;
  step?: number;
  unit?: string;
  placeholder?: string;
  width?: number;
}) {
  const [text, setText] = useState(value == null ? "" : String(value));
  useEffect(() => setText(value == null ? "" : String(value)), [value]);

  const commit = () => {
    if (text.trim() === "") {
      onChange(undefined);
      return;
    }
    let next = Number(text);
    if (!Number.isFinite(next)) {
      setText(value == null ? "" : String(value));
      return;
    }
    if (min != null) next = Math.max(min, next);
    if (max != null) next = Math.min(max, next);
    if (step >= 1) next = Math.round(next);
    setText(String(next));
    if (next !== value) onChange(next);
  };

  return (
    <div className="input-group">
      <input
        className="tabular"
        style={{ width }}
        inputMode="numeric"
        value={text}
        placeholder={placeholder}
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
      />
      {unit && <span className="addon">{unit}</span>}
    </div>
  );
}

export function TextInput({
  value,
  onChange,
  placeholder,
  width = 240,
  password,
  mono,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  width?: number;
  password?: boolean;
  mono?: boolean;
}) {
  const [text, setText] = useState(value);
  const [reveal, setReveal] = useState(false);
  useEffect(() => setText(value), [value]);
  const commit = () => text !== value && onChange(text);

  if (password) {
    return (
      <div className="input-group">
        <input
          style={{ width: width - 34 }}
          className={mono ? "mono" : undefined}
          type={reveal ? "text" : "password"}
          value={text}
          placeholder={placeholder}
          onChange={(e) => setText(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
        />
        <button type="button" className="addon-btn" onClick={() => setReveal((r) => !r)} title={reveal ? "隐藏" : "显示"}>
          {reveal ? <EyeOff size={15} /> : <Eye size={15} />}
        </button>
      </div>
    );
  }
  return (
    <input
      className={`input ${mono ? "mono" : ""}`}
      style={{ width }}
      value={text}
      placeholder={placeholder}
      onChange={(e) => setText(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
    />
  );
}

export function Select({
  value,
  options,
  onChange,
  width = 200,
}: {
  value: string | number | undefined;
  options: Option[];
  onChange: (value: string) => void;
  width?: number;
}) {
  const known = options.some((o) => String(o.value) === String(value));
  return (
    <select className="select" style={{ width }} value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
      {!known && value != null && value !== "" && <option value={String(value)}>{String(value)}</option>}
      {options.map((o) => (
        <option key={String(o.value)} value={String(o.value)}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

export function Segmented<T extends string | number>({
  value,
  options,
  onChange,
}: {
  value: T | undefined;
  options: { label: ReactNode; value: T }[];
  onChange: (value: T) => void;
}) {
  return (
    <div className="segmented" role="radiogroup">
      {options.map((o) => (
        <button
          key={String(o.value)}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          className={o.value === value ? "active" : ""}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function TagInput({
  value,
  onChange,
  placeholder,
  width = 320,
  transform = (s) => s,
  split = /[,，、\s]+/,
}: {
  value: (string | number)[];
  onChange: (value: (string | number)[]) => void;
  placeholder?: string;
  width?: number;
  transform?: (text: string) => string | number;
  /** Separator pattern; null keeps the whole input as one entry. */
  split?: RegExp | null;
}) {
  const [text, setText] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const add = () => {
    const parts = (split ? text.split(split) : [text])
      .map((s) => s.trim())
      .filter(Boolean)
      .map(transform);
    if (parts.length) {
      const next = [...value];
      parts.forEach((p) => !next.some((v) => String(v) === String(p)) && next.push(p));
      onChange(next);
    }
    setText("");
  };
  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || (split && e.key === ",")) {
      e.preventDefault();
      add();
    } else if (e.key === "Backspace" && !text && value.length) {
      onChange(value.slice(0, -1));
    }
  };
  return (
    <div className="tags" style={{ width }} onClick={() => inputRef.current?.focus()}>
      {value.map((item) => (
        <span className="tag" key={String(item)}>
          {String(item)}
          <button type="button" onClick={() => onChange(value.filter((v) => v !== item))} aria-label="删除">
            <X size={12} />
          </button>
        </span>
      ))}
      <input
        ref={inputRef}
        value={text}
        placeholder={value.length ? "" : placeholder}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        onBlur={add}
      />
    </div>
  );
}

/** Pick and order a subset of options (e.g. directory structure parts). */
export function OrderedPicker({
  value,
  options,
  onChange,
}: {
  value: string[];
  options: Option[];
  onChange: (value: string[]) => void;
}) {
  return (
    <div className="chips">
      {options.map((o) => {
        const index = value.indexOf(String(o.value));
        const on = index >= 0;
        return (
          <button
            key={String(o.value)}
            type="button"
            className={`chip ${on ? "on" : ""}`}
            onClick={() => onChange(on ? value.filter((v) => v !== o.value) : [...value, String(o.value)])}
          >
            {on && <span className="chip-index">{index + 1}</span>}
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

export function PathInput({
  value,
  onChange,
  placeholder,
  file,
  extensions,
  width = 360,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  file?: boolean;
  extensions?: string[];
  width?: number;
}) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  const browse = async () => {
    const picked = file ? await pickFile(value, extensions) : await pickDirectory(value);
    if (picked) onChange(picked);
  };
  return (
    <div className="input-group" style={{ width }}>
      <input
        style={{ flex: 1, width: "auto" }}
        value={text}
        placeholder={placeholder}
        onChange={(e) => setText(e.target.value)}
        onBlur={() => text !== value && onChange(text)}
        onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
        title={text}
      />
      {!file && value && (
        <button type="button" className="addon-btn" title="打开" onClick={() => openPath(value)}>
          <FolderOpen size={15} />
        </button>
      )}
      <button type="button" className="addon-btn" title="浏览…" onClick={browse}>
        <FileSearch size={15} />
      </button>
    </div>
  );
}
