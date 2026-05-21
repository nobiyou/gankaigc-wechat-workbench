import { NavLink, Outlet, useLocation } from "react-router-dom";

import { PRIMARY_NAV_ITEMS } from "./navigation";
import { buildAppShellViewModel } from "../view-models/appShell";

export function AppShell() {
  const location = useLocation();
  const shellViewModel = buildAppShellViewModel(location.pathname);

  return (
    <div className="app-shell">
      <aside className="app-shell__sidebar">
        <div className="app-shell__brand">
          <p className="app-shell__eyebrow">Content Workbench</p>
          <h1>Gank AI GC</h1>
          <p className="app-shell__copy">
            面向公众号内容生产的工作台，按 Dashboard、来源、流水线、项目、设置拆分日常操作。
          </p>
        </div>
        <nav aria-label="Primary" className="primary-nav">
          {PRIMARY_NAV_ITEMS.map((item) => (
            <NavLink
              key={item.key}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) => (isActive ? "primary-nav__item primary-nav__item--active" : "primary-nav__item")}
            >
              <span className="primary-nav__label">{item.label}</span>
              <span className="primary-nav__description">{item.description}</span>
            </NavLink>
          ))}
        </nav>
      </aside>

      <main className="app-shell__main">
        <header className="app-shell__header">
          <div className="app-shell__header-meta">
            <p className="app-shell__eyebrow">当前工作区</p>
            <h2>{shellViewModel.activePrimary.label}</h2>
          </div>
          <p className="app-shell__header-copy">{shellViewModel.activePrimary.description}</p>
        </header>

        {shellViewModel.sectionNavItems.length > 0 ? (
          <nav aria-label="Section" className="section-nav">
            {shellViewModel.sectionNavItems.map((item) => (
              <NavLink
                key={item.key}
                to={item.to}
                className={({ isActive }) => (isActive ? "section-nav__item section-nav__item--active" : "section-nav__item")}
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        ) : null}

        <Outlet />
      </main>
    </div>
  );
}
