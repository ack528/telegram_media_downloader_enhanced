import { useEffect, useState } from "react";

import { LoginDialog, WelcomeWizard } from "./components/dialogs";
import { SaveBar, Sidebar, Toasts } from "./components/layout";
import About from "./pages/About";
import Chats from "./pages/Chats";
import Dashboard from "./pages/Dashboard";
import Logs from "./pages/Logs";
import Network from "./pages/Network";
import SchemaPage from "./pages/SchemaPage";
import Settings from "./pages/Settings";
import Tasks from "./pages/Tasks";
import { AppProvider, useApp } from "./lib/store";

function needsSetup(config: Record<string, unknown> | undefined, exists: boolean | undefined) {
  if (exists === false) return true;
  const id = String(config?.api_id ?? "");
  const hash = String(config?.api_hash ?? "");
  return !id || !hash || id.startsWith("your_") || hash.startsWith("your_");
}

function Shell() {
  const { nav, doc } = useApp();
  const [welcome, setWelcome] = useState(false);
  const [welcomeShown, setWelcomeShown] = useState(false);

  useEffect(() => {
    if (doc && !welcomeShown && needsSetup(doc.config, doc.exists)) {
      setWelcome(true);
      setWelcomeShown(true);
    }
  }, [doc, welcomeShown]);

  // Each page/tab starts at the top unless a search result asked for a row.
  useEffect(() => {
    if (!nav.highlight) document.querySelector(".content")?.scrollTo({ top: 0 });
  }, [nav.page, nav.tabs, nav.highlight]);

  let page;
  switch (nav.page) {
    case "dashboard":
      page = <Dashboard />;
      break;
    case "tasks":
      page = <Tasks />;
      break;
    case "download":
      page = <SchemaPage key="download" page="download" />;
      break;
    case "upload":
      page = <SchemaPage key="upload" page="upload" />;
      break;
    case "chats":
      page = <Chats />;
      break;
    case "network":
      page = <Network />;
      break;
    case "logs":
      page = <Logs />;
      break;
    case "settings":
      page = <Settings />;
      break;
    case "about":
      page = <About />;
      break;
  }

  return (
    <div className="app">
      <Sidebar />
      <div className="main">{page}</div>
      <SaveBar />
      <Toasts />
      <LoginDialog />
      {welcome && <WelcomeWizard onClose={() => setWelcome(false)} />}
    </div>
  );
}

export default function App() {
  return (
    <AppProvider>
      <Shell />
    </AppProvider>
  );
}
