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
        className="rounded border px-3 py-2"
        placeholder="What were Apple's total net sales in fiscal 2024?"
        value={question}
        onChange={(event) => setQuestion(event.target.value)}
      />
      <div className="flex gap-2">
        <select
          aria-label="Company"
          className="rounded border px-2 py-1 text-sm"
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
          className="rounded border px-2 py-1 text-sm"
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
          className="rounded bg-blue-600 px-4 py-1 text-sm text-white disabled:bg-slate-300"
        >
          {disabled ? "Asking…" : "Ask"}
        </button>
      </div>
    </form>
  );
}
