"use client";

import { useState } from "react";

import { AnswerStream } from "@/components/answer-stream";
import { AskForm } from "@/components/ask-form";
import { FilingViewer } from "@/components/filing-viewer";
import { initialAnswerState, reduceAnswer } from "@/lib/answer";
import type { AnswerState } from "@/lib/answer";
import { askStream } from "@/lib/api";
import type { AskFilters } from "@/lib/api";
import type { Citation } from "@/lib/types";

export default function AskPage() {
  const [answer, setAnswer] = useState<AnswerState>(initialAnswerState);
  const [active, setActive] = useState<{
    accession: string | null;
    sids: number[];
  }>({ accession: null, sids: [] });

  async function ask(question: string, filters: AskFilters) {
    setAnswer({ ...initialAnswerState, status: "streaming" });
    setActive({ accession: null, sids: [] });
    try {
      for await (const event of askStream(question, filters)) {
        setAnswer((previous) => reduceAnswer(previous, event));
      }
    } catch (error) {
      setAnswer((previous) => ({
        ...previous,
        status: "error",
        errorMessage:
          error instanceof Error ? error.message : "Could not reach the API.",
      }));
    }
  }

  function select(citation: Citation) {
    setActive({ accession: citation.accession, sids: citation.sids });
  }

  return (
    <main className="grid h-screen grid-cols-2">
      <section className="overflow-y-auto p-6">
        <h1 className="mb-4 text-xl font-semibold">EDGAR Answers</h1>
        <AskForm disabled={answer.status === "streaming"} onSubmit={ask} />
        <AnswerStream state={answer} onSelect={select} />
      </section>
      <section className="overflow-y-auto border-l bg-white">
        {/* key on accession: switching filings remounts with fresh state,
            while clicking another citation in the same filing keeps the
            mounted 818 KB of HTML and only re-runs the highlight effect. */}
        <FilingViewer
          key={active.accession ?? "none"}
          accession={active.accession}
          sids={active.sids}
        />
      </section>
    </main>
  );
}
