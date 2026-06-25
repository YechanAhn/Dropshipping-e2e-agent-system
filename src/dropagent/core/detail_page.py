"""
Deterministic Korean 상세페이지 (detail-page) renderer from AliExpress data.

Produces Naver Smart-Editor-compatible HTML (860px, inline styles) following the
researched 11-section PASONA structure -- WITHOUT requiring an LLM. AliExpress DS
data already comes back with Korean titles/descriptions (target_language=ko), so
this localizes + lays out the source directly. The LLM layer
(``ContentGenerator.generate_detail_page``) can replace/augment the copy when an
API key is configured; this is the always-available design + automation base and
the deterministic fallback.

Principles (from research workflow wv0vk6i6c):
- Fact-grounded only: never fabricate specs, reviews, certifications, or efficacy.
  Reviews use the real DS order count or operational trust, not invented numbers.
- No superlatives/銘柄: no 최고/최저가/1위/100%/정품/명품 (the ContentGenerator
  AVOID_WORDS guardrail also strips these post-render).
- Image rights: AliExpress CDN images are embedded for preview but flagged
  (IMAGE_RIGHTS / NEEDS_IMAGE_CLEANUP) -- replace with owned/licensed media before
  publishing (AliExpress API grants no re-hosting rights).
- KC 인증 / 전자상거래법 상품정보제공고시 surfaced as a compliant disclosure block.
"""

from __future__ import annotations

import html
from decimal import Decimal
from typing import Any

ACCENT = "#c2410c"  # warm brand accent
INK = "#1a1a1a"
MUTED = "#6b7280"
LINE = "#e5e7eb"
SOFT = "#fff7ed"
WIDTH = 860

SHIP_DAYS_MIN = 7
SHIP_DAYS_MAX = 15


def _attr(obj: Any, *names: str, default: Any = None) -> Any:
    cur = obj
    for name in names:
        if cur is None:
            return default
        cur = cur.get(name) if isinstance(cur, dict) else getattr(cur, name, None)
    return cur if cur is not None else default


def _esc(text: Any) -> str:
    return html.escape(str(text or "")).strip()


def _fmt_won(value: Any) -> str:
    try:
        return f"₩{int(Decimal(str(value))):,}"
    except Exception:  # noqa: BLE001
        return ""


def _images(detail: Any) -> list[str]:
    urls = list(_attr(detail, "image_urls", default=[]) or [])
    if not urls:
        main = _attr(detail, "image_url", default="")
        if main:
            urls = [str(main)]
    # de-dup, keep order
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        u = str(u)
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _section(key: str, title: str, body: str) -> str:
    return (
        f'<section data-sec="{key}" style="max-width:{WIDTH}px;margin:0 auto 40px;'
        f'padding:0 8px;font-family:Pretendard,-apple-system,sans-serif;color:{INK};'
        f'line-height:1.7;">'
        f'<h2 style="font-size:22px;font-weight:800;margin:0 0 16px;padding-left:12px;'
        f'border-left:4px solid {ACCENT};">{title}</h2>{body}</section>'
    )


def _img(url: str, alt: str = "") -> str:
    return (
        f'<img src="{_esc(url)}" alt="{_esc(alt)}" '
        f'style="width:100%;max-width:{WIDTH}px;height:auto;display:block;'
        f'margin:0 auto 12px;border-radius:8px;" />'
    )


