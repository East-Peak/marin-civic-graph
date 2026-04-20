// app/src/tests/components/data/data-table.test.tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { DataTable, exportCsv } from "@/components/data/data-table";
import type { ColumnDef } from "@/lib/server/data-queries";

const BASE_COLUMNS: ColumnDef[] = [
  { key: "decided_at", label: "Decided at", sortable: true, alignment: "left" },
  { key: "title", label: "Title", sortable: true, alignment: "left" },
  {
    key: "institution_name",
    label: "Institution",
    sortable: false,
    alignment: "left",
  },
  { key: "id", label: "Decision id", alignment: "left", link: "entity-route" },
];

const BASE_ROWS: Record<string, unknown>[] = [
  {
    decided_at: "2024-03-14",
    title: "Budget FY25",
    institution_name: "SR City Council",
    id: "decision-sr-budget-fy25",
  },
  {
    decided_at: "2024-06-02",
    title: "Merrydale Shelter",
    institution_name: "SR City Council",
    id: "decision-sr-merrydale-shelter",
  },
  {
    decided_at: "2024-01-08",
    title: "Park closure",
    institution_name: "SR Parks",
    id: "decision-sr-park-closure",
  },
];

describe("DataTable", () => {
  it("renders one header per column and one row per data row", () => {
    render(<DataTable rows={BASE_ROWS} columns={BASE_COLUMNS} slug="x" />);
    expect(screen.getByText("Decided at")).toBeInTheDocument();
    expect(screen.getByText("Title")).toBeInTheDocument();
    expect(screen.getByText("Budget FY25")).toBeInTheDocument();
    expect(screen.getByText("Merrydale Shelter")).toBeInTheDocument();
    expect(screen.getByText("Park closure")).toBeInTheDocument();
  });

  it("renders id cells as entity links using prefix routing", () => {
    render(<DataTable rows={BASE_ROWS} columns={BASE_COLUMNS} slug="x" />);
    const link = screen.getByRole("link", { name: "decision-sr-merrydale-shelter" });
    expect(link.getAttribute("href")).toBe("/decision/sr-merrydale-shelter");
  });

  it("sorts DESC on first click of a sortable header, toggles ASC on second", () => {
    render(<DataTable rows={BASE_ROWS} columns={BASE_COLUMNS} slug="x" />);
    const header = screen.getByText(/Decided at/i);
    // Starting order is insertion order.
    const table = screen.getByTestId("data-table");
    let rows = within(table).getAllByRole("row").slice(1); // skip header row
    expect(rows[0].textContent).toContain("Budget FY25");
    // First click -> DESC.
    fireEvent.click(header);
    rows = within(table).getAllByRole("row").slice(1);
    expect(rows[0].textContent).toContain("Merrydale Shelter"); // 2024-06-02
    expect(rows[2].textContent).toContain("Park closure"); // 2024-01-08
    // Second click -> ASC.
    fireEvent.click(header);
    rows = within(table).getAllByRole("row").slice(1);
    expect(rows[0].textContent).toContain("Park closure");
    expect(rows[2].textContent).toContain("Merrydale Shelter");
  });

  it("does not respond to clicks on non-sortable headers", () => {
    render(<DataTable rows={BASE_ROWS} columns={BASE_COLUMNS} slug="x" />);
    const header = screen.getByText(/Institution/i);
    fireEvent.click(header);
    // Order unchanged.
    const table = screen.getByTestId("data-table");
    const firstDataRow = within(table).getAllByRole("row")[1];
    expect(firstDataRow.textContent).toContain("Budget FY25");
  });

  it("shows a 'No rows' placeholder when there are no rows", () => {
    render(<DataTable rows={[]} columns={BASE_COLUMNS} slug="x" />);
    expect(screen.getByText(/No rows/i)).toBeInTheDocument();
  });

  it("triggers a browser download when Export CSV is clicked", () => {
    const originalCreate = URL.createObjectURL;
    const originalRevoke = URL.revokeObjectURL;
    const create = vi.fn(() => "blob:x");
    const revoke = vi.fn();
    URL.createObjectURL = create as typeof URL.createObjectURL;
    URL.revokeObjectURL = revoke as typeof URL.revokeObjectURL;

    render(<DataTable rows={BASE_ROWS} columns={BASE_COLUMNS} slug="sr-decisions" />);
    fireEvent.click(screen.getByRole("button", { name: /export csv/i }));
    expect(create).toHaveBeenCalled();

    URL.createObjectURL = originalCreate;
    URL.revokeObjectURL = originalRevoke;
  });
});

describe("exportCsv", () => {
  it("produces a header row + one row per data row", async () => {
    const { blob, filename } = exportCsv(BASE_ROWS, BASE_COLUMNS, "sr-decisions");
    const text = await blob.text();
    const lines = text.split("\n");
    expect(lines[0]).toBe("Decided at,Title,Institution,Decision id");
    expect(lines.length).toBe(1 + BASE_ROWS.length);
    expect(filename.startsWith("sr-decisions-")).toBe(true);
    expect(filename.endsWith(".csv")).toBe(true);
  });

  it("quotes fields containing commas or quotes", async () => {
    const rows = [
      {
        decided_at: "2024-03-14",
        title: 'Hello, "world"',
        institution_name: "SR",
        id: "decision-x",
      },
    ];
    const { blob } = exportCsv(rows, BASE_COLUMNS, "x");
    const text = await blob.text();
    expect(text).toContain('"Hello, ""world"""');
  });

  it("produces rows of length === columns.length even for missing values", async () => {
    const rows = [{ decided_at: "2024-03-14", id: "decision-x" }];
    const { blob } = exportCsv(rows, BASE_COLUMNS, "x");
    const text = await blob.text();
    const body = text.split("\n")[1];
    // 3 commas means 4 columns.
    expect((body.match(/,/g) ?? []).length).toBe(3);
  });
});
