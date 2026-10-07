import { PageHeader } from "../components/layout";
import { SettingSections } from "../components/settings";
import { pageDef, settingsFor, type PageId } from "../lib/schema";
import { useCurrentTab } from "../lib/store";

/** A settings page rendered entirely from the schema (下载 / 上传). */
export default function SchemaPage({ page }: { page: PageId }) {
  const def = pageDef(page);
  const tab = useCurrentTab(page, def.tabs[0].id);
  const defs = settingsFor(page, tab);
  return (
    <>
      <PageHeader page={page} tab={tab} count={defs.length} />
      <main className="content">
        <div className="content-inner">
          <SettingSections defs={defs} />
        </div>
      </main>
    </>
  );
}
