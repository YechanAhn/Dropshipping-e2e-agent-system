# DropAgent Frontend

Next.js 14 (App Router) + TypeScript + Tailwind CSS v3 control dashboard for the DropAgent dropshipping system.

## Quick Start

```bash
cd frontend
npm install
cp .env.local.example .env.local   # edit API_PROXY_TARGET if backend runs elsewhere
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Architecture

```
frontend/
├── app/                  # Next.js App Router pages
│   ├── layout.tsx        # Root layout (Sidebar + ToastProvider)
│   ├── page.tsx          # 개요 (Overview)
│   ├── products/page.tsx # 상품 (Products)
│   ├── orders/page.tsx   # 주문 (Orders)
│   └── settings/page.tsx # 설정 (Settings)
├── components/
│   ├── layout/           # Sidebar, Topbar
│   └── ui/               # Button, Card, StatCard, Badge, Toggle, Slider,
│                         # DataTable, EmptyState, Skeleton, Toast
├── lib/
│   ├── types.ts          # API type definitions
│   ├── api.ts            # Typed fetch client (calls /api/*)
│   └── format.ts         # KRW / number / percent / date formatters
└── ...config files
```

## API Proxy

The Next.js dev server rewrites `/api/*` → `http://localhost:8000/*` (configurable via `API_PROXY_TARGET` in `.env.local`). The frontend never makes cross-origin requests.

## Design System

- **Font**: Pretendard (CDN)
- **Palette**: Warm paper `#F7F5F2`, Claude coral `#D97757`, Wanted blue `#3B6CFF`
- **Radius**: cards `rounded-2xl`, inputs `rounded-xl`, badges `rounded-full`

## Build

```bash
npm run build
npm start
```
