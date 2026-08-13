import { Link, Route, Routes } from "react-router-dom";

import CompanyDetail from "./pages/CompanyDetail";
import Dashboard from "./pages/Dashboard";
import NewCompany from "./pages/NewCompany";

export default function App() {
  return (
    <div className="mx-auto min-h-screen max-w-6xl px-5 py-8">
      <header className="mb-8 flex flex-wrap items-end justify-between gap-3 border-b border-edge pb-5">
        <div>
          <Link to="/" className="text-xl font-semibold tracking-tight text-slate-100">
            Strategy<span className="text-accent">Sphere</span>
          </Link>
          <p className="mt-1 text-xs text-slate-500">
            SWOT scoring · GE-McKinsey matrix · pricing engine · narrated, not decided, by an LLM
          </p>
        </div>
      </header>

      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/new" element={<NewCompany />} />
        <Route path="/companies/:companyId" element={<CompanyDetail />} />
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
