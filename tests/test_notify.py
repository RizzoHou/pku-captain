"""Pure notification helpers (format_update, _applescript, should_notify).
Platform-agnostic — MacNotifier itself is not constructed (it requires macOS)."""

from treehole.monitor import Comment, Update
from treehole.notify import _applescript, format_update, should_notify


def _update(delta, comments=(), text="hello world", old=5):
    return Update(pid="123", old_reply=old, new_reply=old + delta, delta=delta,
                  text=text, new_comments=list(comments))


def test_format_update_single_comment():
    u = _update(1, [Comment(cid=9, text="nice", name_tag="Alice")])
    title, subtitle, message = format_update(u)
    assert title == "树洞 #123 · +1 新回复"
    assert subtitle == "hello world"
    assert message == "[Alice] nice"


def test_format_update_caps_to_newest_three():
    cmts = [Comment(cid=i, text=t, name_tag="洞主")
            for i, t in enumerate(["a", "b", "c", "d", "e", "f", "g"], 1)]
    u = _update(7, cmts)  # 7 new; banner shows the newest 3 + summary
    title, _, message = format_update(u)
    assert title == "树洞 #123 · +7 新回复"
    assert message == "[洞主] e\n[洞主] f\n[洞主] g\n… 还有 4 条"  # newest 3, 4 hidden


def test_format_update_hidden_counts_against_delta_not_shown():
    cmts = [Comment(cid=1, text="a", name_tag="A"), Comment(cid=2, text="b", name_tag="B")]
    u = _update(5, cmts)  # 5 new but only 2 comments fetched; cap=3 shows both
    _, _, message = format_update(u)
    assert message == "[A] a\n[B] b\n… 还有 3 条"  # hidden = delta(5) - shown(2)


def test_format_update_no_comments_falls_back_to_count():
    u = _update(3, [], text="")
    title, subtitle, message = format_update(u)
    assert "+3 新回复" in title
    assert subtitle == "5 → 8"          # empty text -> count range
    assert message == "5 → 8"


def test_applescript_escapes_quotes_and_backslashes():
    script = _applescript('ti"tle', "sub", 'mes\\sage', "default")
    assert script == ('display notification "mes\\\\sage" with title "ti\\"tle" '
                      'subtitle "sub" sound name "default"')


def test_applescript_escapes_newlines():
    # A raw LF in an AppleScript string literal is a syntax error; it must become
    # the two-character \n escape, never an actual linefeed.
    script = _applescript("t", "s", "[A] a\n[B] b", None)
    assert "\n" not in script           # no real linefeed survives into the source
    assert "[A] a\\n[B] b" in script    # emitted as the \n escape


def test_applescript_omits_empty_subtitle_and_no_sound():
    script = _applescript("t", "", "m", None)
    assert script == 'display notification "m" with title "t"'


def test_should_notify_rate_limits():
    assert should_notify({}, "k", now=1000, interval=100) is True          # never fired
    assert should_notify({"k": 1000}, "k", now=1050, interval=100) is False  # too soon
    assert should_notify({"k": 1000}, "k", now=1100, interval=100) is True   # window elapsed
