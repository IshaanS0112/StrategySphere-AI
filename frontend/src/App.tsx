import { Link, NavLink, Route, Routes } from "react-router-dom";

import CompanyDetail from "./pages/CompanyDetail";
import Dashboard from "./pages/Dashboard";
import NewCompany from "./pages/NewCompany";
import PortfolioView from "./pages/PortfolioView";
import TimelineView from "./pages/TimelineView";

/**
 * The shell: a sticky, blurred header over a page that scrolls under it.
 *
 * Navigation carries a text label per item rather than icons alone, and the
 * active route is marked by weight and a rule as well as by colour — nothing
 * in this interface is encoded by colour by itself.
 */

const NAV = [
  { to: "/", label: "Companies", end: true },
  { to: "/portfolios", label: "Portfolio" },
  { to: "/new", label: "New company" },
];

function Mark() {
  return (
    <span className="flex items-center gap-2.5">
      {/* The GE-McKinsey grid itself, at 20px: two thresholds, one plotted
          point. The product's whole idea in a mark. */}
      <svg width="22" height="22" viewBox="0 0 22 22" aria-hidden="true" className="shrink-0">
        <rect x="1" y="1" width="20" height="20" rx="4" className="fill-panel-2 stroke-edge-strong" />
        <path d="M8 2v18M15 2v18M2 8h18M2 15h18" className="stroke-edge-strong" strokeWidth="0.75" />
        <circle cx="16.5" cy="5.5" r="2.4" className="fill-accent" />
      </svg>
      <span className="text-base font-semibold tracking-tight text-slate-50">
        Strategy<span className="text-accent">Sphere</span>
      </span>
    </span>
  );
}

export default function App() {
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-40 border-b border-edge/80 bg-ink/80 backdrop-blur-xl">
        <div className="mx-auto flex h-14 max-w-7xl items-center justify-between gap-6 px-5">
          <Link to="/" className="group rounded-md" aria-label="StrategySphere home">
            <Mark />
          </Link>

          <nav className="flex items-center gap-1" aria-label="Main">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  [
                    "relative rounded-lg px-3 py-1.5 text-xs font-medium transition-colors duration-200",
                    isActive
                      ? "text-slate-50 after:absolute after:inset-x-3 after:-bottom-[13px] after:h-px after:bg-accent"
                      : "text-slate-400 hover:bg-panel-2 hover:text-slate-100",
                  ].join(" ")
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-5 py-8">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/new" element={<NewCompany />} />
          <Route path="/companies/:companyId" element={<CompanyDetail />} />
          <Route path="/entities/:entityKey" element={<TimelineView />} />
          <Route path="/portfolios" element={<PortfolioView />} />
          <Route path="/portfolios/:portfolioId" element={<PortfolioView />} />
          <Route
            path="*"
            element={
              <div className="panel p-8 text-center">
                <p className="text-sm text-slate-400">Nothing here.</p>
                <Link to="/" className="btn-ghost mt-4">
                  Back to companies
                </Link>
              </div>
            }
          />
        </Routes>
      </main>

      <footer className="mx-auto max-w-7xl px-5 pb-10 pt-4">
        <p className="border-t border-edge/60 pt-4 text-2xs leading-relaxed text-slate-600">
          Every figure on every screen is computed before any language model is called.
          The benchmark table is built from SEC XBRL filings; the framework itself has
          been backtested and did not beat a revenue-growth baseline — see
          <span className="text-slate-500"> docs/validation_results.md</span>.
        </p>
      </footer>
    </div>
  );
}
