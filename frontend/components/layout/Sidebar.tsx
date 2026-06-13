'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { LayoutDashboard, Package, ShoppingCart, Settings } from 'lucide-react';

const navItems = [
  { href: '/', label: '개요', icon: LayoutDashboard },
  { href: '/products', label: '상품', icon: Package },
  { href: '/orders', label: '주문', icon: ShoppingCart },
  { href: '/settings', label: '설정', icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="fixed left-0 top-0 h-full w-60 bg-surface border-r border-border flex flex-col z-20">
      {/* Brand */}
      <div className="px-6 py-5 border-b border-border">
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-lg bg-primary flex items-center justify-center flex-shrink-0">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
              <path d="M7 1L12.5 4.25V10.75L7 14L1.5 10.75V4.25L7 1Z" fill="white" fillOpacity="0.9" />
              <path d="M7 4L10 5.75V9.25L7 11L4 9.25V5.75L7 4Z" fill="white" fillOpacity="0.4" />
            </svg>
          </div>
          <div>
            <span className="text-sm font-bold text-ink tracking-tight">DropAgent</span>
            <span className="block text-[10px] text-muted leading-none mt-0.5">드롭쉬핑 자동화</span>
          </div>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 py-4 px-3" aria-label="메인 네비게이션">
        <ul className="space-y-0.5">
          {navItems.map(({ href, label, icon: Icon }) => {
            const isActive = href === '/' ? pathname === '/' : pathname.startsWith(href);
            return (
              <li key={href}>
                <Link
                  href={href}
                  className={[
                    'flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-all duration-150',
                    isActive
                      ? 'bg-primary-soft text-primary'
                      : 'text-muted hover:bg-paper hover:text-ink',
                  ].join(' ')}
                  aria-current={isActive ? 'page' : undefined}
                >
                  <Icon size={18} strokeWidth={isActive ? 2.5 : 2} />
                  {label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      {/* Footer */}
      <div className="px-6 py-4 border-t border-border">
        <p className="text-[10px] text-muted">v0.1.0 · Phase 1</p>
      </div>
    </aside>
  );
}
