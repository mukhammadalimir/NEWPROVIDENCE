from app.bot import render
from app.services.search import search


async def test_card_message(session, make_services):
    r = await search(session, make_services(google_api_key=""), "baliq")
    text = render.card_text(r["cards"][0], "uz", render.meaning_lang(r))
    assert "<b>鱼</b>" in text and "魚" in text and "yú" in text
    assert "baliq" in text and "海鱼" in text and "我喜欢吃鱼。" in text
    assert "Tahririyat" in text  # источник указан
    assert "taxminiy" in text  # приблизительное звучание помечено


async def test_text_message_marks_machine_translation(session, make_services):
    r = await search(session, make_services(), "我喜欢吃鱼。")
    body = render.text_result(r, "ru") + render.notices_text(r, "ru")
    assert "Men baliq" in body and "машинный" in body
