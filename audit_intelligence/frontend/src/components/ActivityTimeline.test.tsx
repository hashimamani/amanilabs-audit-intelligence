import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ActivityTimeline } from "./ActivityTimeline";

describe("ActivityTimeline", () => {
  it("turns each action into a sentence with the actor", () => {
    render(
      <ActivityTimeline
        entries={[
          { at: "2026-10-19T10:00:00Z", actor_email: "a@x", actor_name: "Jane", action: "status_changed", detail: { from: "Open", to: "Closed", bulk: true } },
          { at: "2026-10-19T09:00:00Z", actor_email: "a@x", actor_name: "Jane", action: "note_added", detail: { note: "called the member" } },
          { at: "2026-10-19T08:00:00Z", actor_email: "a@x", actor_name: "Jane", action: "assigned", detail: { from: null, to: "Peter" } },
        ]}
      />,
    );
    expect(screen.getByText(/changed status from Open to Closed \(bulk update\)/)).toBeInTheDocument();
    expect(screen.getByText(/added a note: "called the member"/)).toBeInTheDocument();
    expect(screen.getByText(/assigned the case to Peter/)).toBeInTheDocument();
    expect(screen.getAllByText("Jane")).toHaveLength(3);
  });

  it("says so when nothing has happened", () => {
    render(<ActivityTimeline entries={[]} />);
    expect(screen.getByText(/No activity yet/)).toBeInTheDocument();
  });
});
