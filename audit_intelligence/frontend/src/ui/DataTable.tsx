import { useMemo, useState } from "react";
import {
  type ColumnDef,
  type SortingState,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ArrowUpDown, ChevronLeft, ChevronRight, Search } from "lucide-react";

export interface DataTableProps<T> {
  columns: ColumnDef<T, unknown>[];
  data: T[];
  getRowId: (row: T) => string;
  searchPlaceholder?: string;
  initialSort?: SortingState;
  pageSize?: number;
  selection?: { selected: Set<string>; onChange: (next: Set<string>) => void };
  onRowClick?: (row: T) => void;
  emptyState?: React.ReactNode;
}

export function DataTable<T>({
  columns,
  data,
  getRowId,
  searchPlaceholder = "Search...",
  initialSort = [],
  pageSize = 25,
  selection,
  onRowClick,
  emptyState,
}: DataTableProps<T>) {
  const [sorting, setSorting] = useState<SortingState>(initialSort);
  const [globalFilter, setGlobalFilter] = useState("");

  const allColumns = useMemo<ColumnDef<T, unknown>[]>(() => {
    if (!selection) return columns;
    const selectColumn: ColumnDef<T, unknown> = {
      id: "select",
      enableSorting: false,
      header: ({ table }) => {
        const ids = table.getRowModel().rows.map((r) => r.id);
        const allSelected = ids.length > 0 && ids.every((id) => selection.selected.has(id));
        return (
          <input
            type="checkbox"
            aria-label="Select all on this page"
            className="accent-indigo-600"
            checked={allSelected}
            onChange={() => {
              const next = new Set(selection.selected);
              if (allSelected) ids.forEach((id) => next.delete(id));
              else ids.forEach((id) => next.add(id));
              selection.onChange(next);
            }}
          />
        );
      },
      cell: ({ row }) => (
        <input
          type="checkbox"
          aria-label={`Select ${row.id}`}
          className="accent-indigo-600"
          checked={selection.selected.has(row.id)}
          onClick={(e) => e.stopPropagation()}
          onChange={() => {
            const next = new Set(selection.selected);
            if (next.has(row.id)) next.delete(row.id);
            else next.add(row.id);
            selection.onChange(next);
          }}
        />
      ),
    };
    return [selectColumn, ...columns];
  }, [columns, selection]);

  const table = useReactTable({
    data,
    columns: allColumns,
    getRowId,
    state: { sorting, globalFilter },
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
    globalFilterFn: "includesString",
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: { pagination: { pageSize } },
  });

  const rows = table.getRowModel().rows;
  const total = table.getFilteredRowModel().rows.length;
  const { pageIndex } = table.getState().pagination;
  const first = total === 0 ? 0 : pageIndex * pageSize + 1;
  const last = Math.min(total, (pageIndex + 1) * pageSize);

  return (
    <div className="space-y-3">
      <div className="relative max-w-sm">
        <Search className="pointer-events-none absolute top-2 left-2.5 h-4 w-4 text-slate-400" />
        <input
          value={globalFilter}
          onChange={(e) => setGlobalFilter(e.target.value)}
          placeholder={searchPlaceholder}
          aria-label="Search"
          className="input-field w-full pl-8"
        />
      </div>

      {total === 0 && emptyState ? (
        emptyState
      ) : (
        <div className="card overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead className="bg-slate-50">
              {table.getHeaderGroups().map((hg) => (
                <tr key={hg.id}>
                  {hg.headers.map((header) => {
                    const canSort = header.column.getCanSort();
                    const sorted = header.column.getIsSorted();
                    return (
                      <th key={header.id} className="px-4 py-2 text-left font-medium text-slate-500">
                        {header.isPlaceholder ? null : canSort ? (
                          <button
                            onClick={header.column.getToggleSortingHandler()}
                            className="flex items-center gap-1 hover:text-slate-700"
                          >
                            {flexRender(header.column.columnDef.header, header.getContext())}
                            {sorted === "asc" ? (
                              <ArrowUp className="h-3 w-3" />
                            ) : sorted === "desc" ? (
                              <ArrowDown className="h-3 w-3" />
                            ) : (
                              <ArrowUpDown className="h-3 w-3 text-slate-300" />
                            )}
                          </button>
                        ) : (
                          flexRender(header.column.columnDef.header, header.getContext())
                        )}
                      </th>
                    );
                  })}
                </tr>
              ))}
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map((row) => (
                <tr
                  key={row.id}
                  onClick={onRowClick ? () => onRowClick(row.original) : undefined}
                  className={`${onRowClick ? "cursor-pointer" : ""} ${selection?.selected.has(row.id) ? "bg-indigo-50/60" : "hover:bg-slate-50"}`}
                >
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} className="px-4 py-3">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          <div className="flex items-center justify-between border-t border-slate-100 px-4 py-2 text-xs text-slate-500">
            <span>
              {first}–{last} of {total}
            </span>
            <div className="flex items-center gap-1">
              <button
                onClick={() => table.previousPage()}
                disabled={!table.getCanPreviousPage()}
                aria-label="Previous page"
                className="rounded p-1 hover:bg-slate-100 disabled:opacity-40"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
              <span>
                Page {pageIndex + 1} of {Math.max(1, table.getPageCount())}
              </span>
              <button
                onClick={() => table.nextPage()}
                disabled={!table.getCanNextPage()}
                aria-label="Next page"
                className="rounded p-1 hover:bg-slate-100 disabled:opacity-40"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
