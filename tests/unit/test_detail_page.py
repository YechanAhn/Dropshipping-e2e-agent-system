"""Unit tests for the deterministic Korean detail-page renderer."""

from decimal import Decimal
from types import SimpleNamespace

from dropagent.core.detail_page import render_detail_page

_SECTIONS = [
    "hook",
    "problem",
    "benefit",
    "detail_spec",
    "usage",
    "size_option",
    "trust",
    "shipping",
    "cert_as",
    "faq",
    "cta_review",
]


def _detail(**over):
    base = dict(
        title="E6S 무선 블루투스 이어폰 TWS",
        description="블루투스 5.0, 노이즈 캔슬링, 충전 케이스 포함",
        image_urls=["https://ae01.x/1.jpg", "https://ae01.x/2.jpg", "https://ae01.x/3.jpg"],
        video_url="https://video.x/1.mp4",
        options=[
            SimpleNamespace(name="색상", value="검정색", stock=37, image_url="https://ae01.x/c.jpg"),
            SimpleNamespace(name="색상", value="흰색", stock=10, image_url=None),
        ],
        order_count=5000,
        price=SimpleNamespace(sale_price=Decimal("4240")),
        shipping_info=SimpleNamespace(days=7),
        currency="KRW",
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_all_eleven_sections_present():
    html = render_detail_page(_detail())
    for sec in _SECTIONS:
        assert f'data-sec="{sec}"' in html, f"missing section {sec}"


def test_embeds_gallery_video_options_price():
    html = render_detail_page(_detail(), recommended_price=10900)
    assert "https://ae01.x/1.jpg" in html  # hero
    assert "https://ae01.x/2.jpg" in html  # gallery
    assert "<video" in html and "https://video.x/1.mp4" in html
    assert "검정색" in html and "흰색" in html  # options table
    assert "₩10,900" in html  # recommended price wins
    assert "블루투스 5.0" in html  # real DS description used (localized source)


def test_real_order_count_used_no_fabrication():
    html = render_detail_page(_detail(order_count=5000))
    assert "5,000+" in html
    # no fabricated review / superlative copy ("100%" is excluded: it legitimately
    # appears in CSS like width:100%, not as a marketing claim)
    for banned in ("최고", "최저가", "1위", "정품", "명품"):
        assert banned not in html


def test_legal_and_image_rights_markers():
    html = render_detail_page(_detail())
    assert "IMAGE_RIGHTS" in html  # rights caveat for AliExpress CDN media
    assert "NEEDS_IMAGE_CLEANUP" in html
    assert "KC 인증" in html  # compliance disclosure
    assert "상품정보제공고시" in html
    assert "해외구매대행" in html


def test_html_escaping_of_title():
    html = render_detail_page(_detail(title="<script>alert(1)</script> 이어폰"))
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_minimal_data_does_not_crash():
    bare = SimpleNamespace(
        title="간단 상품",
        description="",
        image_urls=[],
        video_url=None,
        options=[],
        order_count=0,
        price=SimpleNamespace(sale_price=Decimal("0")),
        shipping_info=SimpleNamespace(days=0),
        currency="KRW",
    )
    html = render_detail_page(bare)
    # core sections still render; size_option is skipped when there are no options
    assert 'data-sec="hook"' in html
    assert 'data-sec="cta_review"' in html
    assert 'data-sec="size_option"' not in html
    assert "VIDEO_SLOT: no source video" in html


def test_falls_back_to_image_url_when_no_gallery():
    d = _detail(image_urls=[], image_url="https://ae01.x/only.jpg")
    html = render_detail_page(d)
    assert "https://ae01.x/only.jpg" in html
