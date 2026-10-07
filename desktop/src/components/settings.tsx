import { useEffect, useRef, useState, type ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

import { autostart } from "../lib/api";
import { SECTIONS, type SettingDef } from "../lib/schema";
import { coerceId, getIn, useApp } from "../lib/store";
import { NumberInput, OrderedPicker, PathInput, Segmented, Select, Switch, TagInput, TextInput } from "./controls";

export function Card({
  icon: Icon,
  title,
  desc,
  count,
  extra,
  children,
  id,
}: {
  icon?: LucideIcon;
  title: ReactNode;
  desc?: ReactNode;
  count?: number;
  extra?: ReactNode;
  children?: ReactNode;
  id?: string;
}) {
  return (
    <section className="card" id={id}>
      <div className="card-head">
        {Icon && <Icon size={22} strokeWidth={1.8} />}
        <div className="flex-1">
          <div className="card-title">{title}</div>
          {desc && <div className="card-desc">{desc}</div>}
        </div>
        <div className="card-head-extra">
          {extra}
          {count != null && <span className="pill">{count} 项</span>}
        </div>
      </div>
      {children}
    </section>
  );
}

export function Row({
  icon: Icon,
  title,
  desc,
  children,
  id,
  wide,
  highlight,
}: {
  icon?: LucideIcon;
  title: ReactNode;
  desc?: ReactNode;
  children?: ReactNode;
  id?: string;
  wide?: boolean;
  highlight?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (highlight) ref.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [highlight]);
  return (
    <div className={`row ${highlight ? "highlight" : ""}`} id={id} ref={ref}>
      {Icon && <Icon className="row-icon" size={22} strokeWidth={1.5} />}
      <div className="row-text">
        <div className="row-title">{title}</div>
        {desc && <div className="row-desc">{desc}</div>}
      </div>
      {children != null && <div className={`row-control ${wide ? "wide" : ""}`}>{children}</div>}
    </div>
  );
}

function AutostartSwitch() {
  const { toast } = useApp();
  const [enabled, setEnabled] = useState(false);
  useEffect(() => {
    autostart()
      .then((a) => a.isEnabled())
      .then(setEnabled)
      .catch(() => undefined);
  }, []);
  return (
    <Switch
      checked={enabled}
      onChange={async (next) => {
        try {
          const plugin = await autostart();
          await (next ? plugin.enable() : plugin.disable());
          setEnabled(next);
        } catch (error) {
          toast(String(error), "error");
        }
      }}
    />
  );
}

const ID_FIELDS = new Set(["allowed_user_ids"]);

/** Render the control for one schema setting against config draft or desktop settings. */
export function SettingControl({ def }: { def: SettingDef }) {
  const { draft, settings, updateDraft, updateSettings } = useApp();
  if (def.path[0] === "__autostart") return <AutostartSwitch />;

  const source = def.desktop ? settings : draft;
  const raw = getIn(source, def.path);
  const value = raw === undefined ? def.defaultValue : raw;
  const set = (next: unknown) => {
    if (def.desktop) updateSettings({ [def.path[0]]: next } as never);
    else updateDraft(def.path, next);
  };

  switch (def.type) {
    case "switch":
      return <Switch checked={Boolean(value)} onChange={set} label={def.title} />;
    case "optional-switch":
      return <Switch checked={raw != null} onChange={(on) => set(on ? def.enableValue : undefined)} label={def.title} />;
    case "member": {
      const list: string[] = Array.isArray(raw) ? raw : [];
      const on = list.includes(def.member!);
      return (
        <Switch
          checked={on}
          label={def.title}
          onChange={(next) => set(next ? [...list, def.member] : list.filter((m) => m !== def.member))}
        />
      );
    }
    case "number":
      return (
        <NumberInput
          value={typeof value === "number" ? value : value == null || value === "" ? undefined : Number(value)}
          onChange={set}
          min={def.min}
          max={def.max}
          step={def.step}
          unit={def.unit}
          placeholder={def.placeholder}
        />
      );
    case "text":
      return (
        <TextInput
          value={value == null ? "" : String(value)}
          width={def.width}
          placeholder={def.placeholder}
          onChange={(text) => set(def.id === "api_id" ? coerceId(text) : text)}
        />
      );
    case "password":
      return (
        <TextInput
          password
          mono
          value={value == null ? "" : String(value)}
          width={def.width}
          placeholder={def.placeholder}
          onChange={set}
        />
      );
    case "select":
      return <Select value={value as string} options={def.options!} onChange={set} width={def.width ?? 220} />;
    case "segmented":
      return <Segmented value={value as string} options={def.options as { label: string; value: string }[]} onChange={set} />;
    case "tags":
      return (
        <TagInput
          value={Array.isArray(value) ? value : []}
          placeholder={def.placeholder}
          onChange={set}
          transform={ID_FIELDS.has(def.id) ? coerceId : (s) => s.replace(/^\./, "").toLowerCase()}
        />
      );
    case "time":
      return (
        <input
          type="time"
          className="input tabular"
          style={{ width: 130 }}
          value={value == null ? "" : String(value)}
          onChange={(e) => e.target.value && set(e.target.value)}
        />
      );
    case "ordered":
      return <OrderedPicker value={Array.isArray(value) ? value : []} options={def.options!} onChange={set} />;
    case "path":
      return <PathInput value={value == null ? "" : String(value)} placeholder={def.placeholder} onChange={set} />;
    case "file":
      return (
        <PathInput
          file
          value={value == null ? "" : String(value)}
          placeholder={def.placeholder}
          onChange={set}
          extensions={def.id === "enginePath" ? ["exe", "py"] : ["exe"]}
        />
      );
    default:
      return null;
  }
}

/** One card per section for the given settings, EcoPaste style. */
export function SettingSections({ defs, after }: { defs: SettingDef[]; after?: Record<string, ReactNode> }) {
  const { draft, nav } = useApp();
  const visible = defs.filter((d) => !d.showIf || getIn(draft, d.showIf) != null);
  const sections = [...new Set(visible.map((d) => d.section))];
  return (
    <>
      {sections.map((sectionId) => {
        const section = SECTIONS[sectionId];
        const items = visible.filter((d) => d.section === sectionId);
        return (
          <Card key={sectionId} icon={section.icon} title={section.title} count={items.length}>
            {items.map((def) => (
              <Row
                key={def.id}
                icon={def.icon}
                title={def.title}
                desc={def.desc}
                id={`setting-${def.id}`}
                highlight={nav.highlight === def.id}
                wide={def.type === "ordered" || def.type === "tags"}
              >
                <SettingControl def={def} />
              </Row>
            ))}
            {after?.[sectionId]}
          </Card>
        );
      })}
    </>
  );
}
