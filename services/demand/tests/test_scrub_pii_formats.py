# ruff: noqa: E501
import pytest

from ff_demand.compliance import scrub_pii

PHONES = [
    "+964 770 123 4567", "+9647701234567", "00964 770 123 4567", "07701234567", "0770 123 4567",
    "0770-123-4567", "٠٧٧٠١٢٣٤٥٦٧", "+٩٦٤ ٧٧٠ ١٢٣ ٤٥٦٧", "(0770) 123 4567", "+964-770-123-4567",
]


@pytest.mark.parametrize("ph", PHONES)
def test_iraqi_phone_formats(ph):
    out = scrub_pii(f"تواصل معي {ph} شكراً")
    assert "[phone]" in out
    assert not any(c.isdigit() for c in out), out


@pytest.mark.parametrize("txt", [
    "https://wa.me/9647701234567", "wa.me/9647701234567", "https://t.me/someuser", "t.me/some_user",
    "chat.whatsapp.com/AbCdEf123", "api.whatsapp.com/send?phone=9647701234567", "telegram.me/foo",
])
def test_messenger_links(txt):
    out = scrub_pii(f"راسلني {txt} الآن")
    assert "wa.me" not in out and "t.me" not in out and "whatsapp" not in out and "telegram" not in out
    assert "9647701234567" not in out and "someuser" not in out and "AbCdEf123" not in out


@pytest.mark.parametrize("txt", [
    "name [at] gmail dot com", "name (at) gmail (dot) com", "name at gmail dot com",
    "name AT gmail DOT com", "name{at}gmail{dot}com", "name [@] gmail [.] com", "n.a-me [at] mail.example dot org",
    "name@gmail.com", "اسم [at] gmail dot com",
])
def test_obfuscated_emails(txt):
    out = scrub_pii(f"mail: {txt} ok")
    assert out == "mail: [email] ok", out


@pytest.mark.parametrize("iban", [
    "IQ98NBIQ850123456789012", "IQ98 NBIQ 8501 2345 6789 012", "DE89 3704 0044 0532 0130 00", "GB29NWBK60161331926819",
])
def test_iban(iban):
    out = scrub_pii(f"حول على {iban} من فضلك")
    assert "[iban]" in out, out
    assert "NBIQ" not in out and "0044" not in out and "NWBK" not in out


def test_no_false_positives():
    for s in ["price 3500-4200 usd", "need 500 kg steel at the port", "we meet at noon", "look at it dot by dot",
              "الكمية 1500 طن بسعر 3500-4200"]:
        assert scrub_pii(s) == s
