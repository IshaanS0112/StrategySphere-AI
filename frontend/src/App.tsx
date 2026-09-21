import { Link, Route, Routes } from "react-router-dom";

import CompanyDetail from "./pages/CompanyDetail";
import Dashboard from "./pages/Dashboard";
import NewCompany from "./pages/NewCompany";
import PortfolioView from "./pages/PortfolioView";
import TimelineView from "./pages/TimelineView";

export default function App() {
  return (
    <div className="mx-auto min-h-screen max-w-6xl px-5 py-8">
      <header className="mb-8 flex flex-wrap items-end justify-between gap-3 border-b border-edge pb-5">
        <div>
          <Link to="/" className="text-xl font-semibold tracking-tight text-slate-100">
            Strategy<span className="text-accent">Sphere</span>
          </Link>
          <p className="mt-1 text-xs text-slate-500">
            SWOT · GE-McKinsey · Porter’s Five Forces · pricing · sensitivity ·
            uncertainty · portfolio allocation
          </p>
        </div>
        <Link to="/portfolios" className="btn-ghost">
          Portfolio
        </Link>
      </header>

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
            <p className="panel p-6 text-sm text-slate-400">
              Nothing here.{" "}
              <Link to="/" className="text-accent">
                Back to companies
              </Link>
            </p>
          }
        />
      </Routes>
    </div>
  );
}
