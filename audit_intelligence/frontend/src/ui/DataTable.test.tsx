import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ColumnDef } from "@tanstack/react-table";
import { describe, expect, it, vi } from "vitest";
import { DataTable } from "./DataTable";

interface Row {
  id: string;
  name: string;
  risk: number;
}

const columns: ColumnDef<Row, unknown>[] = [
  { id: "name", accessorKey: "name", header: "Name" },
  { id: "risk", accessorKey: "risk", header: "Risk" },
];

const rows: Row[] = Array.from({ length: 30 }, (_, i) => ({ id: `r${i}`, name: `Member ${i}`, risk: i }));

function bodyNames() {
  const body = screen.getAllByRole("rowgroup")[1];
  return within(body)
    .getAllByRole("row")
    .map((r) => within(r).getAllByRole("cell")[0]?.textContent ?? "");
}

describe("DataTable", () => {
  it("sorts by the initial sort, paginates, and toggles sort on header click", async () => {
    render(<DataTable columns={columns} data={rows} getRowId={(r) => r.id} initialSort={[{ id: "risk", desc: true }]} pageSize={10} />);
    expect(bodyNames()[0]).toBe("Member 29");
    expect(screen.getByText("1–10 of 30")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /next page/i }));
    expect(bodyNames()[0]).toBe("Member 19");

    // TanStack cycles desc -> cleared -> asc -> desc.
    const riskHeader = screen.getByRole("button", { name: /^Risk/ });
    await userEvent.click(riskHeader);
    await userEvent.click(riskHeader);
    expect(bodyNames()[0]).toBe("Member 0");
    await userEvent.click(riskHeader);
    expect(bodyNames()[0]).toBe("Member 29");
  });

  it("filters on the search box and reports the filtered count", async () => {
    render(<DataTable columns={columns} data={rows} getRowId={(r) => r.id} pageSize={10} />);
    await userEvent.type(screen.getByRole("textbox", { name: /search/i }), "Member 2");
    expect(screen.getByText("1–10 of 11")).toBeInTheDocument();
  });

  it("selects rows and the whole page without triggering the row click", async () => {
    const onChange = vi.fn();
    const onRowClick = vi.fn();
    render(
      <DataTable
        columns={columns}
        data={rows.slice(0, 3)}
        getRowId={(r) => r.id}
        selection={{ selected: new Set(), onChange }}
        onRowClick={onRowClick}
      />,
    );
    await userEvent.click(screen.getByRole("checkbox", { name: "Select r1" }));
    expect(onChange).toHaveBeenLastCalledWith(new Set(["r1"]));
    expect(onRowClick).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("checkbox", { name: /select all on this page/i }));
    expect(onChange).toHaveBeenLastCalledWith(new Set(["r0", "r1", "r2"]));

    await userEvent.click(screen.getByText("Member 2"));
    expect(onRowClick).toHaveBeenCalledWith(rows[2]);
  });
});
