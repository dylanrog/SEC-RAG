"use client";

import { useEffect, useState } from "react";

import { fetchCompanies } from "@/lib/api";
import type { AskFilters } from "@/lib/api";
import type { Company } from "@/lib/types";

export function AskForm({
  disabled,
  onSubmit,
}: {
  disabled: boolean;
  onSubmit: (question: string, filters: AskFilters) => void;
}) {
  const [question, setQuestion] = useState("");
  const [ticker, setTicker] = useState("");
  const [formType, setFormType] = useState("");
  const [companies, setCompanies] = useState<Company[]>([]);

  useEffect(() => {
    // A failed company list only costs the filter dropdown, so it must not
    // block asking questions.
    fetchCompanies()
      .then(setCompanies)
      .catch(() => setCompanies([]));
  }, []);

  return (
    <form
      className="mb-6 flex flex-col gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        if (!question.trim()) return;
        onSubmit(question.trim(), {
          ticker: ticker || undefined,
          form_type: formType || undefined,
        });
      }}
    >
      <input
        aria-label="Question"
        className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:border-blue-600 focus:outline-none"
        placeholder="What were Apple's total net sales in fiscal 2024?"
        value={question}
        onChange={(event) => setQuestion(event.target.value)}
      />
      <div className="flex gap-2">
        <select
          aria-label="Company"
          className="rounded border border-slate-700 bg-slate-900 px-2 py-1 font-mono text-xs text-slate-300"
          value={ticker}
          onChange={(event) => setTicker(event.target.value)}
        >
          <option value="">All companies</option>
          {companies.map((company) => (
            <option key={company.cik} value={company.ticker}>
              {company.ticker}
            </option>
          ))}
        </select>
        <select
          aria-label="Form type"
          className="rounded border border-slate-700 bg-slate-900 px-2 py-1 font-mono text-xs text-slate-300"
          value={formType}
          onChange={(event) => setFormType(event.target.value)}
        >
          <option value="">All forms</option>
          <option value="10-K">10-K</option>
          <option value="10-Q">10-Q</option>
        </select>
        <button
          type="submit"
          disabled={disabled}
          className="rounded bg-blue-700 px-4 py-1 text-sm text-white hover:bg-blue-600 disabled:bg-slate-800 disabled:text-slate-500"
        >
          {disabled ? "Asking…" : "Ask"}
        </button>
      </div>
    </form>
  );
}
