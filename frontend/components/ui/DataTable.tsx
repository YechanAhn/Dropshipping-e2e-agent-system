import { ReactNode } from 'react';

export interface Column<T> {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
  className?: string;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  keyExtractor: (row: T) => string | number;
  className?: string;
}

export function DataTable<T>({ columns, rows, keyExtractor, className = '' }: DataTableProps<T>) {
  return (
    <div className={['w-full overflow-x-auto', className].join(' ')}>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border">
            {columns.map((col) => (
              <th
                key={col.key}
                className={[
                  'py-3 px-4 text-left text-xs font-semibold text-muted uppercase tracking-wider whitespace-nowrap',
                  col.className ?? '',
                ].join(' ')}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {rows.map((row) => (
            <tr
              key={keyExtractor(row)}
              className="hover:bg-paper/60 transition-colors duration-100"
            >
              {columns.map((col) => (
                <td
                  key={col.key}
                  className={[
                    'py-3 px-4 text-ink whitespace-nowrap',
                    col.className ?? '',
                  ].join(' ')}
                >
                  {col.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
