import { useRef, useState } from "react";
import type { FormEvent } from "react";

import { ErrorMessage } from "../components/Status";
import { api } from "../lib/api";
import { askErrorMessage, MAX_QUESTION } from "../lib/ask";
import { formatToolCall } from "../lib/toolCalls";
import type { AskResponse } from "../lib/types";

const EXAMPLES = [
  "How much did I spend in total?",
  "What are my top 3 merchants?",
  "How much did I spend on dining last month?",
  "Which month did I spend the most?",
];

export function AskPage() {
  const [question, setQuestion] = useState("");
  const [asked, setAsked] = useState<string | null>(null);
  const [result, setResult] = useState<AskResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const answerRef = useRef<HTMLHeadingElement>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const text = question.trim();
    if (!text) {
      setError("Type a question first.");
      inputRef.current?.focus();
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const response = await api<AskResponse>("/assistant/ask", { body: { question: text } });
      setAsked(text);
      setResult(response);
      requestAnimationFrame(() => answerRef.current?.focus());
    } catch (err) {
      setError(askErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  function fillExample(example: string) {
    setQuestion(example);
    setError(null);
    inputRef.current?.focus();
  }

  const remaining = MAX_QUESTION - question.length;

  return (
    <>
      <h1>Ask about your spending</h1>
      <p className="lede">
        Ask a question in your own words. Each question is answered on its own: the assistant
        doesn't remember earlier questions, so include everything it needs, such as the dates.
      </p>

      <section className="card narrow-wide" aria-labelledby="ask-heading">
        <h2 id="ask-heading" className="visually-hidden">
          Your question
        </h2>
        <form onSubmit={submit} noValidate>
          <div className="field">
            <label htmlFor="question">Question</label>
            <textarea
              id="question"
              ref={inputRef}
              rows={3}
              maxLength={MAX_QUESTION}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                // Cmd/Ctrl+Enter asks, like other chat boxes; Enter alone adds a line.
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) e.currentTarget.form?.requestSubmit();
              }}
              aria-describedby="question-count"
              placeholder="How much did I spend on groceries in March 2024?"
            />
            <p id="question-count" className={remaining < 50 ? "hint hint-warn" : "hint"}>
              {question.length} / {MAX_QUESTION} characters
            </p>
          </div>

          <div className="examples" role="group" aria-label="Example questions">
            <span className="hint">Try:</span>
            {EXAMPLES.map((example) => (
              <button key={example} type="button" className="chip" onClick={() => fillExample(example)}>
                {example}
              </button>
            ))}
          </div>

          {error && (
            <div className="ask-error">
              <ErrorMessage error={error} />
            </div>
          )}
          <button type="submit" className="button button-primary" disabled={busy}>
            {busy ? "Thinking…" : "Ask"}
          </button>
          {busy && (
            <p className="status status-loading" role="status">
              Looking at your spending. This can take a few seconds.
            </p>
          )}
        </form>
      </section>

      {result ? (
        <section className="card narrow-wide answer" aria-labelledby="answer-heading">
          <h2 id="answer-heading" ref={answerRef} tabIndex={-1}>
            Answer
          </h2>
          <p className="asked">“{asked}”</p>
          <p className="answer-text">{result.answer}</p>
          <details className="how">
            <summary>How I got this</summary>
            {result.tool_calls.length === 0 ? (
              <p className="hint">The assistant answered without looking up any of your data.</p>
            ) : (
              <ol className="tool-calls">
                {result.tool_calls.map((call, index) => {
                  const formatted = formatToolCall(call);
                  return (
                    <li key={index}>
                      <span className="tool-title">{formatted.title}</span>
                      <span className="tool-details">{formatted.details.join(" · ")}</span>
                    </li>
                  );
                })}
              </ol>
            )}
            <p className="hint">
              Only these totals, with category and merchant names, were sent to the model, never
              individual transactions.
            </p>
          </details>
        </section>
      ) : (
        !busy &&
        !error && (
          <div className="status status-empty narrow-wide">
            <p className="status-title">No question yet</p>
            <p>Pick an example above or type your own. Answers use only your own transactions.</p>
          </div>
        )
      )}
    </>
  );
}
