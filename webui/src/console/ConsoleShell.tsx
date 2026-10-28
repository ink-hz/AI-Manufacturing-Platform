import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import type { WorkbenchUser } from "../types";
import "./console.css";

export type ConsoleView =
  | "home"
  | "projects"
  | "tasks"
  | "handbook"
  | "legacy"
  | "collaboration";
const modules = [
  ["home", "工作台"],
  ["projects", "制造项目"],
  ["tasks", "事项"],
  ["collaboration", "系统协同"],
  ["handbook", "制造手册"],
] as const;
const paths = {
  home: "M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z",
  projects: "M3 7h7l2-3h9v16H3zM3 10h18",
  tasks: "m3 6 2 2 3-4M11 6h10M3 13l2 2 3-4M11 13h10M11 20h10",
  collaboration: "M3 3h6v6H3zM15 15h6v6h-6zM15 3h6v6h-6zM6 9v9h9M9 6h6",
  handbook:
    "M12 6v15M12 6C9 3 5 3 2 4v15c4-1 7-1 10 2 3-3 6-3 10-2V4c-3-1-7-1-10 2",
  menu: "M4 6h16M4 12h16M4 18h16",
  back: "m10 5-7 7 7 7M3 12h18",
  close: "m6 6 12 12M6 18 18 6",
  collapse: "M9 3v18M3 3h18v18H3zM17 8l-4 4 4 4",
};
function Icon({ name }: { name: keyof typeof paths }) {
  return (
    <svg
      className="mf-console-icon"
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d={paths[name]} />
    </svg>
  );
}
export function ConsoleShell({
  view,
  projectName,
  creating,
  user,
  taskCount,
  readOnly,
  busy,
  onNavigate,
  onCreate,
  onNavigatePlatform,
  onLogout,
  children,
  navigation,
  modeAction,
  canCreate = true,
}: {
  navigation?: readonly (readonly [Exclude<ConsoleView, "legacy">, string])[];
  modeAction?: { label: string; run(): void };
  canCreate?: boolean;
  view: ConsoleView;
  projectName?: string;
  creating: boolean;
  user?: WorkbenchUser;
  taskCount?: number;
  readOnly: boolean;
  busy: boolean;
  onNavigate: (view: ConsoleView) => void;
  onCreate: () => void;
  onNavigatePlatform?: () => void;
  onLogout?: () => void;
  children: ReactNode;
}) {
  const [collapsed, setCollapsed] = useState(false),
    [drawer, setDrawer] = useState(false),
    [menu, setMenu] = useState(false);
  const sidebar = useRef<HTMLElement>(null),
    drawerToggle = useRef<HTMLButtonElement>(null),
    account = useRef<HTMLDivElement>(null),
    trigger = useRef<HTMLButtonElement>(null),
    menuBox = useRef<HTMLDivElement>(null);
  const id = useId();
  const displayName = user?.displayName.trim() || "企业账号";
  const actualModules = navigation || modules;
  const title =
    actualModules.find(([key]) => key === view)?.[1] || "流程现状参考";
  function closeMenu(restore = true) {
    setMenu(false);
    if (restore) trigger.current?.focus();
  }
  useEffect(() => {
    if (!menu) return;
    menuBox.current
      ?.querySelector<HTMLElement>('[role="menuitem"]:not(:disabled)')
      ?.focus();
    const outside = (event: PointerEvent) => {
      if (!account.current?.contains(event.target as Node)) setMenu(false);
    };
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeMenu();
      }
      if (event.key === "Tab") {
        closeMenu();
        return;
      }
      if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const items = [
        ...(menuBox.current?.querySelectorAll<HTMLButtonElement>(
          "button:not(:disabled)",
        ) || []),
      ];
      const index = items.indexOf(document.activeElement as HTMLButtonElement);
      const next =
        event.key === "Home"
          ? 0
          : event.key === "End"
            ? items.length - 1
            : (index + (event.key === "ArrowUp" ? -1 : 1) + items.length) %
              items.length;
      items[next]?.focus();
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", key);
    };
  }, [menu]);
  useEffect(() => {
    if (!drawer) return;
    sidebar.current?.querySelector<HTMLElement>("button")?.focus();
    function key(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        setDrawer(false);
      }
      if (event.key !== "Tab") return;
      const items = [
        ...(sidebar.current?.querySelectorAll<HTMLButtonElement>(
          "button:not(:disabled)",
        ) || []),
      ];
      const index = items.indexOf(document.activeElement as HTMLButtonElement);
      if (event.shiftKey && index <= 0) {
        event.preventDefault();
        items.at(-1)?.focus();
      } else if (!event.shiftKey && (index === items.length - 1 || index < 0)) {
        event.preventDefault();
        items[0]?.focus();
      }
    }
    document.addEventListener("keydown", key);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", key);
      document.body.style.overflow = previousOverflow;
      drawerToggle.current?.focus();
    };
  }, [drawer]);
  return (
    <div
      className={`mf-console${collapsed ? " mf-console-collapsed" : ""}${drawer ? " mf-console-drawer" : ""}`}
    >
      <a className="mf-console-skip" href={`#${id}-content`}>
        跳至工作内容
      </a>
      {drawer && (
        <div
          className="mf-console-overlay"
          onClick={() => setDrawer(false)}
          aria-hidden="true"
        />
      )}
      <aside
        className="mf-console-sidebar"
        id={`${id}-navigation`}
        ref={sidebar}
        role={drawer ? "dialog" : undefined}
        aria-modal={drawer || undefined}
        aria-label={drawer ? "制造导航" : "制造平台导航"}
      >
        <div className="mf-console-brand">
          <span className="mf-console-mark" aria-hidden="true">
            O
          </span>
          <span className="mf-console-label">
            <strong>奥比大制造</strong>
            <small>制造协同管理平台</small>
          </span>
          <button
            className="mf-console-drawer-close"
            aria-label="关闭导航"
            onClick={() => setDrawer(false)}
          >
            <Icon name="close" />
          </button>
        </div>
        <nav aria-label="制造工作区">
          <p className="mf-console-group mf-console-label">业务工作区</p>
          {actualModules.map(([key, label]) => (
            <button
              key={key}
              aria-label={label}
              title={collapsed ? label : undefined}
              aria-current={view === key ? "page" : undefined}
              onClick={() => {
                setDrawer(false);
                onNavigate(key);
              }}
            >
              <Icon name={key} />
              <span className="mf-console-label">{label}</span>
              {key === "tasks" && !!taskCount && (
                <span
                  className="mf-console-count"
                  aria-label={`${taskCount} 项未完成`}
                >
                  {taskCount}
                </span>
              )}
            </button>
          ))}
        </nav>
        <div className="mf-console-sidebar-bottom">
          {onNavigatePlatform && (
            <button
              disabled={busy}
              onClick={() => {
                setDrawer(false);
                onNavigatePlatform();
              }}
              aria-label="返回 Agent 平台"
              title={collapsed ? "返回 Agent 平台" : undefined}
            >
              <Icon name="back" />
              <span className="mf-console-label">返回 Agent 平台</span>
            </button>
          )}
          {!drawer && (
            <button
              className="mf-console-collapse"
              aria-label={collapsed ? "展开侧栏" : "收起侧栏"}
              aria-expanded={!collapsed}
              onClick={() => setCollapsed((value) => !value)}
            >
              <Icon name="collapse" />
              <span className="mf-console-label">收起侧栏</span>
            </button>
          )}
        </div>
      </aside>
      <div className="mf-console-workspace" inert={drawer || undefined}>
        <header className="mf-console-topbar">
          <button
            className="mf-console-drawer-toggle"
            ref={drawerToggle}
            aria-label="打开导航"
            aria-controls={`${id}-navigation`}
            aria-expanded={drawer}
            onClick={() => {
              setMenu(false);
              setDrawer(true);
            }}
          >
            <Icon name="menu" />
          </button>
          <div className="mf-console-breadcrumb" aria-label="当前位置">
            <span>制造管理</span>
            <span aria-hidden="true">/</span>
            <strong>{title}</strong>
            {view === "projects" && (creating || projectName) && (
              <>
                <span aria-hidden="true">/</span>
                <span>{creating ? "新建项目" : projectName}</span>
              </>
            )}
          </div>
          <div className="mf-console-account" ref={account}>
            {onNavigatePlatform || onLogout ? (
              <button
                ref={trigger}
                className="mf-console-user"
                aria-label="账户菜单"
                aria-haspopup="menu"
                aria-expanded={menu}
                aria-controls={`${id}-account`}
                onClick={() => setMenu((value) => !value)}
                onKeyDown={(event) => {
                  if (["ArrowDown", "ArrowUp"].includes(event.key)) {
                    event.preventDefault();
                    setMenu(true);
                  }
                }}
              >
                <span className="mf-console-avatar" aria-hidden="true">
                  {Array.from(displayName)[0]}
                </span>
                <span className="mf-console-user-label">
                  <strong>{displayName}</strong>
                  {user?.roleLabel && <small>{user.roleLabel}</small>}
                </span>
                <span aria-hidden="true">⌄</span>
              </button>
            ) : (
              <div className="mf-console-user">
                <span className="mf-console-avatar" aria-hidden="true">
                  {Array.from(displayName)[0]}
                </span>
                <span className="mf-console-user-label">
                  <strong>{displayName}</strong>
                  {user?.roleLabel && <small>{user.roleLabel}</small>}
                </span>
              </div>
            )}
            {menu && (
              <div
                ref={menuBox}
                className="mf-console-menu"
                id={`${id}-account`}
                role="menu"
                aria-label="账户操作"
              >
                {onNavigatePlatform && (
                  <button
                    role="menuitem"
                    disabled={busy}
                    onClick={() => {
                      closeMenu();
                      onNavigatePlatform();
                    }}
                  >
                    返回 Agent 平台
                  </button>
                )}
                {onLogout && (
                  <button
                    role="menuitem"
                    disabled={busy}
                    onClick={() => {
                      closeMenu();
                      onLogout();
                    }}
                  >
                    退出登录
                  </button>
                )}
              </div>
            )}
          </div>
        </header>
        <main className="mf-console-content" id={`${id}-content`} tabIndex={-1}>
          <div className="mf-console-page-heading">
            <div>
              <p>
                {view === "home" ? "交付协同 · 日常工作" : "制造业务工作区"}
              </p>
              <h1>{title}</h1>
            </div>
            <div className="mf-actions">
              {modeAction && (
                <button disabled={busy} onClick={modeAction.run}>
                  {modeAction.label}
                </button>
              )}
              {canCreate && (
                <button
                  className="mf-primary"
                  disabled={readOnly || busy}
                  onClick={onCreate}
                >
                  新建项目
                </button>
              )}
            </div>
          </div>
          {children}
        </main>
      </div>
    </div>
  );
}