def render_detail_page(
    detail: Any,
    *,
    naver_title: str | None = None,
    recommended_price: Any | None = None,
) -> str:
    """Render an 11-section Korean Smart-Editor detail page from AliExpress data.

    Args:
        detail: AliProductDetail-like (title, description, image_urls/image_url,
            video_url, options, price.sale_price, currency, order_count,
            shipping_info.days).
        naver_title: SEO/Korean title to headline with (falls back to detail title).
        recommended_price: KRW price to display (falls back to detail sale price).

    Returns:
        A single HTML string (Smart-Editor compatible) -- the 11 sections in order.
    """
    title = _esc(naver_title or _attr(detail, "title", default="상품"))
    images = _images(detail)
    hero = images[0] if images else ""
    gallery = images[1:7]
    video_url = _attr(detail, "video_url", default=None)
    description = _esc(_attr(detail, "description", default=""))
    options = list(_attr(detail, "options", default=[]) or [])
    order_count = int(_attr(detail, "order_count", default=0) or 0)
    ship_days = int(_attr(detail, "shipping_info", "days", default=0) or 0)
    price = recommended_price if recommended_price is not None else _attr(detail, "price", "sale_price")
    price_str = _fmt_won(price)

    parts: list[str] = []
    parts.append(
        "<!-- IMAGE_RIGHTS: images are AliExpress CDN; replace with owned/licensed "
        "media before publishing. NEEDS_IMAGE_CLEANUP: check for watermarks/foreign text. -->"
    )

    # 1) hook
    hook_body = (_img(hero, title) if hero else "") + (
        f'<p style="font-size:20px;font-weight:700;text-align:center;margin:8px 0;">'
        f"필요한 순간, 부담 없이 — {title}</p>"
        f'<p style="text-align:center;color:{MUTED};margin:0;">'
        "찾고 계셨던 그 구성, 합리적인 가격으로 준비했어요.</p>"
    )
    parts.append(_section("hook", "이런 상품을 찾고 계셨나요?", hook_body))

    # 2) problem
    parts.append(
        _section(
            "problem",
            "이런 점, 불편하지 않으셨어요?",
            '<p>막상 사려고 하면 가격은 부담되고, 막상 저렴한 건 품질이 걱정되고… '
            "선택이 망설여지셨을 거예요. 매번 비교하느라 시간만 보내셨다면, 이 페이지가 "
            "도움이 될 거예요.</p>",
        )
    )

    # 3) benefit
    benefit_items = [
        "합리적인 가격 — 해외 직소싱으로 거품을 줄였어요.",
        "필요한 구성만 깔끔하게 — 실사용 중심.",
        "출고 전 육안 검수 후 안전 포장 발송.",
    ]
    benefit_body = '<ul style="padding-left:18px;margin:0;">' + "".join(
        f'<li style="margin:6px 0;">{b}</li>' for b in benefit_items
    ) + "</ul>"
    parts.append(_section("benefit", "이래서 만족하실 거예요", benefit_body))

    # 4) detail_spec
    spec_rows = [("상품명", title), ("판매가", price_str), ("원산지/수입", "중국 (해외구매대행)")]
    if order_count > 0:
        spec_rows.append(("누적 주문", f"{order_count:,}+"))
    spec_table = (
        '<table style="width:100%;border-collapse:collapse;margin:0 0 16px;">'
        + "".join(
            f'<tr><th style="text-align:left;width:120px;background:{SOFT};'
            f'border:1px solid {LINE};padding:10px;font-weight:700;">{k}</th>'
            f'<td style="border:1px solid {LINE};padding:10px;">{v}</td></tr>'
            for k, v in spec_rows
            if v
        )
        + "</table>"
    )
    desc_block = (
        f'<div style="white-space:pre-line;color:{INK};">{description}</div>'
        if description
        else f'<p style="color:{MUTED};">상세 사양은 옵션/문의를 참고해 주세요.</p>'
    )
    detail_imgs = "".join(_img(u, title) for u in gallery)
    parts.append(_section("detail_spec", "상품 상세 정보", spec_table + desc_block + detail_imgs))

    # 5) usage (+ video)
    usage_body = (
        '<p>일상에서 이렇게 활용해 보세요 — 사용 장면을 영상으로 확인하실 수 있어요.</p>'
    )
    if video_url:
        usage_body += (
            f'<!-- VIDEO_SLOT: re-upload licensed video to Naver Smart Editor (internal only) -->'
            f'<video src="{_esc(video_url)}" controls '
            f'style="width:100%;max-width:{WIDTH}px;border-radius:8px;"></video>'
        )
    else:
        usage_body += "<!-- VIDEO_SLOT: no source video -->"
    parts.append(_section("usage", "이렇게 활용하세요", usage_body))

    # 6) size_option
    if options:
        rows = ""
        for opt in options[:30]:
            name = _esc(_attr(opt, "name", default=""))
            value = _esc(_attr(opt, "value", default=""))
            stock = _attr(opt, "stock", default=None)
            stock_str = f"{int(stock):,}개" if stock not in (None, "") else "재고 확인"
            rows += (
                f'<tr><td style="border:1px solid {LINE};padding:8px;">{value or name}</td>'
                f'<td style="border:1px solid {LINE};padding:8px;color:{MUTED};">{stock_str}</td></tr>'
            )
        option_body = (
            f'<table style="width:100%;border-collapse:collapse;">'
            f'<tr><th style="background:{SOFT};border:1px solid {LINE};padding:8px;'
            f'text-align:left;">옵션</th><th style="background:{SOFT};border:1px solid {LINE};'
            f'padding:8px;text-align:left;">재고</th></tr>{rows}</table>'
            '<p style="color:#6b7280;font-size:13px;margin-top:8px;">'
            "옵션별 재고/사이즈는 구매 시점에 따라 달라질 수 있어요.</p>"
        )
        parts.append(_section("size_option", "옵션 / 사이즈", option_body))

    # 7) trust
    trust_body = (
        '<p>모든 상품은 <b>출고 전 육안 검수</b>를 거쳐 발송돼요.</p>'
    )
    if order_count > 0:
        trust_body += f'<p>해외 원 판매처 기준 <b>누적 주문 {order_count:,}+</b> 의 검증된 상품이에요.</p>'
    parts.append(_section("trust", "믿고 구매하세요", trust_body))

    # 8) shipping
    parts.append(
        _section(
            "shipping",
            "배송 · 교환 · 환불 안내",
            f"<p>본 상품은 <b>해외구매대행</b> 상품이에요. 주문 후 현지 출고와 통관을 거쳐 "
            f"<b>약 {SHIP_DAYS_MIN}~{SHIP_DAYS_MAX} 영업일</b> 내 도착해요"
            + (f" (판매처 표기 약 {ship_days}일)." if ship_days else ".")
            + " 통관 절차상 부분 취소·교환이 제한될 수 있어 주문 전 옵션을 꼭 확인해 주세요. "
            "단순 변심 환불은 왕복 배송비가 발생할 수 있어요.</p>",
        )
    )

    # 9) cert_as (legal)
    parts.append(
        _section(
            "cert_as",
            "인증 / 상품정보제공고시",
            "<!-- KC 인증 대상(전기/어린이/생활용품 등)일 경우 인증정보 확인 후 표기 필요 -->"
            '<table style="width:100%;border-collapse:collapse;">'
            + "".join(
                f'<tr><th style="text-align:left;width:160px;background:{SOFT};'
                f'border:1px solid {LINE};padding:8px;">{k}</th>'
                f'<td style="border:1px solid {LINE};padding:8px;">{v}</td></tr>'
                for k, v in [
                    ("품명", title),
                    ("제조국", "중국"),
                    ("수입형태", "해외구매대행"),
                    ("KC 인증", "대상 여부 확인 후 표기 (전기·어린이·생활용품 등)"),
                    ("A/S 안내", "구매내역의 판매자 문의로 접수"),
                ]
            )
            + "</table>"
            '<p style="color:#6b7280;font-size:12px;margin-top:8px;">'
            "전자상거래법 상품정보제공고시 항목입니다. 미확인 인증·효능은 표기하지 않습니다.</p>",
        )
    )

    # 10) faq
    faqs = [
        ("배송은 얼마나 걸리나요?", f"해외 출고·통관 포함 약 {SHIP_DAYS_MIN}~{SHIP_DAYS_MAX} 영업일 소요돼요."),
        ("교환·반품 되나요?", "통관 특성상 제한될 수 있어요. 옵션을 꼭 확인 후 주문 부탁드려요."),
        ("옵션은 어떻게 선택하나요?", "상단 옵션 표를 참고해 주문 시 선택하시면 돼요."),
    ]
    faq_body = "".join(
        f'<p style="margin:10px 0;"><b style="color:{ACCENT};">Q. {_esc(q)}</b><br>'
        f"A. {_esc(a)}</p>"
        for q, a in faqs
    )
    parts.append(_section("faq", "자주 묻는 질문", faq_body))

    # 11) cta_review
    cta_body = (
        f'<div style="text-align:center;padding:24px;background:{SOFT};border-radius:12px;">'
        + (f'<p style="font-size:20px;font-weight:800;margin:0 0 8px;">{price_str}</p>' if price_str else "")
        + '<p style="margin:0 0 16px;color:#374151;">지금 담아두고 부담 없이 받아보세요.</p>'
        + f'<div style="display:inline-block;background:{ACCENT};color:#fff;font-weight:800;'
        'padding:12px 28px;border-radius:999px;">구매하러 가기</div>'
        + '<p style="margin:16px 0 0;color:#6b7280;font-size:13px;">'
        "받으신 후 포토 리뷰를 남겨주시면 다음 구매에 큰 도움이 돼요 :)</p></div>"
    )
    parts.append(_section("cta_review", "지금 만나보세요", cta_body))

    return "\n".join(parts)
